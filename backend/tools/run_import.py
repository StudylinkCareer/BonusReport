"""
backend/tools/run_import.py

CLI for batch-importing closed-file reports into tx_case +
tx_case_notes_staging.

Usage:
    python -m backend.tools.run_import <path>
    python -m backend.tools.run_import <path> -v
    python -m backend.tools.run_import <path> --dry-run

<path> may be a single .xlsx file or a directory. Directories are
walked recursively, so you can point at a year folder (e.g. 2024) or
even the top-level "Input Files Original" folder and every closed-file
xlsx beneath will be imported.

File selection
--------------
- Only .xlsx files (case-insensitive) are considered.
- Excel lock files starting with '~$' are skipped.
- Files whose names don't contain '<Month> <YYYY>' are skipped with a
  warning -- these aren't CRM files (e.g. bao caos use 'tháng_<m>_<y>'
  and won't parse).
- Files that pass the filename check but fail at the sheet level
  (UnexpectedSheetError -- e.g. corrupt short-form files using
  'Sheet1' instead of 'Student Contract') are caught by the
  orchestrator's per-file try/except and logged as errors, not crashes.

Transaction behaviour
---------------------
Per-file transactions, per orchestrator's contract. A failure on one
file does NOT stop the batch -- subsequent files are still attempted.
The exit code is 0 on full success, 1 if any file had errors.

In --dry-run, the orchestrator is bypassed; we only enumerate and
report which files would be imported. No DB writes occur.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterator

from backend.importer.orchestrator import run_file
from backend.importer.reader import FilenameParseError, parse_filename


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _candidate_files(root: Path) -> Iterator[Path]:
    """Yield .xlsx files at or under root, skipping Excel lock files."""
    if root.is_file():
        if root.suffix.lower() == ".xlsx" and not root.name.startswith("~$"):
            yield root
        return
    for p in root.rglob("*.xlsx"):
        if p.name.startswith("~$"):
            continue
        yield p


def _filter_by_filename(
    paths: list[Path],
    log: logging.Logger,
) -> list[Path]:
    """Drop any file whose name does not contain Month_Year, with a
    warning. The orchestrator would itself raise FilenameParseError
    for these, but pre-filtering keeps the batch summary clean.
    """
    keepers: list[Path] = []
    for p in paths:
        try:
            parse_filename(p)
        except FilenameParseError:
            log.warning("Skipping (no Month/Year in filename): %s", p.name)
            continue
        keepers.append(p)
    return keepers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-import closed-file reports into tx_case."
    )
    parser.add_argument(
        "path", type=Path,
        help="File or directory to import. Directories are walked recursively.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be imported without writing to the DB.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show DEBUG-level logging.",
    )
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    log = logging.getLogger("run_import")

    if not args.path.exists():
        log.error("Path does not exist: %s", args.path)
        return 2

    candidates = sorted(_candidate_files(args.path))
    if not candidates:
        log.warning("No .xlsx files found under %s", args.path)
        return 0
    log.info("Found %d candidate xlsx file(s) under %s", len(candidates), args.path)

    importable = _filter_by_filename(candidates, log)
    if not importable:
        log.error("No files have parseable Month/Year filenames.")
        return 2
    log.info("%d file(s) will be imported.", len(importable))

    if args.dry_run:
        for p in importable:
            print(f"  WOULD IMPORT: {p}")
        return 0

    # Real import. Aggregate the per-file WriteResult counters.
    totals = {
        "inserted": 0, "updated": 0, "rows_skipped": 0,
        "notes_attached": 0, "notes_orphan": 0,
    }
    files_with_errors: list[tuple[str, list[str]]] = []

    for p in importable:
        log.info("---- %s ----", p.name)
        try:
            result = run_file(p)
        except Exception as exc:  # orchestrator only re-raises if conn is borrowed
            log.exception("Hard failure on %s", p.name)
            files_with_errors.append((p.name, [repr(exc)]))
            continue

        totals["inserted"] += result.inserted
        totals["updated"] += result.updated
        totals["rows_skipped"] += result.rows_skipped
        totals["notes_attached"] += result.notes_attached
        totals["notes_orphan"] += result.notes_orphan
        if result.errors:
            files_with_errors.append((p.name, list(result.errors)))

    # Summary
    print()
    print("=" * 64)
    print(f"  Files attempted          {len(importable)}")
    print(f"  Rows inserted            {totals['inserted']}")
    print(f"  Rows updated             {totals['updated']}")
    print(f"  Rows skipped             {totals['rows_skipped']}")
    print(f"  Notes attached           {totals['notes_attached']}")
    print(f"  Notes orphan             {totals['notes_orphan']}")
    print(f"  Files with errors        {len(files_with_errors)}")
    print("=" * 64)
    if files_with_errors:
        print()
        print("Files with errors:")
        for fname, errs in files_with_errors:
            print(f"  {fname}: {len(errs)} error(s)")
            for err in errs[:3]:
                print(f"      {err}")
            if len(errs) > 3:
                print(f"      ... and {len(errs) - 3} more")

    return 1 if files_with_errors else 0


if __name__ == "__main__":
    sys.exit(main())
