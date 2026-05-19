"""
SAVE TO: backend/api/imports.py
(Full path on your machine: C:\\Users\\rhod_\\Documents\\BonusReport\\Application\\backend\\api\\imports.py)

IMPORTANT: this download is named "imports_api.py" but the deployed filename
must be "imports.py" — rename it when you save.

CRM import endpoints.

POST /api/imports
    Accept one or more CRM closed-file xlsx uploads. For each file:
      1. Parse year/month from the filename.
      2. Save to the persistent Railway volume at
         /data/imports/{year}/{month:02d}/{timestamp}_{filename}.
      3. Validate that the period inside the file (cell A1 / B1 header)
         matches the period from the filename. If they disagree, the
         file is REJECTED and the saved upload is deleted.
      4. Run the importer pipeline against the saved file.
      5. Record the run in tx_import_run (audit log + workflow anchor).
      6. Return a per-file result. One bad file does not block the
         others.

POST /api/imports/consolidated
    Single mass-upload xlsx (regression-test format) containing every
    closed-file row across many months/staff. Period derived per row by
    the orchestrator. Same response shape as /api/imports so the
    frontend handles both modes uniformly.

Engine is NOT auto-run. The user reviews cases and triggers the
engine separately via POST /api/engine/run.

The volume mount path is configurable via env var BONUSREPORT_DATA_DIR
(default /data) so this works locally without a volume too.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.data.connection import get_connection
from backend.importer.orchestrator import run_file
from backend.importer.consolidated_orchestrator import (
    ConsolidatedRunResult,
    run_consolidated,
)
from backend.importer.period_validator import (
    ReportPeriodMismatchError,
    ReportPeriodNotFoundError,
    validate_report_period,
)
from backend.importer.reader import parse_filename


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCEPTED_EXTENSIONS = {".xlsx", ".xlsm"}

# Volume root — overridable via env var so local dev can point at /tmp etc.
DATA_DIR = Path(os.getenv("BONUSREPORT_DATA_DIR", "/data"))
IMPORTS_DIR = DATA_DIR / "imports"


router = APIRouter(prefix="/api/imports", tags=["imports"])


# ---------------------------------------------------------------------------
# bonus_year_month parsing
# ---------------------------------------------------------------------------

# HTML <input type="month"> emits "YYYY-MM" natively. We accept that exact
# format only — anything else is a 400. Backed by tx_case.bonus_year_month
# which is a CHAR(7) string column; we pass the validated 'YYYY-MM' value
# through to the writer verbatim.
_BONUS_YYYY_MM_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _parse_bonus_year_month(value: str) -> str:
    """Validate 'YYYY-MM'. Raise HTTPException(400) on bad input.

    Returns the canonical 'YYYY-MM' form (stripped of whitespace), suitable
    for direct insertion into tx_case.bonus_year_month.
    """
    if not value:
        raise HTTPException(
            status_code=400,
            detail="bonus_year_month is required (format YYYY-MM, e.g. 2024-01).",
        )
    cleaned = value.strip()
    m = _BONUS_YYYY_MM_RE.match(cleaned)
    if not m:
        raise HTTPException(
            status_code=400,
            detail=(
                f"bonus_year_month must be YYYY-MM (e.g. 2024-01). Got: {value!r}"
            ),
        )
    return cleaned


# ---------------------------------------------------------------------------
# POST /api/imports — multi-file
# ---------------------------------------------------------------------------

@router.post("")
async def upload_crm_reports(
    files: list[UploadFile] = File(...),
    bonus_year_month: str = Form(...),
) -> dict:
    """Accept 1+ CRM xlsx uploads. Year/month derived from each filename
    AND validated against the period embedded in the file's header.

    bonus_year_month (YYYY-MM, e.g. '2024-01') is supplied ONCE by the
    uploading DQO and applied uniformly to every row across every file
    in this request. It controls which bonus run the cases are paid in,
    independent of when the case event occurred (filename year/month).

    Returns a per-file result list. Top-level summary counts successes
    and failures. One file's failure does not abort the rest.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one file required.")

    bonus_run_ym = _parse_bonus_year_month(bonus_year_month)
    log.info(
        "Upload batch: %d file(s), bonus_year_month=%s",
        len(files), bonus_run_ym,
    )

    results: list[dict] = []
    for upload in files:
        results.append(await _process_one_file(upload, bonus_run_ym))

    return {
        "total_files": len(files),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "files": results,
    }


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

async def _process_one_file(upload: UploadFile, bonus_year_month: str) -> dict:
    """Process a single uploaded file. Returns a result dict; never raises."""
    if not upload.filename:
        return {"success": False, "filename": None, "error": "No filename supplied."}

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ACCEPTED_EXTENSIONS:
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Unsupported file type {suffix!r}. Accepted: {sorted(ACCEPTED_EXTENSIONS)}.",
        }

    # Parse year/month from filename
    try:
        info = parse_filename(Path(upload.filename))
        year, month = info.year, info.month
    except Exception as exc:
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Could not parse year/month from filename: {exc!s}",
        }

    # Best-effort: derive staff_id from the filename for one-click drilldown
    # on the frontend after upload. None is fine — frontend falls back to a
    # manual staff picker on the review page.
    staff_id = _resolve_staff_from_filename(upload.filename)

    # Build destination path on the volume:
    #   /data/imports/{year}/{month:02d}/{utc-timestamp}_{filename}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = IMPORTS_DIR / str(year) / f"{month:02d}"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "success": False,
            "filename": upload.filename,
            "error": (
                f"Could not create destination directory at {dest_dir}. "
                f"Is the Railway volume attached at {DATA_DIR}? OSError: {exc!s}"
            ),
        }

    dest_path = dest_dir / f"{timestamp}_{upload.filename}"

    # Save the upload bytes to the volume
    try:
        content = await upload.read()
        dest_path.write_bytes(content)
    except OSError as exc:
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Failed to save file to {dest_path}: {exc!s}",
        }

    log.info(
        "Saved upload %s to %s (%d bytes), validating period header",
        upload.filename, dest_path, len(content),
    )

    # ---- Period validation: report's embedded header vs filename ----------
    # If the file's internal period header disagrees with what the filename
    # claims, REJECT the file. The internal header is authoritative because
    # filenames can be renamed by accident.
    try:
        report_period = validate_report_period(
            dest_path, expected_year=year, expected_month=month,
        )
    except ReportPeriodNotFoundError as exc:
        _safely_delete(dest_path)
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Period header missing: {exc!s}",
            "filename_year": year,
            "filename_month": month,
        }
    except ReportPeriodMismatchError as exc:
        _safely_delete(dest_path)
        return {
            "success": False,
            "filename": upload.filename,
            "error": str(exc),
            "filename_year": year,
            "filename_month": month,
        }

    log.info(
        "Period validated for %s: %d-%02d matches header. Running importer.",
        upload.filename, year, month,
    )

    # Run the importer (it owns the DB connection and per-file transaction)
    try:
        result = run_file(
            dest_path,
            run_year=year,
            run_month=month,
            bonus_year_month=bonus_year_month,
        )
    except Exception as exc:
        log.exception("run_file raised for %s", dest_path)
        _safely_delete(dest_path)
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Importer failed: {exc!r}",
            "file_path": str(dest_path),
        }

    # Record the run in tx_import_run
    try:
        import_run_id = _insert_import_run(
            file_path=str(dest_path),
            original_filename=upload.filename,
            run_year=year,
            run_month=month,
            result=result,
        )
    except Exception as exc:
        # Cases were inserted; the audit-log row failed. Partial success.
        log.exception("tx_import_run insert failed for %s", dest_path)
        return {
            "success": True,
            "filename": upload.filename,
            "import_run_id": None,
            "run_year": year,
            "run_month": month,
            "bonus_year_month": bonus_year_month,
            "staff_id": staff_id,
            "report_period": str(report_period),
            "file_path": str(dest_path),
            "summary": _summary_from_result(result),
            "errors": result.errors,
            "warning": f"Cases imported but tx_import_run row not created: {exc!s}",
        }

    return {
        "success": True,
        "filename": upload.filename,
        "import_run_id": import_run_id,
        "run_year": year,
        "run_month": month,
        "bonus_year_month": bonus_year_month,
        "staff_id": staff_id,
        "report_period": str(report_period),
        "file_path": str(dest_path),
        "summary": _summary_from_result(result),
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# POST /api/imports/consolidated — single mass-upload file
# ---------------------------------------------------------------------------

@router.post("/consolidated")
async def upload_consolidated_report(file: UploadFile = File(...)) -> dict:
    """Accept a single mass-upload xlsx (every status across many months in
    one file — the format we use for regression testing).

    Unlike POST /api/imports:
      - one file only
      - no filename → period parsing (file spans many periods)
      - period is derived per row inside the orchestrator
      - tx_import_run is recorded with the *upload* date as run_year/run_month
        (since the data spans many periods, this is the timestamp of the
        action, not of the data)

    Returns the same shape as POST /api/imports so the frontend handles
    both modes uniformly.
    """
    result = await _process_consolidated_file(file)
    return {
        "total_files": 1,
        "successful": 1 if result["success"] else 0,
        "failed": 0 if result["success"] else 1,
        "files": [result],
    }


async def _process_consolidated_file(upload: UploadFile) -> dict:
    """Process one consolidated xlsx. Returns a result dict; never raises.

    Result shape matches the per-file shape returned by POST /api/imports
    so the frontend can render both upload modes with the same code.
    """
    if not upload.filename:
        return {"success": False, "filename": None, "error": "No filename supplied."}

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ACCEPTED_EXTENSIONS:
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Unsupported file type {suffix!r}. Accepted: {sorted(ACCEPTED_EXTENSIONS)}.",
        }

    # Save into a dedicated sub-directory so consolidated files are easy to
    # find later: /data/imports/consolidated/{utc-timestamp}_{filename}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = IMPORTS_DIR / "consolidated"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "success": False,
            "filename": upload.filename,
            "error": (
                f"Could not create destination directory at {dest_dir}. "
                f"Is the Railway volume attached at {DATA_DIR}? OSError: {exc!s}"
            ),
        }
    dest_path = dest_dir / f"{timestamp}_{upload.filename}"

    try:
        content = await upload.read()
        dest_path.write_bytes(content)
    except OSError as exc:
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Failed to save file to {dest_path}: {exc!s}",
        }

    log.info(
        "Saved consolidated upload %s to %s (%d bytes), running importer",
        upload.filename, dest_path, len(content),
    )

    # ---- Run the consolidated importer ------------------------------------
    # truncate_first=False — additive, never wipes existing cases.
    try:
        cresult: ConsolidatedRunResult = run_consolidated(
            dest_path,
            truncate_first=False,
        )
    except Exception as exc:
        log.exception("run_consolidated raised for %s", dest_path)
        _safely_delete(dest_path)
        return {
            "success": False,
            "filename": upload.filename,
            "error": f"Importer failed: {exc!r}",
            "file_path": str(dest_path),
        }

    # Record the run in tx_import_run. Year/month here are the upload-action
    # timestamp, not the data period (which spans many months). The /imports
    # UI surfaces this with a "(consolidated)" label in the filename.
    now = datetime.now(timezone.utc)
    display_filename = f"{upload.filename} (consolidated)"
    try:
        import_run_id = _insert_import_run(
            file_path=str(dest_path),
            original_filename=display_filename,
            run_year=now.year,
            run_month=now.month,
            result=cresult.write,
        )
    except Exception as exc:
        log.exception("tx_import_run insert failed for consolidated %s", dest_path)
        # Cases were inserted; only the audit-log row failed. Partial success.
        return {
            "success": True,
            "filename": upload.filename,
            "import_run_id": None,
            "run_year": now.year,
            "run_month": now.month,
            "staff_id": None,
            "file_path": str(dest_path),
            "summary": _summary_from_consolidated(cresult),
            "errors": cresult.write.errors,
            "warning": f"Cases imported but tx_import_run row not created: {exc!s}",
        }

    # Build a single result row matching the individual-upload response shape.
    response = {
        "success": True,
        "filename": upload.filename,
        "import_run_id": import_run_id,
        "run_year": now.year,
        "run_month": now.month,
        "staff_id": None,
        "file_path": str(dest_path),
        "summary": _summary_from_consolidated(cresult),
        "errors": cresult.write.errors,
    }
    # Surface period-derivation failures as a warning so the user sees them
    # without having to scroll a long errors list.
    if cresult.rows_period_unresolved > 0:
        sample = "; ".join(cresult.period_failures[:3])
        response["warning"] = (
            f"{cresult.rows_period_unresolved} row(s) skipped because the "
            f"period could not be derived. Sample: {sample}"
        )
    return response


def _summary_from_consolidated(cresult: ConsolidatedRunResult) -> dict:
    """Map ConsolidatedRunResult onto the per-file summary shape used by the
    frontend (same fields as _summary_from_result for the individual mode).
    """
    w = cresult.write
    return {
        "inserted": w.inserted,
        "updated": w.updated,
        # rows_skipped here is the writer's count (transformer returned None).
        # rows_period_unresolved is exposed separately via the warning.
        "rows_skipped": w.rows_skipped + cresult.rows_period_unresolved,
        "notes_attached": w.notes_attached,
        "notes_orphan": w.notes_orphan,
        "error_count": len(w.errors),
        # Extra fields specific to consolidated, ignored by the frontend
        # but useful for debugging.
        "rows_seen": cresult.rows_seen,
        "rows_period_unresolved": cresult.rows_period_unresolved,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safely_delete(path: Path) -> None:
    """Best-effort delete used when an upload should not be retained."""
    try:
        path.unlink()
    except OSError:
        log.warning("Could not delete %s after rejection", path)


def _resolve_staff_from_filename(filename: str) -> int | None:
    """Extract staff name from filenames like
        "Trần Thanh Gia Mẫn's report of closed file in January 2025.xlsx"
    and resolve it to a ref_staff.id. Returns None on any failure
    (regex miss, DB miss, or DB error). Never raises.

    Handles both ASCII apostrophe (U+0027) and curly/typographic
    apostrophe (U+2019) since filenames can contain either.
    """
    name_part = unicodedata.normalize("NFC", filename)
    # [\u0027\u2019] = either straight ' or curly '
    m = re.match(
        r"^(.+?)[\u0027\u2019]s\s+report\s+of\s+closed\s+file",
        name_part,
        re.IGNORECASE,
    )
    if not m:
        log.info("Filename did not match staff regex: %r", filename)
        return None
    staff_name = m.group(1).strip()
    if not staff_name:
        return None
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM ref_staff WHERE canonical_name ILIKE %s LIMIT 1",
                    (staff_name,),
                )
                row = cur.fetchone()
                if row is None:
                    log.info(
                        "No ref_staff match for %r (parsed from %r)",
                        staff_name, filename,
                    )
                    return None
                return row["id"]
    except Exception:
        log.exception("Failed to resolve staff_id from filename %r", filename)
        return None


def _summary_from_result(result) -> dict:
    return {
        "inserted": result.inserted,
        "updated": result.updated,
        "rows_skipped": result.rows_skipped,
        "notes_attached": result.notes_attached,
        "notes_orphan": result.notes_orphan,
        "error_count": len(result.errors),
    }


def _insert_import_run(
    *,
    file_path: str,
    original_filename: str,
    run_year: int,
    run_month: int,
    result,
) -> int:
    """Insert one tx_import_run row. Returns the new row's id."""
    sql = """
        INSERT INTO tx_import_run (
            file_path, original_filename, run_year, run_month,
            inserted_count, updated_count, rows_skipped_count,
            notes_attached_count, notes_orphan_count,
            error_count, errors_json
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        )
        RETURNING id
    """
    errors_json = json.dumps(result.errors) if result.errors else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    file_path, original_filename, run_year, run_month,
                    result.inserted, result.updated, result.rows_skipped,
                    result.notes_attached, result.notes_orphan,
                    len(result.errors), errors_json,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"]
