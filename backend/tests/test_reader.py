"""
backend/tests/test_reader.py

Tests for backend/importer/reader.py.

These tests build small xlsx fixtures in pytest's tmp_path and read them
back, so no DB and no real bao-cao files are required.

Run from the project root:
    python -m pytest backend/tests/test_reader.py -v
"""

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from backend.importer.reader import (
    FilenameInfo,
    FilenameParseError,
    HeaderRowNotFoundError,
    RawRow,
    UnexpectedSheetError,
    iter_data_rows,
    parse_filename,
)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename, expected", [
    ("Phạm_Thị_Lợisreportof_closed_file_in_April_2025.xlsx", FilenameInfo(2025, 4)),
    ("Lê Thị Trường An's report of closed file in July 2025.xlsx", FilenameInfo(2025, 7)),
    ("Quan Hoàng Yến's report of closed file in March 2025.xlsx", FilenameInfo(2025, 3)),
    ("anything_january_2024.xlsx", FilenameInfo(2024, 1)),
    ("MIXED_CASE_December_2025.xlsx", FilenameInfo(2025, 12)),
])
def test_parse_filename_extracts_month_and_year(filename, expected):
    assert parse_filename(filename) == expected


def test_parse_filename_accepts_full_path():
    info = parse_filename("/some/path/foo_April_2025.xlsx")
    assert info == FilenameInfo(2025, 4)


def test_parse_filename_raises_on_garbage():
    with pytest.raises(FilenameParseError):
        parse_filename("garbage.xlsx")


def test_parse_filename_raises_on_missing_year():
    with pytest.raises(FilenameParseError):
        parse_filename("April.xlsx")


# ---------------------------------------------------------------------------
# Helpers for building fixture xlsx files
# ---------------------------------------------------------------------------

STANDARD_HEADERS = [
    "No.", "Student Name", "Student ID", "Contract ID",
    "Contract Signed Date", "Client Type", "Country of Study",
    "Refer Source Agent", "System Type", "Application Report Status",
    "Visa Received Date", "Institution Name", "Course Start Date",
    "Course Status", "Counsellor Name", "Case Officer Name", "Notes",
]

VARIANT_HEADERS = (
    STANDARD_HEADERS[:16]
    + ["Customer Incentive  >= VND5000000"]
    + ["Notes"]
)  # 18 columns: insert Customer Incentive before Notes


def _make_xlsx(tmp_path: Path, rows: list[list], sheet_name: str = "Student Contract") -> Path:
    """Build a closed-file-report-shaped xlsx file under tmp_path.

    `rows` is the full sheet content as a list of row lists. Caller is
    responsible for the title row, header row, section dividers, and
    data rows in the right order.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    out = tmp_path / "fixture.xlsx"
    wb.save(out)
    return out


def _sample_data_row(no: int, name: str, contract_id: str = "SLC-X") -> list:
    """Build a 17-column data row with mostly blank cells but realistic types."""
    return [
        no,                              # No.
        name,                            # Student Name
        f"C-{1000+no}",                  # Student ID
        contract_id,                     # Contract ID
        datetime(2024, 6, 1),            # Contract Signed Date
        "Du học (ghi danh)",             # Client Type
        "Australia",                     # Country of Study
        "Some Sub-Agent",                # Refer Source Agent
        "Trong hệ thống",                # System Type
        "Closed - Visa granted",         # Application Report Status
        datetime(2025, 3, 1),            # Visa Received Date
        "The University of Adelaide",    # Institution Name
        datetime(2025, 7, 1),            # Course Start Date
        "",                              # Course Status
        "Phạm Thị Lợi",                  # Counsellor Name
        "Phạm Thị Lợi",                  # Case Officer Name
        "",                              # Notes
    ]


# ---------------------------------------------------------------------------
# iter_data_rows — happy path, 17 columns
# ---------------------------------------------------------------------------

def test_iter_data_rows_yields_each_data_row(tmp_path):
    rows = [
        [None, "Title row spanning here"],          # row 1: title
        STANDARD_HEADERS,                            # row 2: headers
        ["Closed files"],                            # row 3: section divider
        _sample_data_row(1, "Student One"),          # row 4: data
        _sample_data_row(2, "Student Two"),          # row 5: data
    ]
    path = _make_xlsx(tmp_path, rows)
    result = list(iter_data_rows(path))
    assert len(result) == 2
    assert all(isinstance(r, RawRow) for r in result)
    assert result[0].data["Student Name"] == "Student One"
    assert result[1].data["Student Name"] == "Student Two"


def test_iter_data_rows_attaches_section_label(tmp_path):
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        ["Closed files"],
        _sample_data_row(1, "Student One"),
        ["Enrolled"],                                # second section divider
        _sample_data_row(2, "Student Two"),
    ]
    path = _make_xlsx(tmp_path, rows)
    result = list(iter_data_rows(path))
    assert result[0].section_label == "Closed files"
    assert result[1].section_label == "Enrolled"


def test_iter_data_rows_records_row_number(tmp_path):
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        ["Closed files"],
        _sample_data_row(1, "Student One"),  # spreadsheet row 4
    ]
    path = _make_xlsx(tmp_path, rows)
    result = list(iter_data_rows(path))
    assert result[0].row_number == 4


def test_iter_data_rows_skips_blank_rows(tmp_path):
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        [],                                          # blank
        _sample_data_row(1, "Student One"),
        [],                                          # blank
        _sample_data_row(2, "Student Two"),
    ]
    path = _make_xlsx(tmp_path, rows)
    result = list(iter_data_rows(path))
    assert len(result) == 2


def test_iter_data_rows_preserves_dates_as_datetime(tmp_path):
    rows = [
        [None, "Title"],
        STANDARD_HEADERS,
        _sample_data_row(1, "Student One"),
    ]
    path = _make_xlsx(tmp_path, rows)
    row = next(iter(iter_data_rows(path)))
    assert isinstance(row.data["Contract Signed Date"], datetime)
    assert isinstance(row.data["Visa Received Date"], datetime)


# ---------------------------------------------------------------------------
# iter_data_rows — 18-column variant
# ---------------------------------------------------------------------------

def test_iter_data_rows_handles_18_column_variant(tmp_path):
    """A file with the 'Customer Incentive' column inserted before Notes."""
    data_row = _sample_data_row(1, "Student One")
    # Insert "Yes" for Customer Incentive before the final Notes cell
    data_row_18 = data_row[:16] + ["Yes"] + [data_row[16]]
    rows = [
        [None, "Title"],
        VARIANT_HEADERS,
        ["Closed files"],
        data_row_18,
    ]
    path = _make_xlsx(tmp_path, rows)
    result = list(iter_data_rows(path))
    assert len(result) == 1
    assert "Customer Incentive  >= VND5000000" in result[0].data
    assert result[0].data["Customer Incentive  >= VND5000000"] == "Yes"
    # Notes should still be accessible by its header name
    assert "Notes" in result[0].data


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_iter_data_rows_raises_on_unexpected_sheet_name(tmp_path):
    rows = [STANDARD_HEADERS, _sample_data_row(1, "X")]
    path = _make_xlsx(tmp_path, rows, sheet_name="Wrong Name")
    with pytest.raises(UnexpectedSheetError):
        list(iter_data_rows(path))


def test_iter_data_rows_raises_when_no_header_row(tmp_path):
    rows = [
        ["Junk", "More junk"],
        ["Still no headers"],
        ["Nothing useful here"],
    ]
    path = _make_xlsx(tmp_path, rows)
    with pytest.raises(HeaderRowNotFoundError):
        list(iter_data_rows(path))
