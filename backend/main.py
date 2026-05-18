"""
SAVE TO: backend/main.py
(Full path on your machine: C:\\Users\\rhod_\\Documents\\BonusReport\\Application\\backend\\main.py)

StudyLink BonusReport API.

Endpoints live under /api/* to match the Netlify proxy redirect.
"""
# --- Make 'backend' importable as a package alias for the current dir ----
import sys
import types
import json
import traceback
from calendar import monthrange
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_backend_pkg = types.ModuleType("backend")
_backend_pkg.__path__ = [str(_HERE)]
sys.modules["backend"] = _backend_pkg
# ------------------------------------------------------------------------

from typing import Any, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Path as PathParam, Query, Response
from psycopg.rows import dict_row

from backend.data.connection import get_connection
from backend.engine_runner.api_runner import (
    AmendmentWindowExpiredError,
    NoLivePaymentsToReverseError,
    reverse_only_api,
    run_engine_api,
    run_engine_cascade_api,
)
from backend.engine_runner.simulator import (
    CaseNotFoundError,
    CaseNotInReviewError,
    CasePeriodMissingError,
    estimate_bonus_for_case,
)
from backend.approvals import (
    ApprovalAlreadyRecordedError,
    CaseNotFoundError as ApprovalCaseNotFoundError,
    EmptyOverrideReasonError,
    SlotNotFoundError,
    UserNotOnCaseError,
    approve_my_slots,
    check_approvals_for_transition,
    get_case_approvals,
    override_approval,
)
from backend.overrides import (
    CaseNotFoundError as OverrideCaseNotFoundError,
    EmptyReasonError,
    InvalidAmountError,
    StaffNotOnCaseError,
    WorkflowStateError,
    list_case_overrides,
    replace_case_overrides,
)

from backend.auth import (
    COOKIE_NAME,
    LoginRequest,
    LoginResponse,
    UserInfo,
    create_access_token,
    get_current_user,
    require_role,
    verify_password,
)


app = FastAPI(title="BonusReport API")
from backend.api.imports import router as imports_router
app.include_router(
    imports_router,
    dependencies=[Depends(require_role(["DQO", "ADMIN", "DIRECTOR", "FO"]))],
)


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
# Authentication (Phase 14, Block 2)
# ===========================================================================
# Three endpoints for the login lifecycle:
#   POST /api/auth/login   — verify credentials, issue JWT cookie
#   POST /api/auth/logout  — clear the cookie
#   GET  /api/auth/me      — return current user info (so the frontend
#                            can check 'am I logged in?' on page load)
#
# The JWT is delivered as an HttpOnly cookie, not in the response body —
# this keeps it out of JavaScript's reach (defence against XSS).
#
# Future phase (2.3) will apply require_role() to existing endpoints to
# actually enforce authorisation. For now these auth routes coexist with
# the existing unauthenticated endpoints.
# ===========================================================================

@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, response: Response) -> LoginResponse:
    """Verify email + password, issue a JWT cookie, return user info."""
    sql = """
        SELECT
            u.id,
            u.email,
            u.display_name,
            u.password_hash,
            u.staff_id,
            u.employment_status,
            rs.canonical_name AS linked_staff_name,
            COALESCE(
                ARRAY_AGG(r.code ORDER BY r.code)
                    FILTER (WHERE r.code IS NOT NULL),
                ARRAY[]::text[]
            ) AS roles
        FROM app_user u
        LEFT JOIN ref_staff rs      ON rs.id = u.staff_id
        LEFT JOIN app_user_role aur ON aur.user_id = u.id
        LEFT JOIN dim_app_role r    ON r.id = aur.role_id
        WHERE LOWER(u.email) = LOWER(%s)
        GROUP BY u.id, rs.canonical_name
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (req.email,))
            row = cur.fetchone()

    # Generic failure for both "no such user" and "wrong password" —
    # prevents attackers from probing which emails exist.
    if not row or not row["password_hash"]:
        raise HTTPException(401, detail="invalid email or password")
    if not verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, detail="invalid email or password")
    if row["employment_status"] != "ACTIVE":
        raise HTTPException(401, detail="account is inactive")

    token = create_access_token(
        user_id=row["id"],
        email=row["email"],
        roles=list(row["roles"]),
        staff_id=row["staff_id"],
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=8 * 60 * 60,   # 8 hours, in seconds
        httponly=True,          # JavaScript can't read it (XSS defence)
        secure=True,            # cookie only sent over HTTPS
        samesite="lax",         # blocks most CSRF, allows same-site navigation
        path="/",
    )

    return LoginResponse(
        user=UserInfo(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            roles=list(row["roles"]),
            staff_id=row["staff_id"],
            linked_staff_name=row["linked_staff_name"],
        )
    )


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    """Clear the auth cookie. Always succeeds — caller need not be logged in."""
    response.delete_cookie(key=COOKIE_NAME, path="/", samesite="lax")
    return {"success": True}


@app.get("/api/auth/me", response_model=UserInfo)
def me(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """Return the current user's info. The frontend calls this on page
    load to determine whether anyone is logged in (and if so, who).
    Returns 401 if not authenticated."""
    return user



# ===========================================================================
# Staff list
# ===========================================================================

@app.get("/api/staff", dependencies=[Depends(get_current_user)])
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

@app.get("/api/imports", dependencies=[Depends(require_role(["DQO", "ADMIN", "DIRECTOR", "FO"]))])
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

# ===========================================================================
# Shared filter helper for Case Workload + Review Dashboard
# ===========================================================================
# Both GET /api/cases and GET /api/pillars/counts accept the same filter set
# so that pillar counts on the home page match what the user sees when they
# drill into a pillar. This helper builds the WHERE-clause fragments and
# the matching parameter list. Caller composes them with its own clauses.
# ---------------------------------------------------------------------------

def _parse_month(month: Optional[str]) -> Optional[tuple[date, date]]:
    """Convert 'YYYY-MM' to (first-of-month, last-of-month). Returns None
    on bad input rather than raising — bad input just gets ignored.
    """
    if not month:
        return None
    try:
        y_str, m_str = month.split("-")
        y, m = int(y_str), int(m_str)
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            return None
        return date(y, m, 1), date(y, m, monthrange(y, m)[1])
    except (ValueError, AttributeError):
        return None


def _build_case_filters(
    staff_id: Optional[int] = None,
    signed_from: Optional[str] = None,
    signed_to: Optional[str] = None,
    course_from: Optional[str] = None,
    course_to: Optional[str] = None,
    visa_from: Optional[str] = None,
    visa_to: Optional[str] = None,
    bonus_month: Optional[str] = None,
    q_student: Optional[str] = None,
    q_contract: Optional[str] = None,
    app_status: Optional[str] = None,
    client_type: Optional[str] = None,
    institution_id: Optional[int] = None,
    office_id: Optional[int] = None,
) -> tuple[list[str], list[Any]]:
    """Build SQL WHERE-clause fragments + matching parameter values for
    filtering tx_case rows. Every filter is optional.

    Returns:
        (where_clauses, params) — caller joins clauses with ' AND ' and
        passes params to cursor.execute.

    Notes:
      - staff_id matches any of the four staff roles on a case
        (counsellor, case officer, pre-sales, VP).
      - Wildcards on q_student / q_contract use ILIKE %...%.
      - 'bonus_month' is a convenience filter: 'YYYY-MM' expands to a date
        range on contract_signed_date (typical bonus period). Named
        bonus_month, not month, to avoid clash with the legacy 'month'
        period param on /api/cases.
    """
    where: list[str] = []
    params: list[Any] = []

    if staff_id is not None:
        where.append(
            "("
            "c.counsellor_staff_id   = %s OR "
            "c.case_officer_staff_id = %s OR "
            "c.pre_sales_staff_id    = %s OR "
            "c.vp_staff_id           = %s"
            ")"
        )
        params.extend([staff_id, staff_id, staff_id, staff_id])

    # Date ranges (string ISO dates, e.g. '2024-01-15'). Postgres will cast.
    for col, lo, hi in [
        ("contract_signed_date", signed_from, signed_to),
        ("course_start_date",    course_from, course_to),
        ("visa_received_date",   visa_from,   visa_to),
    ]:
        if lo:
            where.append(f"c.{col} >= %s")
            params.append(lo)
        if hi:
            where.append(f"c.{col} <= %s")
            params.append(hi)

    # Bonus-month convenience filter — expands to a date range on contract_signed_date
    month_range = _parse_month(bonus_month)
    if month_range:
        where.append("c.contract_signed_date >= %s AND c.contract_signed_date <= %s")
        params.extend(month_range)

    # Wildcards
    if q_student:
        where.append("(c.student_name ILIKE %s OR c.student_id ILIKE %s)")
        token = f"%{q_student.strip()}%"
        params.extend([token, token])
    if q_contract:
        where.append("c.contract_id ILIKE %s")
        params.append(f"%{q_contract.strip()}%")

    # Dropdowns
    if app_status:
        where.append("c.application_status = %s")
        params.append(app_status)
    if client_type:
        where.append("c.client_type_code = %s")
        params.append(client_type)
    if institution_id is not None:
        where.append("c.institution_id = %s")
        params.append(institution_id)
    if office_id is not None:
        where.append("c.case_office_id = %s")
        params.append(office_id)

    return where, params


# Common FastAPI Query() declarations for the filter parameters. Reused
# by /api/cases and /api/pillars/counts so the two endpoints stay in sync.
_FILTER_PARAMS_DOC = "Optional filter (see Case Workload filter bar)"


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
    # Phase 5: Package + service review flag (services managed via own endpoint)
    "package_fee_id", "service_review_pending",
    # v6.2 spec: new dropdown-controlled tx_case columns
    "system_type", "institution_type", "targets_name",
    # v6.2 spec: deferral code (column exists, now has reference list)
    "deferral_code",
    # v6.2 spec: pre-sales agent (column exists, locked to curated list)
    "pre_sales_staff_id",
}


@app.get("/api/cases", dependencies=[Depends(get_current_user)])
def list_cases(
    # --- mode selectors (one of these mode sets must be active) ----------
    staff_id: Optional[int] = Query(None, description="ref_staff.id; matches any role"),
    year: Optional[int] = Query(None, ge=2020, le=2030, description="Required unless workflow_state is given"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Required unless workflow_state is given"),
    workflow_state: Optional[str] = Query(None, description="One of uploaded/in_review/submitted/closed. When set, year/month are not required."),
    # --- Case Workload filter bar (Phase 4) ------------------------------
    signed_from: Optional[str] = Query(None, description="contract_signed_date >= (YYYY-MM-DD)"),
    signed_to:   Optional[str] = Query(None, description="contract_signed_date <= (YYYY-MM-DD)"),
    course_from: Optional[str] = Query(None, description="course_start_date >= (YYYY-MM-DD)"),
    course_to:   Optional[str] = Query(None, description="course_start_date <= (YYYY-MM-DD)"),
    visa_from:   Optional[str] = Query(None, description="visa_received_date >= (YYYY-MM-DD)"),
    visa_to:     Optional[str] = Query(None, description="visa_received_date <= (YYYY-MM-DD)"),
    bonus_month: Optional[str] = Query(None, description="Convenience: YYYY-MM expanded to a contract_signed_date month range"),
    q_student:   Optional[str] = Query(None, description="Wildcard ILIKE on student_name OR student_id"),
    q_contract:  Optional[str] = Query(None, description="Wildcard ILIKE on contract_id"),
    app_status:  Optional[str] = Query(None, description="Exact match on application_status"),
    client_type: Optional[str] = Query(None, description="Exact match on client_type_code"),
    institution_id: Optional[int] = Query(None, description="Exact match on institution_id"),
    office_id:      Optional[int] = Query(None, description="Exact match on case_office_id"),
) -> list[dict]:
    """Cases either for one (year, month) period or for one workflow_state
    pillar, optionally narrowed by the Case Workload filter bar.

    Mode rules:
      - Period mode (legacy): year + month required.
      - Workflow-state mode (Phase 15): workflow_state required.
      - Exactly one mode must be active.

    All other filters (signed/course/visa date ranges, wildcards, dropdowns,
    bonus_month) are optional and apply on top of the active mode.
    """
    # Determine which mode is in use
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

    # Apply Case Workload filter bar (staff_id + all the other filters)
    extra_where, extra_params = _build_case_filters(
        staff_id=staff_id,
        signed_from=signed_from, signed_to=signed_to,
        course_from=course_from, course_to=course_to,
        visa_from=visa_from,     visa_to=visa_to,
        bonus_month=bonus_month,
        q_student=q_student, q_contract=q_contract,
        app_status=app_status, client_type=client_type,
        institution_id=institution_id, office_id=office_id,
    )
    where_clauses.extend(extra_where)
    params.extend(extra_params)

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
            c.calculated_at,
            c.pre_sales_staff_id,     ps.canonical_name        AS pre_sales_name,

            -- Phase 5 + v6.2: new tx_case columns
            c.package_fee_id,
            COALESCE(NULLIF(TRIM(SPLIT_PART(pkg.description, ' — ', 1)), ''), pkg.service_code) AS package_label,
            pkg.service_code          AS package_code,
            pkg.bonus_payment_basis   AS package_payment_basis,
            c.service_review_pending,
            c.system_type,
            c.institution_type,
            c.targets_name,

            -- Phase 5: Services (multi-select, aggregated as JSON array).
            -- Friendly label uses COALESCE(description, service_code) — same
            -- pattern as the reference list endpoints, so what the user sees
            -- in the chip matches what they see in the dropdown.
            COALESCE(
                (SELECT json_agg(
                    json_build_object(
                        'id',             s.id,
                        'service_fee_id', s.service_fee_id,
                        'service_code',   rsf.service_code,
                        'service_label',  COALESCE(NULLIF(TRIM(SPLIT_PART(rsf.description, ' — ', 1)), ''), rsf.service_code),
                        'category',       rsf.category,
                        'count',          s.count,
                        'bonus_event',    s.bonus_event,
                        'confirmed',      s.confirmed,
                        'detection_source', s.detection_source
                    )
                    ORDER BY COALESCE(NULLIF(TRIM(SPLIT_PART(rsf.description, ' — ', 1)), ''), rsf.service_code)
                )
                FROM tx_case_service s
                JOIN ref_service_fee rsf ON s.service_fee_id = rsf.id
                WHERE s.case_id = c.id),
                '[]'::json
            ) AS services,

            -- Phase 14 Block 4 / C: Per-slot management overrides
            -- (1-to-many child of tx_case, edited on the Submitted board).
            -- Same JSON-array pattern as services. Empty array when none.
            COALESCE(
                (SELECT json_agg(
                    json_build_object(
                        'id',         o.id,
                        'staff_id',   o.staff_id,
                        'staff_name', os.canonical_name,
                        'amount',     o.amount,
                        'reason',     o.reason,
                        'created_at', o.created_at,
                        'updated_at', o.updated_at
                    )
                    ORDER BY os.canonical_name
                )
                FROM tx_case_override o
                LEFT JOIN ref_staff os ON os.id = o.staff_id
                WHERE o.case_id = c.id),
                '[]'::json
            ) AS overrides

        FROM tx_case c
        LEFT JOIN ref_institution inst         ON c.institution_id          = inst.id
        LEFT JOIN dim_country     cn           ON c.country_id              = cn.id
        LEFT JOIN dim_office      case_office  ON c.case_office_id          = case_office.id
        LEFT JOIN dim_office      ref_office   ON c.referring_office_id     = ref_office.id
        LEFT JOIN ref_partner     partner      ON c.referring_partner_id    = partner.id
        LEFT JOIN ref_sub_agent   sub_agent    ON c.referring_sub_agent_id  = sub_agent.id
        LEFT JOIN ref_service_fee fee          ON c.service_fee_id          = fee.id
        LEFT JOIN ref_service_fee pkg          ON c.package_fee_id          = pkg.id
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

@app.patch("/api/cases/{case_id}", dependencies=[Depends(get_current_user)])
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
# Bulk Services replace — PATCH /api/cases/{case_id}/services
# ===========================================================================

# Valid values for tx_case_service.bonus_event — must match the SQL CHECK
# constraint on the column (see services_packages_migration.sql).
VALID_BONUS_EVENTS = {
    "contract_signed_date",
    "visa_received_date",
    "course_start_date",
    "enrolment_date",
    "manual_hold",
}


@app.patch("/api/cases/{case_id}/services", dependencies=[Depends(get_current_user)])
def replace_case_services(case_id: int, body: dict = Body(default_factory=dict)) -> dict:
    """Replace the entire services list for a case (idempotent).

    Each service entry carries:
        service_fee_id   (required, BIGINT, FK to ref_service_fee, must be
                          a SERVICE_FEE or ADDON row — not PACKAGE)
        count            (optional, INT >= 1, defaults to 1)
        bonus_event      (optional, one of VALID_BONUS_EVENTS; if omitted,
                          defaults from ref_service_fee.bonus_payment_basis)

    Request body (JSON):
        {
            "services": [
                {"service_fee_id": 12, "count": 2, "bonus_event": "course_start_date"},
                {"service_fee_id": 17}
            ],
            "confirmed":    true,    // optional; default true
            "clear_review": true     // optional; if true, also set
                                     // tx_case.service_review_pending = FALSE
        }

    Response:
        { "case_id": N, "services": [ {...}, ... ], "service_review_pending": bool }

    Errors:
        400 — bad body / unknown service_fee_id / PACKAGE row / bad bonus_event /
              service has no default bonus_payment_basis and the request didn't
              provide one
        404 — case not found
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")

    raw_services = body.get("services")
    if not isinstance(raw_services, list):
        raise HTTPException(400, "services must be a list (may be empty)")

    # Normalize incoming entries into a dict keyed by service_fee_id so we
    # naturally dedupe within the request (last-one-wins).
    incoming: dict[int, dict] = {}
    for entry in raw_services:
        if not isinstance(entry, dict):
            raise HTTPException(400, "each service entry must be a JSON object")
        sid = entry.get("service_fee_id")
        if not isinstance(sid, int):
            raise HTTPException(400, "service_fee_id must be an integer")
        count = entry.get("count", 1)
        if not isinstance(count, int) or count < 1:
            raise HTTPException(400, f"count must be an integer >= 1 (got {count!r})")
        bonus_event = entry.get("bonus_event")
        if bonus_event is not None:
            if bonus_event not in VALID_BONUS_EVENTS:
                raise HTTPException(
                    400,
                    f"bonus_event must be one of {sorted(VALID_BONUS_EVENTS)}, "
                    f"got {bonus_event!r}",
                )
        incoming[sid] = {"count": count, "bonus_event": bonus_event}

    confirmed = bool(body.get("confirmed", True))
    clear_review = bool(body.get("clear_review", True))

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Ensure case exists
            cur.execute("SELECT id FROM tx_case WHERE id = %s", (case_id,))
            if cur.fetchone() is None:
                raise HTTPException(404, f"Case {case_id} not found")

            # 2. Validate every service_fee_id and resolve its default bonus_event
            #    (used when the request didn't specify one)
            new_ids = list(incoming.keys())
            ref_meta: dict[int, dict] = {}
            if new_ids:
                cur.execute(
                    "SELECT id, category, service_code, bonus_payment_basis "
                    "  FROM ref_service_fee "
                    " WHERE id = ANY(%s)",
                    (new_ids,),
                )
                rows = cur.fetchall()
                ref_meta = {r["id"]: dict(r) for r in rows}
                missing = [i for i in new_ids if i not in ref_meta]
                if missing:
                    raise HTTPException(400, f"Unknown service_fee_ids: {missing}")
                packages = [i for i, m in ref_meta.items() if m["category"] == "PACKAGE"]
                if packages:
                    raise HTTPException(
                        400,
                        f"service_fee_ids {packages} are PACKAGE rows — "
                        f"use PATCH /api/cases/{case_id} with package_fee_id instead.",
                    )

            # 3. Resolve each entry's final bonus_event
            #    (use the request value if provided; otherwise the default from
            #    ref_service_fee.bonus_payment_basis; error if both are missing)
            for sid, entry in incoming.items():
                if entry["bonus_event"] is None:
                    default = ref_meta[sid].get("bonus_payment_basis")
                    if not default:
                        raise HTTPException(
                            400,
                            f"service_fee_id {sid} ({ref_meta[sid]['service_code']}) "
                            f"has no default bonus_payment_basis set on "
                            f"ref_service_fee, and the request did not specify "
                            f"bonus_event for it.",
                        )
                    entry["bonus_event"] = default

            # 4. Diff against current set
            cur.execute(
                "SELECT service_fee_id, count, bonus_event "
                "  FROM tx_case_service "
                " WHERE case_id = %s",
                (case_id,),
            )
            current = {r["service_fee_id"]: dict(r) for r in cur.fetchall()}
            new_set = set(incoming.keys())
            current_set = set(current.keys())
            to_add    = new_set    - current_set
            to_remove = current_set - new_set
            to_keep   = new_set    & current_set

            # 5. Apply diff
            if to_remove:
                cur.execute(
                    "DELETE FROM tx_case_service "
                    " WHERE case_id = %s AND service_fee_id = ANY(%s)",
                    (case_id, list(to_remove)),
                )
            for sid in to_add:
                e = incoming[sid]
                cur.execute(
                    "INSERT INTO tx_case_service "
                    "  (case_id, service_fee_id, count, bonus_event, confirmed, "
                    "   detection_source) "
                    "VALUES (%s, %s, %s, %s, %s, 'user_manual')",
                    (case_id, sid, e["count"], e["bonus_event"], confirmed),
                )
            # For rows we're keeping, only UPDATE if count or bonus_event changed
            # (or confirmed=True and current row is not confirmed)
            for sid in to_keep:
                e = incoming[sid]
                cur_row = current[sid]
                needs_update = (
                    e["count"] != cur_row["count"]
                    or e["bonus_event"] != cur_row["bonus_event"]
                    or confirmed  # always set TRUE when user explicitly saves
                )
                if needs_update:
                    cur.execute(
                        "UPDATE tx_case_service "
                        "   SET count = %s, "
                        "       bonus_event = %s, "
                        "       confirmed = CASE WHEN %s THEN TRUE ELSE confirmed END "
                        " WHERE case_id = %s "
                        "   AND service_fee_id = %s",
                        (e["count"], e["bonus_event"], confirmed, case_id, sid),
                    )

            # 6. Optionally clear the case-level review banner
            if clear_review:
                cur.execute(
                    "UPDATE tx_case "
                    "   SET service_review_pending = FALSE, updated_at = NOW() "
                    " WHERE id = %s",
                    (case_id,),
                )

            # 7. Fetch fresh state to return — uses the same friendly-label
            #    pattern as /api/cases so the frontend gets a consistent shape
            cur.execute(
                """
                SELECT s.id,
                       s.service_fee_id,
                       s.count,
                       s.bonus_event,
                       s.confirmed,
                       s.detection_source,
                       rsf.service_code,
                       rsf.category,
                       COALESCE(NULLIF(TRIM(SPLIT_PART(rsf.description, ' — ', 1)), ''), rsf.service_code) AS service_label
                  FROM tx_case_service s
                  JOIN ref_service_fee rsf ON s.service_fee_id = rsf.id
                 WHERE s.case_id = %s
                 ORDER BY service_label
                """,
                (case_id,),
            )
            services = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT service_review_pending FROM tx_case WHERE id = %s",
                (case_id,),
            )
            review_row = cur.fetchone()

            conn.commit()

    return {
        "case_id": case_id,
        "services": services,
        "service_review_pending": bool(review_row["service_review_pending"]) if review_row else False,
    }


# ===========================================================================
# Bonus simulator — GET /api/cases/{case_id}/estimate-bonus
# ===========================================================================
# Dry-run the bonus engine on a single case to preview the bonus.
# Used by staff during review to see what their bonus would be before the
# case is calculated for real. Available only when workflow_state ==
# 'in_review'. Never writes to the DB.
# ===========================================================================

@app.get(
    "/api/cases/{case_id}/estimate-bonus",
    dependencies=[Depends(get_current_user)],
)
def estimate_case_bonus(
    case_id: int = PathParam(..., ge=1),
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """Preview the bonus for a single case without persisting anything.

    Visibility:
      - Reviewers (DQO / ADMIN / DIRECTOR / FO): see all slots on the case.
      - Everyone else (typically STAFF): see only their own slot(s),
        matched by user.staff_id.

    Returns 400 if the case isn't in 'in_review', 404 if it doesn't exist.
    """
    try:
        result = estimate_bonus_for_case(case_id)
    except CaseNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CaseNotInReviewError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except CasePeriodMissingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Estimate failed: {type(e).__name__}: {e}",
        )

    # Role-based filter on the returned payment list
    is_reviewer = bool(set(user.roles) & {"DQO", "ADMIN", "DIRECTOR", "FO"})
    if is_reviewer:
        visible = result["payments"]
        viewing_mode = "all_slots"
    else:
        # STAFF (or any user without a reviewer role) sees only their
        # own slot(s). Users with no staff_id (function users without
        # reviewer role — shouldn't happen in practice) get nothing.
        if user.staff_id is None:
            visible = []
        else:
            visible = [
                p for p in result["payments"]
                if p.get("staff_id") == user.staff_id
            ]
        viewing_mode = "own_slot_only"

    return {
        "case": result["case"],
        "payments": visible,
        "viewing_mode": viewing_mode,
        "skipped": result["skipped"],
        "errored": result["errored"],
        "disclaimer": (
            "Estimate only — the final bonus may differ when this period "
            "is calculated by Finance. Numbers reflect the case data and "
            "reference rates at the moment of preview."
        ),
    }


# ===========================================================================
# Approvals (Phase 14 Block 3 / B)
# ===========================================================================
# Three endpoints:
#   GET    /api/cases/{id}/approvals          — list slot status (any user)
#   POST   /api/cases/{id}/approve            — self-approve (any user)
#   POST   /api/cases/{id}/override-approval  — manager override (DQO/ADMIN/
#                                                DIRECTOR/FO)
# The transition endpoint below blocks in_review -> submitted until all
# required slots are approved.
# ===========================================================================

@app.get(
    "/api/cases/{case_id}/approvals",
    dependencies=[Depends(get_current_user)],
)
def list_case_approvals(case_id: int = PathParam(..., ge=1)) -> dict:
    """Return the approval status of every applicable slot on the case."""
    try:
        return get_case_approvals(case_id)
    except ApprovalCaseNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Failed to load approvals: {type(e).__name__}: {e}")


@app.post(
    "/api/cases/{case_id}/approve",
    dependencies=[Depends(get_current_user)],
)
def self_approve_case(
    case_id: int = PathParam(..., ge=1),
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """Approve any slot on the case where user.staff_id matches.

    Idempotent — re-approving an already-approved slot is a no-op (it'll
    appear in `already_approved`, not `approved_slots`).
    """
    try:
        return approve_my_slots(
            case_id=case_id,
            user_id=user.id,
            user_staff_id=user.staff_id,
        )
    except UserNotOnCaseError as e:
        raise HTTPException(403, str(e))
    except ApprovalCaseNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Approval failed: {type(e).__name__}: {e}")


@app.post(
    "/api/cases/{case_id}/override-approval",
    dependencies=[Depends(require_role(["DQO", "ADMIN", "DIRECTOR", "FO"]))],
)
def override_case_approval(
    case_id: int = PathParam(..., ge=1),
    body: dict = Body(default_factory=dict),
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """Manager approves a slot on behalf of the assigned staff member.

    Body:
        {
            "role_id": int,
            "staff_id": int,
            "reason": "Staff on leave"
        }
    """
    role_id = body.get("role_id")
    staff_id = body.get("staff_id")
    reason = body.get("reason")

    if not isinstance(role_id, int):
        raise HTTPException(400, "role_id (int) is required")
    if not isinstance(staff_id, int):
        raise HTTPException(400, "staff_id (int) is required")
    if not isinstance(reason, str):
        raise HTTPException(400, "reason (string) is required")

    try:
        return override_approval(
            case_id=case_id,
            role_id=role_id,
            staff_id=staff_id,
            user_id=user.id,
            reason=reason,
        )
    except EmptyOverrideReasonError as e:
        raise HTTPException(400, str(e))
    except SlotNotFoundError as e:
        raise HTTPException(400, str(e))
    except ApprovalAlreadyRecordedError as e:
        raise HTTPException(409, str(e))
    except ApprovalCaseNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Override failed: {type(e).__name__}: {e}")


# ===========================================================================
# Per-slot case overrides (Phase 14 Block 4 / C)
# ===========================================================================
# Two endpoints:
#   GET /api/cases/{id}/overrides           — list current overrides + available staff
#   PUT /api/cases/{id}/overrides           — replace the whole list (DQO/ADMIN/DIR/FO)
# Plus a finalize endpoint:
#   POST /api/cases/finalize                — Submitted+Calculated → Closed
# ===========================================================================

@app.get(
    "/api/cases/{case_id}/overrides",
    dependencies=[Depends(get_current_user)],
)
def list_case_overrides_endpoint(case_id: int = PathParam(..., ge=1)) -> dict:
    """List current overrides for a case, plus the case's slot staff so
    the UI can populate the 'add override' dropdown.
    """
    try:
        return list_case_overrides(case_id)
    except OverrideCaseNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Failed to load overrides: {type(e).__name__}: {e}")


@app.put(
    "/api/cases/{case_id}/overrides",
    dependencies=[Depends(require_role(["DQO", "ADMIN", "DIRECTOR", "FO"]))],
)
def put_case_overrides_endpoint(
    case_id: int = PathParam(..., ge=1),
    body: dict = Body(default_factory=dict),
    user: UserInfo = Depends(get_current_user),
) -> dict:
    """Replace the whole override list for a case.

    Body:
        {
            "overrides": [
                {"staff_id": int, "amount": int, "reason": "str"},
                ...
            ]
        }

    Validation (all-or-nothing):
      - Case must exist and be in workflow_state='submitted'
      - Every staff_id must match a slot on the case
      - Every amount must be a non-zero int
      - Every reason must be non-empty after trimming
      - No duplicate staff_ids

    Returns the fresh list_case_overrides() output on success.
    """
    overrides = body.get("overrides")
    if not isinstance(overrides, list):
        raise HTTPException(400, "Body must contain 'overrides' as a list")

    try:
        return replace_case_overrides(
            case_id=case_id,
            overrides=overrides,
            user_id=user.id,
        )
    except OverrideCaseNotFoundError as e:
        raise HTTPException(404, str(e))
    except WorkflowStateError as e:
        raise HTTPException(409, str(e))
    except StaffNotOnCaseError as e:
        raise HTTPException(400, str(e))
    except (EmptyReasonError, InvalidAmountError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Failed to save overrides: {type(e).__name__}: {e}")


@app.post(
    "/api/cases/finalize",
    dependencies=[Depends(require_role(["DQO", "ADMIN", "DIRECTOR", "FO"]))],
)
def finalize_cases(body: dict = Body(default_factory=dict)) -> dict:
    """Publish & Close — the "Close" button on the Submitted board.

    Under the Block 5 draft/published model this endpoint does TWO things
    in one atomic transaction:

      1. Flips every draft bonus row attached to these cases to PUBLISHED
         (sets tx_bonus_payment.published_at = NOW()). Once published,
         the rows are visible at /bonus/yyyy/mm and locked against engine
         overwrite — undoing requires going through tx_bonus_reversal.

      2. Moves the cases themselves to workflow_state = 'closed', i.e.
         out of the Submitted board and onto the Closed board.

    Both halves either succeed together or roll back together.

    Body:
        {"case_ids": [1, 2, 3]}

    Preconditions (all-or-nothing — any failure aborts the whole thing):
      - Every case must exist (404 if not)
      - Every case must be in workflow_state = 'submitted'
      - Every case must have calculated_at IS NOT NULL (i.e. the Total
        bonus button has been clicked and the engine has run)
      - No case may have any ALREADY-PUBLISHED bonus rows (re-publish
        is not allowed — reverse first via the existing reversal flow)

    Cases with zero bonus rows are fine. The user explicitly wants every
    case to flow through to Closed regardless of whether bonus was
    generated — so a case with no entitled staff still transitions
    successfully; the bonus side is just a no-op for it.

    Response shape preserves the Block 4 fields for frontend compatibility,
    plus a new field for the published-row count:
        {"finalized": int, "ids": [...], "published_payment_rows": int}
    """
    case_ids = body.get("case_ids", [])
    if not isinstance(case_ids, list) or not all(isinstance(i, int) for i in case_ids):
        raise HTTPException(400, "case_ids must be a list of integers")
    if not case_ids:
        raise HTTPException(400, "case_ids cannot be empty")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # ---- Case existence and state checks --------------------------
            cur.execute(
                """
                SELECT id, workflow_state, calculated_at
                FROM tx_case
                WHERE id = ANY(%s)
                """,
                (case_ids,),
            )
            rows_by_id = {r["id"]: r for r in cur.fetchall()}

            missing = [cid for cid in case_ids if cid not in rows_by_id]
            if missing:
                raise HTTPException(404, f"Cases not found: {missing}")

            not_submitted = [
                r["id"] for r in rows_by_id.values()
                if r["workflow_state"] != "submitted"
            ]
            if not_submitted:
                raise HTTPException(
                    400,
                    f"Cannot publish — these cases are not in 'submitted': "
                    f"{not_submitted}",
                )

            not_calculated = [
                r["id"] for r in rows_by_id.values()
                if r["calculated_at"] is None
            ]
            if not_calculated:
                raise HTTPException(
                    400,
                    f"Cannot publish — these cases have not been calculated "
                    f"yet (no engine run): {not_calculated}. Click Total "
                    f"bonus first.",
                )

            # ---- Bonus-row precondition: nothing already published --------
            # Once a row is published, the only legitimate path back to
            # draft is the formal reversal flow. Reject re-publishes here
            # so we never silently overwrite a published_at timestamp.
            cur.execute(
                """
                SELECT DISTINCT case_id
                FROM tx_bonus_payment
                WHERE case_id = ANY(%s)
                  AND published_at IS NOT NULL
                """,
                (case_ids,),
            )
            already_published = [r["case_id"] for r in cur.fetchall()]
            if already_published:
                raise HTTPException(
                    400,
                    f"Cannot publish — these cases have bonus rows that "
                    f"were already published: {already_published}. To redo, "
                    f"reverse first via the existing tx_bonus_reversal flow.",
                )

            # ---- Atomic publish + close ------------------------------------
            # Step 1: flip every draft bonus row attached to these cases
            #         to PUBLISHED. updated_at is set by the trg_set_updated_at
            #         trigger automatically.
            cur.execute(
                """
                UPDATE tx_bonus_payment
                SET published_at = NOW()
                WHERE case_id = ANY(%s)
                  AND published_at IS NULL
                RETURNING id
                """,
                (case_ids,),
            )
            published_payment_ids = [r["id"] for r in cur.fetchall()]

            # Step 2: transition the cases to Closed.
            cur.execute(
                """
                UPDATE tx_case
                SET workflow_state = 'closed', updated_at = NOW()
                WHERE id = ANY(%s)
                RETURNING id
                """,
                (case_ids,),
            )
            closed_case_ids = [r["id"] for r in cur.fetchall()]

            conn.commit()

    return {
        # Legacy field names — preserved so the existing frontend code
        # in /import/review/page.tsx (Block 4) keeps working unchanged.
        "finalized": len(closed_case_ids),
        "ids": closed_case_ids,
        # New field — Batch B will surface this in the success banner.
        "published_payment_rows": len(published_payment_ids),
    }


# ===========================================================================
# Gate-check endpoint — GET /api/cases/gate?year=X&month=Y
# ===========================================================================
# Tells the frontend whether the "Total bonus" button is unlocked for a
# given period. Total bonus runs a full month-wide engine pass that
# persists draft bonus rows, so it should only be allowed once every case
# in the period has been processed past 'uploaded' and 'in_review' into
# 'submitted' (or already 'closed').
#
# Gate is satisfied for (year, month) when:
#   - zero cases in 'uploaded'
#   - zero cases in 'in_review'
#   - at least one case in 'submitted' or 'closed' (i.e. something to total)
#
# Response shape:
#   {
#     "year": int,
#     "month": int,
#     "ready_for_total_bonus": bool,
#     "state_counts": {"uploaded": int, "in_review": int,
#                      "submitted": int, "closed": int},
#     "blocker_case_ids": [int, ...]   # cases still in uploaded + in_review
#   }
#
# Open to any authenticated user — the frontend uses this on the Submitted
# board to enable/disable the Total bonus button and to render a tooltip
# listing the blockers.
# ---------------------------------------------------------------------------

@app.get("/api/cases/gate", dependencies=[Depends(get_current_user)])
def cases_gate(
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
) -> dict:
    """Gate-check for the Total bonus button — see comment block above."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT workflow_state,
                       COUNT(*)::int  AS n,
                       ARRAY_AGG(id ORDER BY id) AS ids
                FROM tx_case
                WHERE run_year = %s AND run_month = %s
                GROUP BY workflow_state
                """,
                (year, month),
            )
            rows = cur.fetchall()

    state_counts = {"uploaded": 0, "in_review": 0, "submitted": 0, "closed": 0}
    blocker_case_ids: list[int] = []
    for r in rows:
        state = r["workflow_state"]
        # Defensive: ignore any unexpected workflow_state values rather than
        # crashing the gate endpoint.
        if state in state_counts:
            state_counts[state] = r["n"]
            if state in ("uploaded", "in_review"):
                blocker_case_ids.extend(r["ids"])

    blocker_case_ids.sort()

    ready = (
        state_counts["uploaded"] == 0
        and state_counts["in_review"] == 0
        and (state_counts["submitted"] + state_counts["closed"]) > 0
    )

    return {
        "year": year,
        "month": month,
        "ready_for_total_bonus": ready,
        "state_counts": state_counts,
        "blocker_case_ids": blocker_case_ids,
    }


# ===========================================================================
# Bulk workflow_state transition — POST /api/cases/transition
# ===========================================================================

VALID_WORKFLOW_STATES = {"uploaded", "in_review", "submitted", "closed"}

# Legal forward transitions. Reversals (e.g. submitted → in_review) are NOT
# part of Phase 3 — they'll be added later for Finance/Senior Manager.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "uploaded":  {"in_review"},
    "in_review": {"submitted"},
    "submitted": {"closed"},
    "closed":    set(),  # terminal for now
}


@app.post("/api/cases/transition", dependencies=[Depends(require_role(["DQO", "ADMIN", "DIRECTOR", "FO"]))])
def transition_cases(body: dict = Body(default_factory=dict)) -> dict:
    """Bulk-transition a list of cases to a new workflow_state.

    Request body (JSON):
        {
            "case_ids": [1, 2, 3, ...],     // tx_case.id values
            "to_state": "in_review"         // one of: uploaded / in_review / submitted / closed
        }

    Validates:
      - case_ids is a non-empty list of ints
      - to_state is a valid workflow_state value
      - All cases share the same current state (mixed batches rejected)
      - The transition current_state -> to_state is legal

    Response:
        {
            "transitioned": 3,
            "from_state": "uploaded",
            "to_state": "in_review",
            "ids": [1, 2, 3]
        }

    Errors:
        400 — bad body, invalid state, illegal transition, mixed current states
        404 — one or more case_ids not found
    """
    case_ids = body.get("case_ids")
    to_state = body.get("to_state")

    # ---- input validation -------------------------------------------------
    if not isinstance(case_ids, list) or not case_ids:
        raise HTTPException(400, "case_ids must be a non-empty list of integers")
    if not all(isinstance(x, int) for x in case_ids):
        raise HTTPException(400, "case_ids must contain only integers")
    if to_state not in VALID_WORKFLOW_STATES:
        raise HTTPException(
            400,
            f"to_state must be one of {sorted(VALID_WORKFLOW_STATES)}, got {to_state!r}",
        )

    # Dedup while preserving order
    case_ids = list(dict.fromkeys(case_ids))

    with get_connection() as conn:
        with conn.cursor() as cur:
            # ---- fetch the current states of all selected cases ----------
            cur.execute(
                "SELECT id, workflow_state FROM tx_case WHERE id = ANY(%s)",
                (case_ids,),
            )
            rows = cur.fetchall()
            found_ids = {r["id"] for r in rows}
            missing = [i for i in case_ids if i not in found_ids]
            if missing:
                raise HTTPException(
                    status_code=404,
                    detail=f"Cases not found: {missing}",
                )

            current_states = {r["workflow_state"] for r in rows}
            if len(current_states) > 1:
                raise HTTPException(
                    400,
                    f"Selected cases are in mixed states {sorted(current_states)}; "
                    f"transition one state at a time.",
                )
            from_state = current_states.pop()

            # ---- transition legality -------------------------------------
            if to_state == from_state:
                raise HTTPException(
                    400,
                    f"All selected cases are already in state {from_state!r}.",
                )
            legal_next = LEGAL_TRANSITIONS.get(from_state, set())
            if to_state not in legal_next:
                raise HTTPException(
                    400,
                    f"Illegal transition {from_state!r} -> {to_state!r}. "
                    f"Legal next states from {from_state!r}: {sorted(legal_next) or 'none'}",
                )

            # ---- approval guard ------------------------------------------
            # Phase 14 Block 3 (B): require all required slots approved
            # before in_review -> submitted.
            if from_state == "in_review" and to_state == "submitted":
                missing = check_approvals_for_transition(case_ids)
                if missing:
                    sample = sorted(missing.items())[:5]
                    detail_lines = [
                        f"case_id={cid}: missing {slots}"
                        for cid, slots in sample
                    ]
                    extra = (
                        f" (and {len(missing) - 5} more)"
                        if len(missing) > 5 else ""
                    )
                    raise HTTPException(
                        400,
                        "Cannot submit — some cases have unapproved required "
                        f"slots{extra}: " + "; ".join(detail_lines),
                    )

            # ---- apply the update ----------------------------------------
            cur.execute(
                "UPDATE tx_case "
                "SET workflow_state = %s, updated_at = NOW() "
                "WHERE id = ANY(%s) "
                "RETURNING id",
                (to_state, case_ids),
            )
            updated_ids = [r["id"] for r in cur.fetchall()]
            conn.commit()

    return {
        "transitioned": len(updated_ids),
        "from_state": from_state,
        "to_state": to_state,
        "ids": updated_ids,
    }


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
    # Phase 5 — ref_service_fee, split into:
    #   service_codes — SERVICE_FEE + ADDON categories (the multi-select Services)
    #   package_codes — PACKAGE category only (the single-select Package)
    # Dropdown label: COALESCE(description, service_code) so we get the friendly
    # name when available, otherwise the machine code.
    "service_codes":
        "SELECT id, "
        "       COALESCE(NULLIF(TRIM(SPLIT_PART(description, ' — ', 1)), ''), service_code) AS name, "
        "       service_code AS code, "
        "       category, "
        "       counsellor_signing_bonus, "
        "       co_signing_bonus, "
        "       bonus_payment_basis "
        "  FROM ref_service_fee "
        " WHERE is_active = TRUE "
        "   AND category IN ('SERVICE_FEE', 'ADDON') "
        " ORDER BY COALESCE(NULLIF(TRIM(SPLIT_PART(description, ' — ', 1)), ''), service_code)",
    "package_codes":
        "SELECT id, "
        "       COALESCE(NULLIF(TRIM(SPLIT_PART(description, ' — ', 1)), ''), service_code) AS name, "
        "       service_code AS code, "
        "       counsellor_signing_bonus, "
        "       co_signing_bonus, "
        "       bonus_payment_basis "
        "  FROM ref_service_fee "
        " WHERE is_active = TRUE "
        "   AND category = 'PACKAGE' "
        " ORDER BY COALESCE(NULLIF(TRIM(SPLIT_PART(description, ' — ', 1)), ''), service_code)",
}

REF_LIST_STATIC: dict[str, list[str]] = {
    "source_types": ["DIRECT", "SUB_AGENT", "MASTER_AGENT", "GROUP", "OFFICE"],
    "import_statuses": ["OK", "UNRESOLVED", "FLAGGED", "SCRAP"],
    # Client type / service category. Union of original 24 + v6.2 template's
    # 34 values (incl. diacritic variants and case differences), deduped.
    # The diacritic variants ARE intentional — same business meaning, but the
    # CRM has been recording them inconsistently and users need to be able to
    # pick whichever spelling matches what the CRM has stored.
    "client_types": [
        "Credential Evaluation",
        "Công tác nước ngoài",
        "Du hoc (Ghi danh + visa)",
        "Du hoc (Ghi danh)",
        "Du hoc (ghi danh + visa)",
        "Du hoc he",
        "Du hoc hè",
        "Du hoc tai cho",
        "Du hoc tai cho (Vietnam)",
        "Du học (Ghi danh + visa)",
        "Du học (Ghi danh)",
        "Du học (Ghi danh+visa)",
        "Du học (Nộp đơn hỗ trợ tài chính)",
        "Du học (chuyển trường)",
        "Du học (ghi danh + visa)",
        "Du học (ghi danh chuyển trường)",
        "Du học (ghi danh)",
        "Du học (hướng dẫn phỏng vấn)",
        "Du học (visa)",
        "Du học (điền đơn chuyển trường)",
        "Du học (điền đơn ghi danh)",
        "Du học (điền đơn visa)",
        "Du học (điền đơn xin học bổng)",
        "Du học (điền đơn, đăng ký lịch phỏng vấn, đóng phí SEVIS)",
        "Du học he",
        "Du học hè",
        "Du học tại chỗ",
        "Du học tại chỗ (VN)",
        "Du học tại chỗ (Vietnam)",
        "Du học/tham quan ngắn hạn theo đoàn",
        "Du lịch",
        "Giám hộ ở nước ngoài",
        "Kết hôn",
        "Người phụ thuộc ở nước ngoài",
        "Thay đổi Giám Hộ / Chỗ ở",
        "Thị thực tạm trú cho sinh viên sau tốt nghiệp",
        "Thị thực tạm trú cho sinh viên tốt nghiệp",
        "Travel Exemption",
        "Visa Dinh cu",
        "Visa Du Lịch",
        "Visa Du hoc only",
        "Visa Du học only",
        "Visa Du lịch",
        "Visa Giam ho",
        "Visa Giám hộ",
        "Visa Phu thuoc",
        "Visa Phụ thuộc",
        "Visa du học only",
        "Visa du lich",
        "Visa giám hộ",
        "Visa phụ thuộc",
        "Visa Định cư",
        "Visa định cư",
        "Điền đơn xin visa",
    ],
    "course_statuses": [
        "Attending",
        "Enrolled",
        "Cancelled",
    ],
    # v6.2 col 21 — Deferral codes
    "deferral_codes": [
        "NONE",
        "DEFERRED",
        "FEE_TRANSFERRED",
        "FEE_WAIVED",
        "NO_SERVICE",
    ],
    # v6.2 col 9 — System Type
    "system_types": [
        "Trong hệ thống",
        "Ngoài hệ thống",
    ],
    # v6.2 col 28 — Institution Type
    "institution_types": [
        "DIRECT",
        "MASTER_AGENT",
        "GROUP",
        "OUT_OF_SYSTEM",
        "RMIT_VN",
        "OTHER_VN",
    ],
    # Phase 5 — valid values for tx_case_service.bonus_event
    # (must match the CHECK constraint in the SQL migration)
    "bonus_events": [
        "contract_signed_date",
        "visa_received_date",
        "course_start_date",
        "enrolment_date",
        "manual_hold",
    ],
    # v6.2 col 17 — curated 6-person Pre-sales list (plus NONE).
    # Locked: this is NOT all-staff; it's a specific subset that earns
    # pre-sales splits. Names must match ref_staff.canonical_name when
    # the importer / engine reads them.
    "presales_agents": [
        "NONE",
        "Gia Mẫn",
        "Hoàng Yến",
        "Huỳnh Anh",
        "Lê Thị Trường An",
        "Trúc Quỳnh (HCM)",
        "Trúc Quỳnh (HN)",
    ],
    # v6.2 cols 31–33 — legacy add-on codes used in old multi-row imports.
    # Kept here for backward compatibility while the new junction-based
    # model is rolled out. New cases should not need this.
    "addon_codes": [
        "EXTRA_SCHOOL",
        "VISITOR_VISA",
        "STUDY_PERMIT_RENEWAL",
        "GUARDIAN_VISA_RENEWAL",
        "SCHOOL_TRANSFER_DET",
        "CAQ",
        "GUARDIAN_HOMESTAY_CHANGE",
        "EXCHANGE",
    ],
}


@app.get("/api/reference/{list_name}", dependencies=[Depends(get_current_user)])
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

def _stamp_calculated_at_for_period(
    year: int, month: int, contract_id: Optional[str] = None
) -> None:
    """Refresh tx_case.calculated_at after a successful engine run.

    Sets calculated_at = NOW() for every case in (year, month) that has at
    least one tx_bonus_payment row, and clears it to NULL for cases that
    don't. This keeps the column consistent across re-runs (the engine
    deletes payment rows before re-writing, so a re-run can legitimately
    leave a case without payment rows if it now errors or is skipped).

    If contract_id is given, only that one case is touched (single-case
    debug runs).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            params: list[Any] = [year, month]
            extra_clause = ""
            if contract_id is not None:
                extra_clause = " AND c.contract_id = %s"
                params.append(contract_id)

            cur.execute(
                f"""
                UPDATE tx_case c
                SET calculated_at = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM tx_bonus_payment p WHERE p.case_id = c.id
                    ) THEN NOW()
                    ELSE NULL
                END
                WHERE c.run_year = %s
                  AND c.run_month = %s
                  {extra_clause}
                """,
                params,
            )
            conn.commit()


@app.post("/api/engine/run", dependencies=[Depends(require_role(["FO", "ADMIN"]))])
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
        result = run_engine_api(
            year=year,
            month=month,
            persist=persist,
            limit=limit,
            contract_id=contract_id,
        )

        # Phase 14 Block 4 / C — stamp tx_case.calculated_at on every case
        # in this (year, month) that now has at least one tx_bonus_payment
        # row, and CLEAR it on cases that don't. The engine deletes existing
        # payment rows for the period before re-writing, so a re-run
        # correctly re-stamps surviving cases and nulls out cases that
        # errored/were skipped this time.
        #
        # Only fires when persist=True (dry-runs don't touch tx_case state).
        if persist:
            _stamp_calculated_at_for_period(year, month, contract_id)

        return result
    except Exception as exc:
        # Phase 13e debug: write the full traceback to stdout with explicit
        # flush so Railway's default log view always shows it. (stderr is
        # buffered/filtered in some log viewers; stdout+flush is reliable.)
        print("=" * 60, flush=True)
        print(
            f"ENGINE RUN FAILED — year={year} month={month} "
            f"contract_id={contract_id!r} limit={limit!r} persist={persist}",
            flush=True,
        )
        print(traceback.format_exc(), flush=True)
        print("=" * 60, flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Engine run failed: {type(exc).__name__}: {exc}",
        )


# ===========================================================================
# Bonus payments — GET /api/bonus
# ===========================================================================

@app.get("/api/bonus", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
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
# Per-staff bao cao reports (Phase 16)
# ===========================================================================

@app.get("/api/bonus/periods", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
def list_bonus_periods() -> list[dict]:
    """All (run_year, run_month) periods present in tx_case, ordered most-
    recent-first. Each row carries:
      - case_count: distinct non-SCRAP cases
      - staff_count: distinct staff appearing in any role (counsellor, CO,
        pre-sales)
      - total_net_payable: SUM of net_payable from tx_bonus_payment (0 if
        engine has not yet run for the period)
      - has_engine_output: TRUE iff at least one tx_bonus_payment row
        exists for the period

    Drives the /bonus index page. Periods with no engine output still
    appear so users can see uploaded-but-uncalculated months.
    """
    sql = """
        WITH period_summary AS (
            SELECT
                c.run_year,
                c.run_month,
                COUNT(DISTINCT c.id)::int AS case_count
              FROM tx_case c
             WHERE c.import_status IS DISTINCT FROM 'SCRAP'
               AND c.run_year IS NOT NULL
               AND c.run_month IS NOT NULL
             GROUP BY c.run_year, c.run_month
        ),
        period_staff AS (
            SELECT run_year, run_month, counsellor_staff_id AS staff_id
              FROM tx_case
             WHERE counsellor_staff_id IS NOT NULL
               AND import_status IS DISTINCT FROM 'SCRAP'
               AND run_year IS NOT NULL AND run_month IS NOT NULL
            UNION
            SELECT run_year, run_month, case_officer_staff_id AS staff_id
              FROM tx_case
             WHERE case_officer_staff_id IS NOT NULL
               AND import_status IS DISTINCT FROM 'SCRAP'
               AND run_year IS NOT NULL AND run_month IS NOT NULL
            UNION
            SELECT run_year, run_month, pre_sales_staff_id AS staff_id
              FROM tx_case
             WHERE pre_sales_staff_id IS NOT NULL
               AND import_status IS DISTINCT FROM 'SCRAP'
               AND run_year IS NOT NULL AND run_month IS NOT NULL
        ),
        period_staff_count AS (
            SELECT run_year, run_month, COUNT(DISTINCT staff_id)::int AS staff_count
              FROM period_staff
             GROUP BY run_year, run_month
        ),
        period_bonus AS (
            SELECT
                run_year,
                run_month,
                COALESCE(SUM(net_payable), 0)::bigint AS total_net_payable,
                COUNT(*)::int                         AS payment_count
              FROM tx_bonus_payment
             GROUP BY run_year, run_month
        )
        SELECT
            ps.run_year,
            ps.run_month,
            ps.case_count,
            COALESCE(psc.staff_count, 0)              AS staff_count,
            COALESCE(pb.total_net_payable, 0)         AS total_net_payable,
            COALESCE(pb.payment_count, 0) > 0         AS has_engine_output
          FROM period_summary       ps
          LEFT JOIN period_staff_count psc
                 ON ps.run_year = psc.run_year AND ps.run_month = psc.run_month
          LEFT JOIN period_bonus pb
                 ON ps.run_year = pb.run_year  AND ps.run_month = pb.run_month
         ORDER BY ps.run_year DESC, ps.run_month DESC
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            return list(cur.fetchall())


# ---- Per-staff bao cao helpers (Phase 16) --------------------------------
# These are templated/approximate Vietnamese phrases used for the
# Note BONUS Enrolled and Note BONUS Priority columns. The intent is to
# look like the bao cao output, not to be policy-correct. A future phase
# will replace these by strings emitted directly by the engine into
# tx_bonus_payment.calc_notes.

_ENROLLED_NOTE_BY_STATUS = {
    "Closed - Cancelled":                    "Hồ sơ hủy. Bonus mức = 0.",
    "Closed - Visa refused":                 "Visa từ chối. Bonus mức = 0.",
    "Closed - Visa granted":                 "Đã có visa, chưa nhập học.",
    "Closed - Enrolled":                     "Đã nhập học. Nhận bonus mức 'Enrolled'.",
    "Closed - Enrolled, then Visa granted":  "Nhập học rồi có visa. Nhận bonus mức 'Enrolled, then Visa granted'.",
    "Closed - Visa granted, then enrolled":  "Có visa rồi nhập học. Nhận bonus mức 'Visa granted, then enrolled'.",
    "Current - Enrolled":                    "Đã nhập học, đang chờ visa. Nhận 50% bonus mức 'Current - Enrolled'.",
}

# Bao cao display order. Statuses not in this list are appended at the end.
_SECTION_ORDER = [
    "Closed - Visa granted, then enrolled",
    "Closed - Enrolled, then Visa granted",
    "Closed - Enrolled",
    "Current - Enrolled",
    "Closed - Visa granted",
    "Closed - Visa refused",
    "Closed - Cancelled",
]

_TIER_LABEL = {
    "UNDER":  "Under target",
    "TARGET": "Hit target",
    "OVER":   "Over target (all cases)",
}


def _enrolled_note(status, bonus_enrolled, tier, target, actual, run_year, run_month):
    base = _ENROLLED_NOTE_BY_STATUS.get(status or "", f"Status: {status or '?'}")
    if bonus_enrolled > 0 and tier and target is not None and actual is not None:
        tier_lbl = _TIER_LABEL.get(tier, tier)
        base += (f" Tháng {run_month:02d}/{run_year}, chỉ tiêu {target}. "
                 f"Đạt {actual}. Tier: {tier_lbl}.")
    return base


def _priority_note(institution_name, bonus_priority):
    if bonus_priority == 0:
        return ""
    if not institution_name:
        return "Priority bonus áp dụng."
    return f"Thêm bonus Priority cho Trường {institution_name}."


def _section_sort_key(section_name: str):
    try:
        return (_SECTION_ORDER.index(section_name), section_name)
    except ValueError:
        return (999, section_name)


@app.get("/api/bonus/reports/{year}/{month}", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
def per_staff_bao_cao(
    year: int = PathParam(..., ge=2020, le=2099),
    month: int = PathParam(..., ge=1, le=12),
) -> dict:
    """Per-staff bao cao-format report data for one (year, month).

    Returns one report per staff member who has any role on any case in
    the period. Each staff's report is sectioned by application_status
    (bao cao style) and includes templated Vietnamese justification notes
    for the BONUS Enrolled and BONUS Priority columns.

    Data sourcing:
      - Cases come from tx_case (so zero-bonus cases appear even if the
        engine has not yet written a tx_bonus_payment row for them).
      - Bonus amounts come from tx_bonus_payment when present, 0 otherwise.
      - SCRAP cases are excluded.

    Response shape:
        {
          "year": 2023,
          "month": 10,
          "staff_reports": [
            {
              "staff_id": 9,
              "staff_name": "Phạm Thị Lợi",
              "role_code": "CO_SUB",
              "office_code": "DN",
              "sections": [
                {
                  "section_name": "Closed - Visa granted, then enrolled",
                  "cases": [ { no, contract_id, student_name, ..., bonus_enrolled,
                               note_bonus_enrolled, bonus_priority,
                               note_bonus_priority } ],
                  "subtotal_enrolled": 11000000,
                  "subtotal_priority":  1485000
                }, ...
              ],
              "total_enrolled": 17300000,
              "total_priority":  1485000,
              "grand_total":    18785000
            }, ...
          ]
        }
    """
    # --- 1. Pull every distinct (case, staff) pair for the period --------
    # GROUP BY (case_id, staff_id) collapses the multi-role case (e.g.
    # Lợi as both Counsellor AND CO on the same file) to a single row.
    # slot_roles records WHICH roles she filled, joined with '/'.
    sql = """
        WITH case_staff_distinct AS (
            SELECT
                c.id                                AS case_id,
                slot.staff_id                       AS slot_staff_id,
                STRING_AGG(slot.role_code, '/' ORDER BY slot.role_code)
                                                    AS slot_role
              FROM tx_case c
              CROSS JOIN LATERAL (
                  VALUES
                      (c.counsellor_staff_id,   'COUNSELLOR'),
                      (c.case_officer_staff_id, 'CO'),
                      (c.pre_sales_staff_id,    'PRESALES')
              ) AS slot(staff_id, role_code)
             WHERE c.run_year  = %s
               AND c.run_month = %s
               AND c.import_status IS DISTINCT FROM 'SCRAP'
               AND slot.staff_id IS NOT NULL
             GROUP BY c.id, slot.staff_id
        )
        SELECT
            csd.case_id,
            csd.slot_staff_id,
            csd.slot_role,
            c.contract_id,
            c.student_name,
            c.student_id,
            c.contract_signed_date,
            c.client_type_code,
            c.application_status,
            c.course_status,
            c.visa_received_date,
            c.course_start_date,
            c.notes,
            c.run_year,
            c.run_month,
            c.referring_agent_text_raw,
            c.referring_source_type,
            inst.canonical_name        AS institution_name,
            cn.name                    AS country_name,
            counsellor.canonical_name  AS counsellor_name,
            co.canonical_name          AS case_officer_name,
            partner.name               AS referring_partner_name,
            sub_agent.canonical_name   AS referring_sub_agent_name,
            s.canonical_name           AS staff_name,
            r.code                     AS staff_role_code,
            o.code                     AS staff_office_code,
            bp.bonus_enrolled,
            bp.bonus_priority,
            bp.tier_for_period,
            bp.target_for_period,
            bp.actual_for_period
          FROM case_staff_distinct csd
          JOIN tx_case c ON csd.case_id = c.id
          JOIN ref_staff s ON csd.slot_staff_id = s.id
          LEFT JOIN dim_role        r          ON s.primary_role_id      = r.id
          LEFT JOIN dim_office      o          ON s.home_office_id       = o.id
          LEFT JOIN ref_institution inst       ON c.institution_id       = inst.id
          LEFT JOIN dim_country     cn         ON c.country_id           = cn.id
          LEFT JOIN ref_staff       counsellor ON c.counsellor_staff_id  = counsellor.id
          LEFT JOIN ref_staff       co         ON c.case_officer_staff_id = co.id
          LEFT JOIN ref_partner     partner    ON c.referring_partner_id = partner.id
          LEFT JOIN ref_sub_agent   sub_agent  ON c.referring_sub_agent_id = sub_agent.id
          LEFT JOIN LATERAL (
              SELECT
                  COALESCE(SUM(bp.tier_bonus + bp.package_bonus
                             + bp.addon_bonus + bp.flat_local_enrolment_bonus), 0)::bigint
                                              AS bonus_enrolled,
                  COALESCE(SUM(bp.priority_bonus), 0)::bigint
                                              AS bonus_priority,
                  MAX(bp.tier)                AS tier_for_period,
                  MAX(bp.target)              AS target_for_period,
                  MAX(bp.actual_enrolled)     AS actual_for_period
                FROM tx_bonus_payment bp
               WHERE bp.case_id   = csd.case_id
                 AND bp.staff_id  = csd.slot_staff_id
                 AND bp.run_year  = c.run_year
                 AND bp.run_month = c.run_month
          ) bp ON TRUE
         ORDER BY s.canonical_name NULLS LAST,
                  c.application_status NULLS LAST,
                  c.contract_id
    """

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, [year, month])
            rows = list(cur.fetchall())

    # --- 2. Group: staff -> section -> case ------------------------------
    by_staff: dict[int, dict] = {}
    for row in rows:
        sid = row["slot_staff_id"]
        if sid not in by_staff:
            by_staff[sid] = {
                "staff_id":         sid,
                "staff_name":       row["staff_name"],
                "role_code":        row["staff_role_code"],
                "office_code":      row["staff_office_code"],
                "sections_by_name": {},
                "total_enrolled":   0,
                "total_priority":   0,
            }
        staff = by_staff[sid]

        section_name = row["application_status"] or "(unknown status)"
        if section_name not in staff["sections_by_name"]:
            staff["sections_by_name"][section_name] = {
                "section_name":      section_name,
                "cases":             [],
                "subtotal_enrolled": 0,
                "subtotal_priority": 0,
            }
        section = staff["sections_by_name"][section_name]

        bonus_e = int(row["bonus_enrolled"] or 0)
        bonus_p = int(row["bonus_priority"] or 0)

        # Refer-source: pick the first populated field in the bao cao's
        # natural preference order (sub-agent → partner → free-text).
        refer_source = (
            row.get("referring_sub_agent_name")
            or row.get("referring_partner_name")
            or row.get("referring_agent_text_raw")
            or ""
        )

        # In-system vs out-system display
        rst = row.get("referring_source_type") or ""
        system_type = "Ngoài hệ thống" if rst == "OUT_SYSTEM" else "Trong hệ thống"

        case_payload = {
            "case_id":             row["case_id"],
            "contract_id":         row["contract_id"],
            "student_name":        row["student_name"],
            "student_id":          row["student_id"],
            "signed_date":         row["contract_signed_date"].isoformat() if row["contract_signed_date"] else None,
            "client_type":         row["client_type_code"],
            "country":             row["country_name"],
            "refer_source":        refer_source,
            "system_type":         system_type,
            "application_status":  row["application_status"],
            "visa_date":           row["visa_received_date"].isoformat() if row["visa_received_date"] else None,
            "institution":         row["institution_name"],
            "course_start":        row["course_start_date"].isoformat() if row["course_start_date"] else None,
            "course_status":       row["course_status"],
            "counsellor":          row["counsellor_name"],
            "co":                  row["case_officer_name"],
            "notes":               row["notes"],
            "slot_role":           row["slot_role"],
            "bonus_enrolled":      bonus_e,
            "note_bonus_enrolled": _enrolled_note(
                row["application_status"], bonus_e,
                row["tier_for_period"], row["target_for_period"],
                row["actual_for_period"], year, month,
            ),
            "bonus_priority":      bonus_p,
            "note_bonus_priority": _priority_note(row["institution_name"], bonus_p),
        }

        section["cases"].append(case_payload)
        section["subtotal_enrolled"] += bonus_e
        section["subtotal_priority"] += bonus_p
        staff["total_enrolled"]      += bonus_e
        staff["total_priority"]      += bonus_p

    # --- 3. Materialise final structure ----------------------------------
    staff_reports = []
    for staff in by_staff.values():
        sections = sorted(
            staff["sections_by_name"].values(),
            key=lambda s: _section_sort_key(s["section_name"]),
        )
        for section in sections:
            for idx, case in enumerate(section["cases"], start=1):
                case["no"] = idx
        staff_reports.append({
            "staff_id":       staff["staff_id"],
            "staff_name":     staff["staff_name"],
            "role_code":      staff["role_code"],
            "office_code":    staff["office_code"],
            "sections":       sections,
            "total_enrolled": staff["total_enrolled"],
            "total_priority": staff["total_priority"],
            "grand_total":    staff["total_enrolled"] + staff["total_priority"],
        })

    staff_reports.sort(key=lambda r: ((r["staff_name"] or "").lower(), r["staff_id"]))

    return {
        "year":          year,
        "month":         month,
        "staff_reports": staff_reports,
    }



# ===========================================================================
# User layout variants — per-(acting_as, page_key) saved column layouts
# (Phase 17a)
# ===========================================================================
#
# Layout state for the /import/review case table is saved under a row in
# `user_layout`. The acting_as key is emitted by lib/role.ts:
#
#   'admin' | 'persona:director' | 'persona:manager' | 'persona:quality_officer'
#         | 'persona:finance_officer' | 'staff:<id>'
#
# The frontend treats one variant per (acting_as, page_key) as "default" and
# loads it automatically on mount. is_default is enforced unique by a partial
# index on the table.

_USER_LAYOUT_COLS = (
    "id, acting_as, page_key, variant_name, is_default, "
    "layout_json, created_at, updated_at"
)


@app.get("/api/user_layout", dependencies=[Depends(get_current_user)])
def list_user_layouts(
    acting_as: str = Query(..., min_length=1, max_length=64,
                           description="e.g. 'admin', 'persona:director', 'staff:42'"),
    page_key: str = Query(..., min_length=1, max_length=64,
                          description="e.g. 'import_review'"),
) -> dict:
    """List all variants for one (acting_as, page_key). Default first, then alpha."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT {_USER_LAYOUT_COLS}
                FROM user_layout
                WHERE acting_as = %(acting_as)s
                  AND page_key  = %(page_key)s
                ORDER BY is_default DESC, variant_name ASC
            """, {"acting_as": acting_as, "page_key": page_key})
            return {"items": [dict(r) for r in cur.fetchall()]}


@app.get("/api/user_layout/{layout_id}", dependencies=[Depends(get_current_user)])
def get_user_layout(layout_id: int = PathParam(..., ge=1)) -> dict:
    """Return one variant by id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT {_USER_LAYOUT_COLS}
                FROM user_layout
                WHERE id = %(id)s
            """, {"id": layout_id})
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Layout {layout_id} not found.",
                )
            return dict(row)


@app.post("/api/user_layout", dependencies=[Depends(get_current_user)])
def create_user_layout(body: dict[str, Any] = Body(...)) -> dict:
    """
    Create a new variant.

    Body: {acting_as, page_key, variant_name, is_default?, layout_json}.
    is_default defaults to false. If true, any existing default for the same
    (acting_as, page_key) is cleared first so the partial-unique-index is
    satisfied.
    """
    for required in ("acting_as", "page_key", "variant_name"):
        if not body.get(required) or not isinstance(body[required], str):
            raise HTTPException(
                status_code=400,
                detail=f"Missing required string field: {required}",
            )

    is_default = bool(body.get("is_default", False))
    layout_json = body.get("layout_json", {})
    if not isinstance(layout_json, dict):
        raise HTTPException(status_code=400, detail="layout_json must be a JSON object.")

    params = {
        "acting_as":    body["acting_as"],
        "page_key":     body["page_key"],
        "variant_name": body["variant_name"],
        "is_default":   is_default,
        "layout_json":  json.dumps(layout_json),
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            if is_default:
                cur.execute("""
                    UPDATE user_layout SET is_default = false
                    WHERE acting_as = %(acting_as)s
                      AND page_key  = %(page_key)s
                      AND is_default = true
                """, params)

            try:
                cur.execute(f"""
                    INSERT INTO user_layout
                      (acting_as, page_key, variant_name, is_default, layout_json)
                    VALUES
                      (%(acting_as)s, %(page_key)s, %(variant_name)s,
                       %(is_default)s, %(layout_json)s::jsonb)
                    RETURNING {_USER_LAYOUT_COLS}
                """, params)
            except Exception as exc:
                conn.rollback()
                msg = str(exc)
                if "uq_user_layout_triple" in msg or "duplicate key" in msg.lower():
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"A variant named {body['variant_name']!r} already "
                            f"exists for this role + page."
                        ),
                    )
                raise HTTPException(status_code=400, detail=f"Create failed: {msg}")

            row = cur.fetchone()
            conn.commit()
            return dict(row)


@app.patch("/api/user_layout/{layout_id}", dependencies=[Depends(get_current_user)])
def update_user_layout(
    layout_id: int = PathParam(..., ge=1),
    body: dict[str, Any] = Body(...),
) -> dict:
    """
    Update variant_name, is_default, and/or layout_json on an existing row.

    Switching a row to is_default=true clears any other default on the same
    (acting_as, page_key) pair first.
    """
    allowed = {"variant_name", "is_default", "layout_json"}
    rejected = [k for k in body if k not in allowed]
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Field(s) not editable: {rejected}. Allowed: {sorted(allowed)}",
        )
    if not body:
        raise HTTPException(status_code=400, detail="Empty update body.")

    if "layout_json" in body and not isinstance(body["layout_json"], dict):
        raise HTTPException(status_code=400, detail="layout_json must be a JSON object.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Find the row so we know its (acting_as, page_key) for the
            # default-clearing logic.
            cur.execute("""
                SELECT acting_as, page_key FROM user_layout WHERE id = %(id)s
            """, {"id": layout_id})
            existing = cur.fetchone()
            if existing is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Layout {layout_id} not found.",
                )

            if body.get("is_default") is True:
                cur.execute("""
                    UPDATE user_layout SET is_default = false
                    WHERE acting_as = %(acting_as)s
                      AND page_key  = %(page_key)s
                      AND id        <> %(id)s
                      AND is_default = true
                """, {**existing, "id": layout_id})

            set_parts: list[str] = []
            params: dict[str, Any] = {"id": layout_id}
            if "variant_name" in body:
                set_parts.append("variant_name = %(variant_name)s")
                params["variant_name"] = body["variant_name"]
            if "is_default" in body:
                set_parts.append("is_default = %(is_default)s")
                params["is_default"] = bool(body["is_default"])
            if "layout_json" in body:
                set_parts.append("layout_json = %(layout_json)s::jsonb")
                params["layout_json"] = json.dumps(body["layout_json"])

            sql = f"""
                UPDATE user_layout
                SET {', '.join(set_parts)},
                    updated_at = NOW()
                WHERE id = %(id)s
                RETURNING {_USER_LAYOUT_COLS}
            """

            try:
                cur.execute(sql, params)
            except Exception as exc:
                conn.rollback()
                msg = str(exc)
                if "uq_user_layout_triple" in msg or "duplicate key" in msg.lower():
                    raise HTTPException(
                        status_code=409,
                        detail="A variant with that name already exists for this role + page.",
                    )
                raise HTTPException(status_code=400, detail=f"Update failed: {msg}")

            row = cur.fetchone()
            conn.commit()
            return dict(row)


@app.delete("/api/user_layout/{layout_id}", dependencies=[Depends(get_current_user)])
def delete_user_layout(layout_id: int = PathParam(..., ge=1)) -> dict:
    """Delete one variant. Returns {'deleted_id': N}."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM user_layout WHERE id = %(id)s RETURNING id
            """, {"id": layout_id})
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Layout {layout_id} not found.",
                )
            conn.commit()
            return {"deleted_id": layout_id}


# ===========================================================================
# Pillar counts — drives the 4-pillar home page tiles (Phase 15)
# ===========================================================================

@app.get("/api/pillars/counts", dependencies=[Depends(get_current_user)])
def pillar_counts(
    # Case Workload filter bar — same params as /api/cases. Counts per
    # pillar reflect whatever filter the user has applied on the home page
    # so that drilling into a pillar shows exactly that many cases.
    staff_id: Optional[int] = Query(None),
    signed_from: Optional[str] = Query(None),
    signed_to:   Optional[str] = Query(None),
    course_from: Optional[str] = Query(None),
    course_to:   Optional[str] = Query(None),
    visa_from:   Optional[str] = Query(None),
    visa_to:     Optional[str] = Query(None),
    bonus_month: Optional[str] = Query(None),
    q_student:   Optional[str] = Query(None),
    q_contract:  Optional[str] = Query(None),
    app_status:  Optional[str] = Query(None),
    client_type: Optional[str] = Query(None),
    institution_id: Optional[int] = Query(None),
    office_id:      Optional[int] = Query(None),
) -> dict[str, int]:
    """Per-workflow_state case counts for the 4-pillar home page,
    narrowed by the Case Workload filter bar.

    Response:
        { "uploaded": N, "in_review": N, "submitted": N, "closed": N, "total": N }

    Missing states return as 0 so the frontend can read every key.
    """
    # Compose filter clauses using the shared helper
    extra_where, extra_params = _build_case_filters(
        staff_id=staff_id,
        signed_from=signed_from, signed_to=signed_to,
        course_from=course_from, course_to=course_to,
        visa_from=visa_from,     visa_to=visa_to,
        bonus_month=bonus_month,
        q_student=q_student, q_contract=q_contract,
        app_status=app_status, client_type=client_type,
        institution_id=institution_id, office_id=office_id,
    )
    where_sql = (" WHERE " + " AND ".join(extra_where)) if extra_where else ""

    sql = f"""
        SELECT c.workflow_state, COUNT(*) AS n
          FROM tx_case c
          {where_sql}
         GROUP BY c.workflow_state
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, extra_params)
                rows = cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB error: {e}")

    counts = {"uploaded": 0, "in_review": 0, "submitted": 0, "closed": 0}
    for row in rows:
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


@app.get("/api/pillars/{state}/cases", dependencies=[Depends(get_current_user)])
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


# ===========================================================================
# Bonus reversal — Phase 13b/c
# ===========================================================================

@app.get("/api/bonus/reverse/authorised-keys", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
def list_reversal_authorised_keys() -> dict:
    """
    Acting-as keys allowed to reverse bonus runs.

    Returns the active rows from ref_amendment_authorised_persona, used by
    the frontend to enable/disable the Reverse button based on the current
    "Acting as" persona selection in role.ts.

    Response:
        {
          "authorised_keys": [
            {"acting_as_key": "admin", "display_name": "..."},
            {"acting_as_key": "persona:director", "display_name": "..."},
            ...
          ]
        }
    """
    sql = """
        SELECT acting_as_key, display_name
          FROM ref_amendment_authorised_persona
         WHERE active = true
         ORDER BY display_name
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
    return {"authorised_keys": rows}


@app.get("/api/bonus/reverse/reasons", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
def list_reversal_reasons() -> dict:
    """
    User-selectable reversal reason codes for the Reverse modal dropdown.

    Excludes the system-only CASCADE_FROM_PRIORITY_IMPACT code, which the
    cascade orchestrator applies automatically to downstream-affected staff
    and is never user-selected. Only active rows are returned.

    Response:
        {
          "reasons": [
            {"code": "DATA_ERROR", "display_name": "...", "notes": "..."},
            ...
          ]
        }
    """
    sql = """
        SELECT code, display_name, notes
          FROM ref_reversal_reason
         WHERE active = true
           AND code <> 'CASCADE_FROM_PRIORITY_IMPACT'
         ORDER BY display_order, display_name
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
    return {"reasons": rows}


@app.post("/api/bonus/reverse-only", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
def reverse_only(body: dict = Body(default_factory=dict)) -> dict:
    """
    Phase 13e — Reverse a staff's bonus payments for one period AND move
    the affected cases back to workflow_state 'submitted' so they can be
    edited and re-closed. Does NOT re-run the engine.

    This is the standard reversal flow: Finance flags a disagreement →
    cases go back to QM/Case Officer for review → after corrections, cases
    re-close → bonus engine runs again (via /api/engine/run).

    Request body (JSON):
        {
          "year": 2024,
          "month": 1,
          "trigger_staff_id": 9,
          "reversed_by_acting_as": "persona:finance_officer",
          "reason_code": "DISAGREEMENT",
          "notes": "Spot-check on partner X bonus tier"  // optional
        }

    Response:
        {
          "year": int, "month": int,
          "trigger_staff_id": int,
          "reversal_id": int,
          "payment_count": int,
          "total_reversed_amount": int,
          "cases_unlocked": int,
        }

    Errors:
        400 — bad year/month/staff_id/acting_as_key/reason_code/notes
        403 — acting_as_key not in ref_amendment_authorised_persona
        409 — amendment window expired OR no live payments to reverse
        500 — engine raised mid-operation (DB rolled back)
    """
    year = body.get("year")
    month = body.get("month")
    trigger_staff_id = body.get("trigger_staff_id")
    reversed_by_acting_as = body.get("reversed_by_acting_as")
    reason_code = body.get("reason_code")
    notes = body.get("notes")

    # Basic type/range validation — matches /api/engine/run style
    if not isinstance(year, int) or not isinstance(month, int):
        raise HTTPException(400, "year and month must be integers")
    if not (2020 <= year <= 2099):
        raise HTTPException(400, "year out of range (2020–2099)")
    if not (1 <= month <= 12):
        raise HTTPException(400, "month must be 1–12")
    if not isinstance(trigger_staff_id, int) or trigger_staff_id < 1:
        raise HTTPException(400, "trigger_staff_id must be a positive integer")
    if not isinstance(reversed_by_acting_as, str) or not reversed_by_acting_as.strip():
        raise HTTPException(400, "reversed_by_acting_as must be a non-empty string")
    if not isinstance(reason_code, str) or not reason_code.strip():
        raise HTTPException(400, "reason_code must be a non-empty string")
    if notes is not None and not isinstance(notes, str):
        raise HTTPException(400, "notes must be a string or null")

    # Authorisation gate — guard BEFORE DB writes
    auth_sql = """
        SELECT 1
          FROM ref_amendment_authorised_persona
         WHERE acting_as_key = %s
           AND active = true
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(auth_sql, (reversed_by_acting_as,))
            if cur.fetchone() is None:
                raise HTTPException(
                    403,
                    f"acting-as key '{reversed_by_acting_as}' is not authorised "
                    f"to reverse bonus runs",
                )

    # Reason code validation
    if reason_code == "CASCADE_FROM_PRIORITY_IMPACT":
        raise HTTPException(
            400,
            "reason_code 'CASCADE_FROM_PRIORITY_IMPACT' is reserved for the "
            "cascade orchestrator and cannot be used as a user-selected reason",
        )
    reason_check_sql = """
        SELECT 1
          FROM ref_reversal_reason
         WHERE code = %s
           AND active = true
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(reason_check_sql, (reason_code,))
            if cur.fetchone() is None:
                raise HTTPException(
                    400,
                    f"unknown reason_code '{reason_code}' "
                    f"(see GET /api/bonus/reverse/reasons for valid codes)",
                )

    try:
        return reverse_only_api(
            year=year,
            month=month,
            trigger_staff_id=trigger_staff_id,
            reversed_by_acting_as=reversed_by_acting_as,
            reason_code=reason_code,
            notes=notes,
        )
    except AmendmentWindowExpiredError as exc:
        raise HTTPException(409, str(exc))
    except NoLivePaymentsToReverseError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            500,
            f"Reverse-only failed: {type(exc).__name__}: {exc}",
        )


@app.post("/api/bonus/reverse-and-rerun-cascade", dependencies=[Depends(require_role(["DIRECTOR", "FO", "ADMIN"]))])
def reverse_and_rerun_cascade(body: dict = Body(default_factory=dict)) -> dict:
    """
    Reverse a staff's bonus payments for one period, re-run the engine for
    them, then cascade-reverse-and-rerun any OTHER staff whose live priority
    bonus payments are stale because the trigger staff's re-run changed the
    priority quota tracker state.

    Each cascade iteration handles one staff (reverse → re-run → check
    warnings → enqueue newly-affected). The whole cascade runs in a single
    DB transaction — if anything fails, all reversals and re-runs roll back.

    Request body (JSON):
        {
          "year": 2024,
          "month": 11,
          "trigger_staff_id": 9,
          "reversed_by_acting_as": "persona:finance_officer",
          "initial_reason_code": "DISAGREEMENT",
          "notes": "Finance challenged the partner X bonus",  // optional
          "max_iterations": 10                                 // optional
        }

    Response: full result dict from run_engine_cascade_api with reversals[],
    reruns[], final_warnings[], pending_unprocessed[], and cascade_complete.

    Errors:
        400 — bad year/month/staff_id/acting_as_key/reason_code/notes
        403 — acting_as_key not in ref_amendment_authorised_persona
        409 — amendment window expired OR no live payments to reverse
        500 — engine raised mid-cascade (DB rolled back)
    """
    year = body.get("year")
    month = body.get("month")
    trigger_staff_id = body.get("trigger_staff_id")
    reversed_by_acting_as = body.get("reversed_by_acting_as")
    initial_reason_code = body.get("initial_reason_code")
    notes = body.get("notes")
    max_iterations = body.get("max_iterations", 10)

    # Basic type/range validation — match style of /api/engine/run
    if not isinstance(year, int) or not isinstance(month, int):
        raise HTTPException(400, "year and month must be integers")
    if not (2020 <= year <= 2099):
        raise HTTPException(400, "year out of range (2020–2099)")
    if not (1 <= month <= 12):
        raise HTTPException(400, "month must be 1–12")
    if not isinstance(trigger_staff_id, int) or trigger_staff_id < 1:
        raise HTTPException(400, "trigger_staff_id must be a positive integer")
    if not isinstance(reversed_by_acting_as, str) or not reversed_by_acting_as.strip():
        raise HTTPException(400, "reversed_by_acting_as must be a non-empty string")
    if not isinstance(initial_reason_code, str) or not initial_reason_code.strip():
        raise HTTPException(400, "initial_reason_code must be a non-empty string")
    if notes is not None and not isinstance(notes, str):
        raise HTTPException(400, "notes must be a string or null")
    if not isinstance(max_iterations, int) or max_iterations < 1 or max_iterations > 50:
        raise HTTPException(400, "max_iterations must be an integer between 1 and 50")

    # Authorisation gate — guard BEFORE doing any DB writes.
    # 403 (not 400) because the request is well-formed but the actor is
    # not permitted. 401 would imply auth was missing entirely.
    # active=true filter prevents soft-deactivated personas from passing.
    auth_sql = """
        SELECT 1
          FROM ref_amendment_authorised_persona
         WHERE acting_as_key = %s
           AND active = true
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(auth_sql, (reversed_by_acting_as,))
            if cur.fetchone() is None:
                raise HTTPException(
                    403,
                    f"acting-as key '{reversed_by_acting_as}' is not authorised "
                    f"to reverse bonus runs",
                )

    # Reason-code sanity check — verify against ref_reversal_reason. This
    # catches typos/stale frontend dropdowns BEFORE the cascade starts.
    # CASCADE_FROM_PRIORITY_IMPACT is rejected here because it's
    # system-only — users shouldn't be able to spoof it as an initial reason.
    if initial_reason_code == "CASCADE_FROM_PRIORITY_IMPACT":
        raise HTTPException(
            400,
            "initial_reason_code 'CASCADE_FROM_PRIORITY_IMPACT' is reserved "
            "for the cascade orchestrator and cannot be used as an initial reason",
        )
    reason_check_sql = """
        SELECT 1
          FROM ref_reversal_reason
         WHERE code = %s
           AND active = true
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(reason_check_sql, (initial_reason_code,))
            if cur.fetchone() is None:
                raise HTTPException(
                    400,
                    f"unknown initial_reason_code '{initial_reason_code}' "
                    f"(see GET /api/bonus/reverse/reasons for valid codes)",
                )

    try:
        return run_engine_cascade_api(
            year=year,
            month=month,
            trigger_staff_id=trigger_staff_id,
            reversed_by_acting_as=reversed_by_acting_as,
            initial_reason_code=initial_reason_code,
            notes=notes,
            max_iterations=max_iterations,
        )
    except AmendmentWindowExpiredError as exc:
        raise HTTPException(409, str(exc))
    except NoLivePaymentsToReverseError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        # Print full traceback to stderr so Railway Deploy Logs capture it.
        # Without this, FastAPI's HTTPException swallows the original
        # exception and we lose the file/line info.
        traceback.print_exc()
        raise HTTPException(
            500,
            f"Cascade reverse-and-rerun failed: {type(exc).__name__}: {exc}",
        )


# Note: The duplicate inline @app.post("/api/imports") that previously lived
# at the bottom of this file has been removed. The router-based version in
# backend.api.imports now solely handles uploads, with multi-file support
# and persistent storage to the Railway volume.
