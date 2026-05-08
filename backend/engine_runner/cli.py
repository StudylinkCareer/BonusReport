"""
backend/engine_runner/cli.py

Command-line entrypoint for running the engine on a single (year, month).

Usage:
    python -m backend.engine_runner.cli --year 2025 --month 4
    python -m backend.engine_runner.cli --year 2025 --month 4 --persist

Default mode is --dry-run (prints BonusPayment objects to stdout, no DB
writes). Use --persist when you've eyeballed the output and want to
write to tx_bonus_payment AND manage tx_carry_over_balance state.

Flow:
    1. Load ReferenceData via the data layer (one snapshot of all ref/dim tables)
    2. Aggregate YTD priority-list counts (channel-split: direct/sub/total)
    3. Load open carry-over balances → prior_withholdings_by_contract_staff
    3a. (Phase 12b) Load tx_priority_quota_tracker → priority_quota_state
    3b. (Phase 12b) Load prior priority withholdings → prior_priority_withholdings_by_contract_staff
    4. Build RunContext for the period
    5. Query tx_case rows for (year, month)
    6. For each row:
         - Try to adapt to CaseInput (skip if not adaptable)
         - Try to run engine.calculate_case (collect errors, don't abort)
    7. Print summary (cases processed, skipped, errored, payments emitted)
    8. If --persist:
         - DELETE existing tx_bonus_payment rows for (run_year, run_month)
         - INSERT each new payment (incl. priority_withheld_amount,
           priority_unlocked_amount, priority_schedule_type)
         - Manage tx_carry_over_balance lifecycle
         - (Phase 12b) UPSERT tx_priority_quota_tracker from ctx.priority_quota_state
         - Run priority_finalizer to write retroactive priority payments
           for any (case, slot) whose threshold was met by end of this month
         - Re-runs of the same month are idempotent

Phase 8 priority retroactive layer:
    The forward calc_priority_bonus only pays priority when the threshold
    is already met at the start of the month. When threshold is crossed
    DURING month M (e.g. enough enrolments accumulate by end-of-M to cross
    the partner's annual KPI), priority_finalizer.run() writes catch-up
    rows for all eligible YTD cases. Catch-up rows carry run_month=M
    (when the threshold was crossed / paid) and a retroactive_priority
    flag in audit_json.

Phase 12b SPLIT_25_25_50 layer:
    For 2025+ (gated by ref_priority_group.priority_split_rule_type), the
    at-enrolment 50% of priority bonus splits into 25% now + 25% withheld
    for visa-receipt release. The 25% withheld portion lives on
    tx_bonus_payment.priority_withheld_amount; on the visa-receipt run the
    carry-over branch releases it via priority_unlocked_amount. The
    final 50% is gated on year-end quota completion (year-end finalizer,
    not yet built). All 2024 priority groups remain on STANDARD_50_50,
    so this layer is a no-op for 2024 reruns.

Phase 7 carry-over key fix: tx_case has a different case_id for every
(contract, run_year, run_month) tuple. Carry-over lookup, opening, and
closing all key on (contract_id, staff_id), with case_id stored in
tx_carry_over_balance only as audit/lineage information.

Defensive design: per-case errors are caught and reported so one bad row
doesn't kill the whole run.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from backend.data.connection import get_connection
from backend.data.ref_loaders import load_priority_quota_tracker
from backend.data.reference_data import load_reference_data
from backend.engine.calc import calculate_case
from backend.engine.models import RunContext
from backend.engine_runner import priority_finalizer
from backend.engine_runner.adapter import (
    CaseNotAdaptableError,
    NON_ADAPTABLE_STATUSES,
    adapt_case,
)
from backend.engine_runner.ytd_aggregator import (
    PriorityYtdSnapshot,
    aggregate_ytd,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the BonusReport engine for one (year, month) period.",
    )
    parser.add_argument("--year",  type=int, required=True, help="Run year, e.g. 2025")
    parser.add_argument("--month", type=int, required=True, help="Run month, 1-12")
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Write outputs to tx_bonus_payment and manage "
             "tx_carry_over_balance. Default is dry-run (print only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N cases (useful for spot-checking).",
    )
    parser.add_argument(
        "--contract-id",
        type=str,
        default=None,
        help="Process only the case with this contract_id (debug a single case).",
    )
    args = parser.parse_args(argv)
    if not (1 <= args.month <= 12):
        parser.error("--month must be between 1 and 12")
    return args


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_cases(
    cursor: Any,
    *,
    year: int,
    month: int,
    contract_id: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Load tx_case rows for the run period as a list of dicts."""
    sql = """
        SELECT *
          FROM tx_case
         WHERE run_year = %s
           AND run_month = %s
    """
    params: list[Any] = [year, month]

    if contract_id is not None:
        sql += " AND contract_id = %s"
        params.append(contract_id)

    sql += " ORDER BY id"

    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    cursor.execute(sql, params)
    return list(cursor.fetchall())


def load_open_carry_overs(cursor: Any) -> dict[tuple[str, int], int]:
    """
    Load all open carry-over balances → {(contract_id, staff_id): withheld_amount}.

    Phase 7 carry-over key fix: tx_carry_over_balance stores case_id (FK to
    tx_case), but tx_case has a separate row per (contract, run_year,
    run_month). When April runs and looks for a withholding opened by Feb,
    the case_ids will differ — they're for the same contract but different
    monthly rows. Joining tx_case here translates case_id back to
    contract_id, which is the stable identifier.

    Populates RunContext.prior_withholdings_by_contract_staff so the engine's
    carry-over supersede logic finds the right withholding to release when
    is_carry_over fires.
    """
    cursor.execute(
        """
        SELECT c.contract_id, cob.staff_id, cob.withheld_amount
          FROM tx_carry_over_balance cob
          JOIN tx_case c ON c.id = cob.case_id
         WHERE cob.is_open = TRUE
        """
    )
    return {
        (row["contract_id"], row["staff_id"]): row["withheld_amount"]
        for row in cursor.fetchall()
    }


def load_prior_priority_withholdings(cursor: Any) -> dict[tuple[str, int], int]:
    """
    Phase 12b: Load net remaining priority withholdings keyed by
    (contract_id, staff_id).

    For SPLIT_25_25_50 cases, the at-enrolment 25% is paid immediately, the
    next 25% is withheld at the same row (priority_withheld_amount > 0) until
    visa receipt + file closure (carry-over branch), and the final 50% is
    released by the year-end finalizer when the partner quota is met.

    This loader returns the NET remaining withhold for each (contract, staff)
    pair: SUM(priority_withheld_amount) − SUM(priority_unlocked_amount). The
    engine reads this in payment_timing's carry-over branch (a) to release
    the locked-at-start 25% on visa receipt.

    Symmetric with load_open_carry_overs in spirit but distinct in storage:
    base-bonus carry-over uses tx_carry_over_balance (a separate table with
    open/closed rows); priority carry-over lives inline on tx_bonus_payment
    columns and is reconstructed here as a net delta. No state table needed.

    Returns empty dict if no rows match — engine treats every case as
    no-prior-priority-withhold (priority_unlocked stays 0 in the carry-over
    branch).
    """
    cursor.execute(
        """
        SELECT c.contract_id,
               bp.staff_id,
               SUM(bp.priority_withheld_amount) - SUM(bp.priority_unlocked_amount)
                   AS net_withheld
          FROM tx_bonus_payment bp
          JOIN tx_case c ON c.id = bp.case_id
         WHERE bp.priority_withheld_amount > 0
            OR bp.priority_unlocked_amount > 0
         GROUP BY c.contract_id, bp.staff_id
        HAVING SUM(bp.priority_withheld_amount)
             - SUM(bp.priority_unlocked_amount) > 0
        """
    )
    return {
        (row["contract_id"], row["staff_id"]): int(row["net_withheld"])
        for row in cursor.fetchall()
    }


def load_enrolments_by_staff_office(
    cursor: Any,
    year: int,
    month: int,
) -> dict[tuple[int, int], int]:
    """
    Count current-month enrolments grouped by (staff_id, office_id).

    A case counts as an enrolment for a given staff member when:
      - the case is in this run period (run_year, run_month)
      - the case has import_status='OK' (skip SCRAP, UNRESOLVED etc.)
      - the case's application_status maps to a ref_status_split row
        with counts_as_enrolled=TRUE
      - the staff member fills the counsellor or case_officer slot on
        the case

    Per policy §I.1.1: enrolment KPI applies to Counsellor/CO pairs and
    CO Sub agents. Presales and VP slots are not in the enrolment KPI
    and are excluded here.

    A case is counted ONCE per staff member even when same person fills
    both counsellor and case_officer slots (the same-person consolidation
    pattern), via DISTINCT on (staff_id, case_id).

    Country weighting (e.g. Malaysia counts as 0.5 per policy §I.2) is
    NOT applied here — every counted case adds 1.0. This is conservative
    for hitting target and matches the simpler accounting in current
    bao caos. If precise weighting becomes important, refactor later.

    The office_id used is the case's case_office_id. ref_staff_target
    rows are keyed by (staff_id, office_id), so a staff member working
    a case in a different office than their home office will accrue
    that enrolment to the case's office bucket.

    Returns:
        Dict {(staff_id, office_id): enrolment_count}.
        Empty dict if no qualifying cases for the period.
    """
    cursor.execute(
        """
        WITH staff_on_case AS (
            SELECT DISTINCT slots.staff_id, tc.case_office_id, tc.id AS case_id
              FROM tx_case tc
              JOIN ref_status_split rss
                ON rss.status = tc.application_status
        CROSS JOIN LATERAL (
                VALUES
                    (tc.counsellor_staff_id),
                    (tc.case_officer_staff_id)
            ) AS slots(staff_id)
             WHERE tc.run_year = %s
               AND tc.run_month = %s
               AND tc.import_status = 'OK'
               AND rss.counts_as_enrolled = TRUE
               AND slots.staff_id IS NOT NULL
        )
        SELECT staff_id, case_office_id AS office_id,
               COUNT(*) AS enrolment_count
          FROM staff_on_case
         GROUP BY staff_id, case_office_id
        """,
        (year, month),
    )
    return {
        (row["staff_id"], row["office_id"]): row["enrolment_count"]
        for row in cursor.fetchall()
    }


def build_run_context(
    priority_ytd: PriorityYtdSnapshot,
    prior_withholdings: dict[tuple[str, int], int],
    enrolments_by_staff_office: dict[tuple[int, int], int],
    ref: Any,
    *,
    year: int,
    month: int,
    priority_quota_tracker: dict[int, dict] | None = None,
    prior_priority_withholdings: dict[tuple[str, int], int] | None = None,
) -> RunContext:
    """
    Construct the RunContext for this period.

    targets_by_staff_office is built from ref.staff_targets — filtered to
    rows whose year/month match this run period and reshaped into the
    (staff_id, office_id) → target dict the engine wants.

    prior_withholdings_by_contract_staff is wired (Phase 7) — populated
    from tx_carry_over_balance via load_open_carry_overs, joined to
    tx_case so the key is (contract_id, staff_id) rather than
    (case_id, staff_id). See models.py docstring for the rationale.

    enrolments_by_staff_office is wired — populated from current-month
    tx_case rows via load_enrolments_by_staff_office. With this dict
    populated, classify_tier in calc_tier.py can compare each staff
    member's current-month enrolment count against their target and
    select the appropriate tier (UNDER / TARGET / OVER).

    priority_ytd (Phase 8) — the channel-split YTD snapshot built by
    aggregate_ytd. Replaces the prior pair of dicts
    (enrolments_by_priority_list_ytd, ..._institution_ytd). calc_priority
    reads role_count and total_count from this snapshot for threshold
    gating.

    Phase 12b additions:
      priority_quota_state — keyed by priority_list_institution_id; each
        value is a dict {'count_direct': int, 'count_sub': int, ...}.
        Mutated in place by payment_timing when SPLIT-rule priority cases
        first appear; persisted back via persist_priority_quota_tracker
        after the run loop. Defaults to {} when the tracker is empty.
      prior_priority_withholdings_by_contract_staff — keyed by
        (contract_id, staff_id), value is the net unreleased priority
        withhold. Read by payment_timing's carry-over branch (a) to
        release on visa receipt. Defaults to {} when no prior withholds.

    seen_priority_case_ids is initialized to an empty set inside
    RunContext (default factory) — it accumulates during the run to
    dedup multi-slot cases.

    One field remains stubbed empty pending follow-up:

      * clawback_balances_by_staff — from tx_clawback_balance.
    """
    targets_by_staff_office: dict[tuple[int, int], int] = {
        (row["staff_id"], row["office_id"]): row["target"]
        for row in ref.staff_targets.values()
        if row.get("year") == year and row.get("month") == month
    }

    return RunContext(
        year=year,
        month=month,
        enrolments_by_staff_office=enrolments_by_staff_office,
        targets_by_staff_office=targets_by_staff_office,
        priority_ytd=priority_ytd,
        clawback_balances_by_staff={},
        prior_withholdings_by_contract_staff=prior_withholdings,
        priority_quota_state=priority_quota_tracker or {},
        prior_priority_withholdings_by_contract_staff=prior_priority_withholdings or {},
        # seen_priority_case_ids defaults to empty set in the dataclass
    )


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

def _print_payment(payment: Any) -> None:
    """Compact one-liner for a BonusPayment."""
    print(
        f"    case={payment.case_id:>5}  "
        f"slot={payment.slot_label:<14}  "
        f"staff={payment.staff_name:<28}  "
        f"tier={payment.tier_bonus:>11,}  "
        f"priority={payment.priority_bonus:>11,}  "
        f"package={payment.package_bonus:>11,}  "
        f"gross={payment.gross_bonus:>11,}  "
        f"net={payment.net_payable:>11,}"
    )


def print_summary(
    *,
    total_cases: int,
    adapted: int,
    skipped: list[tuple[dict, str]],
    errored: list[tuple[dict, BaseException]],
    payments: list[Any],
) -> None:
    print()
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  Total tx_case rows in period:   {total_cases:>5}")
    print(f"  Adapted to CaseInput:           {adapted:>5}")
    print(f"  Skipped (not adaptable):        {len(skipped):>5}")
    print(f"  Errored during engine call:     {len(errored):>5}")
    print(f"  BonusPayment rows produced:     {len(payments):>5}")

    if skipped:
        print()
        print("  Skipped cases:")
        for row, reason in skipped:
            print(f"    {row.get('contract_id', '<no-id>'):<20} {reason}")

    if errored:
        print()
        print("  Errored cases:")
        for row, exc in errored:
            print(f"    {row.get('contract_id', '<no-id>'):<20} "
                  f"{type(exc).__name__}: {exc}")

    print("=" * 80)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _audit_get(audit: dict | None, *path: str, default: Any = None) -> Any:
    """Defensive nested .get() for audit_json paths."""
    cur: Any = audit or {}
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _to_jsonable(obj: Any) -> Any:
    """Convert audit dict so it's json.dumps-safe (Decimal, date, datetime)."""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def persist_payments(
    cursor: Any,
    *,
    year: int,
    month: int,
    payments: list[Any],
    case_office_id_map: dict[int, int],
    case_contract_id_map: dict[int, str],
) -> None:
    """
    Write payments to tx_bonus_payment AND manage tx_carry_over_balance.

    Idempotent for full-period re-runs:
      * tx_bonus_payment rows for (year, month) are wiped + reinserted.
        This INCLUDES any retroactive priority rows priority_finalizer
        wrote in a prior run for this period — they get rewritten too.
      * tx_carry_over_balance rows whose withheld_run was this period
        are wiped (we'll re-create them from this run)
      * tx_carry_over_balance rows whose released_run was this period
        are reverted to open (we'll re-close them from this run)

    For each payment:
      * INSERT a tx_bonus_payment row keyed by
        (case_id, slot, run_year, run_month)
      * If is_current_enrolled flag fired AND there's a positive
        carry-over withholding (gross - base_payable_after_split):
        DELETE-then-INSERT a fresh open tx_carry_over_balance row
      * If is_carry_over flag fired AND unlocked_from_prior > 0:
        UPDATE the matching open tx_carry_over_balance row to closed,
        recording the release fields

    Phase 12b: Three new columns are persisted on every row:
      * priority_withheld_amount  — at-enrolment portion held back under SPLIT
      * priority_unlocked_amount  — release-event portion paid this run
      * priority_schedule_type    — 'STANDARD' or 'SPLIT_25_25_50'
    All default to 0/STANDARD; for STANDARD_50_50 priority groups (all of
    2024) the values are always 0/0/'STANDARD' — zero behaviour change.

    Phase 7 carry-over key fix: when matching open balances to close
    (or to defensively delete before opening a new one), the match is
    by (contract_id, staff_id) — not (case_id, staff_id) — because
    tx_case has a different case_id for every monthly row of the same
    contract. We translate by joining tx_carry_over_balance.case_id to
    tx_case to filter on contract_id.

    Args:
        case_office_id_map:   {tx_case.id → office_id} for the period.
        case_contract_id_map: {tx_case.id → contract_id} for the period.
    """
    # ----- Idempotency cleanup -------------------------------------------
    cursor.execute(
        "DELETE FROM tx_bonus_payment "
        "WHERE run_year = %s AND run_month = %s",
        (year, month),
    )

    cursor.execute(
        "DELETE FROM tx_carry_over_balance "
        "WHERE withheld_run_year = %s AND withheld_run_month = %s",
        (year, month),
    )

    # Revert any closures done in this run back to open
    cursor.execute(
        """UPDATE tx_carry_over_balance
              SET is_open              = TRUE,
                  released_amount      = NULL,
                  released_run_year    = NULL,
                  released_run_month   = NULL,
                  released_status_code = NULL,
                  updated_at           = NOW()
            WHERE released_run_year  = %s
              AND released_run_month = %s""",
        (year, month),
    )

    # ----- Write each payment + manage carry-over ------------------------
    inserted_count = 0
    co_opened_count = 0
    co_closed_count = 0
    co_no_prior_count = 0

    for p in payments:
        # Pull audit signals
        audit = p.audit_json or {}
        timing = audit.get("payment_timing", {}) or {}
        flags = timing.get("status_flags", {}) or {}
        tier_audit = audit.get("tier", {}) or {}

        # Office derivation
        if p.case_id not in case_office_id_map:
            raise RuntimeError(
                f"persist_payments: case_id={p.case_id} not in "
                f"case_office_id_map. This shouldn't happen — every payment "
                f"should correspond to a tx_case row we already loaded."
            )
        office_id = case_office_id_map[p.case_id]

        # Contract id (Phase 7 — needed for carry-over matching across months)
        if p.case_id not in case_contract_id_map:
            raise RuntimeError(
                f"persist_payments: case_id={p.case_id} not in "
                f"case_contract_id_map. Every payment must correspond to a "
                f"loaded tx_case row."
            )
        contract_id = case_contract_id_map[p.case_id]

        # Tier metadata (defensive — calc_tier audit shape may evolve)
        tier_name = tier_audit.get("tier")
        target_val = tier_audit.get("target")
        actual_enrolled = (
            tier_audit.get("actual_enrolled")
            or tier_audit.get("enrolled")
        )
        base_rate = int(tier_audit.get("base_rate") or 0)

        # Split pct from timing audit (stored as string)
        split_pct_str = timing.get("split_pct", "1.0")

        # INSERT tx_bonus_payment (Phase 12b: 3 new columns appended)
        cursor.execute(
            """INSERT INTO tx_bonus_payment (
                    case_id, slot, staff_id, role_id, office_id,
                    tier, target, actual_enrolled, base_rate, split_pct,
                    tier_bonus, package_bonus, addon_bonus, priority_bonus,
                    presales_share_taken, flat_local_enrolment_bonus,
                    advance_offset, gross_bonus, net_payable,
                    priority_withheld_amount, priority_unlocked_amount,
                    priority_schedule_type,
                    calc_notes, audit_json,
                    run_year, run_month,
                    calculated_at, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    NOW(), NOW()
                )""",
            (
                p.case_id, p.slot_label.upper(), p.staff_id, p.role_id, office_id,
                tier_name, target_val, actual_enrolled, base_rate, split_pct_str,
                p.tier_bonus, p.package_bonus, p.addon_bonus, p.priority_bonus,
                p.presales_share_taken, p.flat_local_enrolment_bonus,
                p.advance_offset, p.gross_bonus, p.net_payable,
                p.priority_withheld_amount, p.priority_unlocked_amount,
                p.priority_schedule_type,
                p.calc_notes, Json(_to_jsonable(audit)),
                year, month,
            ),
        )
        inserted_count += 1

        # ----- tx_carry_over_balance management --------------------------
        status_code = timing.get("status_code", "")

        # Open a new carry-over when is_current_enrolled fires with
        # a positive withholding portion.
        if flags.get("is_current_enrolled"):
            base_after_split = int(timing.get("base_payable_after_split") or 0)
            carry_over_amount = max(0, p.gross_bonus - base_after_split)
            if carry_over_amount > 0:
                # Defensively clear any open row for this CONTRACT + staff.
                # (Phase 7 fix: match by contract_id, not case_id, because
                # tx_case has a different case_id per monthly run.)
                cursor.execute(
                    """DELETE FROM tx_carry_over_balance
                        WHERE staff_id = %s
                          AND is_open  = TRUE
                          AND case_id IN (
                              SELECT id FROM tx_case
                               WHERE contract_id = %s
                          )""",
                    (p.staff_id, contract_id),
                )
                cursor.execute(
                    """INSERT INTO tx_carry_over_balance (
                            case_id, staff_id, withheld_amount,
                            withheld_run_year, withheld_run_month,
                            withheld_status_code, is_open
                        ) VALUES (%s, %s, %s, %s, %s, %s, TRUE)""",
                    (
                        p.case_id, p.staff_id, carry_over_amount,
                        year, month, status_code,
                    ),
                )
                co_opened_count += 1

        # Close an existing open balance when is_carry_over fires with
        # a tracked unlocked amount.
        # (Phase 7 fix: match by contract_id + staff_id, not case_id +
        # staff_id, because the open balance was opened in a different
        # month and has a different case_id.)
        if flags.get("is_carry_over"):
            unlocked = int(timing.get("unlocked_from_prior") or 0)
            if unlocked > 0:
                cursor.execute(
                    """UPDATE tx_carry_over_balance
                          SET is_open              = FALSE,
                              released_amount      = %s,
                              released_run_year    = %s,
                              released_run_month   = %s,
                              released_status_code = %s,
                              updated_at           = NOW()
                        WHERE staff_id = %s
                          AND is_open  = TRUE
                          AND case_id IN (
                              SELECT id FROM tx_case
                               WHERE contract_id = %s
                          )""",
                    (
                        unlocked, year, month, status_code,
                        p.staff_id, contract_id,
                    ),
                )
                if cursor.rowcount > 0:
                    co_closed_count += 1
            else:
                # is_carry_over fired but no prior was tracked — the
                # engine already surfaced the CARRY_OVER_NO_PRIOR warning;
                # we just count it for the persist summary.
                co_no_prior_count += 1

    print(
        f"Persisted {inserted_count} tx_bonus_payment rows. "
        f"Carry-overs: opened={co_opened_count}, "
        f"closed={co_closed_count}, "
        f"no-prior={co_no_prior_count}."
    )


def persist_priority_quota_tracker(
    cursor: Any,
    *,
    year: int,
    month: int,
    priority_quota_state: dict[int, dict],
) -> None:
    """
    Phase 12b: Persist ctx.priority_quota_state back to
    tx_priority_quota_tracker.

    Called after persist_payments. The engine has been mutating
    priority_quota_state in place during the run, incrementing counts when
    SPLIT-rule priority cases first appear (gated by
    ref_priority_group.priority_split_rule_type = 'CURRENT_ENROL_25_25_50').

    For 2024 reruns, priority_quota_state stays empty because all 2024
    priority groups remain on STANDARD_50_50 — payment_timing's increment
    block doesn't fire, so no UPSERT happens and the tracker table stays
    pristine.

    Idempotent: ON CONFLICT DO UPDATE means re-running the same month
    overwrites prior tracker values rather than double-counting. The
    seen_priority_case_ids dedup inside payment_timing prevents
    multi-slot duplicates within one run.
    """
    if not priority_quota_state:
        print("Priority quota tracker: no state to persist (no SPLIT-rule "
              "increments this run).")
        return

    upserted_count = 0
    for pli_id, tracker in priority_quota_state.items():
        cursor.execute(
            """INSERT INTO tx_priority_quota_tracker (
                    priority_list_institution_id,
                    enrolment_count_direct,
                    enrolment_count_sub,
                    last_updated_run_year,
                    last_updated_run_month
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (priority_list_institution_id) DO UPDATE SET
                    enrolment_count_direct  = EXCLUDED.enrolment_count_direct,
                    enrolment_count_sub     = EXCLUDED.enrolment_count_sub,
                    last_updated_run_year   = EXCLUDED.last_updated_run_year,
                    last_updated_run_month  = EXCLUDED.last_updated_run_month,
                    updated_at              = NOW()""",
            (
                pli_id,
                tracker.get('count_direct', 0),
                tracker.get('count_sub', 0),
                year,
                month,
            ),
        )
        upserted_count += 1

    print(f"Priority quota tracker: upserted {upserted_count} row(s).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print(f"Engine run: year={args.year} month={args.month} "
          f"persist={args.persist} limit={args.limit} "
          f"contract_id={args.contract_id!r}")

    with get_connection() as conn:
        # Reference data uses the existing data layer (uses a default cursor)
        ref = load_reference_data(conn)
        print(f"Loaded ReferenceData: "
              f"{len(ref.institutions)} institutions, "
              f"{len(ref.staff)} staff, "
              f"{len(ref.priority_lists)} priority lists, "
              f"{len(ref.priority_list_institutions)} junction rows.")

        # Phase 12b: priority quota tracker (priority_list_institution_id →
        # {'count_direct': int, 'count_sub': int, ...}). Loaded outside the
        # dict-cursor block because load_priority_quota_tracker opens its own
        # cursor on the connection.
        priority_quota_tracker = load_priority_quota_tracker(conn)
        print(f"Priority quota tracker loaded: "
              f"{len(priority_quota_tracker)} priority-list-institution(s) "
              f"with prior-period enrolment counts.")

        with conn.cursor(row_factory=dict_row) as cursor:
            # YTD aggregator (Phase 8: returns PriorityYtdSnapshot with
            # channel splits, not the prior pair of dicts).
            priority_ytd = aggregate_ytd(
                cursor, year=args.year, month=args.month,
            )
            print(f"YTD: {len(priority_ytd.by_list)} list-channel buckets, "
                  f"{len(priority_ytd.by_list_institution)} carve-out buckets")

            # Open carry-over balances → prior_withholdings keyed by
            # (contract_id, staff_id)
            prior_withholdings = load_open_carry_overs(cursor)
            print(f"Open carry-over balances loaded: "
                  f"{len(prior_withholdings)} (contract, staff) pairs with "
                  f"pending withholdings.")

            # Phase 12b: prior priority withholdings keyed by
            # (contract_id, staff_id). Net = SUM(withheld) - SUM(unlocked)
            # across the case's history; engine releases this on visa
            # receipt under SPLIT_25_25_50.
            prior_priority_withholdings = load_prior_priority_withholdings(cursor)
            print(f"Prior priority withholdings loaded: "
                  f"{len(prior_priority_withholdings)} (contract, staff) "
                  f"pairs with unreleased priority withholds.")

            # Current-month enrolment counts → enrolments_by_staff_office.
            # Wired (was previously stubbed). Drives UNDER/TARGET/OVER tier
            # selection in classify_tier.
            enrolments = load_enrolments_by_staff_office(
                cursor, year=args.year, month=args.month,
            )
            total_enrolments = sum(enrolments.values())
            print(f"Enrolments this period: {total_enrolments} across "
                  f"{len(enrolments)} (staff, office) bucket(s).")

            ctx = build_run_context(
                priority_ytd, prior_withholdings, enrolments, ref,
                year=args.year, month=args.month,
                priority_quota_tracker=priority_quota_tracker,
                prior_priority_withholdings=prior_priority_withholdings,
            )

            # Load cases
            case_rows = load_cases(
                cursor,
                year=args.year, month=args.month,
                contract_id=args.contract_id,
                limit=args.limit,
            )
            print(f"Loaded {len(case_rows)} tx_case row(s) for period.")

            # Build the case_id → office_id and case_id → contract_id maps
            # for persist (Phase 7 fix: contract_id needed for cross-month
            # carry-over matching).
            case_office_id_map: dict[int, int] = {
                r["id"]: r["case_office_id"] for r in case_rows
            }
            case_contract_id_map: dict[int, str] = {
                r["id"]: r["contract_id"] for r in case_rows
            }

            # Adapt + run engine
            skipped: list[tuple[dict, str]] = []
            errored: list[tuple[dict, BaseException]] = []
            payments: list[Any] = []
            adapted_count = 0

            for case_row in case_rows:
                contract_id = case_row.get("contract_id", "<no-id>")

                try:
                    case_input = adapt_case(case_row, ref)
                except CaseNotAdaptableError as e:
                    skipped.append((case_row, e.reason))
                    continue
                except Exception as e:
                    errored.append((case_row, e))
                    print(f"\n[ADAPT-ERROR] {contract_id}: {type(e).__name__}: {e}")
                    traceback.print_exc()
                    continue

                adapted_count += 1

                try:
                    case_payments = calculate_case(case_input, ctx, ref)
                except Exception as e:
                    errored.append((case_row, e))
                    print(f"\n[CALC-ERROR] {contract_id}: {type(e).__name__}: {e}")
                    traceback.print_exc()
                    continue

                if case_payments:
                    print(f"\n  contract={contract_id} → {len(case_payments)} payment row(s):")
                    for p in case_payments:
                        _print_payment(p)
                    payments.extend(case_payments)

            print_summary(
                total_cases=len(case_rows),
                adapted=adapted_count,
                skipped=skipped,
                errored=errored,
                payments=payments,
            )

            if args.persist:
                persist_payments(
                    cursor,
                    year=args.year, month=args.month,
                    payments=payments,
                    case_office_id_map=case_office_id_map,
                    case_contract_id_map=case_contract_id_map,
                )

                # Phase 12b: write back ctx.priority_quota_state. Runs
                # AFTER persist_payments so that if persist throws, the
                # tracker stays consistent with the (untouched) bonus-
                # payment rows. For 2024 (all groups STANDARD_50_50),
                # priority_quota_state stays empty and this is a no-op.
                persist_priority_quota_tracker(
                    cursor,
                    year=args.year, month=args.month,
                    priority_quota_state=ctx.priority_quota_state,
                )

                # Phase 8: retroactive priority catch-up.
                # Runs after persist so it sees this month's just-written
                # rows, then fills in retroactive priority for any (case,
                # slot) whose threshold was met by end of this month.
                # Idempotent: persist_payments wiped this period's rows
                # first, including any prior finalizer-written rows.
                print()
                # fin_summary = priority_finalizer.run(
                #    cursor,
                #    year=args.year,
                #    month=args.month,
                #    ref=ref,
                #)
                #print(
                #    f"Priority finalizer: examined={fin_summary['rows_examined']} "
                #    f"paid={fin_summary['rows_paid']} "
                #    f"amount_total={fin_summary['amount_paid_total']:,} đ "
                #    f"skipped(threshold)={fin_summary['skipped_threshold_not_met']} "
                #    f"skipped(no-target)={fin_summary['skipped_no_target_row']} "
                #    f"skipped(zero-pct)={fin_summary['skipped_no_bonus_pct']}"
                #)

                conn.commit()
                print("Committed to DB.")
            else:
                print("\n(dry-run; no DB writes. Add --persist to write outputs.)")

    return 0 if not errored else 1


if __name__ == "__main__":
    sys.exit(main())
