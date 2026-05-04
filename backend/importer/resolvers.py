"""
backend/importer/resolvers.py

Single-purpose lookup functions: raw CRM text -> canonical bigint ID (or None).

Each resolver takes:
  - cursor: a psycopg cursor (caller manages the connection and transaction).
            Assumed to be configured with row_factory=dict_row (per
            backend/data/connection.py), so rows are accessed as dicts.
  - raw:    the string from a CRM cell, or None.

Returns:
  - The canonical ID, or None if the text is blank, missing, or unrecognised.

Design notes
------------
* Each entity resolver tries the alias table first, then falls back to the
  canonical-name column on the parent table. This makes the importer
  robust to incomplete seeding.
* All matches are case-insensitive and tolerate leading/trailing/internal
  whitespace variation.
* For institution and sub-agent, we follow merged_into_id so callers
  never see a deprecated record's ID.
* No exceptions are raised on misses. Returning None is the contract; the
  transformer will decide whether the miss is fatal, a warning, or expected.
"""

from datetime import date
from typing import Optional


def _normalize(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    cleaned = " ".join(str(s).split())
    return cleaned if cleaned else None


def resolve_country(cursor, raw: Optional[str]) -> Optional[int]:
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT id FROM dim_country
           WHERE LOWER(name) = LOWER(%s) OR LOWER(code) = LOWER(%s)""",
        (text, text),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def resolve_office(cursor, raw: Optional[str]) -> Optional[int]:
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT id FROM dim_office
           WHERE LOWER(name) = LOWER(%s) OR LOWER(code) = LOWER(%s)""",
        (text, text),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def resolve_sub_agent(cursor, raw: Optional[str]) -> Optional[int]:
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT sa.id, sa.merged_into_id
           FROM ref_sub_agent_alias a
           JOIN ref_sub_agent       sa ON sa.id = a.sub_agent_id
           WHERE LOWER(a.alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["merged_into_id"] or row["id"]
    cursor.execute(
        """SELECT id, merged_into_id FROM ref_sub_agent
           WHERE LOWER(canonical_name) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["merged_into_id"] or row["id"]
    return None


def resolve_partner(cursor, raw: Optional[str]) -> Optional[int]:
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT p.id
           FROM ref_partner_alias a
           JOIN ref_partner       p ON p.id = a.partner_id
           WHERE LOWER(a.alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["id"]
    cursor.execute(
        "SELECT id FROM ref_partner WHERE LOWER(name) = LOWER(%s)",
        (text,),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def resolve_institution(cursor, raw: Optional[str]) -> Optional[int]:
    """Institution text -> ref_institution.id.

    Caller MUST strip asterisk markers and partner-name suffix BEFORE
    calling — that parsing is transformer.py's job.
    """
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT i.id, i.merged_into_id
           FROM ref_institution_alias a
           JOIN ref_institution       i ON i.id = a.institution_id
           WHERE LOWER(a.alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["merged_into_id"] or row["id"]
    cursor.execute(
        """SELECT id, merged_into_id FROM ref_institution
           WHERE LOWER(canonical_name) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["merged_into_id"] or row["id"]
    return None


def resolve_staff(cursor, raw: Optional[str]) -> Optional[int]:
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT s.id
           FROM ref_staff_alias a
           JOIN ref_staff       s ON s.id = a.staff_id
           WHERE LOWER(a.alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["id"]
    cursor.execute(
        "SELECT id FROM ref_staff WHERE LOWER(canonical_name) = LOWER(%s)",
        (text,),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def resolve_status(cursor, raw: Optional[str]) -> Optional[int]:
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT s.id
           FROM ref_status_split_alias a
           JOIN ref_status_split       s ON s.id = a.status_id
           WHERE LOWER(a.alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def resolve_staff_role(cursor, staff_id: Optional[int]) -> Optional[int]:
    if staff_id is None:
        return None
    cursor.execute(
        "SELECT primary_role_id FROM ref_staff WHERE id = %s",
        (staff_id,),
    )
    row = cursor.fetchone()
    return row["primary_role_id"] if row else None


def resolve_staff_employment(cursor, staff_id: Optional[int]) -> Optional[str]:
    if staff_id is None:
        return None
    cursor.execute(
        "SELECT employment_status FROM ref_staff WHERE id = %s",
        (staff_id,),
    )
    row = cursor.fetchone()
    return row["employment_status"] if row else None


# ---------------------------------------------------------------------------
# Partner-institution junction helpers (Phase 6i / 6j)
# ---------------------------------------------------------------------------

def lookup_partner_institution_links(
    cursor,
    institution_id: Optional[int],
    case_date: Optional[date] = None,
) -> list[int]:
    """Return all partner_ids actively linked to this institution at case_date.

    The transformer uses this for two purposes:
      1. When the CRM institution name has a single-asterisk suffix
         (e.g. "X * - Navitas"), we resolve "Navitas" to a partner_id and
         then verify that link is among the active links for X at case_date.
      2. When the CRM has a bare asterisk (no suffix), we look up active
         links and use the unique one if exactly one exists.

    Args:
        institution_id: resolved institution canonical id, or None.
        case_date: the contract-signed date for the case. If None, returns
            currently-open links (effective_to IS NULL). If a date, returns
            links where effective_from <= case_date <= COALESCE(effective_to, infinity).

    Returns:
        List of partner_ids. Empty list if institution_id is None or no
        links exist.
    """
    if institution_id is None:
        return []

    if case_date is None:
        cursor.execute(
            """SELECT partner_id
               FROM ref_partner_institution
               WHERE institution_id = %s AND effective_to IS NULL""",
            (institution_id,),
        )
    else:
        cursor.execute(
            """SELECT partner_id
               FROM ref_partner_institution
               WHERE institution_id = %s
                 AND effective_from <= %s
                 AND (effective_to IS NULL OR effective_to >= %s)""",
            (institution_id, case_date, case_date),
        )

    return [row["partner_id"] for row in cursor.fetchall()]
