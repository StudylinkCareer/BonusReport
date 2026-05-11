"""
backend/api/pillars.py

Endpoints powering the 4-pillar home page.

GET /api/pillars/counts
    Returns { uploaded, in_review, submitted, closed, total } — the per-state
    case counts for the home page tiles. Single SQL roundtrip.

This module deliberately mirrors the pattern used by backend.api.imports
(FastAPI router + dependency on get_connection). If your FastAPI app uses
a different DB-access pattern, adjust the get_connection import and the
cursor open below.
"""

from fastapi import APIRouter, HTTPException

from backend.data.connection import get_connection


router = APIRouter(prefix="/api/pillars", tags=["pillars"])


@router.get("/counts")
def pillar_counts() -> dict[str, int]:
    """Return the per-workflow_state counts for the 4-pillar home page.

    Response shape:
        {
            "uploaded":   123,
            "in_review":  456,
            "submitted":   78,
            "closed":      90,
            "total":      747
        }

    Missing states (none in DB) are returned as 0 so the frontend can
    blindly read every key without null-handling.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT workflow_state, COUNT(*) AS n
                      FROM tx_case
                     GROUP BY workflow_state
                    """
                )
                rows = cursor.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc!r}") from exc

    counts = {
        "uploaded": 0,
        "in_review": 0,
        "submitted": 0,
        "closed": 0,
    }
    for row in rows:
        # Support both dict-row cursors (RealDictCursor) and tuple cursors.
        if isinstance(row, dict):
            state = row["workflow_state"]
            n = row["n"]
        else:
            state, n = row[0], row[1]
        if state in counts:
            counts[state] = int(n)

    counts["total"] = sum(counts.values())
    return counts
