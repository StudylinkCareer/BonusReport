# ============================================================================
# Phase 16c — Client Type dropdown fix
# ============================================================================
#
# THE BUG:
#   REF_LIST_STATIC['client_types'] returned display-label strings like
#   "Du học (Ghi danh + visa)". The frontend SelectCell saved that string
#   straight into tx_case.client_type_code. The DB has a CHECK constraint
#   accepting only the 10 canonical codes (DU_HOC_FULL etc.), so every save
#   failed with chk_tx_case_client_type_code violation.
#
# THE FIX:
#   Replace the static list with a query against ref_client_type returning
#   {code, name} pairs. Frontend switches Client Type from SelectCell (string
#   in / string out) to CodeSelectCell (label shown / code saved).
#
# This file contains the BACKEND patch only. Frontend changes go to
# frontend/app/import/review/page.tsx separately.
#
# ----------------------------------------------------------------------------
# EDIT 1 — Add a new entry to REF_LIST_QUERIES (around line 1703-1742)
# ----------------------------------------------------------------------------
#
# Inside the REF_LIST_QUERIES dict, add this entry. Suggested placement: just
# after "statuses" since they're conceptually similar (both are ref tables
# with id/code/name). Order within the dict doesn't matter functionally.

# ADD THIS LINE inside REF_LIST_QUERIES:

    "client_types":
        "SELECT id, "
        "       code, "
        "       display_name_vi AS name "
        "  FROM ref_client_type "
        " WHERE (effective_to IS NULL OR effective_to >= CURRENT_DATE) "
        " ORDER BY display_name_vi",

# ----------------------------------------------------------------------------
# EDIT 2 — REMOVE the 'client_types' entry from REF_LIST_STATIC
# ----------------------------------------------------------------------------
#
# Inside REF_LIST_STATIC (around line 1743-1768), DELETE the entire
# "client_types": [ ... 65 hardcoded strings ... ] block, including the
# preceding comment block that explains the diacritic variants. That comment
# block is now stale: there ARE no diacritic variants, there are only the
# 10 canonical codes mapped to canonical display labels.

# DELETE this entire block (from REF_LIST_STATIC):
#
#     # Client type / service category. Union of original 24 + v6.2 template's
#     # 34 values (incl. diacritic variants and case differences), deduped.
#     # The diacritic variants ARE intentional — same business meaning, but the
#     # CRM has been recording them inconsistently and users need to be able to
#     # pick whichever spelling matches what the CRM has stored.
#     "client_types": [
#         "Credential Evaluation",
#         "Công tác nước ngoài",
#         ... (all 65 lines of strings) ...
#         "Điền đơn xin visa",
#     ],

# ----------------------------------------------------------------------------
# VERIFICATION
# ----------------------------------------------------------------------------
# After saving main.py and restarting the API:
#
#   curl http://localhost:8000/api/reference/client_types
#
# Should return:
#   {"name":"client_types","items":[
#     {"id":..., "code":"DEPENDANT_VISA",      "name":"Visa Phụ thuộc"},
#     {"id":..., "code":"DU_HOC_ENROL_ONLY",   "name":"Du học (Ghi danh)"},
#     {"id":..., "code":"DU_HOC_FULL",         "name":"Du học (Ghi danh + visa)"},
#     ... 7 more
#   ]}
#
# Display order matches Vietnamese alphabetical sort of display_name_vi.

# ----------------------------------------------------------------------------
# NOTE on the importer
# ----------------------------------------------------------------------------
# The importer (backend/importer/resolvers.py) resolves client_type from CRM
# Excel files. It maps fuzzy text matches to canonical codes via aliases.
# This patch does NOT change the importer — only the dropdown for manual
# review edits. Importer behavior is unaffected.
