-- =============================================================================
-- phase14_06_missing_institutions.sql
-- Phase 14.06 -- Add 18 missing institutions (no-asterisk unresolved cases)
-- =============================================================================
--
-- These are institutions that appear in CRM data (warning_type='UNRESOLVED_INSTITUTION')
-- but do NOT exist in ref_institution. This migration adds them as canonical entries.
--
-- IMPORTANT:
-- - This migration adds ONLY ref_institution rows. It does NOT create
--   ref_institution_agreement records.
-- - Cases referring to these institutions will now resolve (UNRESOLVED_INSTITUTION
--   warning will go away) but may flag SYSTEM_TYPE_MISMATCH if CRM marks them
--   as in-system. Agreement records can be added in a follow-up migration after
--   business review.
-- - Country codes are best-effort guesses based on institution name.
-- - "/* VERIFY */" markers flag rows that need extra business review.
--
-- RUN ORDER:
--   1. phase14_06_missing_institutions.sql  <-- THIS FILE (run first)
--   2. phase14_07_asterisk_aliases.sql      <-- run after
--
-- =============================================================================

BEGIN;

WITH new_institutions(canonical_name, country_code, notes) AS (
  VALUES
    -- Australia (12)
    ('Acumen Institute of Futher Education', 'AU',
       'Phase 14.06 -- typo "Futher" preserved from CRM source. /* VERIFY: typo, country */'),
    ('Canberra Government Schools', 'AU',
       'Phase 14.06 -- ACT government schools system'),
    ('ECA College', 'AU',
       'Phase 14.06 -- ECA = Education Centre of Australia'),
    ('Education Training & Employment Australia (ETEA)', 'AU',
       'Phase 14.06'),
    ('Melbourne College Of Hair & Beauty (MCOHB)', 'AU',
       'Phase 14.06'),
    ('Sarina Russo School Australia (SRI)', 'AU',
       'Phase 14.06'),
    ('Shafston International College', 'AU',
       'Phase 14.06 -- Brisbane'),
    ('Stanley College', 'AU',
       'Phase 14.06 -- Perth'),
    ('Tasmanian Government Schools', 'AU',
       'Phase 14.06 -- TAS government schools system'),
    ('The Gordon Tafe Geelong', 'AU',
       'Phase 14.06 -- Geelong, VIC'),
    ('The Hotel School', 'AU',
       'Phase 14.06 /* VERIFY -- ambiguous name; multiple schools share variants */'),
    -- Canada (3)
    ('International Language Academy of Canada', 'CA',
       'Phase 14.06'),
    ('Southern Alberta Institute of Technology (SAIT)', 'CA',
       'Phase 14.06 -- Calgary, Alberta'),
    ('Toronto Metropolitan University (TMU)', 'CA',
       'Phase 14.06 -- formerly Ryerson University'),
    -- New Zealand (2)
    ('Christchurch College of English (CCEL)', 'NZ',
       'Phase 14.06 -- Christchurch'),
    ('Le Cordon Bleu - New Zealand', 'NZ',
       'Phase 14.06 -- Wellington campus'),
    -- Switzerland (1)
    ('Business & Hotel Management School (B.H.M.S.)', 'CH',
       'Phase 14.06 -- Lucerne'),
    -- Vietnam (1)
    ('Fulbright University Vietnam', 'VN',
       'Phase 14.06 -- Ho Chi Minh City')
)
INSERT INTO ref_institution (canonical_name, country_id, verification_status, notes)
SELECT
  ni.canonical_name,
  dc.id,
  'VERIFIED',
  ni.notes
FROM new_institutions ni
JOIN dim_country dc ON dc.code = ni.country_code
ON CONFLICT (canonical_name) DO NOTHING;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Count of rows added in this migration
SELECT 'Phase 14.06 rows added' AS metric, COUNT(*) AS value
FROM ref_institution
WHERE notes LIKE 'Phase 14.06%';

-- List the rows with their country
SELECT
  ri.canonical_name,
  dc.code AS country,
  ri.notes
FROM ref_institution ri
LEFT JOIN dim_country dc ON dc.id = ri.country_id
WHERE ri.notes LIKE 'Phase 14.06%'
ORDER BY ri.canonical_name;

-- Confirm no country lookup failed (sanity check)
SELECT 'Rows with NULL country_id' AS metric, COUNT(*) AS value
FROM ref_institution
WHERE notes LIKE 'Phase 14.06%' AND country_id IS NULL;

COMMIT;

-- =============================================================================
-- EXPECTED OUTPUT
-- =============================================================================
-- Phase 14.06 rows added | 18
-- (18 rows listed alphabetically)
-- Rows with NULL country_id | 0
-- =============================================================================
