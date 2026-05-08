"""
StudyLink BonusReport API.

Endpoints live under /api/* to match the Netlify proxy redirect.
"""
from fastapi import FastAPI, HTTPException

from data.connection import get_connection


app = FastAPI(title="BonusReport API")


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