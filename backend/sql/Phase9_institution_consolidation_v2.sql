-- ===========================================================================
-- Phase 9: Institution duplicate consolidation (CORRECTED v2)
--
-- Fix from v1: the unique constraint on ref_institution_alias is on the
-- `alias` column alone (ref_institution_alias_alias_key), not on
-- (institution_id, alias). Any alias text can exist at most once in the
-- whole table. The previous version tried to INSERT canonical-name aliases
-- for keepers without checking if that alias text already pointed at the
-- rogue. This version reorders: redirect existing rogue aliases first
-- (UPDATE — collision-free since alias is globally unique), then INSERT
-- only the alias texts that aren't anywhere yet.
--
-- Pairs:
--   102 EQI                                                  → 307 Education Queensland International (EQI)
--   225 Macquarie University - MQ                            → 107 Macquarie University
--   297 British University Vietnam                           → 147 British University Vietnam (BUV)
--   137 South Australian Institute of Business and Technology→ 277 SAIBT - South Australian Institute of Business and Technology
--   130 Griffith College                                     → 141 Griffith College
--   310 Griffith College - Brisbane                          → 141 Griffith College
--   282 Victoria University - Sydney City Centre             → 288 Victoria University
--   269 ILSC                                                 → 241 ILSC Australia
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Redirect existing aliases that point at rogues → point at keepers
--    Safe because alias text is globally unique — keeper can never already
--    have an alias with the same text (would have failed unique constraint
--    when the rogue's alias was originally inserted).
-- ---------------------------------------------------------------------------
UPDATE ref_institution_alias SET institution_id = 307 WHERE institution_id = 102;
UPDATE ref_institution_alias SET institution_id = 107 WHERE institution_id = 225;
UPDATE ref_institution_alias SET institution_id = 147 WHERE institution_id = 297;
UPDATE ref_institution_alias SET institution_id = 277 WHERE institution_id = 137;
UPDATE ref_institution_alias SET institution_id = 141 WHERE institution_id IN (130, 310);
UPDATE ref_institution_alias SET institution_id = 288 WHERE institution_id = 282;
UPDATE ref_institution_alias SET institution_id = 241 WHERE institution_id = 269;

-- ---------------------------------------------------------------------------
-- 2. Add any canonical-name aliases that aren't yet in the table at all
--    NOT EXISTS guards on the alias column alone (matching the actual
--    unique constraint).
-- ---------------------------------------------------------------------------
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT v.institution_id, v.alias
FROM (VALUES
    (307, 'EQI'),
    (107, 'Macquarie University - MQ'),
    (147, 'British University Vietnam'),
    (277, 'South Australian Institute of Business and Technology'),
    (141, 'Griffith College'),
    (141, 'Griffith College - Brisbane'),
    (288, 'Victoria University - Sydney City Centre'),
    (241, 'ILSC')
) AS v(institution_id, alias)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution_alias a WHERE a.alias = v.alias
);

-- ---------------------------------------------------------------------------
-- 3. Redirect priority_list_institution rows from rogues → keepers
--    Only 130 (2 rows) and 137 (1 row) reference rogues per diagnostic.
--    Keepers 141 and 277 currently have no priority list rows → no collision.
-- ---------------------------------------------------------------------------
UPDATE ref_priority_list_institution SET institution_id = 141 WHERE institution_id = 130;
UPDATE ref_priority_list_institution SET institution_id = 277 WHERE institution_id = 137;

-- ---------------------------------------------------------------------------
-- 4. Redirect ref_institution_agreement rows from rogues → keepers
--    NB: if a keeper already has an agreement with the same partner this
--    will fail on a unique constraint — ROLLBACK and we'll switch to an
--    INSERT-WHERE-NOT-EXISTS / DELETE pattern.
-- ---------------------------------------------------------------------------
UPDATE ref_institution_agreement SET institution_id = 307 WHERE institution_id = 102;
UPDATE ref_institution_agreement SET institution_id = 141 WHERE institution_id = 130;
UPDATE ref_institution_agreement SET institution_id = 277 WHERE institution_id = 137;
UPDATE ref_institution_agreement SET institution_id = 241 WHERE institution_id = 269;
UPDATE ref_institution_agreement SET institution_id = 147 WHERE institution_id = 297;

-- ---------------------------------------------------------------------------
-- 5. Redirect tx_case rows from rogues → keepers (all months, all years)
-- ---------------------------------------------------------------------------
UPDATE tx_case SET institution_id = 307 WHERE institution_id = 102;
UPDATE tx_case SET institution_id = 107 WHERE institution_id = 225;
UPDATE tx_case SET institution_id = 147 WHERE institution_id = 297;
UPDATE tx_case SET institution_id = 277 WHERE institution_id = 137;
UPDATE tx_case SET institution_id = 141 WHERE institution_id = 130;
UPDATE tx_case SET institution_id = 141 WHERE institution_id = 310;
UPDATE tx_case SET institution_id = 288 WHERE institution_id = 282;
UPDATE tx_case SET institution_id = 241 WHERE institution_id = 269;

-- ---------------------------------------------------------------------------
-- 6. Delete the rogue ref_institution rows
-- ---------------------------------------------------------------------------
DELETE FROM ref_institution
WHERE id IN (102, 225, 297, 137, 130, 310, 282, 269);

-- ---------------------------------------------------------------------------
-- VERIFICATION — review before COMMIT
-- ---------------------------------------------------------------------------
SELECT 'rogues_remaining_in_ref_institution' AS check_name, COUNT(*)::text AS result
FROM ref_institution
WHERE id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'keepers_still_present', COUNT(*)::text
FROM ref_institution
WHERE id IN (107, 141, 147, 277, 288, 241, 307)
UNION ALL
SELECT 'tx_case_still_referencing_rogues', COUNT(*)::text
FROM tx_case
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'priority_list_still_referencing_rogues', COUNT(*)::text
FROM ref_priority_list_institution
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'agreements_still_referencing_rogues', COUNT(*)::text
FROM ref_institution_agreement
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'aliases_still_referencing_rogues', COUNT(*)::text
FROM ref_institution_alias
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'EQI_alias_now_resolves_to', i.id::text
FROM ref_institution_alias a
JOIN ref_institution i ON i.id = a.institution_id
WHERE a.alias = 'EQI'
UNION ALL
SELECT 'Griffith_College_Brisbane_alias_now_resolves_to', i.id::text
FROM ref_institution_alias a
JOIN ref_institution i ON i.id = a.institution_id
WHERE a.alias = 'Griffith College - Brisbane'
ORDER BY check_name;

-- Expected:
--   aliases_still_referencing_rogues                        0
--   agreements_still_referencing_rogues                     0
--   EQI_alias_now_resolves_to                               307
--   Griffith_College_Brisbane_alias_now_resolves_to         141
--   keepers_still_present                                   7
--   priority_list_still_referencing_rogues                  0
--   rogues_remaining_in_ref_institution                     0
--   tx_case_still_referencing_rogues                        0

-- If verification matches:    COMMIT;
-- If anything wrong:           ROLLBACK;
