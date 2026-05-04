"""
backend/importer/orchestrator.py

Run the full import pipeline (reader → transformer → writer) for a single
closed-file report and return a WriteResult summarising what happened.

Transaction policy (Q4 = Option A):
  Per-file transactions. The orchestrator can either:
    * Open and own a connection itself (default — used by the CLI), or
    * Borrow a caller-supplied connection (used by tests, so they can
      roll back at the end without polluting the DB).

  When owning the connection: commits on success, rolls back on any
  unhandled exception, then re-raises. The CLI catches at its level and
  proceeds with the next file.

Per-row failures (transformer returning None, writer catching DB errors)
do NOT abort the file — they're logged into result.errors and counted
in result.rows_skipped / result.notes_orphan, per Q2 = Option A.
"""

import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Optional

from backend.data.connection import get_connection
from backend.importer.reader import iter_data_rows, parse_filename
from backend.importer.transformer import transform_row
from backend.importer.writer import WriteResult, write_transformer_output


log = logging.getLogger(__name__)


def run_file(
    path: Path | str,
    *,
    conn=None,
    run_year: Optional[int] = None,
    run_month: Optional[int] = None,
) -> WriteResult:
    """Import a single closed-file xlsx into tx_case + tx_case_notes_staging.

    Args:
        path: path to the xlsx file.
        conn: optional pre-opened psycopg connection. If None, the
            orchestrator opens one and manages commit/rollback itself.
            If supplied, the caller is responsible for transaction control.
        run_year, run_month: override the run period. If either is None,
            both are parsed from the filename.

    Returns:
        WriteResult — populated with counts even if errors occurred.

    Raises:
        FilenameParseError if year/month can't be derived from the filename.
        Re-raises any unhandled exception from the streaming loop, after
        rolling back the transaction (only if the orchestrator owns the
        connection).
    """
    path = Path(path)
    result = WriteResult()

    # Determine run period
    if run_year is None or run_month is None:
        info = parse_filename(path)
        run_year = info.year
        run_month = info.month
    log.info("Importing %s as run %d-%02d", path.name, run_year, run_month)

    # Decide who owns the connection. nullcontext lets us write the same
    # `with` regardless.
    own_conn = conn is None
    cm = get_connection() if own_conn else nullcontext(conn)

    with cm as active_conn:
        with active_conn.cursor() as cursor:
            try:
                rows_seen = 0
                for raw in iter_data_rows(path):
                    rows_seen += 1
                    record, notes = transform_row(
                        cursor, raw,
                        run_year=run_year, run_month=run_month,
                    )
                    write_transformer_output(
                        cursor, record, notes,
                        run_year=run_year, run_month=run_month,
                        result=result,
                    )

                if own_conn:
                    active_conn.commit()
                log.info(
                    "Done %s: rows_seen=%d inserted=%d updated=%d skipped=%d "
                    "notes_attached=%d notes_orphan=%d errors=%d",
                    path.name, rows_seen, result.inserted, result.updated,
                    result.rows_skipped, result.notes_attached,
                    result.notes_orphan, len(result.errors),
                )
            except Exception as exc:
                # Unhandled — usually a DB connection drop or bad SQL.
                # Per-row failures are caught by writer.write_transformer_output
                # and don't reach here.
                if own_conn:
                    active_conn.rollback()
                msg = f"Import of {path.name} aborted: {exc!r}"
                log.exception(msg)
                result.errors.append(msg)
                if not own_conn:
                    # Caller manages the connection; let the exception
                    # propagate so they can decide.
                    raise
                # When we own the connection, swallow the exception and
                # return the result so the CLI can move on to the next file.

    return result
