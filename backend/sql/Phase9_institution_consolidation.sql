-- ===========================================================================
-- Phase 9: Institution duplicate consolidation
-- 
-- Eight pairs/triples of duplicate canonical institution rows are merged.
-- The "rogue" canonical is removed; the "keeper" canonical absorbs:
--   - the rogue's canonical_name (added as alias)
--   - any aliases the rogue had
--   - any priority_list_institution junction rows
--   - any institution_agreement rows
--   - any tx_case references
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
--
-- Wrapped in BEGIN — review the verification queries at the bottom before
-- choosing COMMIT or ROLLBACK.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add rogue canonical names as aliases of keepers (skipping duplicates)
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
    SELECT 1 FROM ref_institution_alias a
    WHERE a.institution_id = v.institution_id
      AND a.alias = v.alias
);

-- ---------------------------------------------------------------------------
-- 2. Migrate any aliases the rogues already had to point at the keepers
--    (skipping ones the keeper already has)
-- ---------------------------------------------------------------------------
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT
    CASE a.institution_id
        WHEN 102 THEN 307
        WHEN 225 THEN 107
        WHEN 297 THEN 147
        WHEN 137 THEN 277
        WHEN 130 THEN 141
        WHEN 310 THEN 141
        WHEN 282 THEN 288
        WHEN 269 THEN 241
    END AS new_institution_id,
    a.alias
FROM ref_institution_alias a
WHERE a.institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
  AND NOT EXISTS (
    SELECT 1 FROM ref_institution_alias k
    WHERE k.institution_id = CASE a.institution_id
                                 WHEN 102 THEN 307
                                 WHEN 225 THEN 107
                                 WHEN 297 THEN 147
                                 WHEN 137 THEN 277
                                 WHEN 130 THEN 141
                                 WHEN 310 THEN 141
                                 WHEN 282 THEN 288
                                 WHEN 269 THEN 241
                             END
      AND k.alias = a.alias
);

-- 2b. Delete rogue alias rows now that the keepers have all the aliases
DELETE FROM ref_institution_alias
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269);

-- ---------------------------------------------------------------------------
-- 3. Redirect priority_list_institution rows from rogues → keepers
--    Only 130 (2 rows) and 137 (1 row) are referenced.
--    141 and 277 currently have no priority list links, so no collision risk.
-- ---------------------------------------------------------------------------
UPDATE ref_priority_list_institution SET institution_id = 141 WHERE institution_id = 130;
UPDATE ref_priority_list_institution SET institution_id = 277 WHERE institution_id = 137;

-- ---------------------------------------------------------------------------
-- 4. Redirect ref_institution_agreement rows from rogues → keepers
--    102, 130, 137, 269, 297 each have one agreement row.
--    NB: if a keeper already has an agreement with the same partner this will
--    fail on a unique constraint — ROLLBACK and we'll switch to an
--    INSERT-WHERE-NOT-EXISTS / DELETE pattern.
-- ---------------------------------------------------------------------------
UPDATE ref_institution_agreement SET institution_id = 307 WHERE institution_id = 102;
UPDATE ref_institution_agreement SET institution_id = 141 WHERE institution_id = 130;
UPDATE ref_institution_agreement SET institution_id = 277 WHERE institution_id = 137;
UPDATE ref_institution_agreement SET institution_id = 241 WHERE institution_id = 269;
UPDATE ref_institution_agreement SET institution_id = 147 WHERE institution_id = 297;

-- ---------------------------------------------------------------------------
-- 5. Redirect tx_case rows from rogues → keepers (all months, all years)
--    Only 102 (13 rows) and 269 (2 rows) actually have tx_case references,
--    but the other UPDATEs are no-op safety nets.
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
SELECT 'rogues_remaining_in_ref_institution' AS check_name, COUNT(*) AS n
FROM ref_institution
WHERE id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'keepers_still_present', COUNT(*)
FROM ref_institution
WHERE id IN (107, 141, 147, 277, 288, 241, 307)
UNION ALL
SELECT 'tx_case_still_referencing_rogues', COUNT(*)
FROM tx_case
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'priority_list_still_referencing_rogues', COUNT(*)
FROM ref_priority_list_institution
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'agreements_still_referencing_rogues', COUNT(*)
FROM ref_institution_agreement
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'aliases_still_referencing_rogues', COUNT(*)
FROM ref_institution_alias
WHERE institution_id IN (102, 225, 297, 137, 130, 310, 282, 269)
UNION ALL
SELECT 'EQI_now_resolves_to_307', i.id
FROM ref_institution_alias a
JOIN ref_institution i ON i.id = a.institution_id
WHERE a.alias = 'EQI'
ORDER BY check_name;

-- Expected output:
--   aliases_still_referencing_rogues       → 0
--   agreements_still_referencing_rogues    → 0
--   EQI_now_resolves_to_307                → 307
--   keepers_still_present                  → 7
--   priority_list_still_referencing_rogues → 0
--   rogues_remaining_in_ref_institution    → 0
--   tx_case_still_referencing_rogues       → 0

-- If the verification looks right:
--   COMMIT;
-- Otherwise:
--   ROLLBACK;
