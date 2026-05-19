"""
backend/importer/orchestrator.py

Run the full import pipeline (reader → transformer → writer) for a single
closed-file report and return a WriteResult summarising what happened.

Transaction policy:
  Per-file transactions. The orchestrator can either:
    * Open and own a connection itself (default — used by the CLI), or
    * Borrow a caller-supplied connection (used by tests / FastAPI).

  When owning the connection: commits on success, rolls back on any
  unhandled exception, then re-raises (or swallows, see below).

Per-row failures (transformer returning None, writer catching DB errors,
writer reporting BLOCKED) do NOT abort the file — they're counted in the
WriteResult fields and the file processes to completion.
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
    bonus_year_month: str,
    conn=None,
    run_year: Optional[int] = None,
    run_month: Optional[int] = None,
) -> WriteResult:
    """Import a single closed-file xlsx into tx_case + tx_case_notes_staging.

    Args:
        path: path to the xlsx file.
        bonus_year_month: DQO-keyed bonus run period in 'YYYY-MM' form,
            applied uniformly to every row produced by this import.
            REQUIRED. Distinct from run_year/run_month which reflect when
            the case event happened (parsed from filename); this reflects
            which bonus run the case should be paid in (supports
            retroactive / forward-dated uploads). Stored to
            tx_case.bonus_year_month (CHAR(7)).
        conn: optional pre-opened psycopg connection. If None, the
            orchestrator opens one and manages commit/rollback itself.
            If supplied, the caller is responsible for transaction control.
        run_year, run_month: override the run period. If either is None,
            both are parsed from the filename.

    Returns:
        WriteResult — populated with counts even if errors occurred.
        Includes result.blocked and result.blocked_details listing any
        rows rejected because (contract_id, application_status) already
        existed in tx_case.

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
    log.info(
        "Importing %s as run %d-%02d (bonus_year_month=%s)",
        path.name, run_year, run_month, bonus_year_month,
    )

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
                        bonus_year_month=bonus_year_month,
                    )
                    write_transformer_output(
                        cursor, record, notes,
                        run_year=run_year, run_month=run_month,
                        result=result,
                    )

                if own_conn:
                    active_conn.commit()
                log.info(
                    "Done %s: rows_seen=%d inserted=%d blocked=%d skipped=%d "
                    "notes_attached=%d notes_orphan=%d errors=%d",
                    path.name, rows_seen, result.inserted, result.blocked,
                    result.rows_skipped, result.notes_attached,
                    result.notes_orphan, len(result.errors),
                )
                if result.blocked > 0:
                    log.info(
                        "%d row(s) BLOCKED by existing (contract_id, application_status). "
                        "See result.blocked_details for the list — the frontend should "
                        "prompt the user about replace/delete based on existing "
                        "workflow_state.",
                        result.blocked,
                    )
            except Exception as exc:
                # Unhandled — usually a DB connection drop or bad SQL.
                # Per-row failures are caught in writer.write_transformer_output
                # and don't reach here.
                if own_conn:
                    active_conn.rollback()
                msg = f"Import of {path.name} aborted: {exc!r}"
                log.exception(msg)
                result.errors.append(msg)
                if not own_conn:
                    raise
                # When we own the connection, swallow the exception and
                # return the result so the CLI can move on to the next file.

    return result
