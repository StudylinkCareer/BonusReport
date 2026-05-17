"""
backend/engine_runner/api_runner.py

API-friendly wrappers around the engine runner. Two public entry points:

  * run_engine_api — run the engine for one (year, month, optional staff_id).
    Mirrors cli.main() but returns a structured dict instead of printing.
    When staff_id is given (Phase 13b staff-scoped re-run), the response
    includes priority_impact_warnings flagging other staff whose live
    priority payments may now be stale.

  * run_engine_cascade_api — Phase 13b. Reverses the trigger staff's run,
    re-runs it, then cascade-reverses-and-rerun any other staff flagged
    in priority_impact_warnings, until no warnings remain or max_iterations
    is reached. All operations in a single transaction.

Both functions reuse the same loader / persist primitives as cli.py — single
source of truth for the engine flow.

Transaction policy:
  run_engine_api opens a connection, runs the engine in dry-run, then if
  persist=True calls persist_payments + persist_priority_quota_tracker and
  commits at the end.

  run_engine_cascade_api opens one connection for the entire cascade. All
  reversals + re-runs commit together at the end. Any exception means
  full rollback.

Returns JSON-serialisable result dicts suitable for FastAPI's automatic
response encoding.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row

from backend.data.connection import get_connection
from backend.data.ref_loaders import load_priority_quota_tracker
from backend.data.reference_data import load_reference_data
from backend.engine.calc import calculate_case
from backend.engine.reversal_check import (
    LivePaymentRowsExistError,
    PriorityImpactWarning,
    check_no_live_payments,
    compute_priority_impact_warnings,
    snapshot_priority_quota_tracker,
)
from backend.engine_runner.adapter import (
    CaseNotAdaptableError,
    adapt_case,
)
from backend.engine_runner.cli import (
    build_run_context,
    load_cases,
    load_enrolments_by_staff_office,
    load_open_carry_overs,
    load_prior_priority_withholdings,
    persist_payments,
    persist_priority_quota_tracker,
)
from backend.engine_runner.ytd_aggregator import aggregate_ytd


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AmendmentWindowExpiredError(Exception):
    """Raised when a reversal is attempted past the amendment window
    (default 30 days, configurable via ref_setting.amendment_window_days)."""

    def __init__(
        self,
        staff_id: int,
        run_year: int,
        run_month: int,
        first_run_at: datetime,
        age_days: int,
        window_days: int,
    ) -> None:
        self.staff_id = staff_id
        self.run_year = run_year
        self.run_month = run_month
        self.first_run_at = first_run_at
        self.age_days = age_days
        self.window_days = window_days
        super().__init__(
            f"Amendment window of {window_days} days has expired for "
            f"staff_id={staff_id} {run_year}-{run_month:02d}. "
            f"First persisted {age_days} days ago at {first_run_at.isoformat()}. "
            f"Post-window reversal via negative offset is not yet implemented."
        )


class NoLivePaymentsToReverseError(Exception):
    """Raised when a reversal is attempted on (staff, period) with no live
    payment rows. Either the period was never run, or all rows are already
    reversed."""

    def __init__(self, staff_id: int, run_year: int, run_month: int) -> None:
        self.staff_id = staff_id
        self.run_year = run_year
        self.run_month = run_month
        super().__init__(
            f"No live tx_bonus_payment rows for staff_id={staff_id} "
            f"{run_year}-{run_month:02d} — nothing to reverse."
        )


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------

def _get_amendment_window_days(conn) -> int:
    """Read ref_setting.amendment_window_days; default 30 if missing."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM ref_setting WHERE key = 'amendment_window_days'"
        )
        row = cur.fetchone()
    if row is None:
        return 30
    return int(row[0])


# ---------------------------------------------------------------------------
# Reversal helper (Phase 13b)
# ---------------------------------------------------------------------------

def _reverse_staff_payments(
    cursor,
    *,
    staff_id: int,
    run_year: int,
    run_month: int,
    reversed_by_acting_as: str,
    reason_code: str,
    notes: str | None,
    amendment_window_days: int,
) -> dict[str, Any]:
    """Reverse all live tx_bonus_payment rows for (staff, run_year, run_month).

    Atomic within the cursor's transaction. Does NOT commit — caller is
    responsible.

    Steps:
      1. Aggregate live rows: count, sum, first_run_at.
      2. If no live rows → raise NoLivePaymentsToReverseError.
      3. Check amendment window — if older than window_days, raise
         AmendmentWindowExpiredError.
      4. INSERT tx_bonus_reversal row.
      5. UPDATE tx_bonus_payment rows to flag with reversal_id + reversed_at.

    Carry-over balance state from the reversed run is NOT undone here —
    the next persist_payments call (in the re-run) will wipe and recreate
    its carry-over state via the existing DELETE/UPDATE logic, since those
    scope by withheld_run_year/month and released_run_year/month.

    Returns:
        {
          "reversal_id": int,
          "payment_count": int,
          "total_reversed_amount": int,
          "first_run_at": ISO timestamp,
        }
    """
    # Step 1: Aggregate live rows
    cursor.execute(
        """
        SELECT MIN(created_at) AS first_run_at,
               COUNT(*)        AS row_count,
               COALESCE(SUM(gross_bonus), 0) AS total_gross
          FROM tx_bonus_payment
         WHERE run_year   = %s
           AND run_month  = %s
           AND staff_id   = %s
           AND reversal_id IS NULL
        """,
        (run_year, run_month, staff_id),
    )
    summary = cursor.fetchone()

    row_count = int(summary["row_count"] or 0)
    if row_count == 0:
        raise NoLivePaymentsToReverseError(staff_id, run_year, run_month)

    first_run_at = summary["first_run_at"]
    total_gross = int(summary["total_gross"] or 0)

    # Step 2: Window check
    now_utc = datetime.now(timezone.utc)
    if first_run_at.tzinfo is None:
        # Defensive: assume UTC if column came back naive
        first_run_at = first_run_at.replace(tzinfo=timezone.utc)
    age_days = (now_utc - first_run_at).days
    if age_days > amendment_window_days:
        raise AmendmentWindowExpiredError(
            staff_id=staff_id,
            run_year=run_year,
            run_month=run_month,
            first_run_at=first_run_at,
            age_days=age_days,
            window_days=amendment_window_days,
        )

    # Step 3: Insert reversal event row
    cursor.execute(
        """
        INSERT INTO tx_bonus_reversal (
            staff_id, run_year, run_month,
            reversed_by_acting_as, reason_code, notes,
            payment_count, total_reversed_amount
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            staff_id, run_year, run_month,
            reversed_by_acting_as, reason_code, notes,
            row_count, total_gross,
        ),
    )
    reversal_id = int(cursor.fetchone()["id"])

    # Step 4: Flag the payment rows
    cursor.execute(
        """
        UPDATE tx_bonus_payment
           SET reversal_id = %s,
               reversed_at = NOW()
         WHERE run_year   = %s
           AND run_month  = %s
           AND staff_id   = %s
           AND reversal_id IS NULL
        """,
        (reversal_id, run_year, run_month, staff_id),
    )

    return {
        "reversal_id": reversal_id,
        "payment_count": row_count,
        "total_reversed_amount": total_gross,
        "first_run_at": first_run_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Warning serialisation
# ---------------------------------------------------------------------------

def _staff_name(ref: Any, staff_id: int) -> str:
    staff = ref.staff.get(staff_id, {})
    return (
        staff.get("canonical_name")
        or staff.get("name")
        or f"<staff_id={staff_id}>"
    )


def _institution_name(ref: Any, institution_id: int) -> str:
    inst = ref.institutions.get(institution_id, {})
    return (
        inst.get("canonical_name")
        or inst.get("name")
        or f"<institution_id={institution_id}>"
    )


def _warning_to_dict(w: PriorityImpactWarning, ref: Any) -> dict[str, Any]:
    """Serialise a PriorityImpactWarning to JSON-friendly dict, enriching
    with names from ReferenceData."""
    return {
        "partner_name": _institution_name(ref, w.institution_id),
        "priority_list_institution_id": w.priority_list_institution_id,
        "institution_id": w.institution_id,
        "count_delta_direct": w.count_delta_direct,
        "count_delta_sub": w.count_delta_sub,
        "potentially_affected_payments": [
            {
                "staff_id": e.staff_id,
                "staff_name": _staff_name(ref, e.staff_id),
                "case_count": e.case_count,
                "total_priority_bonus": e.total_priority_bonus,
            }
            for e in w.potentially_affected_payments
        ],
    }


# ---------------------------------------------------------------------------
# Engine execution helper (shared by both public entry points)
# ---------------------------------------------------------------------------

def _run_engine_within_connection(
    conn,
    ref: Any,
    *,
    year: int,
    month: int,
    persist: bool,
    staff_id: int | None,
    limit: int | None,
    contract_id: str | None,
    pre_tracker_snapshot: dict[int, dict[str, int]] | None,
) -> dict[str, Any]:
    """Run the engine for one (year, month, optional staff_id) using an
    existing connection. Does NOT commit — caller is responsible.

    When persist=True and pre_tracker_snapshot is provided, computes priority
    impact warnings against the post-state and includes them in the result.

    Returns the same dict shape as run_engine_api's documented response.
    """
    priority_quota_tracker = load_priority_quota_tracker(conn)

    skipped: list[dict] = []
    errored: list[dict] = []
    payments: list[Any] = []
    adapted_count = 0
    total_cases = 0
    gross_total = 0
    net_total = 0
    warnings_payload: list[dict] = []

    with conn.cursor(row_factory=dict_row) as cursor:
        priority_ytd = aggregate_ytd(cursor, year=year, month=month)
        prior_withholdings = load_open_carry_overs(cursor)
        prior_priority_withholdings = load_prior_priority_withholdings(cursor)
        enrolments = load_enrolments_by_staff_office(
            cursor, year=year, month=month,
        )

        ctx = build_run_context(
            priority_ytd, prior_withholdings, enrolments, ref,
            year=year, month=month,
            priority_quota_tracker=priority_quota_tracker,
            prior_priority_withholdings=prior_priority_withholdings,
        )

        case_rows = load_cases(
            cursor,
            year=year, month=month,
            contract_id=contract_id,
            staff_id=staff_id,
            limit=limit,
        )
        total_cases = len(case_rows)

        case_office_id_map = {r["id"]: r["case_office_id"] for r in case_rows}
        case_contract_id_map = {r["id"]: r["contract_id"] for r in case_rows}

        # Adapt + run engine per case
        for case_row in case_rows:
            cid = case_row.get("contract_id") or "<no-id>"

            try:
                case_input = adapt_case(case_row, ref)
            except CaseNotAdaptableError as e:
                skipped.append({"contract_id": cid, "reason": e.reason})
                continue
            except Exception as e:
                errored.append({
                    "contract_id": cid,
                    "error": f"{type(e).__name__}: {e}",
                    "phase": "adapt",
                })
                continue

            adapted_count += 1

            try:
                case_payments = calculate_case(case_input, ctx, ref)
            except Exception as e:
                errored.append({
                    "contract_id": cid,
                    "error": f"{type(e).__name__}: {e}",
                    "phase": "calc",
                })
                continue

            if case_payments:
                payments.extend(case_payments)
                for p in case_payments:
                    gross_total += int(p.gross_bonus or 0)
                    net_total += int(p.net_payable or 0)

        # Persist if requested
        if persist:
            persist_payments(
                cursor,
                year=year, month=month,
                payments=payments,
                case_office_id_map=case_office_id_map,
                case_contract_id_map=case_contract_id_map,
                staff_id=staff_id,
            )
            persist_priority_quota_tracker(
                cursor,
                year=year, month=month,
                priority_quota_state=ctx.priority_quota_state,
            )

            # Phase 13b: compute priority impact warnings if this was a
            # staff-scoped re-run and a pre-snapshot was supplied.
            if staff_id is not None and pre_tracker_snapshot is not None:
                post_snapshot = snapshot_priority_quota_tracker(conn)
                warnings = compute_priority_impact_warnings(
                    conn,
                    run_year=year,
                    run_month=month,
                    staff_id_rerun=staff_id,
                    old_tracker_snapshot=pre_tracker_snapshot,
                    new_tracker_state=post_snapshot,
                )
                warnings_payload = [_warning_to_dict(w, ref) for w in warnings]

    return {
        "year": year,
        "month": month,
        "persist": persist,
        "staff_id": staff_id,
        "total_cases": total_cases,
        "adapted": adapted_count,
        "skipped": skipped,
        "errored": errored,
        "payment_count": len(payments),
        "gross_total": gross_total,
        "net_total": net_total,
        "priority_impact_warnings": warnings_payload,
    }


# ---------------------------------------------------------------------------
# Public: run_engine_api
# ---------------------------------------------------------------------------

def run_engine_api(
    *,
    year: int,
    month: int,
    persist: bool = True,
    staff_id: int | None = None,
    limit: int | None = None,
    contract_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the engine for one (year, month) period. Optional staff scoping.
    No stdout writes.

    Args:
        year, month:  run period (month 1-12).
        persist:      if True, write to tx_bonus_payment + manage
                      tx_carry_over_balance + tx_priority_quota_tracker.
                      If False, dry run with no DB writes.
        staff_id:     Phase 13b staff-scoped re-run. Filters case loading
                      to cases involving this staff, and scopes the persist
                      DELETE/UPDATE statements. Other staff's live rows are
                      untouched. When given AND persist=True, the response
                      includes priority_impact_warnings.
        limit:        optional cap on tx_case rows processed.
        contract_id:  optional contract filter (debug a single case).

    Returns:
        {
          "year": int,
          "month": int,
          "persist": bool,
          "staff_id": int | None,
          "total_cases": int,
          "adapted": int,
          "skipped": [{"contract_id": str, "reason": str}],
          "errored": [{"contract_id": str, "error": str, "phase": str}],
          "payment_count": int,
          "gross_total": int,
          "net_total": int,
          "priority_impact_warnings": [
            {
              "partner_name": str,
              "priority_list_institution_id": int,
              "institution_id": int,
              "count_delta_direct": int,
              "count_delta_sub": int,
              "potentially_affected_payments": [
                {"staff_id": int, "staff_name": str, "case_count": int,
                 "total_priority_bonus": int},
                ...
              ]
            },
            ...
          ]
        }

    Raises:
        ValueError if month is out of range.
        LivePaymentRowsExistError if persist=True and live rows exist for
            the target (staff, period) — reverse first.
        Any exception from the engine itself (caught at the API layer
        and turned into a 500).
    """
    if not (1 <= month <= 12):
        raise ValueError("month must be between 1 and 12")

    with get_connection() as conn:
        ref = load_reference_data(conn)

        # Phase 13b: snapshot tracker BEFORE persist when staff-scoped.
        pre_tracker_snapshot: dict[int, dict[str, int]] | None = None
        if persist and staff_id is not None:
            pre_tracker_snapshot = snapshot_priority_quota_tracker(conn)

        result = _run_engine_within_connection(
            conn, ref,
            year=year, month=month,
            persist=persist,
            staff_id=staff_id,
            limit=limit,
            contract_id=contract_id,
            pre_tracker_snapshot=pre_tracker_snapshot,
        )

        if persist:
            conn.commit()

    return result


# ---------------------------------------------------------------------------
# Public: run_engine_cascade_api (Phase 13b)
# ---------------------------------------------------------------------------

def run_engine_cascade_api(
    *,
    year: int,
    month: int,
    trigger_staff_id: int,
    reversed_by_acting_as: str,
    initial_reason_code: str,
    notes: str | None = None,
    max_iterations: int = 10,
) -> dict[str, Any]:
    """
    Cascade reverse + re-run starting from trigger_staff_id, then iteratively
    process any other staff flagged in priority_impact_warnings until no
    warnings remain or max_iterations is reached.

    Each iteration handles ONE staff:
      1. Reverse all live tx_bonus_payment rows for that staff/period
         (creates a tx_bonus_reversal log entry).
         The first iteration uses initial_reason_code; subsequent iterations
         use 'CASCADE_FROM_PRIORITY_IMPACT' with a note referencing the trigger.
      2. Re-run the engine for that staff (persist + tracker update).
      3. Compute priority_impact_warnings comparing pre/post tracker state.
      4. Add any newly-affected staff to the pending queue.

    All operations run in a single transaction. If anything fails, the entire
    cascade rolls back — no partial state.

    Args:
        year, month:                run period (month 1-12).
        trigger_staff_id:           the staff whose disagreement triggered
                                    the cascade. Their reversal uses
                                    initial_reason_code.
        reversed_by_acting_as:      the actingAsKey from the frontend (e.g.
                                    'persona:finance_officer'). Must exist
                                    in ref_amendment_authorised_persona.
        initial_reason_code:        reason code for the trigger reversal
                                    (e.g. 'DATA_ERROR', 'DISAGREEMENT').
                                    Cascade reversals always use
                                    'CASCADE_FROM_PRIORITY_IMPACT'.
        notes:                      optional free-text notes attached to the
                                    trigger reversal.
        max_iterations:             cap on cascade depth (default 10).
                                    If exceeded, cascade_complete=False in
                                    the response and remaining pending staff
                                    are listed in pending_unprocessed.

    Returns:
        {
          "year": int, "month": int,
          "trigger_staff_id": int,
          "max_iterations": int,
          "iterations_used": int,
          "cascade_complete": bool,
          "reversals": [
            {
              "iteration": int, "staff_id": int, "staff_name": str,
              "reversal_id": int, "reason_code": str,
              "payment_count": int, "total_reversed_amount": int,
            },
            ...
          ],
          "reruns": [
            {
              "iteration": int, "staff_id": int, "staff_name": str,
              "total_cases": int, "adapted": int, "skipped": [...],
              "errored": [...], "payment_count": int,
              "gross_total": int, "net_total": int,
            },
            ...
          ],
          "final_warnings": [...],          # warnings still active after last iteration
          "pending_unprocessed": [int],     # staff IDs in queue when max_iterations hit
        }

    Raises:
        ValueError if month is out of range.
        AmendmentWindowExpiredError if any staff's first_run_at is past the window.
        NoLivePaymentsToReverseError if trigger_staff_id has no live rows.
        Any exception from the engine itself.
    """
    if not (1 <= month <= 12):
        raise ValueError("month must be between 1 and 12")
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    reversals: list[dict] = []
    reruns: list[dict] = []
    processed: set[int] = set()
    pending: list[int] = [trigger_staff_id]
    iteration = 0
    final_warnings: list[dict] = []

    with get_connection() as conn:
        ref = load_reference_data(conn)
        amendment_window_days = _get_amendment_window_days(conn)
        trigger_name = _staff_name(ref, trigger_staff_id)

        with conn.cursor(row_factory=dict_row) as cursor:
            while pending and iteration < max_iterations:
                # Take next staff from the queue
                staff_id = pending.pop(0)
                if staff_id in processed:
                    continue
                iteration += 1
                processed.add(staff_id)

                # Determine reason code + notes for this reversal
                if staff_id == trigger_staff_id and iteration == 1:
                    this_reason = initial_reason_code
                    this_notes = notes
                else:
                    this_reason = "CASCADE_FROM_PRIORITY_IMPACT"
                    this_notes = (
                        f"Cascade from re-run of {trigger_name} for "
                        f"{year}-{month:02d}."
                    )

                # Snapshot tracker BEFORE this staff's re-run
                pre_snapshot = snapshot_priority_quota_tracker(conn)

                # Step 1: Reverse this staff's live rows
                try:
                    reversal = _reverse_staff_payments(
                        cursor,
                        staff_id=staff_id,
                        run_year=year,
                        run_month=month,
                        reversed_by_acting_as=reversed_by_acting_as,
                        reason_code=this_reason,
                        notes=this_notes,
                        amendment_window_days=amendment_window_days,
                    )
                except NoLivePaymentsToReverseError:
                    # Edge case: cascade flagged a staff but their rows were
                    # already reversed by a concurrent process, OR the
                    # warnings query was overly broad. Skip silently.
                    if staff_id == trigger_staff_id:
                        # If the TRIGGER has nothing live, the whole cascade
                        # is a no-op — surface this as an error.
                        raise
                    continue

                reversals.append({
                    "iteration": iteration,
                    "staff_id": staff_id,
                    "staff_name": _staff_name(ref, staff_id),
                    "reversal_id": reversal["reversal_id"],
                    "reason_code": this_reason,
                    "payment_count": reversal["payment_count"],
                    "total_reversed_amount": reversal["total_reversed_amount"],
                })

                # Step 2: Re-run engine for this staff
                rerun = _run_engine_within_connection(
                    conn, ref,
                    year=year, month=month,
                    persist=True,
                    staff_id=staff_id,
                    limit=None,
                    contract_id=None,
                    pre_tracker_snapshot=pre_snapshot,
                )
                reruns.append({
                    "iteration": iteration,
                    "staff_id": staff_id,
                    "staff_name": _staff_name(ref, staff_id),
                    "total_cases": rerun["total_cases"],
                    "adapted": rerun["adapted"],
                    "skipped": rerun["skipped"],
                    "errored": rerun["errored"],
                    "payment_count": rerun["payment_count"],
                    "gross_total": rerun["gross_total"],
                    "net_total": rerun["net_total"],
                })

                # Step 3: Examine warnings from this iteration's re-run.
                # Any newly-affected staff (not yet processed and not in
                # pending) get queued.
                for w in rerun["priority_impact_warnings"]:
                    for affected in w["potentially_affected_payments"]:
                        sid = int(affected["staff_id"])
                        if sid not in processed and sid not in pending:
                            pending.append(sid)

                # Track the latest warnings as "final" — they're overwritten
                # each iteration. The final assignment captures warnings
                # after the cascade settles.
                final_warnings = list(rerun["priority_impact_warnings"])

            cascade_complete = len(pending) == 0

            # If we exited because max_iterations was hit, surface remaining
            # pending staff for the caller to address manually.
            pending_unprocessed = list(pending) if not cascade_complete else []

            conn.commit()

    return {
        "year": year,
        "month": month,
        "trigger_staff_id": trigger_staff_id,
        "max_iterations": max_iterations,
        "iterations_used": iteration,
        "cascade_complete": cascade_complete,
        "reversals": reversals,
        "reruns": reruns,
        "final_warnings": final_warnings,
        "pending_unprocessed": pending_unprocessed,
    }
