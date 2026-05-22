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
    """Country text -> dim_country.id.

    Checks ref_country_alias first (catches CRM variants like 'USA', 'UK',
    typos like 'Switzeland'), then falls back to dim_country.name/code for
    direct matches. Mirrors resolve_office's alias-first pattern.
    """
    text = _normalize(raw)
    if not text:
        return None
    # Try alias table first
    cursor.execute(
        """SELECT country_id FROM ref_country_alias
           WHERE LOWER(alias) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["country_id"]
    # Fallback: direct name/code lookup on dim_country
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


# ---------------------------------------------------------------------------
# Phase 14c — Package fee alias resolution
# ---------------------------------------------------------------------------

def resolve_package_fee_by_alias(
    cursor,
    text: Optional[str],
    partial_min_len: Optional[int] = None,
) -> Optional[int]:
    """Resolve text to a ref_service_fee.id via ref_service_fee_alias.

    Two-mode interface:
      - partial_min_len=None (default): exact alias_text_nfc match.
        Fast — used by whole-line and no-parens matching strategies.
      - partial_min_len=N: substring search where the alias is contained
        inside `text` AND the alias is at least N chars long. Slower —
        used as a fallback strategy when the package name is embedded
        in longer free-text.

    Args:
        cursor: psycopg cursor (assumed dict_row factory).
        text:   NFC-normalised lowercased input. Caller is responsible
                for normalisation; this function does no further cleaning.
        partial_min_len: see above.

    Returns:
        ref_service_fee.id of the matched canonical row, or None.
        In partial mode the LONGEST alias wins — protects against
        'standard' matching before 'standard plus' would.

    Note: ref_service_fee_alias can target rows of any category
    (PACKAGE, SERVICE_FEE, ADDON, CONTRACT). The transformer's
    package-resolution helper enforces category context when needed.
    """
    if not text:
        return None

    if partial_min_len is None:
        cursor.execute(
            """SELECT service_fee_id
               FROM ref_service_fee_alias
               WHERE alias_text_nfc = %s
               LIMIT 1""",
            (text,),
        )
        row = cursor.fetchone()
        return row["service_fee_id"] if row else None

    # Partial-match: alias must be a substring of input text, length-filtered.
    # Longest-first wins.
    cursor.execute(
        """SELECT service_fee_id
           FROM ref_service_fee_alias
           WHERE length(alias_text_nfc) >= %s
             AND position(alias_text_nfc IN %s) > 0
           ORDER BY length(alias_text_nfc) DESC
           LIMIT 1""",
        (partial_min_len, text),
    )
    row = cursor.fetchone()
    return row["service_fee_id"] if row else None


def resolve_client_type(cursor, raw: Optional[str]) -> Optional[str]:
    """Client type text -> ref_client_type.code (the canonical string).

    Returns the canonical code (e.g. 'DU_HOC_FULL'), not the integer id —
    because tx_case.client_type_code stores the code string and has a
    CHECK constraint against the 10 valid codes:
      DU_HOC_FULL, DU_HOC_ENROL_ONLY, SUMMER_STUDY, VIETNAM_DOMESTIC,
      GUARDIAN_VISA, TOURIST_VISA, MIGRATION_VISA, DEPENDANT_VISA,
      VISA_ONLY_SERVICE, UNRESOLVED.

    Returns None if input is blank/missing. Caller distinguishes that
    from "text present but unresolved" (which should be stamped as
    'UNRESOLVED' on the record so the CHECK constraint accepts it and
    DQO can review).

    Alias-first lookup mirrors all other resolvers. Falls back to a
    direct code match (defensive — in case CRM ever sends the canonical
    code itself like 'DU_HOC_FULL').
    """
    text = _normalize(raw)
    if not text:
        return None
    cursor.execute(
        """SELECT ct.code
             FROM ref_client_type_alias a
             JOIN ref_client_type ct ON ct.id = a.client_type_id
            WHERE LOWER(a.alias_text) = LOWER(%s)""",
        (text,),
    )
    row = cursor.fetchone()
    if row:
        return row["code"]
    # Fallback: direct code match on ref_client_type
    cursor.execute(
        "SELECT code FROM ref_client_type WHERE code = %s",
        (text,),
    )
    row = cursor.fetchone()
    return row["code"] if row else None


# Note: lookup_partner_institution_links() was removed as part of
# Phase7prep_v2_extension. Partner derivation from institution is now an
# engine-runtime concern using ref_institution_agreement; the importer
# records only what's explicitly in the CRM Refer Source Agent column.
