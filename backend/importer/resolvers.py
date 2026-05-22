"""
RESOLVERS ADDITION FOR PHASE 14C

Add this function to backend/importer/resolvers.py. It runs the
ref_service_fee_alias lookup that _resolve_package_from_notes() calls.

Two-mode interface:
  - With partial_min_len=None (default): exact alias_text_nfc match.
    Fast, used by the whole-line and no-parens strategies.
  - With partial_min_len=N: substring search where the alias is
    contained inside the input text. Slower, used by Strategy 3.

The DB does length filtering via WHERE length(alias_text_nfc) >= N
so the resolver doesn't have to load the whole alias table to Python.

Naming: ref_service_fee_alias targets ref_service_fee rows of any
category (PACKAGE, SERVICE_FEE, ADDON, CONTRACT). Currently used only
for PACKAGE rows in Phase 14c but the function name doesn't restrict.
"""

# Copy below into resolvers.py in the lookup-functions section.

def resolve_package_fee_by_alias(
    cursor,
    text: str,
    partial_min_len: int | None = None,
) -> int | None:
    """Resolve text to a ref_service_fee.id via ref_service_fee_alias.

    Args:
        cursor: psycopg cursor.
        text: NFC-normalised lowercased input text. Caller is responsible
            for normalisation; this function does no further cleaning.
        partial_min_len: If None, exact match on alias_text_nfc.
            If an int, substring search where the alias is contained
            within `text` AND the alias is at least N characters long.

    Returns:
        ref_service_fee.id of the matched canonical row, or None.
        When multiple aliases match (partial mode), the LONGEST alias
        wins — protects against 'standard' matching before
        'standard plus' would.
    """
    if not text:
        return None

    if partial_min_len is None:
        cursor.execute(
            """
            SELECT service_fee_id
            FROM ref_service_fee_alias
            WHERE alias_text_nfc = %s
            LIMIT 1
            """,
            (text,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    # Partial-match: alias is a substring of input text, length-filtered.
    # Longest-first wins.
    cursor.execute(
        """
        SELECT service_fee_id
        FROM ref_service_fee_alias
        WHERE length(alias_text_nfc) >= %s
          AND position(alias_text_nfc IN %s) > 0
        ORDER BY length(alias_text_nfc) DESC
        LIMIT 1
        """,
        (partial_min_len, text),
    )
    row = cursor.fetchone()
    return row[0] if row else None
