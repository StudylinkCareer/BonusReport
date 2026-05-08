-- =============================================================================
-- Phase7prep — Pre-flight checks
-- Run this FIRST. Read the output. If anything is unexpected, STOP.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- Check 1: ref_institution columns we depend on
--   Expected: 2 rows, listing aggregate_priority_partner_id and priority_partner_id
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 1 — ref_institution columns' AS check_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'ref_institution'
  AND column_name IN ('aggregate_priority_partner_id', 'priority_partner_id', 'classification', 'is_priority_member')
ORDER BY column_name;


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 2: dim_role.code values
--   Expected: COUNS_DIR, CO_DIR, CO_SUB, PRESALES, VP — all 5 present
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 2 — dim_role.code values' AS check_name,
    code, name
FROM dim_role
ORDER BY code;


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 3: dim_office.code values
--   Expected: HCM, HN, DN at minimum
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 3 — dim_office.code values' AS check_name,
    code, name, country_code
FROM dim_office
ORDER BY code;


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 4: ref_partner — should have all 27 partners from Doc 7
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 4 — ref_partner count' AS check_name,
    COUNT(*) AS total,
    SUM(CASE WHEN classification = 'GROUP' THEN 1 ELSE 0 END) AS groups,
    SUM(CASE WHEN classification = 'MASTER_AGENT' THEN 1 ELSE 0 END) AS master_agents
FROM ref_partner;
-- Expected: total=27, groups=18, master_agents=9


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 5: ref_partner — verify the two MA-genuine partners exist by name
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 5 — ApplyBoard and Can-Achieve exist' AS check_name,
    name, classification
FROM ref_partner
WHERE name IN ('ApplyBoard', 'Can-Achieve')
ORDER BY name;
-- Expected: 2 rows


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 6: ref_partner — verify ILAC exists for Phase 6l link
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 6 — ILAC exists' AS check_name,
    name, classification
FROM ref_partner
WHERE name = 'ILAC';
-- Expected: 1 row


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 7: ref_staff — Phạm Thị Lợi exists
--   Note: secondary_role_id is added by TX1, so we don't check for it here.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 7 — Phạm Thị Lợi exists' AS check_name,
    canonical_name, primary_role_id
FROM ref_staff
WHERE canonical_name = 'Phạm Thị Lợi';
-- Expected: 1 row


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 8: ref_priority_target current state
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 8 — existing priority targets' AS check_name,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT priority_partner_id) AS distinct_partners,
    MIN(year) AS earliest_year,
    MAX(year) AS latest_year
FROM ref_priority_target;
-- This shows what data will be migrated to effective-dated form.


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 9: ref_institution.classification distribution
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 9 — institution classification distribution' AS check_name,
    classification,
    COUNT(*) AS count
FROM ref_institution
GROUP BY classification
ORDER BY classification;
-- Shows how many rows will be reclassified.


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 10: ref_institution rows with priority FK set
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 10 — institution priority FK populated' AS check_name,
    COUNT(*) FILTER (WHERE aggregate_priority_partner_id IS NOT NULL) AS with_aggregate_fk,
    COUNT(*) FILTER (WHERE priority_partner_id IS NOT NULL) AS with_priority_fk
FROM ref_institution;
-- These are the rows that will become ref_priority_partner_institution junction rows.


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 11: dim_country — confirm AU, CA, NZ, SG codes exist
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 11 — country codes exist' AS check_name,
    code, name
FROM dim_country
WHERE code IN ('AU', 'CA', 'NZ', 'SG')
ORDER BY code;
-- Expected: 4 rows. If SG is missing or coded differently (e.g. 'SING'), fix the migration.


-- ─────────────────────────────────────────────────────────────────────────────
-- Check 12: trg_set_updated_at function exists
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    'Check 12 — trigger function exists' AS check_name,
    proname
FROM pg_proc
WHERE proname = 'trg_set_updated_at';
-- Expected: 1 row


-- ─────────────────────────────────────────────────────────────────────────────
-- IF ALL CHECKS PASS:
--   - Take a database backup (Railway → Database → Backups)
--   - Run TX1 (described in deployment walkthrough)
--   - Verify TX1 NOTICE output reads "TX1 schema changes verified."
--   - Run TX2
--   - Verify TX2 NOTICE output reads "TX2 data verification PASSED."
--
-- IF ANY CHECK FAILS:
--   - STOP. Send the output back. Do not run the migration.
-- =============================================================================
