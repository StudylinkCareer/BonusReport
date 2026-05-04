"""
backend/tests/test_writer.py

Tests for backend/importer/writer.py.

Isolation strategy: each test gets its own DB connection via the
`writer_conn` fixture and never commits. When pytest exits the fixture's
context manager, psycopg rolls back any uncommitted changes — so test
rows (with synthetic contract_ids like 'TEST-WRITER-...') never persist.

Run from project root:
    python -m pytest backend/tests/test_writer.py -v
"""

from datetime import date

import pytest

from backend.data.connection import get_connection
from backend.importer.transformer import CaseRecord, NoteRecord
from backend.importer.writer import (
    WriteResult,
    write_case,
    write_notes,
    write_transformer_output,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def writer_conn():
    """A function-scoped connection that never commits.

    All test writes are rolled back automatically when the connection
    context exits.
    """
    with get_connection() as conn:
        yield conn
        # Connection's __exit__ rolls back uncommitted work.


@pytest.fixture(scope="function")
def cursor(writer_conn):
    with writer_conn.cursor() as cur:
        yield cur


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _real_office_id(cursor) -> int:
    cursor.execute("SELECT id FROM dim_office LIMIT 1")
    return cursor.fetchone()["id"]


def _real_country_id(cursor) -> int:
    cursor.execute("SELECT id FROM dim_country WHERE code = 'AU'")
    return cursor.fetchone()["id"]


def _build_record(cursor, contract_id: str = "TEST-WRITER-001", **overrides) -> CaseRecord:
    """Build a CaseRecord with safe real FKs and synthetic contract_id."""
    defaults = dict(
        contract_id=contract_id,
        student_id="C-TEST",
        student_name="Test Student",
        contract_signed_date=date(2024, 6, 1),
        course_start_date=date(2025, 7, 1),
        visa_received_date=date(2025, 3, 1),
        case_office_id=_real_office_id(cursor),
        country_id=_real_country_id(cursor),
        institution_id=None,
        referring_partner_id=None,
        referring_sub_agent_id=None,
        institution_text_raw=None,
        referring_agent_text_raw=None,
        client_type_code=None,
        application_status=None,
        course_status=None,
        counsellor_staff_id=None,
        counsellor_role_id=None,
        case_officer_staff_id=None,
        case_officer_role_id=None,
        referring_source_type="OFFICE_ONLY",
        import_status="OK",
        incentive_amount=0,
        notes=None,
        run_year=2025,
        run_month=4,
    )
    defaults.update(overrides)
    return CaseRecord(**defaults)


# ---------------------------------------------------------------------------
# write_case — happy path
# ---------------------------------------------------------------------------

def test_write_case_inserts_new_row(cursor):
    record = _build_record(cursor, contract_id="TEST-WRITER-INS-001")
    case_id, action = write_case(cursor, record)
    assert action == "inserted"
    assert isinstance(case_id, int) and case_id > 0

    cursor.execute("SELECT contract_id, import_status FROM tx_case WHERE id = %s", (case_id,))
    row = cursor.fetchone()
    assert row["contract_id"] == "TEST-WRITER-INS-001"
    assert row["import_status"] == "OK"


def test_write_case_second_call_updates(cursor):
    """Second call with same key triggers UPDATE (Q1 = Option B)."""
    record_v1 = _build_record(cursor, contract_id="TEST-WRITER-UPD-001",
                              student_name="Original Name")
    case_id_1, action_1 = write_case(cursor, record_v1)
    assert action_1 == "inserted"

    record_v2 = _build_record(cursor, contract_id="TEST-WRITER-UPD-001",
                              student_name="Updated Name")
    case_id_2, action_2 = write_case(cursor, record_v2)
    assert action_2 == "updated"
    assert case_id_2 == case_id_1  # same row

    cursor.execute("SELECT student_name FROM tx_case WHERE id = %s", (case_id_1,))
    assert cursor.fetchone()["student_name"] == "Updated Name"


def test_write_case_different_run_creates_new_row(cursor):
    """Same contract_id but different run = different row."""
    record_apr = _build_record(cursor, contract_id="TEST-WRITER-RUN-001",
                               run_year=2025, run_month=4)
    record_may = _build_record(cursor, contract_id="TEST-WRITER-RUN-001",
                               run_year=2025, run_month=5)
    id_apr, _ = write_case(cursor, record_apr)
    id_may, _ = write_case(cursor, record_may)
    assert id_apr != id_may


def test_write_case_preserves_engine_fields_on_update(cursor):
    """Re-importing must NOT clobber engine-populated fields."""
    record = _build_record(cursor, contract_id="TEST-WRITER-ENG-001")
    case_id, _ = write_case(cursor, record)

    # Simulate engine populating its fields. 'DEFERRED' is one of the
    # allowed values per the tx_case_deferral_code_check constraint.
    cursor.execute(
        """UPDATE tx_case SET deferral_code = %s, handover_flag = %s
           WHERE id = %s""",
        ("DEFERRED", True, case_id),
    )

    # Re-import the same case
    record_v2 = _build_record(cursor, contract_id="TEST-WRITER-ENG-001",
                              student_name="Edited By Re-import")
    write_case(cursor, record_v2)

    cursor.execute(
        "SELECT deferral_code, handover_flag, student_name FROM tx_case WHERE id = %s",
        (case_id,),
    )
    row = cursor.fetchone()
    assert row["deferral_code"] == "DEFERRED"           # untouched by re-import
    assert row["handover_flag"] is True                  # untouched by re-import
    assert row["student_name"] == "Edited By Re-import"  # updated by re-import


# ---------------------------------------------------------------------------
# write_notes
# ---------------------------------------------------------------------------

def test_write_notes_attached_to_case(cursor):
    record = _build_record(cursor, contract_id="TEST-WRITER-NOTE-001")
    case_id, _ = write_case(cursor, record)

    notes = [
        NoteRecord(warning_type="UNRESOLVED_INSTITUTION",
                   raw_value="Some Random College",
                   note="Row 5: institution did not resolve."),
        NoteRecord(warning_type="SYSTEM_TYPE_MISMATCH",
                   raw_value="OUT vs IN_SYSTEM_REGULAR",
                   note="Row 5: system type vs classification mismatch."),
    ]
    written = write_notes(cursor, case_id, notes, run_year=2025, run_month=4)
    assert written == 2

    cursor.execute(
        "SELECT count(*) AS n FROM tx_case_notes_staging WHERE case_id = %s",
        (case_id,),
    )
    assert cursor.fetchone()["n"] == 2


def test_write_orphan_notes_with_null_case_id(cursor):
    """Q3 = Option A: orphans go to staging with case_id NULL."""
    notes = [NoteRecord(
        warning_type="MISSING_CONTRACT_ID",
        raw_value=None,
        note="Row 7: blank Contract ID — row skipped.",
    )]
    written = write_notes(cursor, None, notes, run_year=2025, run_month=4)
    assert written == 1

    cursor.execute(
        """SELECT count(*) AS n FROM tx_case_notes_staging
           WHERE case_id IS NULL AND run_year = 2025 AND run_month = 4
             AND warning_type = 'MISSING_CONTRACT_ID'"""
    )
    assert cursor.fetchone()["n"] >= 1


def test_write_notes_empty_list_is_noop(cursor):
    """Empty list returns 0 and issues no SQL."""
    written = write_notes(cursor, None, [], run_year=2025, run_month=4)
    assert written == 0


# ---------------------------------------------------------------------------
# write_transformer_output — orchestration helper
# ---------------------------------------------------------------------------

def test_write_transformer_output_with_record_and_notes(cursor):
    record = _build_record(cursor, contract_id="TEST-WRITER-TX-001")
    notes = [NoteRecord(warning_type="WARN", raw_value=None, note="hi")]
    result = WriteResult()

    write_transformer_output(
        cursor, record, notes,
        run_year=2025, run_month=4, result=result,
    )
    assert result.inserted == 1
    assert result.updated == 0
    assert result.rows_skipped == 0
    assert result.notes_attached == 1
    assert result.notes_orphan == 0
    assert result.errors == []


def test_write_transformer_output_with_none_record(cursor):
    """When transformer returns None, writer logs orphan notes and counts the skip."""
    notes = [NoteRecord(
        warning_type="MISSING_CONTRACT_ID",
        raw_value=None,
        note="Row 9: blank Contract ID.",
    )]
    result = WriteResult()

    write_transformer_output(
        cursor, None, notes,
        run_year=2025, run_month=4, result=result,
    )
    assert result.inserted == 0
    assert result.rows_skipped == 1
    assert result.notes_orphan == 1
    assert result.notes_attached == 0
    assert result.errors == []


def test_write_transformer_output_second_record_increments_updated(cursor):
    record_v1 = _build_record(cursor, contract_id="TEST-WRITER-TX-002")
    result = WriteResult()
    write_transformer_output(cursor, record_v1, [],
                             run_year=2025, run_month=4, result=result)

    record_v2 = _build_record(cursor, contract_id="TEST-WRITER-TX-002")
    write_transformer_output(cursor, record_v2, [],
                             run_year=2025, run_month=4, result=result)

    assert result.inserted == 1
    assert result.updated == 1
