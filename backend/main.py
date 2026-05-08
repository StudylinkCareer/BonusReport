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
from typing import Any, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Path as PathParam, Query, UploadFile

from backend.data.connection import get_connection
from backend.importer.orchestrator import run_file


app = FastAPI(title="BonusReport API")
from backend.api.imports import router as imports_router
app.include_router(imports_router)


# ===========================================================================
# Health
# ===========================================================================

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


# ===========================================================================
# Staff list
# ===========================================================================

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


# ===========================================================================
# Cases for review (extended — every reviewable column, all FKs joined)
# ===========================================================================

# Fields the user is allowed to edit via PATCH /api/cases/{id}.
# Mirrors writer._INSERT_COLUMNS (importer-controlled fields), minus the
# upsert conflict key (run_year, run_month) which would break re-imports
# if changed. Adding referring_office_id from Phase 11a even though the
# pasted writer.py predates that change — schema supports it.
EDITABLE_FIELDS = {
    "contract_id", "student_id", "student_name",
    "contract_signed_date", "course_start_date", "visa_received_date",
    "case_office_id", "country_id", "institution_id",
    "institution_text_raw",
    "referring_partner_id", "referring_sub_agent_id", "referring_office_id",
    "referring_agent_text_raw", "referring_source_type",
    "client_type_code", "application_status", "course_status",
    "counsellor_staff_id", "counsellor_role_id",
    "case_officer_staff_id", "case_officer_role_id",
    "import_status",
    "incentive_amount", "notes",
}


@app.get("/api/cases")
def list_cases(
    staff_id: Optional[int] = Query(None, description="ref_staff.id; if omitted, returns all cases for the period"),
    year: int = Query(..., ge=2020, le=2030),
    month: int = Query(..., ge=1, le=12),
) -> list[dict]:
    """
    Cases for one (year, month). If staff_id provided, filtered to cases
    where that staff appears in any role (counsellor, case officer, or VP).

    Returns every reviewable column with human-readable FK values alongside
    the raw IDs (so the frontend can both display and edit).
    """
    where_extra = ""
    params: list[Any] = [year, month]
    if staff_id is not None:
        where_extra = """
          AND (
                c.counsellor_staff_id   = %s
             OR c.case_officer_staff_id = %s
             OR c.vp_staff_id           = %s
          )
        """
        params.extend([staff_id, staff_id, staff_id])

    sql = f"""
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
            c.incentive_amount,
            c.prior_month_rate,
            c.notes,
            c.run_year,
            c.run_month,
            c.created_at,
            c.updated_at,

            -- Institution (resolved + raw text from the CRM)
            c.institution_id,
            inst.canonical_name        AS institution_name,
            c.institution_text_raw,

            -- Country
            c.country_id,
            cn.name                    AS country_name,

            -- Case office (where the case is processed)
            c.case_office_id,
            case_office.code           AS case_office_code,

            -- Referring office (Phase 11a; lead source)
            c.referring_office_id,
            ref_office.code            AS referring_office_code,

            -- Referring partner (Master Agent / Group)
            c.referring_partner_id,
            partner.canonical_name     AS referring_partner_name,

            -- Referring sub-agent
            c.referring_sub_agent_id,
            sub_agent.canonical_name   AS referring_sub_agent_name,

            -- Raw text from CRM (preserve for audit)
            c.referring_agent_text_raw,
            c.referring_source_type,

            -- Service fee (engine-resolved; display only)
            c.service_fee_id,
            fee.label                  AS service_fee_label,

            -- Counsellor
            c.counsellor_staff_id,
            counsellor.canonical_name  AS counsellor_name,
            c.counsellor_role_id,
            counsellor_role.code       AS counsellor_role_code,

            -- Case officer
            c.case_officer_staff_id,
            co.canonical_name          AS case_officer_name,
            c.case_officer_role_id,
            co_role.code               AS case_officer_role_code,

            -- Presales (engine-managed; display only)
            c.presales_staff_id,
            presales.canonical_name    AS presales_name,
            c.presales_share_pct,

            -- VP (engine-managed; display only)
            c.vp_staff_id,
            vp.canonical_name          AS vp_name,

            -- Target owner (engine-managed)
            c.target_owner_staff_id,
            target_owner.canonical_name AS target_owner_name

        FROM tx_case c
        LEFT JOIN ref_institution inst         ON c.institution_id          = inst.id
        LEFT JOIN dim_country     cn           ON c.country_id              = cn.id
        LEFT JOIN dim_office      case_office  ON c.case_office_id          = case_office.id
        LEFT JOIN dim_office      ref_office   ON c.referring_office_id     = ref_office.id
        LEFT JOIN ref_partner     partner      ON c.referring_partner_id    = partner.id
        LEFT JOIN ref_sub_agent   sub_agent    ON c.referring_sub_agent_id  = sub_agent.id
        LEFT JOIN ref_service_fee fee          ON c.service_fee_id          = fee.id
        LEFT JOIN ref_staff       counsellor   ON c.counsellor_staff_id     = counsellor.id
        LEFT JOIN dim_role        counsellor_role ON c.counsellor_role_id   = counsellor_role.id
        LEFT JOIN ref_staff       co           ON c.case_officer_staff_id   = co.id
        LEFT JOIN dim_role        co_role      ON c.case_officer_role_id    = co_role.id
        LEFT JOIN ref_staff       presales     ON c.presales_staff_id       = presales.id
        LEFT JOIN ref_staff       vp           ON c.vp_staff_id             = vp.id
        LEFT JOIN ref_staff       target_owner ON c.target_owner_staff_id   = target_owner.id
        WHERE c.run_year  = %s
          AND c.run_month = %s
          {where_extra}
        ORDER BY c.contract_id
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


# ===========================================================================
# Case edit (PATCH a single case before engine run)
# ===========================================================================

@app.patch("/api/cases/{case_id}")
def update_case(
    case_id: int = PathParam(..., ge=1),
    updates: dict[str, Any] = Body(
        ...,
        description="Partial dict of {field: new_value}. Only importer-controlled fields are accepted.",
        example={"institution_id": 123, "import_status": "OK"},
    ),
) -> dict:
    """
    Update one or more importer-controlled fields on a single tx_case row.

    Validation:
      * Field names must be in EDITABLE_FIELDS (engine-managed fields rejected).
      * Empty body → 400.
      * Type coercion is delegated to psycopg — bad types raise a clean DB error.

    Returns the updated row in the same shape as GET /api/cases.
    """
    if not updates:
        raise HTTPException(status_code=400, detail="Empty update body.")

    rejected = [k for k in updates if k not in EDITABLE_FIELDS]
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Field(s) not editable: {rejected}. "
                f"These are engine-managed and cannot be edited via this endpoint."
            ),
        )

    set_clauses = [f"{k} = %({k})s" for k in updates]
    params = dict(updates)
    params["id"] = case_id

    sql = f"""
        UPDATE tx_case
        SET {', '.join(set_clauses)},
            updated_at = NOW()
        WHERE id = %(id)s
        RETURNING id, run_year, run_month
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(sql, params)
            except Exception as exc:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Update failed: {exc!s}")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")
            conn.commit()

    # Re-fetch the full row via list_cases logic so the response matches
    # the GET shape exactly. Inefficient but consistent.
    return _fetch_one_case(case_id)


def _fetch_one_case(case_id: int) -> dict:
    """Internal: fetch one case using the same JOINs as list_cases."""
    # Same SELECT as list_cases but filtered by id. Keeping inline so any
    # column-list change in list_cases automatically propagates here would
    # be ideal, but for now this is a pragmatic copy of the column list.
    sql = """
        SELECT
            c.id, c.contract_id, c.student_id, c.student_name,
            c.application_status, c.course_status, c.import_status,
            c.contract_signed_date, c.course_start_date, c.visa_received_date,
            c.client_type_code, c.handover_flag, c.case_transition,
            c.deferral_code, c.incentive_amount, c.prior_month_rate,
            c.notes, c.run_year, c.run_month, c.created_at, c.updated_at,
            c.institution_id,         inst.canonical_name      AS institution_name,
            c.institution_text_raw,
            c.country_id,             cn.name                  AS country_name,
            c.case_office_id,         case_office.code         AS case_office_code,
            c.referring_office_id,    ref_office.code          AS referring_office_code,
            c.referring_partner_id,   partner.canonical_name   AS referring_partner_name,
            c.referring_sub_agent_id, sub_agent.canonical_name AS referring_sub_agent_name,
            c.referring_agent_text_raw, c.referring_source_type,
            c.service_fee_id,         fee.label                AS service_fee_label,
            c.counsellor_staff_id,    counsellor.canonical_name AS counsellor_name,
            c.counsellor_role_id,     counsellor_role.code     AS counsellor_role_code,
            c.case_officer_staff_id,  co.canonical_name        AS case_officer_name,
            c.case_officer_role_id,   co_role.code             AS case_officer_role_code,
            c.presales_staff_id,      presales.canonical_name  AS presales_name,
            c.presales_share_pct,
            c.vp_staff_id,            vp.canonical_name        AS vp_name,
            c.target_owner_staff_id,  target_owner.canonical_name AS target_owner_name
        FROM tx_case c
        LEFT JOIN ref_institution inst          ON c.institution_id          = inst.id
        LEFT JOIN dim_country     cn            ON c.country_id              = cn.id
        LEFT JOIN dim_office      case_office   ON c.case_office_id          = case_office.id
        LEFT JOIN dim_office      ref_office    ON c.referring_office_id     = ref_office.id
        LEFT JOIN ref_partner     partner       ON c.referring_partner_id    = partner.id
        LEFT JOIN ref_sub_agent   sub_agent     ON c.referring_sub_agent_id  = sub_agent.id
        LEFT JOIN ref_service_fee fee           ON c.service_fee_id          = fee.id
        LEFT JOIN ref_staff       counsellor    ON c.counsellor_staff_id     = counsellor.id
        LEFT JOIN dim_role        counsellor_role ON c.counsellor_role_id    = counsellor_role.id
        LEFT JOIN ref_staff       co            ON c.case_officer_staff_id   = co.id
        LEFT JOIN dim_role        co_role       ON c.case_officer_role_id    = co_role.id
        LEFT JOIN ref_staff       presales      ON c.presales_staff_id       = presales.id
        LEFT JOIN ref_staff       vp            ON c.vp_staff_id             = vp.id
        LEFT JOIN ref_staff       target_owner  ON c.target_owner_staff_id   = target_owner.id
        WHERE c.id = %s
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (case_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")
            return dict(row)


# ===========================================================================
# Reference lists (dropdown options for the Review screen)
# ===========================================================================

# DB-backed reference lists. Each entry is a SQL query returning at minimum
# {id, name}; some return extra columns (e.g. partner.classification) which
# the frontend can use to group or filter.
#
# Naming: list_name in the URL path → SELECT below. Adding a new dropdown
# is a one-line addition to this dict.
REF_LIST_QUERIES: dict[str, str] = {
    "institutions": """
        SELECT id, canonical_name AS name
        FROM ref_institution
        ORDER BY canonical_name
    """,
    "sub_agents": """
        SELECT id, canonical_name AS name
        FROM ref_sub_agent
        ORDER BY canonical_name
    """,
    "partners": """
        SELECT id, canonical_name AS name
        FROM ref_partner
        ORDER BY canonical_name
    """,
    "offices": """
        SELECT id, code, name
        FROM dim_office
        ORDER BY code
    """,
    "countries": """
        SELECT id, code, name
        FROM dim_country
        ORDER BY name
    """,
    "staff_active": """
        SELECT id, canonical_name AS name
        FROM ref_staff
        WHERE employment_status = 'ACTIVE'
        ORDER BY canonical_name
    """,
    "staff_all": """
        SELECT id, canonical_name AS name, employment_status
        FROM ref_staff
        ORDER BY canonical_name
    """,
    "statuses": """
        SELECT id, canonical_name AS name
        FROM ref_status_split
        ORDER BY canonical_name
    """,
    "roles": """
        SELECT id, code, name
        FROM dim_role
        ORDER BY code
    """,
}

# Static enums for fields that don't have a dedicated reference table.
# If the frontend needs more values, add them here.
REF_LIST_STATIC: dict[str, list[str]] = {
    "source_types": ["DIRECT", "SUB_AGENT", "MASTER_AGENT", "GROUP", "OFFICE"],
    "import_statuses": ["OK", "UNRESOLVED", "FLAGGED", "SCRAP"],
}


@app.get("/api/reference/{list_name}")
def get_reference_list(list_name: str = PathParam(..., min_length=1)) -> dict:
    """
    Return the options for a single dropdown.

    Path parameter list_name dispatches to either a SQL query or a static
    enum. Returns {"name": ..., "items": [...]}; for DB-backed lists each
    item is a dict, for static lists each is a string.
    """
    if list_name in REF_LIST_QUERIES:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(REF_LIST_QUERIES[list_name])
                return {"name": list_name, "items": [dict(r) for r in cur.fetchall()]}

    if list_name in REF_LIST_STATIC:
        return {"name": list_name, "items": REF_LIST_STATIC[list_name]}

    available = sorted(set(REF_LIST_QUERIES) | set(REF_LIST_STATIC))
    raise HTTPException(
        status_code=404,
        detail=f"Unknown reference list {list_name!r}. Available: {available}",
    )


# ===========================================================================
# CRM Excel upload → importer pipeline
# (Note: also exposed via backend.api.imports.router — see top of file.
#  This duplicate endpoint is kept for safety; remove once the router
#  version is verified to be the one serving traffic.)
# ===========================================================================

@app.post("/api/imports")
async def upload_import(
    file: UploadFile = File(...),
    year: int = Form(...),
    month: int = Form(...),
) -> dict:
    """Upload a CRM closed-file Excel report."""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .xls")
    if year < 2020 or year > 2030:
        raise HTTPException(status_code=400, detail="Year out of range")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month out of range")

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
