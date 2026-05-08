"""
backend/tests/test_transformer.py

Tests for backend/importer/transformer.py.

Two kinds of tests:
  * Unit tests for the pure-Python parsing helpers (no DB needed).
  * Integration tests that run transform_row() against the live DB.

Run from project root:
    python -m pytest backend/tests/test_transformer.py -v

PHASE 7 NOTE:
    The earlier version of this file tested an asterisk-parsing helper
    (`_parse_institution_field`) and its associated integration tests
    that derived partner routing from `*` / `**` markers in the
    Institution Name field. That whole approach was retired in Phase 7
    in favour of pure alias lookup against `ref_institution_alias`.
    Asterisks are now just text inside aliases. Partner-routing for
    engine logic is derived from `ref_institution_agreement` at run
    time, not from importer parsing.

    Tests removed:
      * 8 unit tests for `_parse_institution_field`
      * 5 integration tests under "New asterisk semantics"

    The remaining tests (happy path, Refer Source Agent cascade, SCRAP
    triggers, missing-required-fields, role-from-staff, incentive
    amount) all remain valid under the Phase 7 model.
"""

from datetime import datetime

import pytest

from backend.data.connection import get_connection
from backend.importer.reader import RawRow
from backend.importer.transformer import (
    _parse_incentive,
    _parse_system_type,
    transform_row,
    STATUS_OK,
    STATUS_SCRAP,
    STATUS_UNRESOLVED,
    STATUS_WARN_MISMATCH,
    SOURCE_NONE,
    SOURCE_OFFICE_ONLY,
    SOURCE_PARTNER,
    SOURCE_SUB_AGENT,
    SOURCE_UNRESOLVED,
)


# ---------------------------------------------------------------------------
# Unit tests — pure-Python helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Trong hệ thống", "IN"),
    ("Ngoài hệ thống", "OUT"),
    ("garbage", None),
    ("", None),
    (None, None),
])
def test_parse_system_type(text, expected):
    assert _parse_system_type(text) == expected


@pytest.mark.parametrize("value, expected", [
    ("Yes", 5_000_000),
    ("No", 0),
    ("", 0),
    (None, 0),
    (5_000_000, 5_000_000),
    ("5,000,000", 5_000_000),
    (0, 0),
    ("garbage", 0),
])
def test_parse_incentive(value, expected):
    assert _parse_incentive(value) == expected


# ---------------------------------------------------------------------------
# Integration fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cursor():
    with get_connection() as conn:
        with conn.cursor() as cur:
            yield cur


def _build_row(row_number: int = 4, **overrides) -> RawRow:
    data = {
        "No.": row_number - 3,
        "Student Name": "Test Student",
        "Student ID": "C-9999",
        "Contract ID": f"SLC-TEST-{row_number}",
        "Contract Signed Date": datetime(2024, 6, 1),
        "Client Type": "Du học (ghi danh)",
        "Country of Study": "Australia",
        "Refer Source Agent": None,
        "System Type": "Trong hệ thống",
        "Application Report Status": "Closed - Visa granted",
        "Visa Received Date": datetime(2025, 3, 1),
        "Institution Name": "The University of Adelaide",
        "Course Start Date": datetime(2025, 7, 1),
        "Course Status": None,
        "Counsellor Name": "Phạm Thị Lợi",
        "Case Officer Name": "Phạm Thị Lợi",
        "Notes": None,
    }
    data.update(overrides)
    return RawRow(row_number=row_number, section_label="Closed files", data=data)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_in_system(cursor):
    raw = _build_row()
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.import_status == STATUS_OK
    assert record.referring_source_type == SOURCE_OFFICE_ONLY
    assert record.country_id is not None
    assert record.institution_id is not None
    assert record.case_office_id is not None
    # _build_row() uses Phạm Thị Lợi (CO_SUB) for both columns; per the
    # CO_SUB slot rule, counsellor is cleared and case_officer is filled.
    assert record.counsellor_staff_id is None
    assert record.counsellor_role_id is None
    assert record.case_officer_staff_id is not None
    assert record.case_officer_role_id == 18  # ROLE_ID_CO_SUB
    assert notes == []


# ---------------------------------------------------------------------------
# Refer Source Agent cascade
# ---------------------------------------------------------------------------

def test_blank_refer_source_is_office_only(cursor):
    raw = _build_row(**{"Refer Source Agent": ""})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.referring_source_type == SOURCE_OFFICE_ONLY


def test_unresolvable_refer_source_marks_unresolved(cursor):
    raw = _build_row(**{
        "Refer Source Agent": "Definitely Not A Real Sub-Agent Or Partner Name",
    })
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.referring_source_type == SOURCE_UNRESOLVED
    assert record.import_status == STATUS_UNRESOLVED


# ---------------------------------------------------------------------------
# SCRAP triggers
# ---------------------------------------------------------------------------

def test_departed_staff_marks_scrap(cursor):
    raw = _build_row(**{
        "Counsellor Name": "Đào Ngọc Sơn",
        "Case Officer Name": "Đào Ngọc Sơn",
    })
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert any(n.warning_type == "DEPARTED_STAFF" for n in notes)


def test_datetime_in_text_field_marks_scrap(cursor):
    raw = _build_row(**{"Refer Source Agent": datetime(2024, 6, 1)})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    if record is not None:
        assert record.import_status == STATUS_SCRAP
    assert any(n.warning_type == "DATE_IN_TEXT_FIELD" for n in notes)


# ---------------------------------------------------------------------------
# Required fields missing
# ---------------------------------------------------------------------------

def test_missing_contract_id_returns_none(cursor):
    raw = _build_row(**{"Contract ID": None})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is None
    assert any(n.warning_type == "MISSING_CONTRACT_ID" for n in notes)


def test_unresolvable_country_returns_none(cursor):
    raw = _build_row(**{"Country of Study": "Atlantis"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is None
    assert any(n.warning_type == "UNRESOLVED_COUNTRY" for n in notes)


# ---------------------------------------------------------------------------
# Role-from-staff-not-column
# ---------------------------------------------------------------------------

def test_co_sub_staff_only_populates_case_officer_slot(cursor):
    """CO_SUB staff always go to case_officer slot, never counsellor slot.
    Phạm Thị Lợi (CO_SUB) appears in both columns of _build_row(); after
    transform, only case_officer should be filled."""
    raw = _build_row()
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    # Counsellor slot must be empty for CO_SUB staff
    assert record.counsellor_staff_id is None
    assert record.counsellor_role_id is None
    # Case officer slot has the CO_SUB staff
    assert record.case_officer_staff_id is not None
    assert record.case_officer_role_id == 18  # ROLE_ID_CO_SUB


# ---------------------------------------------------------------------------
# Incentive amount
# ---------------------------------------------------------------------------

def test_incentive_yes_gives_threshold_amount(cursor):
    raw = _build_row(**{"Customer Incentive  >= VND5000000": "Yes"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.incentive_amount == 5_000_000


def test_no_incentive_column_gives_zero(cursor):
    raw = _build_row()
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.incentive_amount == 0
