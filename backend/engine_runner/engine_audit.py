"""
backend/engine_runner/engine_audit.py

Engine audit recorder — populates tx_engine_run and tx_engine_row_write
for every engine invocation.

Per BonusReport Design Spec v1.0 §11. This module is the FORENSIC BASELINE
instrumentation: it captures every payment row touched by the existing
period-wide engine without changing the engine's behaviour. Once this
instrumentation has been running in production for a while we have a
verifiable baseline against which the case-scoped refactor (planned for
a later phase) can be compared.

Contract
--------
Three public surfaces:

  begin_engine_run(cursor, *, run_type, trigger_reason, ...) -> int
      INSERTs a tx_engine_run row with status='IN_PROGRESS'. Returns the
      new run_id. Call once at the start of each engine invocation.

  capture_pre_writes(cursor, run_id, *, year, month, staff_id=None)
      Before persist_payments DELETEs anything: SELECTs the rows about to
      be wiped and stashes them in a Python-side dict keyed by
      (case_id, slot). Returns the dict; caller passes it back into
      record_post_writes after the INSERT block. This gives us the
      OLD_VALUE for any row that's effectively being UPDATEd (deleted
      then re-inserted with the same identity) plus the OLD_VALUE for any
      row that disappears entirely (effective DELETE — recorded as a
      pseudo-write with action='UPDATE' to a soft-deleted state).

      No actual DB writes happen here — it's a read-only snapshot.

  record_post_writes(cursor, run_id, pre_writes, *, year, month, staff_id=None,
                     override_preserved_by_payment_id=None)
      After persist_payments has finished INSERTing: queries the just-
      written rows and writes one tx_engine_row_write entry per row:
        - INSERT       : present in post-state, no matching pre-state
        - UPDATE       : present in post-state, matching pre-state, values
                         differ
        - NO_CHANGE    : present in post-state, matching pre-state, values
                         identical (the recompute happened to produce the
                         same numbers — useful forensic signal)

      override_preserved_by_payment_id is an optional dict mapping
      bonus_payment_id → bool. When provided, the override_preserved
      column is set accordingly. (For the baseline run, the existing
      engine writes the override fresh from the override table on every
      run, so override_preserved is technically always 'rewritten from
      source', not 'preserved across a no-touch recompute'. We default
      it to True when an override amount is non-zero in the new row,
      reflecting the user-visible reality that the override persisted.)

  finalize_engine_run(cursor, run_id, *, status, error_message=None,
                       rows_inserted, rows_updated, rows_unchanged)
      UPDATEs the tx_engine_run row with completion timestamp, status
      ('SUCCESS' | 'FAILED'), counts, and optional error message.

The module owns no transactions. The caller's cursor is used; the
caller's transaction holds. If the caller rolls back, the audit rows
roll back with everything else (which is the correct behaviour — if the
engine run aborted, the audit shouldn't claim it happened).

Why a Python-side pre-state dict rather than a fancier SQL trigger
approach: triggers would be invisible to the application code and harder
to reason about during the refactor. The pre/post pattern here is
explicit, debuggable, and stays inside the engine_runner module.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Columns we snapshot. Match the INSERT column list in persist_payments
# (cli.py line ~847) plus the row identity columns. If persist_payments'
# INSERT list changes, this list MUST be updated to match.
# ---------------------------------------------------------------------------

_SNAPSHOT_COLUMNS = (
    "id",
    "case_id", "slot", "staff_id", "role_id", "office_id",
    "tier", "target", "actual_enrolled", "base_rate", "split_pct",
    "tier_bonus", "package_bonus", "addon_bonus", "priority_bonus",
    "presales_share_taken", "flat_local_enrolment_bonus",
    "advance_offset", "gross_bonus", "net_payable",
    "priority_withheld_amount", "priority_unlocked_amount",
    "priority_schedule_type",
    "mgmt_override_amount", "mgmt_override_reason",
    "calc_notes",
    "run_year", "run_month",
    "calculated_at",
    # New Phase 15d columns. These were backfilled to NORMAL/source=run on
    # all legacy rows so they're safe to snapshot now.
    "source_period_year", "source_period_month", "adjustment_type",
    # Identity / state columns relevant to audit comparison
    "reversal_id", "reversed_at", "published_at",
)


def _to_jsonable(obj: Any) -> Any:
    """Convert a value to something json.dumps can serialise.

    Mirrors the helper in cli.py — kept local to avoid a cross-module
    import that would force a circular dependency.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def _row_to_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a DB row (dict from dict_row cursor) to a JSON-safe dict
    suitable for storage in *_value_json.
    """
    return {col: _to_jsonable(row.get(col)) for col in _SNAPSHOT_COLUMNS}


# ---------------------------------------------------------------------------
# Public: begin_engine_run
# ---------------------------------------------------------------------------

def begin_engine_run(
    cursor: Any,
    *,
    run_type: str,
    trigger_reason: str,
    triggered_by_user_id: int | None = None,
    case_ids_scope: list[int] | None = None,
    staff_ids_affected: list[int] | None = None,
    period_year: int | None = None,
    period_month: int | None = None,
) -> int:
    """Insert a tx_engine_run row with status='IN_PROGRESS' and return its id.

    All parameters except run_type and trigger_reason are optional. The row
    is finalised by a later finalize_engine_run() call which sets
    completed_at, status, counts, and (if applicable) error_message.

    run_type must be one of: ORIGINAL, RECALC, PROFORMA, DELTA, REVERSAL
    (CHECK constraint on the table will reject anything else).
    """
    cursor.execute(
        """
        INSERT INTO tx_engine_run (
            run_type,
            triggered_by_user_id,
            trigger_reason,
            case_ids_scope,
            staff_ids_affected,
            period_year,
            period_month,
            started_at,
            status
        ) VALUES (
            %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, NOW(), 'IN_PROGRESS'
        )
        RETURNING id
        """,
        (
            run_type,
            triggered_by_user_id,
            trigger_reason,
            json.dumps(case_ids_scope or []),
            json.dumps(staff_ids_affected or []),
            period_year,
            period_month,
        ),
    )
    row = cursor.fetchone()
    run_id = int(row["id"])
    log.info(
        "engine_audit: begin run_id=%d type=%s period=%s-%s reason=%r",
        run_id, run_type,
        period_year, period_month,
        trigger_reason,
    )
    return run_id


# ---------------------------------------------------------------------------
# Public: capture_pre_writes
# ---------------------------------------------------------------------------

def capture_pre_writes(
    cursor: Any,
    run_id: int,
    *,
    year: int,
    month: int,
    staff_id: int | None = None,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Snapshot the tx_bonus_payment rows that are about to be deleted.

    Called by persist_payments AFTER the precheck (so the rows we see are
    the rows that will be wiped) and BEFORE the DELETE itself. We capture
    every column we care about into a Python-side dict keyed by
    (case_id, slot). This dict is the "old state" that record_post_writes
    will diff against after the INSERT block runs.

    The query scoping matches persist_payments' DELETE scope exactly:
      - if staff_id is given: WHERE run_year, run_month, staff_id, NOT reversed
      - else: WHERE run_year, run_month, NOT reversed
    """
    if staff_id is not None:
        sql = """
            SELECT """ + ", ".join(_SNAPSHOT_COLUMNS) + """
            FROM tx_bonus_payment
            WHERE run_year = %s AND run_month = %s
              AND staff_id = %s
              AND reversal_id IS NULL
        """
        params: tuple = (year, month, staff_id)
    else:
        sql = """
            SELECT """ + ", ".join(_SNAPSHOT_COLUMNS) + """
            FROM tx_bonus_payment
            WHERE run_year = %s AND run_month = %s
              AND reversal_id IS NULL
        """
        params = (year, month)

    cursor.execute(sql, params)
    pre_state: dict[tuple[int, str], dict[str, Any]] = {}
    for row in cursor.fetchall():
        key = (int(row["case_id"]), str(row["slot"]))
        pre_state[key] = _row_to_snapshot(row)

    log.info(
        "engine_audit: run_id=%d captured %d pre-write rows",
        run_id, len(pre_state),
    )
    return pre_state


# ---------------------------------------------------------------------------
# Public: record_post_writes
# ---------------------------------------------------------------------------

def record_post_writes(
    cursor: Any,
    run_id: int,
    pre_writes: dict[tuple[int, str], dict[str, Any]],
    *,
    year: int,
    month: int,
    staff_id: int | None = None,
) -> tuple[int, int, int]:
    """Diff the post-write state against the pre-write snapshot and write
    one tx_engine_row_write entry per row.

    Returns (rows_inserted, rows_updated, rows_unchanged).

    Algorithm:
      1. Query the post-write rows in the same scope as pre_writes.
      2. For each post-row, look for a matching pre-row by (case_id, slot).
         - No match → INSERT (no old_value).
         - Match, values identical (excluding id and timestamps) → NO_CHANGE.
         - Match, values differ → UPDATE (old_value = pre-row).
      3. For pre-rows without a matching post-row: rare in today's engine
         (the period-wide rewrite reinserts everything), but possible if a
         case's slot assignment changed mid-period. Recorded as an
         UPDATE to a soft-deleted state for forensic completeness — these
         are the rows the engine effectively eliminated.

    Override preservation flag:
      For each row where mgmt_override_amount is non-NULL and non-zero
      in the post-state AND a matching pre-state row also had a non-NULL,
      non-zero mgmt_override_amount, override_preserved is set TRUE. This
      captures the user-visible fact that the override survived the
      engine's read-from-source-and-rewrite cycle.
    """
    # Query post-state with the same scoping as pre-state
    if staff_id is not None:
        sql = """
            SELECT """ + ", ".join(_SNAPSHOT_COLUMNS) + """
            FROM tx_bonus_payment
            WHERE run_year = %s AND run_month = %s
              AND staff_id = %s
              AND reversal_id IS NULL
        """
        params: tuple = (year, month, staff_id)
    else:
        sql = """
            SELECT """ + ", ".join(_SNAPSHOT_COLUMNS) + """
            FROM tx_bonus_payment
            WHERE run_year = %s AND run_month = %s
              AND reversal_id IS NULL
        """
        params = (year, month)

    cursor.execute(sql, params)
    post_rows = cursor.fetchall()

    rows_inserted = 0
    rows_updated = 0
    rows_unchanged = 0

    seen_keys: set[tuple[int, str]] = set()

    # Columns to exclude from the diff comparison (these change on every
    # write even when the engine's "real" output is identical).
    NOISE_COLUMNS = {"id", "calculated_at"}

    for row in post_rows:
        key = (int(row["case_id"]), str(row["slot"]))
        seen_keys.add(key)
        new_snap = _row_to_snapshot(row)
        old_snap = pre_writes.get(key)
        payment_id = int(row["id"])

        # Determine override_preserved
        new_override = row.get("mgmt_override_amount")
        new_override_active = new_override is not None and int(new_override) != 0
        old_override = old_snap.get("mgmt_override_amount") if old_snap else None
        old_override_active = (
            old_override is not None and old_override != 0
            if old_snap else False
        )
        override_preserved = new_override_active and old_override_active

        if old_snap is None:
            # No matching pre-row → INSERT
            action = "INSERT"
            old_value_param: Any = None
            rows_inserted += 1
        else:
            # Diff the snapshots (ignoring noise columns)
            old_compare = {k: v for k, v in old_snap.items() if k not in NOISE_COLUMNS}
            new_compare = {k: v for k, v in new_snap.items() if k not in NOISE_COLUMNS}
            if old_compare == new_compare:
                action = "NO_CHANGE"
                rows_unchanged += 1
            else:
                action = "UPDATE"
                rows_updated += 1
            old_value_param = json.dumps(old_snap)

        cursor.execute(
            """
            INSERT INTO tx_engine_row_write (
                engine_run_id, bonus_payment_id, action,
                old_value_json, new_value_json, override_preserved
            ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
            """,
            (
                run_id, payment_id, action,
                old_value_param,
                json.dumps(new_snap),
                override_preserved,
            ),
        )

    # Pre-rows without a matching post-row: these existed before, don't
    # exist now. Today's engine doesn't produce this case (period-wide
    # rewrite re-inserts everything), but staff-scoped re-runs theoretically
    # could if a case's staff assignment changed. Record them for
    # forensic completeness.
    for key, old_snap in pre_writes.items():
        if key in seen_keys:
            continue
        # The original payment_id is in old_snap['id']. The row no longer
        # exists in tx_bonus_payment, so FK to bonus_payment_id would fail.
        # Skip with a log entry. (If we later add a soft-delete pattern,
        # this branch becomes a proper UPDATE-to-deleted record.)
        log.warning(
            "engine_audit: run_id=%d pre-row case_id=%s slot=%s no longer "
            "exists in post-state; skipping audit entry (FK to deleted row)",
            run_id, key[0], key[1],
        )

    log.info(
        "engine_audit: run_id=%d wrote %d audit entries "
        "(INSERT=%d UPDATE=%d NO_CHANGE=%d)",
        run_id, rows_inserted + rows_updated + rows_unchanged,
        rows_inserted, rows_updated, rows_unchanged,
    )

    return rows_inserted, rows_updated, rows_unchanged


# ---------------------------------------------------------------------------
# Public: finalize_engine_run
# ---------------------------------------------------------------------------

def finalize_engine_run(
    cursor: Any,
    run_id: int,
    *,
    status: str,
    rows_inserted: int = 0,
    rows_updated: int = 0,
    rows_unchanged: int = 0,
    error_message: str | None = None,
) -> None:
    """Update the tx_engine_run row with completion details.

    status must be 'SUCCESS' or 'FAILED' (CHECK constraint).

    For FAILED runs, the counts represent rows that were committed before
    the failure. They may not be meaningful if the surrounding transaction
    rolled back — but if the transaction did roll back, the engine_run row
    itself rolls back too, so the user never sees a misleading FAILED row.
    """
    cursor.execute(
        """
        UPDATE tx_engine_run
        SET completed_at  = NOW(),
            status        = %s,
            rows_inserted = %s,
            rows_updated  = %s,
            rows_unchanged = %s,
            error_message = %s
        WHERE id = %s
        """,
        (
            status,
            rows_inserted,
            rows_updated,
            rows_unchanged,
            error_message,
            run_id,
        ),
    )
    log.info(
        "engine_audit: finalize run_id=%d status=%s ins=%d upd=%d unchg=%d",
        run_id, status, rows_inserted, rows_updated, rows_unchanged,
    )
