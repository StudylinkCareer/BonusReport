"""
backend/api/imports.py — CRM import endpoints.

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

    Engine is NOT auto-run. The user reviews cases and triggers the
    engine separately via POST /api/engine/run.

The volume mount path is configurable via env var BONUSREPORT_DATA_DIR
(default /data) so this works locally without a volume too.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.data.connection import get_connection
from backend.importer.orchestrator import run_file
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
# POST /api/imports — multi-file
# ---------------------------------------------------------------------------

@router.post("")
async def upload_crm_reports(files: list[UploadFile] = File(...)) -> dict:
    """Accept 1+ CRM xlsx uploads. Year/month derived from each filename
    AND validated against the period embedded in the file's header.

    Returns a per-file result list. Top-level summary counts successes
    and failures. One file's failure does not abort the rest.
    """
    if not files:
        raise HTTPException(status_code=400, detail="At least one file required.")

    results: list[dict] = []
    for upload in files:
        results.append(await _process_one_file(upload))

    return {
        "total_files": len(files),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "files": results,
    }


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

async def _process_one_file(upload: UploadFile) -> dict:
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
        result = run_file(dest_path, run_year=year, run_month=month)
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
        "report_period": str(report_period),
        "file_path": str(dest_path),
        "summary": _summary_from_result(result),
        "errors": result.errors,
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
