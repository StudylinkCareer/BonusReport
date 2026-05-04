-- =============================================================================
-- Phase 6h — Status alias table and seeding
-- File:    Phase6h_status_aliases.sql
-- Purpose: Allow the importer to resolve CRM status strings (which include
--          punctuation/casing variants) to canonical ref_status_split rows.
--
-- Source: distinct_values_for_review.xlsx — "Application Report Status" tab.
--         Of 24 distinct values seen in CRM:
--           - 15 are date timestamps (SCRAP — handled at import time)
--           -  7 already match canonical ref_status_split.status exactly
--           -  2 are spelling variants of canonical statuses
--
-- Design: Add a new ref_status_split_alias table mirroring the alias
--         pattern used for institutions, partners, sub-agents, and staff.
--         Self-aliases for every existing status, plus the 2 variants.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Create the alias table.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ref_status_split_alias (
    id              BIGSERIAL PRIMARY KEY,
    status_id       BIGINT NOT NULL REFERENCES ref_status_split(id),
    alias           VARCHAR(64) NOT NULL UNIQUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE ref_status_split_alias IS
    'Alias mappings from raw CRM status text → canonical ref_status_split row. '
    'Importer uses this to resolve punctuation/casing variants.';


-- -----------------------------------------------------------------------------
-- 2. Self-aliases — every canonical status maps to itself.
-- -----------------------------------------------------------------------------
-- Each existing ref_status_split row gets an alias row matching the canonical
-- text. This lets the importer use a single alias-table lookup regardless of
-- whether the CRM string is canonical or a variant.

INSERT INTO ref_status_split_alias (status_id, alias, notes)
SELECT id, status, 'Phase 6h self-alias.'
FROM ref_status_split
ON CONFLICT (alias) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 3. Variant aliases for the two CRM-observed spelling differences.
-- -----------------------------------------------------------------------------

-- Variant 1: comma form → 'Closed - Visa granted then enrolled' (no comma)
INSERT INTO ref_status_split_alias (status_id, alias, notes)
SELECT id, 'Closed - Visa granted, then enrolled',
       'Phase 6h. Comma variant of canonical (no-comma form).'
FROM ref_status_split
WHERE status = 'Closed - Visa granted then enrolled'
ON CONFLICT (alias) DO NOTHING;

-- Variant 2: comma + cap C → 'Closed - Enrolled then cancelled' (no comma, lower c)
INSERT INTO ref_status_split_alias (status_id, alias, notes)
SELECT id, 'Closed - Enrolled, then Cancelled',
       'Phase 6h. Comma + capitalisation variant of canonical.'
FROM ref_status_split
WHERE status = 'Closed - Enrolled then cancelled'
ON CONFLICT (alias) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 4. Verification.
-- -----------------------------------------------------------------------------
-- Expected:
--   - ref_status_split:        19 statuses (unchanged)
--   - ref_status_split_alias:  19 self + 2 variant = 21 rows total

SELECT 'status_split_total' AS metric, count(*)::text AS value
FROM ref_status_split

UNION ALL

SELECT 'status_split_aliases_total', count(*)::text
FROM ref_status_split_alias

UNION ALL

SELECT 'phase6h_aliases_with_notes', count(*)::text
FROM ref_status_split_alias
WHERE notes LIKE 'Phase 6h%';

COMMIT;
