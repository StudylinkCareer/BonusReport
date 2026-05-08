-- ===========================================================================
-- Phase 9: Institution duplicate consolidation (v3 — Option A: soft-merge)
--
-- Approach: respect existing ref_institution.merged_into_id soft-merge state.
-- Rogues stay in the table as audit records, just with merged_into_id pointing
-- at the keeper. No DELETEs. No FK violations.
--
-- Existing soft-merges already in DB (verified by inspection):
--   225 → 107  Macquarie - MQ → Macquarie University
--   282 → 288  Victoria - SCC → Victoria University
--   141 → 130  Griffith (dup) → Griffith College
--   310 → 130  Griffith - Brisbane → Griffith College
--   277 → 137  SAIBT (long) → South Australian Inst of Business and Tech
--
-- New soft-merges this migration creates:
--   102 → 307  EQI → Education Queensland International (EQI)
--   297 → 147  British University Vietnam → British University Vietnam (BUV)
--   269 → 241  ILSC → ILSC Australia
--
-- Final canonicals (keepers): 130, 137, 107, 147, 241, 288, 307
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Redirect any aliases pointing at rogues → point at keepers
--    Safe because alias text is globally unique. No-op for rogues with no
--    aliases (most of them).
-- ---------------------------------------------------------------------------
UPDATE ref_institution_alias SET institution_id = 307 WHERE institution_id = 102;
UPDATE ref_institution_alias SET institution_id = 107 WHERE institution_id = 225;
UPDATE ref_institution_alias SET institution_id = 147 WHERE institution_id = 297;
UPDATE ref_institution_alias SET institution_id = 137 WHERE institution_id = 277;
UPDATE ref_institution_alias SET institution_id = 130 WHERE institution_id IN (141, 310);
UPDATE ref_institution_alias SET institution_id = 288 WHERE institution_id = 282;
UPDATE ref_institution_alias SET institution_id = 241 WHERE institution_id = 269;

-- ---------------------------------------------------------------------------
-- 2. Add canonical-name aliases for keepers (so the importer resolves rogue
--    canonical names correctly)
--    NOT EXISTS guards on alias text alone (matches the unique constraint).
-- ---------------------------------------------------------------------------
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT v.institution_id, v.alias
FROM (VALUES
    (307, 'EQI'),                                                              -- rogue 102's canonical
    (107, 'Macquarie University - MQ'),                                        -- rogue 225's (already exists)
    (147, 'British University Vietnam'),                                       -- rogue 297's
    (137, 'SAIBT - South Australian Institute of Business and Technology'),    -- rogue 277's
    (130, 'Griffith College - Brisbane'),                                      -- rogue 310's
    (288, 'Victoria University - Sydney City Centre'),                         -- rogue 282's (already exists)
    (241, 'ILSC')                                                              -- rogue 269's
) AS v(institution_id, alias)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution_alias a WHERE a.alias = v.alias
);

-- ---------------------------------------------------------------------------
-- 3. Redirect ref_institution_agreement rows from unmerged rogues → keepers
--    Already-merged rogues (225, 277, 141, 310, 282) had no agreement rows,
--    nothing to do for them.
--    NB: if a keeper already has an agreement with the same partner, UPDATE
--    will fail on a unique constraint — ROLLBACK and we'll fix.
-- ---------------------------------------------------------------------------
UPDATE ref_institution_agreement SET institution_id = 307 WHERE institution_id = 102;
UPDATE ref_institution_agreement SET institution_id = 147 WHERE institution_id = 297;
UPDATE ref_institution_agreement SET institution_id = 241 WHERE institution_id = 269;

-- ---------------------------------------------------------------------------
-- 4. Redirect tx_case rows from unmerged rogues → keepers (all months)
--    Only 102 (13 rows) and 269 (2 rows) actually have tx_case references;
--    297 had 0 in the diagnostic but the UPDATE is a no-op safety net.
-- ---------------------------------------------------------------------------
UPDATE tx_case SET institution_id = 307 WHERE institution_id = 102;
UPDATE tx_case SET institution_id = 147 WHERE institution_id = 297;
UPDATE tx_case SET institution_id = 241 WHERE institution_id = 269;

-- ---------------------------------------------------------------------------
-- 5. Set merged_into_id on the three newly-merged rogues
--    The other five (225, 277, 141, 310, 282) already have it set correctly.
-- ---------------------------------------------------------------------------
UPDATE ref_institution SET merged_into_id = 307 WHERE id = 102 AND merged_into_id IS NULL;
UPDATE ref_institution SET merged_into_id = 147 WHERE id = 297 AND merged_into_id IS NULL;
UPDATE ref_institution SET merged_into_id = 241 WHERE id = 269 AND merged_into_id IS NULL;

-- ---------------------------------------------------------------------------
-- VERIFICATION — review before COMMIT
-- ---------------------------------------------------------------------------
SELECT 'all_8_rogues_now_have_merged_into_id' AS check_name, COUNT(*)::text AS result
FROM ref_institution
WHERE id IN (102, 225, 297, 137, 130, 310, 282, 269)
  AND merged_into_id IS NOT NULL
UNION ALL
SELECT 'rogues_still_unmerged_should_be_zero', COUNT(*)::text
FROM ref_institution
WHERE id IN (102, 225, 297, 277, 141, 310, 282, 269)
  AND merged_into_id IS NULL
UNION ALL
SELECT 'tx_case_still_referencing_rogues', COUNT(*)::text
FROM tx_case
WHERE institution_id IN (102, 225, 297, 277, 141, 310, 282, 269)
UNION ALL
SELECT 'agreements_still_referencing_rogues', COUNT(*)::text
FROM ref_institution_agreement
WHERE institution_id IN (102, 225, 297, 277, 141, 310, 282, 269)
UNION ALL
SELECT 'aliases_still_referencing_rogues', COUNT(*)::text
FROM ref_institution_alias
WHERE institution_id IN (102, 225, 297, 277, 141, 310, 282, 269)
UNION ALL
SELECT 'priority_list_still_referencing_rogues', COUNT(*)::text
FROM ref_priority_list_institution
WHERE institution_id IN (102, 225, 297, 277, 141, 310, 282, 269)
UNION ALL
SELECT 'EQI_alias_resolves_to', i.id::text
FROM ref_institution_alias a
JOIN ref_institution i ON i.id = a.institution_id
WHERE a.alias = 'EQI'
UNION ALL
SELECT 'ILSC_alias_resolves_to', i.id::text
FROM ref_institution_alias a
JOIN ref_institution i ON i.id = a.institution_id
WHERE a.alias = 'ILSC'
UNION ALL
SELECT 'British_University_Vietnam_alias_resolves_to', i.id::text
FROM ref_institution_alias a
JOIN ref_institution i ON i.id = a.institution_id
WHERE a.alias = 'British University Vietnam'
ORDER BY check_name;

-- Expected:
--   British_University_Vietnam_alias_resolves_to   147
--   EQI_alias_resolves_to                          307
--   ILSC_alias_resolves_to                         241
--   agreements_still_referencing_rogues            0
--   aliases_still_referencing_rogues               0
--   all_8_rogues_now_have_merged_into_id           8
--   priority_list_still_referencing_rogues         0
--   rogues_still_unmerged_should_be_zero           0
--   tx_case_still_referencing_rogues               0

-- If verification matches:    COMMIT;
-- If anything wrong:           ROLLBACK;
