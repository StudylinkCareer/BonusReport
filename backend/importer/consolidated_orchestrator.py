"""
backend/importer/consolidated_orchestrator.py

Run the import pipeline for the consolidated CRM file. Replaces the
per-month orchestrator's role for the going-forward format.

Pipeline shape per row:
    consolidated_reader.iter_filtered_rows(...)
        -> derive run_year/run_month from status + dates
        -> transformer.transform_row(...)
        -> writer.write_transformer_output(...)

Differences from the per-month orchestrator (orchestrator.py):
  * No filename-based period parsing — period is derived per row.
  * No per-file commit boundary — the consolidated file is one logical
    "import" so the whole run is one transaction (commit at end, rollback
    on unhandled exception). The CLI controls dry-run.
  * Optional truncate-first pass to wipe tx_case for a clean reimport
    (per Q5 = Truncate first).
  * Filtering is applied at the reader level, not here.

Run period derivation rules (locked, see chat 2026-05-09):
    | Status                                   | Source                        |
    | ---------------------------------------- | ----------------------------- |
    | Closed - Visa granted                    | Visa Received Date            |
    | Closed - Visa granted, then enrolled     | Course Start Date             |
    | Closed - Enrolled, then Visa granted     | Visa Received Date            |
    | Closed - Visa refused                    | Visa Received Date            |
    | Closed - Visa granted then cancelled     | Visa Received Date            |
    | Closed - Enrolment                       | Course Start Date             |
    | Current - Enrolled                       | Course Start Date             |
    | Closed - Institution refused             | Course Start Date             |
    | Closed - Enrolled, then Cancelled        | Course Start Date             |
    | Closed - Cancelled                       | Course Start → Contract Signed|
    | Current                                  | Contract Signed Date          |

Any row whose chosen source date is missing falls back to the next
candidate; if all candidates are missing the row is skipped with a note.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from backend.data.connection import get_connection
from backend.importer.cached_resolvers import ResolverCache
from backend.importer.consolidated_reader import iter_filtered_rows
from backend.importer.reader import RawRow
from backend.importer.transformer import NoteRecord, transform_row
from backend.importer.writer import WriteResult, write_transformer_output


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run-period derivation
# ---------------------------------------------------------------------------

# Per-status preference list. The first non-None date wins. If all are
# None the row is skipped. Keys must match the exact text in
# 'Application Report Status'.
_PERIOD_SOURCES: dict[str, tuple[str, ...]] = {
    "Closed - Visa granted":                ("Visa Received Date",),
    "Closed - Visa granted, then enrolled": ("Course Start Date",),
    "Closed - Enrolled, then Visa granted": ("Visa Received Date",),
    "Closed - Visa refused":                ("Visa Received Date",),
    "Closed - Visa granted then cancelled": ("Visa Received Date",),
    "Closed - Enrolment":                   ("Course Start Date",),
    "Current - Enrolled":                   ("Course Start Date",),
    "Closed - Institution refused":         ("Course Start Date",),
    "Closed - Enrolled, then Cancelled":    ("Course Start Date",),
    "Closed - Cancelled":                   ("Course Start Date", "Contract Signed Date"),
    "Current":                              ("Contract Signed Date",),
}


@dataclass(frozen=True)
class PeriodResolution:
    """Result of deriving a run period for one row."""
    year: Optional[int]
    month: Optional[int]
    source_column: Optional[str]   # which column the date came from, e.g. 'Visa Received Date'
    failure_reason: Optional[str]  # human-readable why-skipped, when year/month are None


def derive_run_period(row_data: dict[str, Any]) -> PeriodResolution:
    """Derive (run_year, run_month) for one consolidated-file row.

    Returns a PeriodResolution; if year/month are None the row should be
    skipped and the failure_reason emitted as an orphan note.
    """
    status_raw = row_data.get("Application Report Status")
    status = str(status_raw).strip() if status_raw else ""
    if not status:
        return PeriodResolution(
            year=None, month=None, source_column=None,
            failure_reason="row has no Application Report Status",
        )

    sources = _PERIOD_SOURCES.get(status)
    if sources is None:
        return PeriodResolution(
            year=None, month=None, source_column=None,
            failure_reason=f"unknown Application Report Status {status!r}",
        )

    for col in sources:
        v = row_data.get(col)
        if isinstance(v, datetime):
            return PeriodResolution(
                year=v.year, month=v.month,
                source_column=col, failure_reason=None,
            )
    # All candidate sources empty
    tried = ", ".join(sources)
    return PeriodResolution(
        year=None, month=None, source_column=None,
        failure_reason=f"status {status!r} expected one of [{tried}] populated, all empty",
    )


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------

@dataclass
class ConsolidatedRunResult:
    """Aggregate counts for one consolidated-import run.

    Wraps WriteResult (which counts inserts/updates/etc.) and adds counts
    specific to this orchestrator (e.g. rows where period derivation failed).
    """
    write: WriteResult = field(default_factory=WriteResult)
    rows_seen: int = 0
    rows_period_unresolved: int = 0
    period_failures: list[str] = field(default_factory=list)  # sample reasons


# ---------------------------------------------------------------------------
# Truncate helper
# ---------------------------------------------------------------------------

def truncate_tx_case(cursor) -> None:
    """Wipe tx_case (and dependent staging notes) for a clean reimport.

    Per Q5: clean slate before bulk consolidated import. Uses TRUNCATE
    CASCADE so tx_case_notes_staging is cleared too. Resets the BIGSERIAL
    so ids start from 1 again.
    """
    log.warning("TRUNCATE tx_case CASCADE — wiping all existing case rows.")
    cursor.execute("TRUNCATE TABLE tx_case RESTART IDENTITY CASCADE")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_consolidated(
    path: Path | str,
    *,
    conn=None,
    truncate_first: bool = False,
    staff_names_lower: Optional[set[str]] = None,
    contract_signed_from: Optional[datetime] = None,
    contract_signed_to:   Optional[datetime] = None,
    visa_received_from:   Optional[datetime] = None,
    visa_received_to:     Optional[datetime] = None,
    course_start_from:    Optional[datetime] = None,
    course_start_to:      Optional[datetime] = None,
    limit: Optional[int] = None,
) -> ConsolidatedRunResult:
    """Import the consolidated CRM file into tx_case.

    Args
    ----
    path : .xlsx file path.
    conn : optional pre-opened psycopg connection. If None, the
        orchestrator opens one and manages commit/rollback. If supplied
        (e.g. for tests/dry-run), the caller is responsible for txn control.
    truncate_first : if True, TRUNCATE tx_case CASCADE before importing.
    staff_names_lower / *_from / *_to / limit : passed through to the
        reader; see consolidated_reader.iter_filtered_rows().

    Returns
    -------
    ConsolidatedRunResult — counts and a sample of period-derivation failures.
    """
    path = Path(path)
    result = ConsolidatedRunResult()
    log.info("Consolidated import starting for %s", path.name)
    if truncate_first:
        log.info("Will TRUNCATE tx_case before import.")

    own_conn = conn is None
    cm = get_connection() if own_conn else nullcontext(conn)

    with cm as active_conn:
        with active_conn.cursor() as cursor:
            try:
                if truncate_first:
                    truncate_tx_case(cursor)

                with ResolverCache(cursor):
                    row_iter = iter_filtered_rows(
                        path,
                        staff_names_lower=staff_names_lower,
                        contract_signed_from=contract_signed_from,
                        contract_signed_to=contract_signed_to,
                        visa_received_from=visa_received_from,
                        visa_received_to=visa_received_to,
                        course_start_from=course_start_from,
                        course_start_to=course_start_to,
                        limit=limit,
                    )

                    for raw in row_iter:
                        result.rows_seen += 1
                        period = derive_run_period(raw.data)

                        if period.year is None:
                            # Skip; log an orphan note so it shows up downstream
                            result.rows_period_unresolved += 1
                            if len(result.period_failures) < 10:
                                result.period_failures.append(
                                    f"row {raw.row_number} (contract={raw.data.get('Contract ID')!r}): "
                                    f"{period.failure_reason}"
                                )
                            notes = [
                                NoteRecord(
                                    warning_type="period_unresolved",
                                    raw_value=str(raw.data.get("Application Report Status") or ""),
                                    note=period.failure_reason or "",
                                )
                            ]
                            write_transformer_output(
                                cursor, None, notes,
                                run_year=0, run_month=0,  # sentinel; orphan note only
                                result=result.write,
                            )
                            continue

                        record, notes = transform_row(
                            cursor, raw,
                            run_year=period.year, run_month=period.month,
                        )
                        write_transformer_output(
                            cursor, record, notes,
                            run_year=period.year, run_month=period.month,
                            result=result.write,
                        )

                if own_conn:
                    active_conn.commit()
                log.info(
                    "Consolidated import done: rows_seen=%d inserted=%d updated=%d "
                    "rows_skipped=%d period_unresolved=%d notes_attached=%d "
                    "notes_orphan=%d errors=%d",
                    result.rows_seen, result.write.inserted, result.write.updated,
                    result.write.rows_skipped, result.rows_period_unresolved,
                    result.write.notes_attached, result.write.notes_orphan,
                    len(result.write.errors),
                )

            except Exception as exc:
                if own_conn:
                    active_conn.rollback()
                msg = f"Consolidated import of {path.name} aborted: {exc!r}"
                log.exception(msg)
                result.write.errors.append(msg)
                if not own_conn:
                    raise
                # Owned connection: swallow + return result so CLI can report.

    return result


# ---------------------------------------------------------------------------
# Filter-set builder (the only DB-touching helper)
# ---------------------------------------------------------------------------

def build_staff_names_lower(
    cursor,
    *,
    staff_name: Optional[str] = None,
    role_codes: Optional[Iterable[str]] = None,
    office_codes: Optional[Iterable[str]] = None,
) -> Optional[set[str]]:
    """Build the lowercase staff-name set for the reader's staff filter.

    Logic
    -----
    If none of staff_name/role_codes/office_codes are provided, returns
    None — telling the reader "no staff filter".

    Otherwise, queries ref_staff (filtered by role/office if provided) and
    ref_staff_alias to return ALL canonical names + aliases for matching
    staff. If staff_name is provided it must resolve to a canonical or
    alias; any role/office filters narrow the set further.

    The resulting set is lowercased + NBSP-stripped to match the reader's
    matching convention.
    """
    if staff_name is None and not role_codes and not office_codes:
        return None

    where_parts = []
    params: list[Any] = []

    if role_codes:
        where_parts.append(
            "s.primary_role_id IN (SELECT id FROM dim_role WHERE code = ANY(%s))"
        )
        params.append(list(role_codes))
    if office_codes:
        where_parts.append(
            "s.home_office_id IN (SELECT id FROM dim_office WHERE code = ANY(%s))"
        )
        params.append(list(office_codes))

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # Get all (id, canonical_name) for staff matching role/office criteria.
    cursor.execute(
        f"SELECT s.id, s.canonical_name FROM ref_staff s {where_sql}",
        params,
    )
    rows = cursor.fetchall()
    matching_ids = [r["id"] for r in rows]
    names: set[str] = {r["canonical_name"] for r in rows}

    # Add aliases for those staff
    if matching_ids:
        cursor.execute(
            "SELECT alias FROM ref_staff_alias WHERE staff_id = ANY(%s)",
            (matching_ids,),
        )
        names.update(r["alias"] for r in cursor.fetchall())

    if staff_name:
        target = staff_name.replace("\u00a0", " ").strip().lower()
        # Filter the role/office-narrowed set down to those matching the name
        names = {n for n in names if n.replace("\u00a0", " ").strip().lower() == target}
        if not names:
            log.warning(
                "build_staff_names_lower: staff_name %r not in role/office-filtered set; "
                "filter will exclude every row.", staff_name,
            )

    return {n.replace("\u00a0", " ").strip().lower() for n in names if n}
