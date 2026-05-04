"""
backend/importer/writer.py

Persist CaseRecord and NoteRecord dataclasses (from transformer.py) to
the live database tables tx_case and tx_case_notes_staging.

Design choices (locked, see chat 2026-05-03):
  * Q1 = Option B: ON CONFLICT (contract_id, run_year, run_month) DO UPDATE.
    Re-importing a case overwrites its importer-controlled fields. Engine-
    populated fields (deferral_code, presales_*, vp_*, run_id, service_fee_id,
    target_owner_staff_id, case_transition, prior_month_rate, handover_flag)
    are left alone — engine re-runs after import to refresh them.
  * Q2 = Option A: a row-level write failure logs and continues. Only true
    DB exceptions (connection drop, etc.) bubble up to the orchestrator.
  * Q3 = Option A: notes for rows that couldn't be inserted go to
    tx_case_notes_staging with case_id = NULL. Run context (run_year,
    run_month) is captured on every note row regardless of orphan status.

The writer does NOT manage transactions. The orchestrator opens one
transaction per file run and commits or rolls back at the file boundary.

Tests: backend/tests/test_writer.py (uses uncommitted-then-rolled-back
connections so test data never persists).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.importer.transformer import CaseRecord, NoteRecord


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------

@dataclass
class WriteResult:
    """Counts what happened during a write batch.

    The orchestrator keeps one of these per file and reports summary at
    end-of-run. Mutated by the write_* functions in this module.
    """
    inserted: int = 0
    updated: int = 0
    rows_skipped: int = 0       # rows where transformer returned None
    notes_attached: int = 0     # notes written with a case_id
    notes_orphan: int = 0       # notes written with case_id = NULL
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "WriteResult") -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.rows_skipped += other.rows_skipped
        self.notes_attached += other.notes_attached
        self.notes_orphan += other.notes_orphan
        self.errors.extend(other.errors)


# ---------------------------------------------------------------------------
# tx_case write
# ---------------------------------------------------------------------------

# Importer-controlled columns. Engine columns are intentionally absent so
# the engine can later populate/refresh them without our writer disturbing
# its work.
_INSERT_COLUMNS = (
    "contract_id", "student_id", "student_name",
    "contract_signed_date", "course_start_date", "visa_received_date",
    "case_office_id", "country_id", "institution_id",
    "institution_text_raw",
    "referring_partner_id", "referring_sub_agent_id", "referring_agent_text_raw",
    "client_type_code", "application_status", "course_status",
    "counsellor_staff_id", "counsellor_role_id",
    "case_officer_staff_id", "case_officer_role_id",
    "referring_source_type", "import_status",
    "incentive_amount", "notes",
    "run_year", "run_month",
)


def _build_case_sql() -> str:
    """Build the upsert SQL string. Single source of truth for the column list."""
    placeholders = ", ".join(f"%({c})s" for c in _INSERT_COLUMNS)
    column_list  = ", ".join(_INSERT_COLUMNS)
    update_pairs = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _INSERT_COLUMNS
        if c not in ("contract_id", "run_year", "run_month")  # don't overwrite the conflict key
    )
    # The (xmax = 0) trick: when ON CONFLICT inserts, xmax stays 0; when it
    # updates, xmax is set to the current transaction id. So this gives us
    # a boolean indicating which path was taken.
    return f"""
        INSERT INTO tx_case ({column_list})
        VALUES ({placeholders})
        ON CONFLICT (contract_id, run_year, run_month) DO UPDATE SET
            {update_pairs}
        RETURNING id, (xmax = 0) AS was_inserted
    """


_CASE_SQL = _build_case_sql()


def write_case(cursor, record: CaseRecord) -> tuple[int, str]:
    """Upsert a CaseRecord into tx_case.

    Returns (case_id, action) where action is 'inserted' or 'updated'.

    Raises whatever psycopg raises on a real DB error (the orchestrator
    decides whether to abort the file or continue).
    """
    params = {col: getattr(record, col) for col in _INSERT_COLUMNS}
    cursor.execute(_CASE_SQL, params)
    row = cursor.fetchone()
    case_id = row["id"]
    action = "inserted" if row["was_inserted"] else "updated"
    log.info(
        "tx_case %s: contract=%s run=%d-%02d id=%d status=%s",
        action, record.contract_id, record.run_year, record.run_month,
        case_id, record.import_status,
    )
    return case_id, action


# ---------------------------------------------------------------------------
# tx_case_notes_staging write
# ---------------------------------------------------------------------------

_NOTE_SQL = """
    INSERT INTO tx_case_notes_staging
        (case_id, run_year, run_month, warning_type, raw_value, note)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


def write_notes(
    cursor,
    case_id: Optional[int],
    notes: list[NoteRecord],
    run_year: int,
    run_month: int,
) -> int:
    """Insert NoteRecords into tx_case_notes_staging.

    case_id may be None (orphan note for a row that couldn't be inserted).
    Returns the number of rows inserted. On empty input, returns 0 and
    issues no SQL.
    """
    if not notes:
        return 0
    rows = [
        (case_id, run_year, run_month, n.warning_type, n.raw_value, n.note)
        for n in notes
    ]
    cursor.executemany(_NOTE_SQL, rows)
    if case_id is None:
        log.info(
            "Logged %d orphan note(s) for run %d-%02d (skipped row).",
            len(rows), run_year, run_month,
        )
    else:
        log.info(
            "Logged %d note(s) for tx_case id=%d run=%d-%02d.",
            len(rows), case_id, run_year, run_month,
        )
    return len(rows)


# ---------------------------------------------------------------------------
# High-level helper: write one transformer result
# ---------------------------------------------------------------------------

def write_transformer_output(
    cursor,
    record: Optional[CaseRecord],
    notes: list[NoteRecord],
    *,
    run_year: int,
    run_month: int,
    result: WriteResult,
) -> None:
    """Persist one (record, notes) pair from transformer.transform_row().

    Q2 policy: per-row write failures are caught, logged, and counted in
    result.errors. The exception does NOT propagate so the orchestrator
    can keep processing the file. Real DB-level exceptions (broken
    connection, etc.) are not caught here — they bubble up and the
    orchestrator decides whether to abort the file.
    """
    if record is None:
        # Skipped row. Notes describe why; persist them as orphans.
        try:
            written = write_notes(cursor, None, notes, run_year, run_month)
            result.rows_skipped += 1
            result.notes_orphan += written
        except Exception as exc:
            msg = f"Failed to log orphan notes for skipped row: {exc!r}"
            log.exception(msg)
            result.errors.append(msg)
        return

    try:
        case_id, action = write_case(cursor, record)
        if action == "inserted":
            result.inserted += 1
        else:
            result.updated += 1
        if notes:
            written = write_notes(cursor, case_id, notes, run_year, run_month)
            result.notes_attached += written
    except Exception as exc:
        msg = (
            f"Failed to write tx_case for contract={record.contract_id} "
            f"run={record.run_year}-{record.run_month:02d}: {exc!r}"
        )
        log.exception(msg)
        result.errors.append(msg)
