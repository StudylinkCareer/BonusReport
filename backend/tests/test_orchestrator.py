"""
backend/tests/test_orchestrator.py

End-to-end tests for backend/importer/orchestrator.run_file.

Isolation: tests pass `conn=` so the orchestrator does NOT commit. The
test fixture's connection rolls back uncommitted work on exit, so test
data never persists.

Run from project root:
    python -m pytest backend/tests/test_orchestrator.py -v
"""

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from backend.data.connection import get_connection
from backend.importer.orchestrator import run_file


STANDARD_HEADERS = [
    "No.", "Student Name", "Student ID", "Contract ID",
    "Contract Signed Date", "Client Type", "Country of Study",
    "Refer Source Agent", "System Type", "Application Report Status",
    "Visa Received Date", "Institution Name", "Course Start Date",
    "Course Status", "Counsellor Name", "Case Officer Name", "Notes",
]


@pytest.fixture(scope="function")
def conn():
    """Function-scoped connection that auto-rollbacks on exit."""
    with get_connection() as c:
        yield c


def _data_row(no: int, contract_id: str, **overrides) -> list:
    """Build a 17-column data row with realistic defaults."""
    row = [
        no,
        f"Test Student {no}",
        f"C-TEST-{no:03d}",
        contract_id,
        datetime(2024, 6, 1),
        "Du học (ghi danh)",
        "Australia",
        None,
        "Trong hệ thống",
        "Closed - Visa granted",
        datetime(2025, 3, 1),
        "The University of Adelaide",
        datetime(2025, 7, 1),
        "",
        "Phạm Thị Lợi",
        "Phạm Thị Lợi",
        "",
    ]
    # Map overrides by header name -> column index
    for k, v in overrides.items():
        if k in STANDARD_HEADERS:
            row[STANDARD_HEADERS.index(k)] = v
    return row


def _make_xlsx(tmp_path: Path, rows: list[list], filename: str) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Student Contract"
    for r in rows:
        ws.append(r)
    out = tmp_path / filename
    wb.save(out)
    return out


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_run_file_imports_all_rows(tmp_path, conn):
    rows = [
        [None, "Title row"],
        STANDARD_HEADERS,
        ["Closed files"],
        _data_row(1, "TEST-ORCH-001"),
        _data_row(2, "TEST-ORCH-002"),
        _data_row(3, "TEST-ORCH-003"),
    ]
    xlsx = _make_xlsx(tmp_path, rows, "report_April_2025.xlsx")

    result = run_file(xlsx, conn=conn)

    assert result.inserted == 3
    assert result.updated == 0
    assert result.rows_skipped == 0
    assert result.errors == []

    # Verify the rows actually landed (in-flight, before rollback)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) AS n FROM tx_case
               WHERE contract_id LIKE 'TEST-ORCH-%' AND run_year = 2025 AND run_month = 4"""
        )
        assert cur.fetchone()["n"] == 3


def test_run_file_picks_up_year_month_from_filename(tmp_path, conn):
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        _data_row(1, "TEST-ORCH-FN-001"),
    ]
    xlsx = _make_xlsx(tmp_path, rows, "Phạm_Thị_Lợi_report_December_2024.xlsx")
    result = run_file(xlsx, conn=conn)
    assert result.inserted == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_year, run_month FROM tx_case WHERE contract_id = 'TEST-ORCH-FN-001'"
        )
        row = cur.fetchone()
        assert row["run_year"] == 2024
        assert row["run_month"] == 12


def test_run_file_explicit_period_overrides_filename(tmp_path, conn):
    rows = [[None, "Title"], STANDARD_HEADERS, _data_row(1, "TEST-ORCH-OVR-001")]
    xlsx = _make_xlsx(tmp_path, rows, "report_April_2025.xlsx")
    result = run_file(xlsx, conn=conn, run_year=2099, run_month=12)
    assert result.inserted == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_year, run_month FROM tx_case WHERE contract_id = 'TEST-ORCH-OVR-001'"
        )
        row = cur.fetchone()
        assert row["run_year"] == 2099
        assert row["run_month"] == 12


# ---------------------------------------------------------------------------
# Skipping behaviour
# ---------------------------------------------------------------------------

def test_run_file_skips_rows_missing_contract_id(tmp_path, conn):
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        _data_row(1, "TEST-ORCH-SKIP-001"),
        _data_row(2, ""),                   # blank contract_id -> skipped
        _data_row(3, "TEST-ORCH-SKIP-002"),
    ]
    xlsx = _make_xlsx(tmp_path, rows, "report_April_2025.xlsx")
    result = run_file(xlsx, conn=conn)

    assert result.inserted == 2
    assert result.rows_skipped == 1
    assert result.notes_orphan >= 1  # MISSING_CONTRACT_ID note logged as orphan


def test_run_file_continues_after_skipped_row(tmp_path, conn):
    """The third row must still get processed even though row 2 was skipped."""
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        _data_row(1, ""),
        _data_row(2, ""),
        _data_row(3, "TEST-ORCH-CONT-001"),
    ]
    xlsx = _make_xlsx(tmp_path, rows, "report_April_2025.xlsx")
    result = run_file(xlsx, conn=conn)

    assert result.rows_skipped == 2
    assert result.inserted == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_run_file_twice_same_period_is_update(tmp_path, conn):
    rows = [[None, "Title"], STANDARD_HEADERS, _data_row(1, "TEST-ORCH-IDEM-001")]
    xlsx = _make_xlsx(tmp_path, rows, "report_April_2025.xlsx")

    r1 = run_file(xlsx, conn=conn)
    r2 = run_file(xlsx, conn=conn)

    assert r1.inserted == 1
    assert r1.updated == 0
    assert r2.inserted == 0
    assert r2.updated == 1
