"""
TRANSFORMER PATCH FOR PHASE 14C — PACKAGE RESOLUTION

Four edits to backend/importer/transformer.py:

  EDIT 1: Add resolve_package_fee_by_alias to imports from resolvers
  EDIT 2: Add `package_fee_id` field to CaseRecord dataclass
  EDIT 3: Add `_resolve_package_from_notes()` helper (copy from below)
  EDIT 4: Call it in transform_row() and pass into CaseRecord(...)

NAMING: The DB column is tx_case.package_fee_id. CaseRecord field
name matches the DB column. The engine's CaseInput field is
.package_service_fee_id — that mapping happens at the engine's load
step (tx_case.package_fee_id → CaseInput.package_service_fee_id),
which is outside the importer's concern.
"""

# ============================================================================
# EDIT 1 — IMPORTS
# ============================================================================
# In transformer.py, modify the resolvers import block to include the new
# resolver function:
#
#   from backend.importer.resolvers import (
#       resolve_country,
#       resolve_institution,
#       resolve_office,
#       resolve_package_fee_by_alias,    # NEW (Phase 14c)
#       resolve_partner,
#       resolve_staff,
#       resolve_staff_employment,
#       resolve_staff_role,
#       resolve_status,
#       resolve_sub_agent,
#   )


# ============================================================================
# EDIT 2 — CaseRecord field
# ============================================================================
# In the CaseRecord dataclass (around line 147), add ONE new field right
# after client_type_code (line 167). Use Optional[int] to match the style
# of other resolvable FK fields:
#
#     client_type_code: Optional[str]
#     package_fee_id: Optional[int]     # NEW (Phase 14c) — resolved from Notes column
#     application_status: Optional[str]
#     ...


# ============================================================================
# EDIT 3 — Resolver helper (copy this into transformer.py)
# ============================================================================
# Place between _resolve_application_status() and transform_row().
# Needs `import re` and `import unicodedata` at top of file (add if absent).

import re
import unicodedata
from typing import Optional


def _resolve_package_from_notes(
    cursor,
    notes_text: Optional[str],
) -> tuple[Optional[int], Optional[str]]:
    """Extract a package fee id from the Notes free-text column.

    Package text typically appears on the first line of Notes, sometimes
    embedded in a longer free-text comment. The resolver tries three
    matching strategies, narrowest-to-broadest:

      1. NFC-normalised lowercased exact match of a whole line.
      2. Same after stripping parenthesised commentary (e.g.,
         'Standard Package 16tr (6tr lần 1)' → 'standard package 16tr').
      3. Substring search using aliases of length >= 7 chars
         (avoids matches on short ambiguous shorthands).

    All matching goes through ref_service_fee_alias, which the
    14c migration populated with both bracketed and non-bracketed
    forms observed in real source data.

    Returns:
        (package_fee_id, warning_or_None)

    The warning is non-None only when notes text exists but no package
    could be resolved AND the text looks like it might be a package
    mention (contains 'package', 'goi', 'gói', 'sds', 'standard plus',
    'superior', 'premium'). Otherwise silent.
    """
    if not notes_text:
        return None, None

    PARTIAL_MIN_LEN = 7

    def _nfc_lower(s: str) -> str:
        return unicodedata.normalize('NFC', s).lower().strip()

    text = str(notes_text)
    normalised_full = _nfc_lower(text)

    # Strategy 1 & 2: per-line exact and no-parens matching
    for line in text.split('\n'):
        nfc = _nfc_lower(line)
        if not nfc:
            continue

        pkg_id = resolve_package_fee_by_alias(cursor, nfc)
        if pkg_id is not None:
            return pkg_id, None

        no_parens = re.sub(r'\([^)]*\)', '', nfc).strip()
        if no_parens and no_parens != nfc:
            pkg_id = resolve_package_fee_by_alias(cursor, no_parens)
            if pkg_id is not None:
                return pkg_id, None

    # Strategy 3: substring search across the whole text
    pkg_id = resolve_package_fee_by_alias(
        cursor, normalised_full, partial_min_len=PARTIAL_MIN_LEN
    )
    if pkg_id is not None:
        return pkg_id, None

    # Nothing matched. Only emit a warning if text looks like a package mention.
    looks_like_package = any(
        marker in normalised_full
        for marker in ('package', 'goi ', 'gói ', 'sds', 'standard plus',
                       'superior', 'premium')
    )
    if looks_like_package:
        warning = (
            f"UNRESOLVED_PACKAGE: Notes text looks like a package mention "
            f"but no alias matched. First 80 chars: {text[:80]!r}"
        )
        return None, warning

    return None, None


# ============================================================================
# EDIT 4 — Call from transform_row()
# ============================================================================
# In transform_row(), AFTER the application_status block (around line 729),
# BEFORE "# ---- Build the record ----", add:
#
#     # ---- Package resolution (Phase 14c) ----
#     notes_text_for_package = _string_or_none(data.get(COL_NOTES))
#     package_fee_id, package_warning = _resolve_package_from_notes(
#         cursor, notes_text_for_package
#     )
#     if package_warning:
#         flags.add(package_warning, STATUS_UNRESOLVED)
#
# Then in the CaseRecord(...) constructor (around line 747), add the field
# right after client_type_code:
#
#         client_type_code=_string_or_none(data.get(COL_CLIENT_TYPE)),
#         package_fee_id=package_fee_id,        # NEW (Phase 14c)
#         application_status=application_status_text,
#         ...


# ============================================================================
# WRITER NOTE
# ============================================================================
# Whatever code persists CaseRecord -> tx_case needs to include the
# package_fee_id column in its INSERT/UPDATE statement. If the writer
# uses a column-list from dataclasses.fields(CaseRecord), automatic.
# If hardcoded, add it manually.
#
# The engine's CaseInput uses field name `package_service_fee_id`. That
# mapping (tx_case.package_fee_id → CaseInput.package_service_fee_id)
# happens at the engine's load step in cli.py / api_runner.py, outside
# the importer's scope.
