"""
backend/importer/writer.py

Persist CaseRecord and NoteRecord dataclasses (from transformer.py) to
the live database tables tx_case and tx_case_notes_staging.

Design choices:

  * DEDUP RULE (Phase 15.1+, replaces the previous ON CONFLICT (contract_id,
    run_year, run_month) DO UPDATE rule):
        A new row is BLOCKED if an existing tx_case row has the same
        (contract_id, application_status). The writer returns the existing
        row's id and workflow_state so the orchestrator/UI can surface
        the right warn/error dialog (per Step 1 design). The importer
        itself never deletes, updates, or overrides — that's a separate
        user-confirmed action.

  * NEW ROWS get workflow_state = 'uploaded'. They wait there until a
    user explicitly moves them to in_review via the Uploaded pillar
    list view.

  * PER-ROW WRITE FAILURES are logged into result.errors and counted in
    result.rows_skipped. Real DB exceptions (connection drop, bad SQL)
    bubble up to the orchestrator, which decides whether to abort the
    file.

  * NOTES for blocked rows are written to tx_case_notes_staging with
    case_id = NULL (orphan). The new tx_case row was never created so
    there's nothing to attach them to.

  * NOTES for transformer-rejected rows (record is None) are also written
    as orphans. Same reasoning.

The writer does NOT manage transactions. The orchestrator owns the
per-file transaction.
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
class BlockedDetail:
    """Identifying info for one blocked row, surfaced to the orchestrator/UI."""
    contract_id: str
    application_status: Optional[str]
    student_name: str
    existing_case_id: int
    existing_workflow_state: str
    existing_run_year: int
    existing_run_month: int


@dataclass
class WriteResult:
    """Counts what happened during a write batch.

    Fields the orchestrator reports at end-of-file:
        inserted        : rows added to tx_case
        rows_skipped    : transformer returned None (data couldn't be transformed)
        blocked         : duplicate by (contract_id, application_status)
        notes_attached  : notes written with case_id populated
        notes_orphan    : notes written with case_id = NULL
        errors          : per-row exceptions (caught and continued)
        blocked_details : one BlockedDetail per blocked row, for UI handling

    `updated` is kept for backward-compat with any downstream parser; never
    incremented under the new dedup policy.
    """
    inserted: int = 0
    updated: int = 0
    rows_skipped: int = 0
    blocked: int = 0
    notes_attached: int = 0
    notes_orphan: int = 0
    errors: list[str] = field(default_factory=list)
    blocked_details: list[BlockedDetail] = field(default_factory=list)

    def merge(self, other: "WriteResult") -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.rows_skipped += other.rows_skipped
        self.blocked += other.blocked
        self.notes_attached += other.notes_attached
        self.notes_orphan += other.notes_orphan
        self.errors.extend(other.errors)
        self.blocked_details.extend(other.blocked_details)


# ---------------------------------------------------------------------------
# tx_case write
# ---------------------------------------------------------------------------

# Importer-controlled columns. Engine columns (deferral_code, presales_*,
# vp_*, run_id, etc.) and workflow_state are intentionally absent — the
# writer adds workflow_state = 'uploaded' explicitly in the INSERT.
_INSERT_COLUMNS = (
    "contract_id", "student_id", "student_name",
    "contract_signed_date", "course_start_date", "visa_received_date",
    "case_office_id", "country_id", "institution_id",
    "institution_text_raw",
    "referring_partner_id", "referring_sub_agent_id", "referring_agent_text_raw",
    "client_type_code", "application_status", "course_status",
    "counsellor_staff_id", "counsellor_role_id",
    "case_officer_staff_id", "case_officer_role_id",
    "pre_sales_staff_id",
    "referring_source_type", "import_status",
    "incentive_amount", "notes",
    "run_year", "run_month",
)


def _build_insert_sql() -> str:
    """Insert SQL with workflow_state hardcoded to 'uploaded' for new rows."""
    placeholders = ", ".join(f"%({c})s" for c in _INSERT_COLUMNS)
    column_list  = ", ".join(_INSERT_COLUMNS)
    return f"""
        INSERT INTO tx_case ({column_list}, workflow_state)
        VALUES ({placeholders}, 'uploaded')
        RETURNING id
    """


_INSERT_SQL = _build_insert_sql()


_DUPLICATE_CHECK_SQL = """
    SELECT id,
           workflow_state,
           run_year,
           run_month
      FROM tx_case
     WHERE contract_id = %s
       AND COALESCE(application_status, '') = COALESCE(%s, '')
     ORDER BY id DESC
     LIMIT 1
"""


def write_case(cursor, record: CaseRecord) -> tuple[int, str, Optional[BlockedDetail]]:
    """Try to insert a CaseRecord. Block if a duplicate exists.

    Returns:
        (case_id, action, blocked_detail) where
        - action == 'inserted'  -> case_id is the new row's id
                                   blocked_detail is None
        - action == 'blocked'   -> case_id is the EXISTING row's id
                                   blocked_detail carries existing workflow_state etc.

    Raises whatever psycopg raises on a real DB error.
    """
    # Step 1: check for existing row by (contract_id, application_status)
    cursor.execute(
        _DUPLICATE_CHECK_SQL,
        (record.contract_id, record.application_status),
    )
    existing = cursor.fetchone()

    if existing is not None:
        detail = BlockedDetail(
            contract_id=record.contract_id,
            application_status=record.application_status,
            student_name=record.student_name,
            existing_case_id=existing["id"],
            existing_workflow_state=existing["workflow_state"],
            existing_run_year=existing["run_year"],
            existing_run_month=existing["run_month"],
        )
        log.warning(
            "tx_case BLOCKED: contract=%s status=%r already exists "
            "(case_id=%d, workflow_state=%s, run=%d-%02d)",
            record.contract_id, record.application_status,
            existing["id"], existing["workflow_state"],
            existing["run_year"], existing["run_month"],
        )
        return existing["id"], "blocked", detail

    # Step 2: clean insert
    params = {col: getattr(record, col) for col in _INSERT_COLUMNS}
    cursor.execute(_INSERT_SQL, params)
    row = cursor.fetchone()
    case_id = row["id"]
    log.info(
        "tx_case inserted: contract=%s run=%d-%02d id=%d status=%s workflow_state=uploaded",
        record.contract_id, record.run_year, record.run_month,
        case_id, record.import_status,
    )
    return case_id, "inserted", None


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
    """Insert NoteRecords. case_id=None for orphans (skipped or blocked row)."""
    if not notes:
        return 0
    rows = [
        (case_id, run_year, run_month, n.warning_type, n.raw_value, n.note)
        for n in notes
    ]
    cursor.executemany(_NOTE_SQL, rows)
    if case_id is None:
        log.info(
            "Logged %d orphan note(s) for run %d-%02d.",
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

    Three outcomes:
      record is None             -> transformer rejected. Notes attach as orphans.
      duplicate found in tx_case -> write_case returns 'blocked'. Notes attach as
                                    orphans (no new row to attach to).
      clean insert               -> notes attach to the new case_id.

    Per-row failures during write are caught, logged into result.errors,
    and do NOT abort the file. Real DB-level exceptions bubble up.
    """
    if record is None:
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
        case_id, action, blocked_detail = write_case(cursor, record)
        if action == "inserted":
            result.inserted += 1
            if notes:
                written = write_notes(cursor, case_id, notes, run_year, run_month)
                result.notes_attached += written
        elif action == "blocked":
            result.blocked += 1
            if blocked_detail is not None:
                result.blocked_details.append(blocked_detail)
            if notes:
                written = write_notes(cursor, None, notes, run_year, run_month)
                result.notes_orphan += written
    except Exception as exc:
        msg = (
            f"Failed to write tx_case for contract={record.contract_id} "
            f"run={record.run_year}-{record.run_month:02d}: {exc!r}"
        )
        log.exception(msg)
        result.errors.append(msg)
