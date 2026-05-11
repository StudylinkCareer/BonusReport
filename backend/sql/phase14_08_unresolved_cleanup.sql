-- =============================================================================
-- phase14_08_unresolved_cleanup.sql
-- Phase 14.08 -- Final cleanup of leftover UNRESOLVED_INSTITUTION cases
-- =============================================================================
--
-- Two-part migration that should drive UNRESOLVED_INSTITUTION to 0:
--
--   PART A: 24 new institution canonicals (institutions genuinely missing
--           from ref_institution after Phase 14.06).
--   PART B: 42 aliases:
--             - 15 mapping to PRE-EXISTING canonicals (Group A)
--             - 27 mapping to canonicals added in PART A above (Group B)
--
-- IMPORTANT:
-- - This migration adds ONLY ref_institution and ref_institution_alias rows.
--   It does NOT create ref_institution_agreement records.
-- - Cases that resolve will move to OK status if a matching agreement exists,
--   otherwise to SYSTEM_TYPE_MISMATCH (the latter is Tier 3 work).
-- - "/* VERIFY */" markers flag rows requiring business review:
--    * Country guesses that may be wrong
--    * Pathway colleges aliased to main universities (may want separate canonicals)
--    * Embry-Riddle defaulted to Florida campus (CRM doesn't specify campus)
--
-- =============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- PART A: 24 new institution canonicals
-- ----------------------------------------------------------------------------

WITH new_institutions(canonical_name, country_code, notes) AS (
  VALUES
    -- Australia (3)
    ('Hills College', 'AU',
       'Phase 14.08 /* VERIFY: country uncertain; could also be US/UK */'),
    ('The University of Newcastle College of International Education (CIE)', 'AU',
       'Phase 14.08 -- AU pathway college for U Newcastle. /* VERIFY: distinct from "Newcastle College" UK */'),
    ('Wakefield School', 'AU',
       'Phase 14.08 /* VERIFY: country and specific school uncertain */'),
    -- Canada (1)
    ('Dalhousie University', 'CA',
       'Phase 14.08 -- Halifax, Nova Scotia'),
    -- Ireland (1)
    ('University of Galway', 'IE',
       'Phase 14.08 -- formerly NUI Galway'),
    -- New Zealand (2)
    ('Aorere College', 'NZ',
       'Phase 14.08 -- Auckland secondary school'),
    ('Pacific International Hotel Management School (PIHMS)', 'NZ',
       'Phase 14.08 -- New Plymouth'),
    -- Singapore (1)
    ('Singapore Institute of Technology (SIT)', 'SG',
       'Phase 14.08'),
    -- United Kingdom (1)
    ('Northumbria University', 'GB',
       'Phase 14.08 -- Newcastle upon Tyne. Spelling corrected from CRM "Northumria"'),
    -- United States (15)
    ('Austin Community College District', 'US',
       'Phase 14.08 -- Texas'),
    ('Fairbanks North Star Borough School District', 'US',
       'Phase 14.08 -- Alaska school district'),
    ('Hillsboro Aero Academy', 'US',
       'Phase 14.08 -- Oregon, aviation training'),
    ('IL Texas Private High School', 'US',
       'Phase 14.08 /* VERIFY name -- may be International Leadership of Texas charter network */'),
    ('Indiana University Bloomington', 'US',
       'Phase 14.08 -- main IU campus (other campuses already in DB)'),
    ('Louisiana State University', 'US',
       'Phase 14.08 -- LSU, Baton Rouge'),
    ('Lutheran High School South', 'US',
       'Phase 14.08 /* VERIFY -- multiple Lutheran schools share similar names; this is likely St. Louis MO */'),
    ('Millersville University', 'US',
       'Phase 14.08 -- Pennsylvania'),
    ('North Park University', 'US',
       'Phase 14.08 -- Chicago, Illinois'),
    ('Red Rocks Community College', 'US',
       'Phase 14.08 -- Lakewood, Colorado'),
    ('Salem State University', 'US',
       'Phase 14.08 -- Massachusetts'),
    ('St Mary''s Preparatory High School', 'US',
       'Phase 14.08 /* VERIFY -- ambiguous name; possibly Orchard Lake MI */'),
    ('University Christian School', 'US',
       'Phase 14.08 /* VERIFY -- ambiguous name; multiple US schools share this name */'),
    ('University of Illinois at Chicago', 'US',
       'Phase 14.08 -- UIC'),
    ('University of Toledo', 'US',
       'Phase 14.08 -- Ohio')
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

-- ----------------------------------------------------------------------------
-- PART B: 42 aliases
-- ----------------------------------------------------------------------------

CREATE TEMP TABLE phase_14_08_aliases (canonical_name TEXT, alias TEXT) ON COMMIT DROP;

INSERT INTO phase_14_08_aliases (canonical_name, alias) VALUES
  -- ===== GROUP A: Aliases for PRE-EXISTING canonicals (15 rows) =====

  -- Both TMUIC variants -> existing "Toronto Metropolitan Uni Intl College (Navitas)"
  ('Toronto Metropolitan Uni Intl College (Navitas)',
       'Toronto Metropolitan University International College (TMUIC) * - Navitas'),
  ('Toronto Metropolitan Uni Intl College (Navitas)',
       'Toronto Metropolitan University International College *'),

  -- Southern Institute of Technology -- DB uses dash form
  ('Southern Institute of Technology - SIT',
       'Southern Institute of Technology (SIT) * - GEEBEE'),

  -- Auburn University at Montgomery -- DB uses "of" not "at"
  ('Auburn University of Montgomery',
       'Auburn University at Montgomery *'),

  -- BCIT -- DB has the long form without parens
  ('British Columbia Institute of Technology',
       'British Columbia Institute of Technology (BCIT) * - ApplyBoard'),

  -- Auckland -- DB has "The University of Auckland"
  ('The University of Auckland',
       'University of Auckland **'),

  -- Tennessee -- main "University of Tennessee" canonical
  ('University of Tennessee',
       'University of Tennessee - Knoxville * - GEEBEE'),

  -- Centennial College -- DB has full name "of Applied Arts and Technology"
  ('Centennial College of Applied Arts and Technology',
       'Centennial College * - Leap GeeBee'),

  -- /* VERIFY: CSU Sydney -> ISC (Navitas pathway) */
  ('Charles Sturt University ISC',
       'Charles Sturt University Sydney * - Navitas'),

  -- /* VERIFY: Embry-Riddle defaulted to Florida (larger campus) -- CRM does not specify */
  ('Embry-Riddle Aeronautical University, Florida',
       'Embry-Riddle Aeronautical  University * - EduCo'),
  ('Embry-Riddle Aeronautical University, Florida',
       'Embry-Riddle Aeronautical  University *- EduCo/ USA'),

  -- /* VERIFY: ULethbridge Calgary (UICC) -> ULIC; may need separate Calgary canonical */
  ('University of Lethbridge International College (ULIC)',
       'ULethbridge International College Calgary (UICC) * - Navitas'),

  -- UWE -- DB has version without parens
  ('University of The West of England',
       'University of The West of England (UWE) **'),

  -- /* VERIFY: Waikato pathway college -> main university; may want separate canonical */
  ('University of Waikato',
       'University of Waikato College * - Navitas'),

  -- /* VERIFY: UWA INTO College -> main university; may want separate canonical */
  ('University of Western Australia (UWA)',
       'UWA College * - INTO'),

  -- ===== GROUP B: Aliases for canonicals added in Part A (27 rows) =====

  ('Aorere College',
       'Aorere College **'),
  ('Austin Community College District',
       'Austin Community College District **'),
  ('Dalhousie University',
       'Dalhousie University *'),
  ('Fairbanks North Star Borough School District',
       'Fairbanks North Star Borough School District **'),
  ('Hillsboro Aero Academy',
       'Hillsboro Aero Academy **'),
  ('Hills College',
       'Hills College *'),
  ('IL Texas Private High School',
       'IL Texas Private High School * - GE'),
  ('Indiana University Bloomington',
       'Indiana University Bloomington **'),
  ('Louisiana State University',
       'Louisiana State University *'),
  ('Louisiana State University',
       'Louisiana State University * - Shorelight Education'),
  ('Lutheran High School South',
       'Lutheran High School South **'),
  ('Millersville University',
       'Millersville University * - Wellspring'),
  ('North Park University',
       'North Park University * - Wellspring'),
  -- Northumria typo -> correctly-spelled Northumbria canonical
  ('Northumbria University',
       'Northumria University * - INTO UK'),
  ('Pacific International Hotel Management School (PIHMS)',
       'Pacific International Hotel Management School (PIHMS) **'),
  ('Red Rocks Community College',
       'Red Rocks Community College **'),
  ('Red Rocks Community College',
       'Red Rocks Community College (RRCC) **'),
  ('Salem State University',
       'Salem State University**'),
  ('Singapore Institute of Technology (SIT)',
       'Singapore Institute of Technology (SIT) **'),
  ('St Mary''s Preparatory High School',
       'St Mary''s Preparatory High School **'),
  ('The University of Newcastle College of International Education (CIE)',
       'The University of Newcastle College of International Education (CIE) *'),
  ('University Christian School',
       'University Christian School **'),
  ('University of Galway',
       'University of Galway **'),
  ('University of Galway',
       'University of Galway * - GEEBEE'),
  ('University of Illinois at Chicago',
       'University of Illinois at Chicago * / Shorelight'),
  ('University of Toledo',
       'University of Toledo * - Wellspring'),
  ('Wakefield School',
       'Wakefield School **');

-- Insert aliases where canonical exists; skip silently otherwise
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT ri.id, aa.alias
FROM phase_14_08_aliases aa
JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name
ON CONFLICT (alias) DO NOTHING;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Part A: institutions added
SELECT 'Phase 14.08 institutions added' AS metric, COUNT(*) AS value
FROM ref_institution WHERE notes LIKE 'Phase 14.08%';

-- List the new institutions with their countries
SELECT ri.canonical_name, dc.code AS country, ri.notes
FROM ref_institution ri
LEFT JOIN dim_country dc ON dc.id = ri.country_id
WHERE ri.notes LIKE 'Phase 14.08%'
ORDER BY ri.canonical_name;

-- Confirm no NULL country (sanity check)
SELECT 'Phase 14.08 rows with NULL country_id' AS metric, COUNT(*) AS value
FROM ref_institution
WHERE notes LIKE 'Phase 14.08%' AND country_id IS NULL;

-- Part B: alias attempt vs success counts
SELECT
  (SELECT COUNT(*) FROM phase_14_08_aliases) AS aliases_attempted,
  (SELECT COUNT(*) FROM phase_14_08_aliases aa
     JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name) AS canonical_match_found,
  (SELECT COUNT(*) FROM phase_14_08_aliases aa
     LEFT JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name
     WHERE ri.id IS NULL) AS canonical_NOT_found;

-- List any unmapped (canonical missing) -- should be ZERO after this migration
SELECT aa.canonical_name AS missing_canonical, aa.alias AS unmapped_alias
FROM phase_14_08_aliases aa
LEFT JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name
WHERE ri.id IS NULL
ORDER BY aa.canonical_name;

COMMIT;

-- =============================================================================
-- EXPECTED OUTPUT
-- =============================================================================
-- Phase 14.08 institutions added                | 24
-- (24 rows listed alphabetically with countries)
-- Phase 14.08 rows with NULL country_id         | 0
-- aliases_attempted=42, canonical_match_found=42, canonical_NOT_found=0
-- (zero rows in unmapped list)
--
-- After this runs, re-run the importer:
--   TRUNCATE TABLE tx_case RESTART IDENTITY CASCADE;
--   python -m backend.importer.consolidated_cli "<CRM file path>"
--
-- Expected post-import warning breakdown:
--   UNRESOLVED_INSTITUTION:  67 -> 0   (cleared)
--   SYSTEM_TYPE_MISMATCH:   261 -> ~290-310 (some new institutions lack agreements;
--                                            this is Tier 3 work)
--   (other warning types unchanged)
-- =============================================================================
