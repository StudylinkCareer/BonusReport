"""
backend/importer/reader.py

Walk a 'report of closed file' xlsx and yield each data row as a RawRow.

The reader has no knowledge of the database or business rules. Its only
jobs are:
  * Open the file and validate the sheet name.
  * Locate the header row (which can be at row 2 or row 3 depending on
    the file) and build a {header_text -> column_index} map.
  * Yield each data row, skipping blank rows, header rows, and section
    divider rows. The most recent section divider seen is attached to
    each yielded row as metadata, in case the transformer wants it.

The reader is column-position-agnostic: rows are yielded as dicts keyed
by header text, so the 17-column and 18-column file variants (the latter
has an extra 'Customer Incentive >= VND5000000' column) are handled
without special-casing in transformer.py.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawRow:
    """One data row from a closed-file report.

    Fields
    ------
    row_number     : 1-based spreadsheet row number (for diagnostics).
    section_label  : The most recent section divider seen above this row,
                     e.g. 'Closed files', 'Enrolled'. None if the file
                     has no section dividers.
    data           : {header_text: cell_value} for every column whose
                     header had non-blank text. Cell values come straight
                     from openpyxl, so dates arrive as datetime objects.
    """
    row_number: int
    section_label: Optional[str]
    data: dict[str, Any]


@dataclass(frozen=True)
class FilenameInfo:
    """Metadata extracted from a closed-file report's filename."""
    year: int
    month: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class FilenameParseError(ValueError):
    """The filename does not contain a recognisable Month_Year suffix."""


class HeaderRowNotFoundError(ValueError):
    """No header row was found in the first few rows of the sheet."""


class UnexpectedSheetError(ValueError):
    """The active sheet is not named 'Student Contract'."""


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Matches '<Month><sep><YYYY>.xlsx' anywhere near the end of the filename.
# Accepts any non-letter separator (underscores, spaces, hyphens) between
# the month word and the year, including none.
_FILENAME_PATTERN = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"[^a-zA-Z0-9]*(\d{4})\.xlsx?$",
    re.IGNORECASE,
)


def parse_filename(path: Path | str) -> FilenameInfo:
    """Extract year and month from a closed-file report's filename.

    Examples that should all parse successfully:
      Phạm_Thị_Lợisreportof_closed_file_in_April_2025.xlsx  -> 2025-04
      Lê Thị Trường An's report of closed file in July 2025.xlsx -> 2025-07
      Quan Hoàng Yếnsreportof closed file in March 2025.xlsx -> 2025-03

    Raises FilenameParseError if no Month + 4-digit year is found.
    """
    name = Path(path).name
    match = _FILENAME_PATTERN.search(name)
    if not match:
        raise FilenameParseError(
            f"Cannot extract month/year from filename: {name!r}"
        )
    month_text, year_text = match.groups()
    return FilenameInfo(
        year=int(year_text),
        month=_MONTH_NAMES[month_text.lower()],
    )


# ---------------------------------------------------------------------------
# Sheet structure detection
# ---------------------------------------------------------------------------

EXPECTED_SHEET_NAME = "Student Contract"
HEADER_SEARCH_DEPTH = 5  # rows


def _find_header_row(ws) -> tuple[int, dict[str, int]]:
    """Scan the first few rows for one that looks like a header row.

    A header row is identified by 'No.' in column A and 'Student Name'
    in column B — a cheap, distinctive signature.

    Returns (row_index_1based, {header_text: column_index_1based}).
    """
    for row_idx in range(1, HEADER_SEARCH_DEPTH + 1):
        a = ws.cell(row=row_idx, column=1).value
        b = ws.cell(row=row_idx, column=2).value
        if a == "No." and b == "Student Name":
            header_map: dict[str, int] = {}
            for col_idx in range(1, ws.max_column + 1):
                cell_value = ws.cell(row=row_idx, column=col_idx).value
                if cell_value is None:
                    continue
                text = str(cell_value).strip()
                if text:
                    header_map[text] = col_idx
            return row_idx, header_map
    raise HeaderRowNotFoundError(
        f"No header row found in first {HEADER_SEARCH_DEPTH} rows of "
        f"sheet {ws.title!r}"
    )


def _is_blank(value: Any) -> bool:
    """Treat None and whitespace-only strings as blank."""
    return value is None or (isinstance(value, str) and not value.strip())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def iter_data_rows(path: Path | str) -> Iterator[RawRow]:
    """Yield each data row from a closed-file report, skipping non-data rows.

    Skipped rows
    ------------
    * Rows above the header (title row in row 1).
    * The header row itself.
    * Completely blank rows.
    * Section divider rows: rows where col A has text but col B is blank
      (e.g. 'Closed files', 'Enrolled'). These update the section_label
      that gets attached to subsequent data rows.

    Yielded rows
    ------------
    Every row where col B contains a student name. The data dict is
    keyed by header text, so callers don't need to know whether the file
    had 17 or 18 columns or which column held what.
    """
    path = Path(path)
    wb = load_workbook(path, data_only=True)
    try:
        ws = wb.active
        if ws.title != EXPECTED_SHEET_NAME:
            raise UnexpectedSheetError(
                f"Expected sheet {EXPECTED_SHEET_NAME!r} in {path.name}, "
                f"got {ws.title!r}"
            )

        header_row_idx, header_map = _find_header_row(ws)
        current_section: Optional[str] = None

        for row_idx in range(header_row_idx + 1, ws.max_row + 1):
            a = ws.cell(row=row_idx, column=1).value
            b = ws.cell(row=row_idx, column=2).value

            # Completely blank row -> skip
            if _is_blank(a) and _is_blank(b):
                continue

            # Section divider -> update label and skip
            if not _is_blank(a) and _is_blank(b):
                current_section = str(a).strip()
                continue

            # Data row -> build dict by header text
            data = {
                header: ws.cell(row=row_idx, column=col).value
                for header, col in header_map.items()
            }
            yield RawRow(
                row_number=row_idx,
                section_label=current_section,
                data=data,
            )
    finally:
        wb.close()
