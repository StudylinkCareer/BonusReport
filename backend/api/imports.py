"""
backend/api/imports.py — CRM import endpoints.

POST /api/imports
    Upload a CRM closed-file xlsx, run it through the importer pipeline
    (backend.importer.orchestrator.run_file), return summary stats.

    The engine is NOT run automatically. The user reviews cases via
    GET /api/imports/{year}/{month} (next endpoint, not in this file)
    and explicitly clicks "Submit to engine" — see the locked design
    decision in chat 2026-05-08.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.importer.orchestrator import run_file
from backend.importer.reader import parse_filename


log = logging.getLogger(__name__)

# Prefix is set on the router itself so main.py just does
# app.include_router(imports_router) — no additional prefix needed.
router = APIRouter(prefix="/api/imports", tags=["imports"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Closed-file CRM reports are always xlsx. Reject anything else early
# rather than letting openpyxl raise a confusing error mid-import.
ACCEPTED_EXTENSIONS = {".xlsx", ".xlsm"}


# ---------------------------------------------------------------------------
# POST /api/imports
# ---------------------------------------------------------------------------

@router.post("")
def upload_crm_report(
    file: UploadFile = File(..., description="CRM closed-file report (.xlsx)"),
    year: Optional[int] = Query(
        None, ge=2020, le=2099,
        description="Override run year (else parsed from filename).",
    ),
    month: Optional[int] = Query(
        None, ge=1, le=12,
        description="Override run month (else parsed from filename).",
    ),
) -> dict:
    """Accept an xlsx upload, run the importer, return summary stats.

    Flow:
      1. Validate extension.
      2. Resolve (run_year, run_month) — from query params if supplied,
         otherwise by parsing the original filename.
      3. Save the uploaded bytes to a temp dir, preserving the original
         filename so the orchestrator's logs show something readable.
      4. Call run_file() with explicit year/month — the temp filename
         won't parse, so we never let the orchestrator try.
      5. Return WriteResult counts + the resolved year/month so the
         frontend knows where to navigate for review.

    The temp dir auto-cleans on context exit.

    Errors:
      400 — wrong extension, or filename unparseable AND no query overrides.
      500 — anything that escapes run_file() (it normally swallows DB
            errors into result.errors, so this is rare).
    """
    # ----- 1. Validate extension --------------------------------------------
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename supplied.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ACCEPTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type {suffix!r}. "
                f"Accepted: {sorted(ACCEPTED_EXTENSIONS)}."
            ),
        )

    # ----- 2. Resolve year/month --------------------------------------------
    if year is not None and month is not None:
        resolved_year, resolved_month = year, month
    else:
        try:
            info = parse_filename(Path(file.filename))
        except Exception as exc:
            # parse_filename raises FilenameParseError; we catch broadly
            # to translate any unexpected failure into a clean 400.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not parse year/month from filename "
                    f"{file.filename!r}: {exc!s}. "
                    f"Pass ?year=YYYY&month=MM to override."
                ),
            )
        resolved_year = year if year is not None else info.year
        resolved_month = month if month is not None else info.month

    log.info(
        "Import upload received: filename=%s resolved_run=%d-%02d size=%s",
        file.filename, resolved_year, resolved_month,
        getattr(file, "size", "unknown"),
    )

    # ----- 3. Save to temp dir, preserving original filename ----------------
    # Using TemporaryDirectory (not NamedTemporaryFile) so the file's
    # name on disk matches the upload — useful for the orchestrator's
    # log lines. The dir auto-cleans on context exit.
    with tempfile.TemporaryDirectory(prefix="bonusreport_import_") as tmpdir:
        tmp_path = Path(tmpdir) / file.filename
        try:
            with tmp_path.open("wb") as f:
                shutil.copyfileobj(file.file, f)
        except OSError as exc:
            log.exception("Failed to write upload to temp path %s", tmp_path)
            raise HTTPException(
                status_code=500,
                detail=f"Could not save uploaded file: {exc!s}",
            )

        # ----- 4. Run the importer ------------------------------------------
        # run_file() owns the DB connection and the transaction. It
        # commits on success, rolls back and swallows on unhandled
        # exceptions, returning a WriteResult either way (per its
        # docstring's Q4 = Option A policy).
        result = run_file(
            tmp_path,
            run_year=resolved_year,
            run_month=resolved_month,
        )

    # ----- 5. Build response ------------------------------------------------
    # Frontend navigates to /imports/{year}/{month} for the review screen.
    return {
        "filename": file.filename,
        "run_year": resolved_year,
        "run_month": resolved_month,
        "summary": {
            "inserted": result.inserted,
            "updated": result.updated,
            "rows_skipped": result.rows_skipped,
            "notes_attached": result.notes_attached,
            "notes_orphan": result.notes_orphan,
            "error_count": len(result.errors),
        },
        "errors": result.errors,
    }