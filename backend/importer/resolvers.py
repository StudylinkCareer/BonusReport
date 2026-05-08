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
    """Office text -> dim_office.id.

    Checks ref_office_alias first (catches CRM Refer Source Agent values
    like 'StudyLink (Văn phòng chi nhánh Hà Nội)' and personal-name
    variants like 'Hoang Le – VP Mel'), then falls back to dim_office
    name/code for short canonical lookups ('HCM', 'Hanoi', etc.).

    The alias-first order means an existing caller passing 'HCM' still
    works (no alias row matches → falls through to dim_office.code).
    """
    text = _normalize(raw)
    if not text:
        return None
    # Try alias table first
    cursor.execute(
        """SELECT office_id FROM ref_office_alias
           WHERE LOWER(alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["office_id"]
    # Fallback: direct name/code lookup on dim_office
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


# Note: lookup_partner_institution_links() was removed as part of
# Phase7prep_v2_extension. Partner derivation from institution is now an
# engine-runtime concern using ref_institution_agreement; the importer
# records only what's explicitly in the CRM Refer Source Agent column.
