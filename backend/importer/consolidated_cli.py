"""
backend/importer/consolidated_cli.py

Command-line entry point for the consolidated CRM importer.

Usage from project root:
    python -m backend.importer.consolidated_cli FILE [options]

Most-common patterns:
    # Import the entire file (dry-run first, then real)
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" --dry-run
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx"

    # Wipe tx_case first then bulk reimport (Q5 = clean slate)
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" --truncate

    # Filter to one staff member's cases only
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" \\
        --staff-name "Phạm Thị Lợi"

    # Filter by role + a date window
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" \\
        --role COUNS_DIR --visa-received-from 2024-01-01 --visa-received-to 2024-06-30

    # Sample the first 50 rows (handy for smoke tests)
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" --limit 50

    # Targeted re-import of just a few cases (no truncate; existing rows
    # are upserted in place). Useful for validating a fix without a full
    # 13-min reload.
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" \\
        --contract SLC-12858 --contract SLC-12859

    # Targeted re-import from a file (one Contract ID per line)
    python -m backend.importer.consolidated_cli "C:/path/Report.xlsx" \\
        --contracts-file flagged_cases.txt

The legacy per-staff per-month importer (backend.importer.cli) is unchanged
and still works for one-off file re-imports.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from backend.data.connection import get_connection
from backend.importer.consolidated_orchestrator import (
    build_staff_names_lower,
    run_consolidated,
)


log = logging.getLogger("consolidated_importer")


# ---------------------------------------------------------------------------
# argparse helpers
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


def _parse_date_arg(s: str) -> datetime:
    """Parse a CLI date argument. Accepts YYYY-MM-DD or DD/MM/YYYY."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"date {s!r} not in any of the accepted formats: {', '.join(_DATE_FORMATS)}"
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(log_dir: Path) -> Path:
    """Configure root logger; mirrors backend.importer.cli's setup."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"consolidated_import_{timestamp}.log"

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return log_path


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def _print_summary(result, dry_run: bool) -> None:
    w = result.write
    print()
    print("=" * 60)
    print("CONSOLIDATED IMPORT SUMMARY" + (" (DRY RUN — NOT COMMITTED)" if dry_run else ""))
    print("=" * 60)
    print(f"  Rows seen (after filters):     {result.rows_seen}")
    print(f"  tx_case inserted:              {w.inserted}")
    print(f"  tx_case blocked (duplicate):   {w.blocked}")
    print(f"  Rows skipped (transformer):    {w.rows_skipped}")
    print(f"  Period unresolved (skipped):   {result.rows_period_unresolved}")
    print(f"  Notes attached to a case:      {w.notes_attached}")
    print(f"  Notes orphaned (no case):      {w.notes_orphan}")
    print(f"  Errors:                        {len(w.errors)}")

    if w.blocked > 0 and w.blocked_details:
        print()
        print(f"  Sample blocked rows (first 10 of {w.blocked}):")
        for d in w.blocked_details[:10]:
            print(
                f"    - {d.contract_id} | status={d.application_status!r} | "
                f"existing case_id={d.existing_case_id} "
                f"workflow_state={d.existing_workflow_state} "
                f"run={d.existing_run_year}-{d.existing_run_month:02d}"
            )
        if w.blocked > 10:
            print(f"    ... and {w.blocked - 10} more (see log file)")

    if result.period_failures:
        print()
        print("  Sample period-derivation failures (first 10):")
        for line in result.period_failures:
            print(f"    - {line}")

    if w.errors:
        print()
        print("  Errors:")
        for err in w.errors[:10]:
            print(f"    - {err}")
        if len(w.errors) > 10:
            print(f"    ... and {len(w.errors) - 10} more (see log file)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import the consolidated CRM xlsx into tx_case.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument("file", type=Path, help="Path to the consolidated CRM .xlsx file.")

    # Run mode
    parser.add_argument("--log-dir", type=Path, default=Path("backend/logs"),
                        help="Directory for run logs (default: backend/logs).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the pipeline but roll back at the end (nothing committed).")
    parser.add_argument("--truncate", action="store_true",
                        help="TRUNCATE tx_case before importing (Q5 = clean slate).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after this many rows have passed all filters (sampling).")

    # Row filters — staff
    parser.add_argument("--staff-name", type=str, default=None,
                        help="Match Counsellor Name OR Case Officer Name (case-insensitive).")
    parser.add_argument("--role", action="append", default=None, metavar="CODE",
                        help="Limit to staff with this primary role code (e.g. COUNS_DIR). Repeatable.")
    parser.add_argument("--office", action="append", default=None, metavar="CODE",
                        help="Limit to staff with this home office code (e.g. HCM). Repeatable.")

    # Row filters — contract IDs (targeted re-imports)
    parser.add_argument("--contract", action="append", default=None, metavar="ID",
                        help="Limit to this Contract ID (e.g. SLC-12858). Repeatable. "
                             "Combine with --contracts-file to extend the set.")
    parser.add_argument("--contracts-file", type=Path, default=None, metavar="PATH",
                        help="Path to a text file with one Contract ID per line. "
                             "Blank lines and lines starting with '#' are ignored. "
                             "Combined with --contract entries (union).")

    # Row filters — dates (inclusive on both ends)
    parser.add_argument("--contract-signed-from", type=_parse_date_arg, default=None)
    parser.add_argument("--contract-signed-to",   type=_parse_date_arg, default=None)
    parser.add_argument("--visa-received-from",   type=_parse_date_arg, default=None)
    parser.add_argument("--visa-received-to",     type=_parse_date_arg, default=None)
    parser.add_argument("--course-start-from",    type=_parse_date_arg, default=None)
    parser.add_argument("--course-start-to",      type=_parse_date_arg, default=None)

    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"ERROR: file not found: {args.file}", file=sys.stderr)
        return 2

    log_path = _setup_logging(args.log_dir)
    log.info("Run starting. Log file: %s", log_path)
    log.info("Input file: %s", args.file)
    if args.dry_run:
        log.info("DRY-RUN mode: nothing will be committed.")
    if args.truncate:
        log.warning("TRUNCATE mode: tx_case will be wiped before import.")

    # Open one connection; orchestrator borrows it (so we control commit/rollback)
    with get_connection() as conn:
        # Build the staff-name filter set from staff_name / role / office, if any
        with conn.cursor() as cursor:
            staff_names_lower = build_staff_names_lower(
                cursor,
                staff_name=args.staff_name,
                role_codes=args.role,
                office_codes=args.office,
            )
        if staff_names_lower is not None:
            log.info(
                "Staff filter active: %d name(s) matched. Sample: %s",
                len(staff_names_lower),
                ", ".join(sorted(staff_names_lower))[:200],
            )

        # Build the optional Contract-ID filter set from --contract entries
        # and/or --contracts-file. Both sources combine (union). None means
        # "no contract filter".
        contract_ids: set[str] | None = None
        if args.contract or args.contracts_file:
            contract_ids = set()
            if args.contract:
                contract_ids.update(c.strip() for c in args.contract if c and c.strip())
            if args.contracts_file:
                if not args.contracts_file.is_file():
                    print(f"ERROR: contracts file not found: {args.contracts_file}",
                          file=sys.stderr)
                    return 2
                with args.contracts_file.open(encoding="utf-8") as fh:
                    for line in fh:
                        s = line.strip()
                        if s and not s.startswith("#"):
                            contract_ids.add(s)
            if not contract_ids:
                print("ERROR: --contract/--contracts-file given but no IDs parsed.",
                      file=sys.stderr)
                return 2
            log.info("Contract-ID filter: %d unique id(s) loaded.", len(contract_ids))

        # Run the import. Pass conn so we own commit/rollback at this layer.
        try:
            result = run_consolidated(
                args.file,
                conn=conn,
                truncate_first=args.truncate,
                staff_names_lower=staff_names_lower,
                contract_ids=contract_ids,
                contract_signed_from=args.contract_signed_from,
                contract_signed_to=args.contract_signed_to,
                visa_received_from=args.visa_received_from,
                visa_received_to=args.visa_received_to,
                course_start_from=args.course_start_from,
                course_start_to=args.course_start_to,
                limit=args.limit,
            )
            if args.dry_run:
                conn.rollback()
                log.info("DRY-RUN complete. All changes rolled back.")
            else:
                conn.commit()
                log.info("Import committed.")
        except Exception as exc:
            conn.rollback()
            log.exception("Import aborted with hard failure: %s", exc)
            print(f"\nFATAL: {exc!r}", file=sys.stderr)
            print(f"See log: {log_path}", file=sys.stderr)
            return 1

    _print_summary(result, dry_run=args.dry_run)
    print(f"\nFull log: {log_path}")
    return 1 if result.write.errors else 0


if __name__ == "__main__":
    sys.exit(main())
