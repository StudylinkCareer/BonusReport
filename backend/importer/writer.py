"""
backend/importer/writer.py

Persist CaseRecord dataclasses (from transformer.py) to tx_case.

Writer v2 changes from previous version:
  * UPSERT by (contract_id, run_year, run_month) — the unique constraint
    added in migration 14_02 lets us INSERT ... ON CONFLICT DO UPDATE.
    Re-importing a month replaces the row in place; the engine sees one
    row per case per month.
  * application_status_id (the canonical FK) is written alongside the
    raw application_status text.
  * flag_reason and import_status come straight from the transformer's
    accumulator — no parallel notes table, no orphan handling.
  * Every CaseRecord is written. The transformer never returns None now,
    so there's no "skipped" case to handle.

Per-row write failures (DB constraint violations, etc.) are logged into
result.errors and counted in result.errors. They do NOT abort the file.
Real DB-level exceptions (connection drop, bad SQL) bubble up to the
orchestrator.

The writer does NOT manage transactions. The orchestrator owns the
per-file transaction.
"""

import logging
from dataclasses import dataclass, field

from backend.importer.transformer import CaseRecord


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------

@dataclass
class WriteResult:
    """Counts what happened during a write batch.

    Fields the orchestrator reports at end-of-file:
        inserted        : new rows added to tx_case
        updated         : existing rows replaced via ON CONFLICT
        ok              : rows written with import_status='OK'
        warn_mismatch   : rows written with import_status='WARN-MISMATCH'
        unresolved      : rows written with import_status='UNRESOLVED'
        scrap           : rows written with import_status='SCRAP'
        errors          : per-row exceptions (caught and continued)
    """
    inserted: int = 0
    updated: int = 0
    ok: int = 0
    warn_mismatch: int = 0
    unresolved: int = 0
    scrap: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "WriteResult") -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.ok += other.ok
        self.warn_mismatch += other.warn_mismatch
        self.unresolved += other.unresolved
        self.scrap += other.scrap
        self.errors.extend(other.errors)


# ---------------------------------------------------------------------------
# UPSERT SQL
# ---------------------------------------------------------------------------

# Columns the importer manages on tx_case. Engine columns (deferral_code,
# vp_*, run_id, calculated_at, workflow_state, etc.) are NOT touched by
# the importer. The writer sets workflow_state='uploaded' on first insert
# but does not reset it on subsequent UPSERTs (so a row that's already
# been promoted to 'in_review' stays there).
_INSERT_COLUMNS = (
    "contract_id",
    "student_id",
    "student_name",
    "contract_signed_date",
    "course_start_date",
    "visa_received_date",
    "case_office_id",
    "country_id",
    "institution_id",
    "institution_text_raw",
    "referring_partner_id",
    "referring_sub_agent_id",
    "referring_office_id",
    "referring_agent_text_raw",
    "client_type_code",
    "application_status",
    "application_status_id",
    "course_status",
    "counsellor_staff_id",
    "counsellor_role_id",
    "case_officer_staff_id",
    "case_officer_role_id",
    "pre_sales_staff_id",
    "referring_source_type",
    "import_status",
    "flag_reason",
    "incentive_amount",
    "notes",
    "run_year",
    "run_month",
    "bonus_year_month",
)

# Columns updated when an UPSERT conflicts. This is every importer-managed
# column EXCEPT the conflict-key columns themselves (contract_id, run_year,
# run_month) — those are by definition unchanged.
_UPDATE_COLUMNS = tuple(
    c for c in _INSERT_COLUMNS
    if c not in ("contract_id", "run_year", "run_month")
)


def _build_upsert_sql() -> str:
    insert_cols = ", ".join(_INSERT_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in _INSERT_COLUMNS)
    update_setters = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLUMNS
    )
    return f"""
        INSERT INTO tx_case ({insert_cols}, workflow_state)
        VALUES ({placeholders}, 'uploaded')
        ON CONFLICT (contract_id, run_year, run_month) DO UPDATE
        SET {update_setters}
        RETURNING id, (xmax = 0) AS was_inserted
    """


_UPSERT_SQL = _build_upsert_sql()


# ---------------------------------------------------------------------------
# tx_case write
# ---------------------------------------------------------------------------

def write_case(cursor, record: CaseRecord) -> tuple[int, bool]:
    """UPSERT a CaseRecord into tx_case.

    Returns (case_id, was_inserted). was_inserted is True for a brand-new
    row, False if an existing row was replaced.

    The xmax=0 trick: in PostgreSQL, for a freshly-inserted row, xmax
    (the system transaction-id of the most recent delete/update) is 0.
    For a row hit by ON CONFLICT DO UPDATE, xmax is the current transaction
    id (non-zero). Cheap, reliable inserted-vs-updated detection.

    Raises whatever psycopg raises on a real DB error.
    """
    params = {col: getattr(record, col) for col in _INSERT_COLUMNS}
    cursor.execute(_UPSERT_SQL, params)
    row = cursor.fetchone()
    case_id = row["id"]
    was_inserted = row["was_inserted"]

    log.info(
        "tx_case %s: contract=%s run=%d-%02d id=%d status=%s",
        "INSERT" if was_inserted else "UPDATE",
        record.contract_id, record.run_year, record.run_month,
        case_id, record.import_status,
    )
    return case_id, was_inserted


# ---------------------------------------------------------------------------
# High-level helper: write one transformer result
# ---------------------------------------------------------------------------

def write_transformer_output(
    cursor,
    record: CaseRecord,
    *,
    result: WriteResult,
) -> None:
    """Persist one CaseRecord from transformer.transform_row().

    Updates the WriteResult counters.

    Per-row failures during write are caught, logged into result.errors,
    and do NOT abort the file. Real DB-level exceptions bubble up.
    """
    try:
        _case_id, was_inserted = write_case(cursor, record)
        if was_inserted:
            result.inserted += 1
        else:
            result.updated += 1

        # Status counters
        if record.import_status == "OK":
            result.ok += 1
        elif record.import_status == "WARN-MISMATCH":
            result.warn_mismatch += 1
        elif record.import_status == "UNRESOLVED":
            result.unresolved += 1
        elif record.import_status == "SCRAP":
            result.scrap += 1
        else:
            # Unknown status — shouldn't happen but don't crash
            log.warning(
                "Unknown import_status %r for contract %s",
                record.import_status, record.contract_id,
            )
    except Exception as exc:
        msg = (
            f"Failed to write tx_case for contract={record.contract_id} "
            f"run={record.run_year}-{record.run_month:02d}: {exc!r}"
        )
        log.exception(msg)
        result.errors.append(msg)
