"""
StudyLink BonusReport API.

Endpoints live under /api/* to match the Netlify proxy redirect.
"""
# --- Make 'backend' importable as a package alias for the current dir ----
# Railway sets the working directory to backend/ (via Root Directory),
# which flattens backend/'s contents to /app/. So the literal folder
# 'backend' doesn't exist on the filesystem there. The engine and
# importer modules use `from backend.X import Y` style imports
# throughout. Rather than rewrite every file, we register a synthetic
# 'backend' package that points at the current directory.
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_backend_pkg = types.ModuleType("backend")
_backend_pkg.__path__ = [str(_HERE)]
sys.modules["backend"] = _backend_pkg
# ------------------------------------------------------------------------

import tempfile
from datetime import date
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.data.connection import get_connection
from backend.importer.orchestrator import run_file


app = FastAPI(title="BonusReport API")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    """Liveness check + DB connectivity."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unreachable: {e}")
    return {"status": "ok", "db": "ok"}


# ---------------------------------------------------------------------------
# Staff list
# ---------------------------------------------------------------------------

@app.get("/api/staff")
def list_staff() -> list[dict]:
    """All staff with primary role + office."""
    sql = """
        SELECT
            s.id,
            s.canonical_name        AS name,
            s.email,
            s.employment_status,
            s.departure_date,
            r.code                  AS role_code,
            r.name                  AS role_name,
            o.code                  AS office_code,
            o.name                  AS office_name
        FROM ref_staff s
        LEFT JOIN dim_role   r ON s.primary_role_id = r.id
        LEFT JOIN dim_office o ON s.home_office_id  = o.id
        ORDER BY s.canonical_name
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Cases for review (one staff, one period)
# ---------------------------------------------------------------------------

@app.get("/api/cases")
def list_cases(
    staff_id: int = Query(..., description="ref_staff.id"),
    year: int = Query(..., ge=2020, le=2030),
    month: int = Query(..., ge=1, le=12),
) -> list[dict]:
    """
    Cases for one staff member in one (year, month).

    Includes any case where the staff appears in ANY role
    (counsellor, case officer, or VP).
    """
    sql = """
        SELECT
            c.id,
            c.contract_id,
            c.student_id,
            c.student_name,
            c.application_status,
            c.course_status,
            c.import_status,
            c.contract_signed_date,
            c.course_start_date,
            c.visa_received_date,
            c.client_type_code,
            c.handover_flag,
            c.case_transition,
            c.deferral_code,
            c.run_year,
            c.run_month,
            c.created_at,
            c.updated_at,
            inst.canonical_name       AS institution_name,
            cn.name                   AS country_name,
            counsellor.canonical_name AS counsellor_name,
            co.canonical_name         AS case_officer_name,
            vp.canonical_name         AS vp_name
        FROM tx_case c
        LEFT JOIN ref_institution inst       ON c.institution_id        = inst.id
        LEFT JOIN dim_country     cn         ON c.country_id            = cn.id
        LEFT JOIN ref_staff       counsellor ON c.counsellor_staff_id   = counsellor.id
        LEFT JOIN ref_staff       co         ON c.case_officer_staff_id = co.id
        LEFT JOIN ref_staff       vp         ON c.vp_staff_id           = vp.id
        WHERE c.run_year  = %s
          AND c.run_month = %s
          AND (
                c.counsellor_staff_id   = %s
             OR c.case_officer_staff_id = %s
             OR c.vp_staff_id           = %s
          )
        ORDER BY c.contract_id
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (year, month, staff_id, staff_id, staff_id))
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# CRM Excel upload → importer pipeline
# ---------------------------------------------------------------------------

@app.post("/api/imports")
async def upload_import(
    file: UploadFile = File(...),
    year: int = Form(...),
    month: int = Form(...),
) -> dict:
    """
    Upload a CRM closed-file Excel report.

    Runs the file through the importer pipeline (reader → transformer →
    writer) and returns a summary of what was inserted, updated, and
    skipped, plus any errors collected per-row.
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .xls")
    if year < 2020 or year > 2030:
        raise HTTPException(status_code=400, detail="Year out of range")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month out of range")

    # Save the upload to a temp path, preserving the original filename
    # so the importer can read it for staff/period inference if needed.
    tmp_dir = Path(tempfile.mkdtemp(prefix="bonusreport_upload_"))
    tmp_path = tmp_dir / file.filename
    content = await file.read()
    tmp_path.write_bytes(content)

    try:
        result = run_file(tmp_path, run_year=year, run_month=month)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e!r}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass

    return {
        "filename": file.filename,
        "year": year,
        "month": month,
        "inserted": result.inserted,
        "updated": result.updated,
        "rows_skipped": result.rows_skipped,
        "notes_attached": result.notes_attached,
        "notes_orphan": result.notes_orphan,
        "errors": result.errors,
    }