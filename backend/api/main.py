"""
backend/api/main.py

StudyLink BonusReport HTTP API — FastAPI scaffold.

Local run:
    uvicorn backend.api.main:app --reload --port 8000

Endpoints:
    GET /health
    GET /staff
    GET /payments?staff_id=X&year=Y&month=M
    GET /api/pillars/counts          (Phase 15: 4-pillar home page)
    GET /docs                        — auto Swagger UI
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.data.connection import get_connection


app = FastAPI(
    title="StudyLink BonusReport API",
    version="0.1.0",
    description="HTTP API exposing engine output for the front-end.",
)

# CORS — allow Next dev server (localhost:3000) and Vite (localhost:5173).
# Add the Netlify deploy URL here once known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://bonusreport.netlify.app",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Liveness check + DB connectivity."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB unreachable: {e}")
    return {"status": "ok", "db": "ok", "version": app.version}


# ---------------------------------------------------------------------------
# Staff list
# ---------------------------------------------------------------------------

@app.get("/staff")
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
# Payments — bao-cao-style view for one staff/month
# ---------------------------------------------------------------------------

@app.get("/payments")
def get_payments(
    staff_id: int = Query(..., description="ref_staff.id"),
    year:     int = Query(..., ge=2020, le=2030),
    month:    int = Query(..., ge=1, le=12),
) -> dict:
    """
    Bonus payments for one staff member in one (year, month).

    Joins tx_bonus_payment to tx_case + ref_institution + dim_country +
    ref_staff + dim_role for ready-to-render rows.
    """
    sql = """
        SELECT
            bp.id                       AS payment_id,
            bp.case_id,
            c.contract_id,
            c.student_name,
            c.application_status,
            inst.canonical_name         AS institution_name,
            cn.name                     AS country_name,
            bp.slot,
            bp.tier,
            bp.target,
            bp.actual_enrolled,
            bp.base_rate,
            bp.split_pct,
            bp.tier_bonus,
            bp.priority_bonus,
            bp.package_bonus,
            bp.addon_bonus,
            bp.gross_bonus,
            bp.priority_withheld_amount,
            bp.priority_unlocked_amount,
            bp.priority_schedule_type,
            bp.advance_offset,
            bp.mgmt_override_amount,
            bp.net_payable,
            bp.calc_notes,
            stf.canonical_name          AS staff_name,
            rl.code                     AS role_code
        FROM tx_bonus_payment   bp
        JOIN tx_case            c   ON bp.case_id        = c.id
        LEFT JOIN ref_institution inst ON c.institution_id = inst.id
        LEFT JOIN dim_country     cn  ON c.country_id     = cn.id
        JOIN ref_staff          stf ON bp.staff_id       = stf.id
        JOIN dim_role           rl  ON bp.role_id        = rl.id
        WHERE bp.staff_id  = %s
          AND bp.run_year  = %s
          AND bp.run_month = %s
        ORDER BY c.contract_id, bp.slot
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (staff_id, year, month))
            rows = [dict(row) for row in cur.fetchall()]

    return {
        "staff_id": staff_id,
        "year":     year,
        "month":    month,
        "payments": rows,
        "totals": {
            "gross": sum((r.get("gross_bonus")  or 0) for r in rows),
            "net":   sum((r.get("net_payable") or 0) for r in rows),
        },
    }


# ---------------------------------------------------------------------------
# Pillar counts — drives the 4-pillar home page tiles (Phase 15)
# ---------------------------------------------------------------------------

@app.get("/api/pillars/counts")
def pillar_counts() -> dict[str, int]:
    """Return per-workflow_state case counts for the 4-pillar home page.

    Response shape:
        {
            "uploaded":   123,
            "in_review":  456,
            "submitted":   78,
            "closed":      90,
            "total":      747
        }

    Missing states return as 0 so the frontend can blindly read every key
    without null-handling.
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
        # Support dict-row cursors (RealDictCursor) or tuple cursors
        if isinstance(row, dict):
            state, n = row["workflow_state"], row["n"]
        else:
            state, n = row[0], row[1]
        if state in counts:
            counts[state] = int(n)

    counts["total"] = sum(counts.values())
    return counts
