"""
backend/importer/cli.py

Command-line entry point for the closed-file importer.

Usage from project root:
    python -m backend.importer.cli FILE_OR_DIR [FILE_OR_DIR ...] [options]

Options:
    --log-dir PATH    Directory for run log files. Default: backend/logs.
    --dry-run         Run the pipeline but never commit. Useful for
                      previewing what an import would do.

Examples:
    # Import a single file
    python -m backend.importer.cli "C:/path/to/report_April_2025.xlsx"

    # Import every closed-file xlsx in a folder
    python -m backend.importer.cli "C:/path/to/2025_reports"

    # Dry run to see what would happen without committing
    python -m backend.importer.cli "C:/path/to/2025_reports" --dry-run
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from backend.data.connection import get_connection
from backend.importer.orchestrator import run_file
from backend.importer.reader import FilenameParseError, parse_filename
from backend.importer.writer import WriteResult


log = logging.getLogger("importer")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(log_dir: Path) -> Path:
    """Configure root logger for this run.

    Adds a file handler under log_dir (created if missing) and a console
    handler on stderr. Returns the path to the log file so the CLI can
    print it at the end.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"import_{timestamp}.log"

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
    # Avoid double-attach if cli.py is invoked twice in a Python session
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    return log_path


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _discover_files(inputs: list[Path]) -> list[Path]:
    """Expand directory arguments into a flat, deduplicated list of xlsx files.

    Files whose names don't parse to a (year, month) are skipped with a
    warning — they're not closed-file reports.
    """
    candidates: list[Path] = []
    for entry in inputs:
        if entry.is_dir():
            candidates.extend(sorted(entry.glob("*.xlsx")))
        elif entry.is_file():
            candidates.append(entry)
        else:
            log.warning("Skipping %s: not a file or directory.", entry)

    valid: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            parse_filename(path)
        except FilenameParseError:
            log.warning("Skipping %s: filename does not contain a recognised Month_Year.", path.name)
            continue
        valid.append(path)
    return valid


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def _print_summary(per_file: list[tuple[Path, WriteResult]]) -> None:
    """Print a friendly summary table to stdout.

    Stdout (not stderr) so it's easy to capture or pipe.
    """
    if not per_file:
        print("\nNo files processed.")
        return

    # Trim filenames to keep the line readable
    name_width = min(50, max(len(p.name) for p, _ in per_file))
    name_width = max(name_width, len("File"))
    header = (
        f"\n{'File':<{name_width}}  "
        f"{'Inserted':>8}  {'Updated':>8}  {'Skipped':>8}  "
        f"{'Notes':>6}  {'Orphan':>6}  {'Errors':>6}"
    )
    print(header)
    print("-" * len(header))

    totals = WriteResult()
    for path, r in per_file:
        print(
            f"{path.name[:name_width]:<{name_width}}  "
            f"{r.inserted:>8}  {r.updated:>8}  {r.rows_skipped:>8}  "
            f"{r.notes_attached:>6}  {r.notes_orphan:>6}  {len(r.errors):>6}"
        )
        totals.merge(r)

    print("-" * len(header))
    print(
        f"{'TOTAL':<{name_width}}  "
        f"{totals.inserted:>8}  {totals.updated:>8}  {totals.rows_skipped:>8}  "
        f"{totals.notes_attached:>6}  {totals.notes_orphan:>6}  {len(totals.errors):>6}"
    )

    if totals.errors:
        print("\nErrors:")
        for err in totals.errors:
            print(f"  - {err}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import closed-file reports into tx_case.")
    parser.add_argument("inputs", nargs="+", type=Path,
                        help="Files or directories to import.")
    parser.add_argument("--log-dir", type=Path, default=Path("backend/logs"),
                        help="Directory for run logs (default: backend/logs).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run pipeline but do not commit anything.")
    args = parser.parse_args(argv)

    log_path = _setup_logging(args.log_dir)
    log.info("Run starting. Log file: %s", log_path)
    if args.dry_run:
        log.info("DRY-RUN mode: nothing will be committed.")

    files = _discover_files(args.inputs)
    if not files:
        log.warning("No matching files found in inputs: %s", [str(p) for p in args.inputs])
        return 0

    per_file: list[tuple[Path, WriteResult]] = []

    if args.dry_run:
        # Single connection across all files; rolled back at the end.
        with get_connection() as conn:
            for path in files:
                try:
                    result = run_file(path, conn=conn)
                except Exception as exc:
                    log.exception("Hard failure importing %s: %s", path.name, exc)
                    result = WriteResult()
                    result.errors.append(repr(exc))
                per_file.append((path, result))
            # Explicit rollback so behaviour is obvious; uncommitted work
            # would roll back anyway when the context exits.
            conn.rollback()
            log.info("DRY-RUN complete. All changes rolled back.")
    else:
        # One connection reused, but committed/rolled back per file
        # (per Q4 = Option A).
        with get_connection() as conn:
            for path in files:
                try:
                    result = run_file(path, conn=conn)
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    log.exception("Hard failure importing %s — file rolled back: %s",
                                  path.name, exc)
                    result = WriteResult()
                    result.errors.append(repr(exc))
                per_file.append((path, result))

    _print_summary(per_file)
    print(f"\nFull log: {log_path}")

    any_errors = any(r.errors for _, r in per_file)
    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main())
