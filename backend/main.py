"""
StudyLink BonusReport API.

Endpoints live under /api/* to match the Netlify proxy redirect.
"""
# --- Make 'backend' importable as a package alias for the current dir ----
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_backend_pkg = types.ModuleType("backend")
_backend_pkg.__path__ = [str(_HERE)]
sys.modules["backend"] = _backend_pkg
# ------------------------------------------------------------------------

from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Path as PathParam, Query
from psycopg.rows import dict_row

from backend.data.connection import get_connection
from backend.engine_runner.api_runner import run_engine_api


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
# Imports list (audit log)
# ===========================================================================

@app.get("/api/imports")
def list_imports(
    year: Optional[int] = Query(None, ge=2020, le=2099),
    month: Optional[int] = Query(None, ge=1, le=12),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    """
    All CRM uploads from tx_import_run, most recent first.
    Optional year/month filter. limit caps the page size.

    Each row also gets a `staff_id` field computed by parsing the filename
    and matching against ref_staff. Returns null when the parse or lookup
    fails. Used by the imports list page to one-click drilldown to the
    review page for that staff/period.
    """
    where = "WHERE 1=1"
    params: list[Any] = []
    if year is not None:
        where += " AND run_year = %s"
        params.append(year)
    if month is not None:
        where += " AND run_month = %s"
        params.append(month)

    sql = f"""
        SELECT
            id, original_filename, file_path,
            run_year, run_month, uploaded_at,
            inserted_count, updated_count, rows_skipped_count,
            notes_attached_count, notes_orphan_count, error_count,
            errors_json, current_state, created_at, updated_at
        FROM tx_import_run
        {where}
        ORDER BY uploaded_at DESC
        LIMIT %s
    """
    params.append(limit)

    # Pre-load all staff once so we don't hit the DB N times for N rows.
    # Build a dict from canonical_name (lower-cased, NFC-normalised) → id.
    import unicodedata as _ud
    name_to_id: dict[str, int] = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, canonical_name FROM ref_staff")
            for row in cur.fetchall():
                key = _ud.normalize("NFC", row["canonical_name"]).lower()
                name_to_id[key] = row["id"]

            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

    # Per-row: parse staff name from filename, look up in dict
    import re as _re
    pat = _re.compile(
        r"^(.+?)[\u0027\u2019]s\s+report\s+of\s+closed\s+file",
        _re.IGNORECASE,
    )
    for row in rows:
        staff_id = None
        fname = row.get("original_filename") or ""
        norm = _ud.normalize("NFC", fname)
        m = pat.match(norm)
        if m:
            key = m.group(1).strip().lower()
            staff_id = name_to_id.get(key)
        row["staff_id"] = staff_id

    return rows


# ===========================================================================
# Cases for review (extended — every reviewable column, all FKs joined)
# ===========================================================================

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
    year: Optional[int] = Query(None, ge=2020, le=2030, description="Required unless workflow_state is given"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Required unless workflow_state is given"),
    workflow_state: Optional[str] = Query(None, description="One of uploaded/in_review/submitted/closed. Alternative filter mode (Phase 15) — when set, year/month are not required."),
) -> list[dict]:
    """Cases either for one (year, month) period or for one workflow_state pillar.

    Filter modes:
        - Period mode (legacy): year + month required. Optionally narrow to staff_id.
        - Workflow-state mode (Phase 15): workflow_state required. Returns all
          cases at that state across all periods/staff.

    Exactly one mode must be active.
    """
    # Determine which filter mode is in use
    has_period = year is not None and month is not None
    has_state = workflow_state is not None

    if has_state and has_period:
        raise HTTPException(
            status_code=400,
            detail="Provide either (year + month) OR workflow_state, not both.",
        )
    if not has_state and not has_period:
        raise HTTPException(
            status_code=400,
            detail="Provide either (year + month) OR workflow_state.",
        )

    where_clauses: list[str] = []
    params: list[Any] = []

    if has_period:
        where_clauses.append("c.run_year = %s AND c.run_month = %s")
        params.extend([year, month])

    if has_state:
        valid = {"uploaded", "in_review", "submitted", "closed"}
        if workflow_state not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"workflow_state must be one of {sorted(valid)}, got {workflow_state!r}",
            )
        where_clauses.append("c.workflow_state = %s")
        params.append(workflow_state)

    if staff_id is not None:
        where_clauses.append("""(
                c.counsellor_staff_id   = %s
             OR c.case_officer_staff_id = %s
             OR c.vp_staff_id           = %s
          )""")
        params.extend([staff_id, staff_id, staff_id])

    where_sql = " AND ".join(where_clauses)

    sql = f"""
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
            c.referring_partner_id,
            partner.name              AS referring_partner_name,
            partner.classification    AS referring_partner_classification,
            c.referring_sub_agent_id, sub_agent.canonical_name AS referring_sub_agent_name,
            c.referring_agent_text_raw, c.referring_source_type,
            c.service_fee_id,         fee.service_code         AS service_fee_label,
            c.counsellor_staff_id,    counsellor.canonical_name AS counsellor_name,
            c.counsellor_role_id,     counsellor_role.code     AS counsellor_role_code,
            c.case_officer_staff_id,  co.canonical_name        AS case_officer_name,
            c.case_officer_role_id,   co_role.code             AS case_officer_role_code,
            c.presales_staff_id,      presales.canonical_name  AS presales_name,
            c.presales_share_pct,
            c.vp_staff_id,            vp.canonical_name        AS vp_name,
            c.target_owner_staff_id,  target_owner.canonical_name AS target_owner_name,
            c.workflow_state,
            c.pre_sales_staff_id,     ps.canonical_name        AS pre_sales_name

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
        LEFT JOIN ref_staff       ps           ON c.pre_sales_staff_id      = ps.id
        WHERE {where_sql}
        ORDER BY c.contract_id
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


# ===========================================================================
# PATCH /api/cases/{id} — edit a single case before engine run
# ===========================================================================

@app.patch("/api/cases/{case_id}")
def update_case(
    case_id: int = PathParam(..., ge=1),
    updates: dict[str, Any] = Body(
        ...,
        description="Partial dict of {field: new_value}. Only importer-controlled fields accepted.",
    ),
) -> dict:
    """Update one or more importer-controlled fields on one tx_case row."""
    if not updates:
        raise HTTPException(status_code=400, detail="Empty update body.")

    rejected = [k for k in updates if k not in EDITABLE_FIELDS]
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Field(s) not editable: {rejected}. These are engine-managed.",
        )

    set_clauses = [f"{k} = %({k})s" for k in updates]
    params = dict(updates)
    params["id"] = case_id

    sql = f"""
        UPDATE tx_case
        SET {', '.join(set_clauses)},
            updated_at = NOW()
        WHERE id = %(id)s
        RETURNING id
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

    return _fetch_one_case(case_id)


def _fetch_one_case(case_id: int) -> dict:
    """Internal: fetch one case using the same JOINs as list_cases."""
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
            c.referring_partner_id,
            partner.name              AS referring_partner_name,
            partner.classification    AS referring_partner_classification,
            c.referring_sub_agent_id, sub_agent.canonical_name AS referring_sub_agent_name,
            c.referring_agent_text_raw, c.referring_source_type,
            c.service_fee_id,         fee.service_code         AS service_fee_label,
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

REF_LIST_QUERIES: dict[str, str] = {
    "institutions": "SELECT id, canonical_name AS name FROM ref_institution ORDER BY canonical_name",
    "sub_agents":   "SELECT id, canonical_name AS name FROM ref_sub_agent ORDER BY canonical_name",
    "partners":     "SELECT id, name, classification FROM ref_partner ORDER BY name",
    "offices":      "SELECT id, code, name FROM dim_office ORDER BY code",
    "countries":    "SELECT id, code, name FROM dim_country ORDER BY name",
    "staff_active": "SELECT id, canonical_name AS name, primary_role_id FROM ref_staff WHERE employment_status = 'ACTIVE' ORDER BY canonical_name",
    "staff_all":    "SELECT id, canonical_name AS name, employment_status, primary_role_id FROM ref_staff ORDER BY canonical_name",
    "statuses":     "SELECT id, status AS name FROM ref_status_split ORDER BY status",
    "roles":        "SELECT id, code, name FROM dim_role ORDER BY code",
}

REF_LIST_STATIC: dict[str, list[str]] = {
    "source_types": ["DIRECT", "SUB_AGENT", "MASTER_AGENT", "GROUP", "OFFICE"],
    "import_statuses": ["OK", "UNRESOLVED", "FLAGGED", "SCRAP"],
}


@app.get("/api/reference/{list_name}")
def get_reference_list(list_name: str = PathParam(..., min_length=1)) -> dict:
    """Return options for a single dropdown."""
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
# Engine run — POST /api/engine/run
# ===========================================================================

@app.post("/api/engine/run")
def run_engine_endpoint(body: dict = Body(default_factory=dict)) -> dict:
    """
    Run the bonus engine for a single (year, month) period.

    Request body (JSON):
        {
            "year": 2024,
            "month": 11,
            "persist": true,         // optional, default true
            "contract_id": "...",    // optional, debug a single case
            "limit": 50              // optional, cap N cases
        }

    Response: result dict from run_engine_api with payment_count,
    gross_total, net_total, skipped[], errored[], etc.

    Errors:
        400 — bad year/month/limit/contract_id
        500 — engine raised mid-run (DB rolled back)
    """
    year = body.get("year")
    month = body.get("month")
    persist = bool(body.get("persist", True))
    limit = body.get("limit")
    contract_id = body.get("contract_id")

    if not isinstance(year, int) or not isinstance(month, int):
        raise HTTPException(400, "year and month must be integers")
    if not (2020 <= year <= 2099):
        raise HTTPException(400, "year out of range (2020–2099)")
    if not (1 <= month <= 12):
        raise HTTPException(400, "month must be 1–12")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise HTTPException(400, "limit must be a positive integer")
    if contract_id is not None and not isinstance(contract_id, str):
        raise HTTPException(400, "contract_id must be a string")

    try:
        return run_engine_api(
            year=year,
            month=month,
            persist=persist,
            limit=limit,
            contract_id=contract_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Engine run failed: {type(exc).__name__}: {exc}",
        )


# ===========================================================================
# Bonus payments — GET /api/bonus
# ===========================================================================

@app.get("/api/bonus")
def list_bonus_payments(
    year: int = Query(..., ge=2020, le=2099, description="Run year"),
    month: int = Query(..., ge=1, le=12, description="Run month 1–12"),
    staff_id: Optional[int] = Query(None, description="Optional: filter to one staff"),
) -> list[dict]:
    """
    All tx_bonus_payment rows for (year, month), with case/staff/role/
    office/institution context joined for display.
    """
    sql = """
        SELECT
            bp.id,
            bp.case_id,
            bp.slot,
            bp.staff_id,
            bp.role_id,
            bp.office_id,
            bp.tier,
            bp.target,
            bp.actual_enrolled,
            bp.base_rate,
            bp.split_pct,
            bp.tier_bonus,
            bp.package_bonus,
            bp.addon_bonus,
            bp.priority_bonus,
            bp.presales_share_taken,
            bp.flat_local_enrolment_bonus,
            bp.advance_offset,
            bp.gross_bonus,
            bp.net_payable,
            bp.priority_withheld_amount,
            bp.priority_unlocked_amount,
            bp.priority_schedule_type,
            bp.calc_notes,
            bp.run_year,
            bp.run_month,
            bp.calculated_at,
            c.contract_id,
            c.student_name,
            c.application_status,
            c.course_status,
            inst.canonical_name           AS institution_name,
            staff.canonical_name          AS staff_name,
            r.code                        AS role_code,
            r.name                        AS role_name,
            office.code                   AS office_code,
            office.name                   AS office_name,
            country.name                  AS country_name
          FROM tx_bonus_payment bp
          JOIN tx_case             c       ON bp.case_id      = c.id
          LEFT JOIN ref_institution inst   ON c.institution_id = inst.id
          LEFT JOIN ref_staff       staff  ON bp.staff_id     = staff.id
          LEFT JOIN dim_role        r      ON bp.role_id      = r.id
          LEFT JOIN dim_office      office ON bp.office_id    = office.id
          LEFT JOIN dim_country     country ON c.country_id   = country.id
         WHERE bp.run_year = %s AND bp.run_month = %s
    """
    params: list[Any] = [year, month]
    if staff_id is not None:
        sql += " AND bp.staff_id = %s"
        params.append(staff_id)
    sql += " ORDER BY staff.canonical_name NULLS LAST, c.contract_id, bp.slot"

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


# ===========================================================================
# Pillar counts — drives the 4-pillar home page tiles (Phase 15)
# ===========================================================================

@app.get("/api/pillars/counts")
def pillar_counts() -> dict[str, int]:
    """Per-workflow_state case counts for the 4-pillar home page.

    Response:
        { "uploaded": N, "in_review": N, "submitted": N, "closed": N, "total": N }

    Missing states return as 0 so the frontend can read every key.
    """
    sql = """
        SELECT workflow_state, COUNT(*) AS n
          FROM tx_case
         GROUP BY workflow_state
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB error: {e}")

    counts = {"uploaded": 0, "in_review": 0, "submitted": 0, "closed": 0}
    for row in rows:
        # Other endpoints in this file (list_imports, list_cases) use dict()
        # on each row, so the cursor returns dict-like rows already.
        if isinstance(row, dict):
            state, n = row["workflow_state"], row["n"]
        else:
            state, n = row[0], row[1]
        if state in counts:
            counts[state] = int(n)
    counts["total"] = sum(counts.values())
    return counts


# ===========================================================================
# Pillar list view — cases at one workflow_state (Phase 15)
# ===========================================================================

VALID_WORKFLOW_STATES = {"uploaded", "in_review", "submitted", "closed"}


@app.get("/api/pillars/{state}/cases")
def list_cases_by_pillar(state: str = PathParam(..., min_length=1)) -> dict:
    """List all cases at a given workflow_state. Used by the pillar drill-down views.

    Returns:
        {
            "state": "uploaded",
            "count": 65,
            "cases": [
                { id, contract_id, student_name, application_status,
                  import_status, institution_name, country_name,
                  counsellor_name, case_officer_name, pre_sales_name,
                  run_year, run_month, updated_at },
                ...
            ]
        }

    The cases list reads from the importer's columns (pre_sales_staff_id),
    not the engine's (presales_staff_id) — so it works for cases at any
    stage including 'uploaded', before the engine has run.
    """
    if state not in VALID_WORKFLOW_STATES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown workflow_state {state!r}. Valid: {sorted(VALID_WORKFLOW_STATES)}",
        )

    sql = """
        SELECT
            c.id,
            c.contract_id,
            c.student_name,
            c.application_status,
            c.import_status,
            c.workflow_state,
            c.run_year,
            c.run_month,
            c.updated_at,
            inst.canonical_name      AS institution_name,
            cn.name                  AS country_name,
            counsellor.canonical_name AS counsellor_name,
            co.canonical_name         AS case_officer_name,
            ps.canonical_name         AS pre_sales_name
          FROM tx_case c
          LEFT JOIN ref_institution inst       ON c.institution_id        = inst.id
          LEFT JOIN dim_country     cn         ON c.country_id            = cn.id
          LEFT JOIN ref_staff       counsellor ON c.counsellor_staff_id   = counsellor.id
          LEFT JOIN ref_staff       co         ON c.case_officer_staff_id = co.id
          LEFT JOIN ref_staff       ps         ON c.pre_sales_staff_id    = ps.id
         WHERE c.workflow_state = %s
         ORDER BY c.updated_at DESC, c.id DESC
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (state,))
            cases = [dict(row) for row in cur.fetchall()]

    return {"state": state, "count": len(cases), "cases": cases}


# Note: The duplicate inline @app.post("/api/imports") that previously lived
# at the bottom of this file has been removed. The router-based version in
# backend.api.imports now solely handles uploads, with multi-file support
# and persistent storage to the Railway volume.
