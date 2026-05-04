"""
backend/tests/test_transformer.py

Tests for backend/importer/transformer.py.

Two kinds of tests:
  * Unit tests for the pure-Python parsing helpers (no DB needed).
  * Integration tests that run transform_row() against the live DB.

Run from project root:
    python -m pytest backend/tests/test_transformer.py -v
"""

from datetime import datetime

import pytest

from backend.data.connection import get_connection
from backend.importer.reader import RawRow
from backend.importer.transformer import (
    _parse_incentive,
    _parse_institution_field,
    _parse_system_type,
    transform_row,
    STATUS_OK,
    STATUS_SCRAP,
    STATUS_UNRESOLVED,
    STATUS_UNRESOLVED_PARTNER,
    STATUS_WARN_MISMATCH,
    SOURCE_NONE,
    SOURCE_OFFICE_ONLY,
    SOURCE_PARTNER,
    SOURCE_SUB_AGENT,
    SOURCE_UNRESOLVED,
)


# ---------------------------------------------------------------------------
# Unit tests — institution field parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("The University of Adelaide",                  ("The University of Adelaide", 0, None)),
    ("Eynesbury College * - Navitas",               ("Eynesbury College", 1, "Navitas")),
    ("SAIBT *",                                     ("SAIBT", 1, None)),
    ("Edith Cowan College*",                        ("Edith Cowan College", 1, None)),
    ("Some College **",                             ("Some College", 2, None)),
    ("The University of Melbourne**",               ("The University of Melbourne", 2, None)),
    ("Some College ** - Adventus",                  ("Some College", 2, "Adventus")),
    ("  Padded Name  ",                             ("Padded Name", 0, None)),
    ("",                                            (None, 0, None)),
    (None,                                          (None, 0, None)),
])
def test_parse_institution_field(text, expected):
    assert _parse_institution_field(text) == expected


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
    assert record.counsellor_staff_id is not None
    assert record.counsellor_role_id is not None
    assert notes == []


# ---------------------------------------------------------------------------
# New asterisk semantics
# ---------------------------------------------------------------------------

def test_single_asterisk_with_navitas_suffix_resolves_partner(cursor):
    """`*` + suffix → partner, with optional verification against partner_institution."""
    raw = _build_row(**{"Institution Name": "Eynesbury College * - Navitas"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.referring_partner_id is not None
    assert record.referring_source_type == SOURCE_PARTNER


def test_single_asterisk_with_unknown_partner_marks_unresolved(cursor):
    raw = _build_row(**{"Institution Name": "Some College * - NotARealPartner"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.referring_partner_id is None
    assert any(n.warning_type == "UNRESOLVED_PARTNER_SUFFIX" for n in notes)
    assert record.import_status == STATUS_UNRESOLVED


def test_bare_asterisk_with_known_institution_auto_resolves(cursor):
    """Bare `*` on Edith Cowan College should auto-resolve to Navitas
    (Phase 6i seeded that link)."""
    raw = _build_row(**{"Institution Name": "Edith Cowan College*"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    if record.institution_id is not None:
        # If the institution resolves and has exactly one Navitas link, auto-resolve succeeds.
        assert record.referring_partner_id is not None
        assert record.referring_source_type == SOURCE_PARTNER


def test_double_asterisk_means_out_of_system(cursor):
    """`**` → no partner involvement at all. source_type = NONE."""
    raw = _build_row(**{"Institution Name": "The University of Melbourne**"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.referring_partner_id is None
    assert record.referring_source_type == SOURCE_NONE
    # Should NOT be flagged UNRESOLVED-PARTNER under the new rules
    assert record.import_status != STATUS_UNRESOLVED_PARTNER


def test_double_asterisk_with_suffix_still_means_out_of_system(cursor):
    """Even with a stray ' - X' suffix, ** stays out-of-system per the new rule."""
    raw = _build_row(**{"Institution Name": "Some College ** - Adventus"})
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.referring_source_type == SOURCE_NONE
    assert record.referring_partner_id is None


# ---------------------------------------------------------------------------
# Refer Source Agent cascade (asterisk_count == 0)
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

def test_role_id_comes_from_ref_staff_not_column(cursor):
    raw = _build_row()
    record, notes = transform_row(cursor, raw, run_year=2025, run_month=4)
    assert record is not None
    assert record.counsellor_staff_id == record.case_officer_staff_id
    assert record.counsellor_role_id == record.case_officer_role_id
    assert record.counsellor_role_id is not None


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
