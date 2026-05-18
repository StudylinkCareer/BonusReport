"""
backend/engine/reversal_check.py

Engine re-run safety check and priority impact assessment (Phase 13b).

Provides:
  * check_no_live_payments — refuses re-run when live (non-reversed)
    tx_bonus_payment rows exist for the target staff/period.
  * snapshot_priority_quota_tracker — captures tx_priority_quota_tracker
    state before a re-run mutates it.
  * compute_priority_impact_warnings — after a staff-scoped re-run,
    identifies other staff whose live priority payments may now be stale
    because tracker counts shifted for a priority partner.

All functions are pure (no commits, no side effects beyond cursor reads).
They are called from persist_payments before/after the actual INSERT block.

The cascade itself (reverse + re-run for affected staff) lives in
api_runner.run_engine_cascade_api — not here. This module just produces
the data the cascade needs.

Names are intentionally NOT included in the warning structures returned
here — only IDs. The api_runner layer enriches with staff_name and
partner_name from ReferenceData at serialisation time, keeping this
module free of cross-module dependencies.

Phase 13b deliverable — Session B+ continuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LivePaymentRowsExistError(Exception):
    """Raised when the engine refuses to persist because live payment rows
    exist for one or more (run_year, run_month, staff_id) combinations.

    The reverse + re-run flow (POST /api/bonus/reverse) must be used first
    to flag the existing rows as reversed before new rows can be written.

    Attributes
    ----------
    year, month : the run period that was refused
    conflicts : list of (staff_id, live_row_count) tuples
    """

    def __init__(
        self,
        year: int,
        month: int,
        conflicts: list[tuple[int, int]],
    ) -> None:
        self.year = year
        self.month = month
        self.conflicts = conflicts
        details = "; ".join(
            f"staff_id={s}: {n} live rows" for s, n in conflicts
        )
        super().__init__(
            f"Refusing to persist bonus run for {year}-{month:02d}: "
            f"live payment rows already exist for these staff. "
            f"Reverse them first via POST /api/bonus/reverse. {details}"
        )


# ---------------------------------------------------------------------------
# Data classes — IDs only; names enriched at serialisation time
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AffectedStaffEntry:
    """One staff member with live priority payments potentially impacted by
    a re-run's tracker state change."""
    staff_id: int
    case_count: int
    total_priority_bonus: int


@dataclass(frozen=True)
class PriorityImpactWarning:
    """One warning describing a priority partner whose quota state shifted
    during a staff-scoped re-run, and the other staff with live priority
    payments touching that partner whose calculations may now be stale."""
    priority_list_institution_id: int
    institution_id: int
    count_delta_direct: int
    count_delta_sub: int
    potentially_affected_payments: list[AffectedStaffEntry]


# ---------------------------------------------------------------------------
# Precheck — refuse if live rows exist
# ---------------------------------------------------------------------------

def check_no_live_payments(
    conn,
    run_year: int,
    run_month: int,
    staff_ids: Iterable[int] | None = None,
) -> None:
    """Refuse if any live (non-reversed) tx_bonus_payment rows exist for the
    given (run_year, run_month, staff_id) combinations.

    Called from persist_payments before any INSERT, ONLY when persist=True.
    Dry runs skip this check.

    Parameters
    ----------
    conn : psycopg connection (opens its own cursor for the precheck query)
    run_year, run_month : target run period
    staff_ids : iterable of staff_id values to check. If None, the entire
        period is checked (any staff_id with live rows triggers the refusal).
        For staff-scoped re-runs, pass a single-element list.

    Raises
    ------
    LivePaymentRowsExistError
        If any live rows exist for the queried combinations.
    """
    if staff_ids is None:
        # Period-wide check
        sql = """
            SELECT staff_id, COUNT(*)::int AS live_count
              FROM tx_bonus_payment
             WHERE run_year = %s
               AND run_month = %s
               AND reversal_id IS NULL
             GROUP BY staff_id
             ORDER BY staff_id
        """
        params: tuple = (run_year, run_month)
    else:
        staff_id_list = list(staff_ids)
        if not staff_id_list:
            return  # nothing to check
        sql = """
            SELECT staff_id, COUNT(*)::int AS live_count
              FROM tx_bonus_payment
             WHERE run_year = %s
               AND run_month = %s
               AND reversal_id IS NULL
               AND staff_id = ANY(%s)
             GROUP BY staff_id
             ORDER BY staff_id
        """
        params = (run_year, run_month, staff_id_list)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if rows:
        # get_connection() defaults to dict_row factory — rows are dicts,
        # not tuples. SQL above aliases the two columns as staff_id and
        # live_count.
        conflicts = [(int(r["staff_id"]), int(r["live_count"])) for r in rows]
        raise LivePaymentRowsExistError(run_year, run_month, conflicts)


# ---------------------------------------------------------------------------
# Priority quota snapshot
# ---------------------------------------------------------------------------

def snapshot_priority_quota_tracker(conn) -> dict[int, dict[str, int]]:
    """Capture current state of tx_priority_quota_tracker for delta comparison.

    Returns a dict keyed by priority_list_institution_id, each value being
    a dict {'count_direct': int, 'count_sub': int}. Empty dict if the tracker
    has no rows (typical for 2024-only environments where all priority
    groups are STANDARD_50_50).

    Used to detect quota state changes across a re-run: call once BEFORE
    persist_payments to capture old state, then again AFTER
    persist_priority_quota_tracker to capture new state. Feed both into
    compute_priority_impact_warnings.
    """
    sql = """
        SELECT priority_list_institution_id,
               COALESCE(enrolment_count_direct, 0) AS count_direct,
               COALESCE(enrolment_count_sub, 0)    AS count_sub
          FROM tx_priority_quota_tracker
    """
    snapshot: dict[int, dict[str, int]] = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            # dict_row cursor — use column names, not indices.
            pli_id = row["priority_list_institution_id"]
            direct = row["count_direct"]
            sub = row["count_sub"]
            snapshot[int(pli_id)] = {
                "count_direct": int(direct),
                "count_sub": int(sub),
            }
    return snapshot


# ---------------------------------------------------------------------------
# Priority impact warnings
# ---------------------------------------------------------------------------

def compute_priority_impact_warnings(
    conn,
    run_year: int,
    run_month: int,
    staff_id_rerun: int,
    old_tracker_snapshot: dict[int, dict[str, int]],
    new_tracker_state: dict[int, dict[str, int]],
) -> list[PriorityImpactWarning]:
    """After a staff-scoped re-run, identify other staff whose live priority
    payments may be stale because tracker counts shifted for a priority
    partner they have cases with.

    Algorithm:
      1. Diff old_tracker_snapshot vs new_tracker_state — find priority_list_
         institution_ids where count_direct or count_sub changed.
      2. For each changed PLI, query tx_bonus_payment for live priority rows
         in this period where:
           - staff_id is NOT the staff being re-run (they're already getting fresh rows)
           - priority_bonus > 0 (no priority component → no staleness risk)
           - the case's institution maps to this PLI
      3. Group results by staff_id and emit a PriorityImpactWarning per
         changed PLI that has affected staff.

    Returns
    -------
    list of PriorityImpactWarning
        Empty list when no quota state changed OR when no other staff have
        live priority rows touching the changed partners.

    Parameters
    ----------
    conn : psycopg connection
    run_year, run_month : the run period being processed
    staff_id_rerun : the staff_id being re-run (excluded from "other staff")
    old_tracker_snapshot : output of snapshot_priority_quota_tracker BEFORE
        the re-run mutated state.
    new_tracker_state : current state AFTER persist_priority_quota_tracker,
        same shape as the snapshot.
    """
    # Step 1: Find PLIs whose count shifted
    all_pli_ids = set(old_tracker_snapshot.keys()) | set(new_tracker_state.keys())
    changed: list[tuple[int, int, int]] = []  # (pli_id, delta_direct, delta_sub)

    zero = {"count_direct": 0, "count_sub": 0}
    for pli_id in all_pli_ids:
        old = old_tracker_snapshot.get(pli_id, zero)
        new = new_tracker_state.get(pli_id, zero)
        d_direct = int(new.get("count_direct", 0)) - int(old.get("count_direct", 0))
        d_sub = int(new.get("count_sub", 0)) - int(old.get("count_sub", 0))
        if d_direct != 0 or d_sub != 0:
            changed.append((pli_id, d_direct, d_sub))

    if not changed:
        return []

    # Step 2 & 3: For each changed PLI, find affected staff
    warnings: list[PriorityImpactWarning] = []

    affected_query = """
        SELECT bp.staff_id,
               COUNT(*)::int AS case_count,
               COALESCE(SUM(bp.priority_bonus), 0)::int AS total_priority_bonus,
               pli.institution_id
          FROM tx_bonus_payment bp
          JOIN tx_case c
            ON c.id = bp.case_id
          JOIN ref_priority_list_institution pli
            ON pli.institution_id = c.institution_id
         WHERE bp.run_year = %s
           AND bp.run_month = %s
           AND bp.reversal_id IS NULL
           AND bp.priority_bonus > 0
           AND bp.staff_id <> %s
           AND pli.id = %s
         GROUP BY bp.staff_id, pli.institution_id
         ORDER BY bp.staff_id
    """

    for pli_id, d_direct, d_sub in changed:
        with conn.cursor() as cur:
            cur.execute(
                affected_query,
                (run_year, run_month, staff_id_rerun, pli_id),
            )
            rows = cur.fetchall()

        if not rows:
            # Quota shifted but no other staff have live priority rows here
            continue

        # dict_row cursor — use column names from the SQL SELECT list above.
        institution_id = int(rows[0]["institution_id"])
        affected = [
            AffectedStaffEntry(
                staff_id=int(r["staff_id"]),
                case_count=int(r["case_count"]),
                total_priority_bonus=int(r["total_priority_bonus"]),
            )
            for r in rows
        ]

        warnings.append(
            PriorityImpactWarning(
                priority_list_institution_id=pli_id,
                institution_id=institution_id,
                count_delta_direct=d_direct,
                count_delta_sub=d_sub,
                potentially_affected_payments=affected,
            )
        )

    return warnings
