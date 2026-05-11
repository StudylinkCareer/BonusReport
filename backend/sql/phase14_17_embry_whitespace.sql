-- =============================================================================
-- Phase 14_17: Embry-Riddle whitespace variant aliases
-- =============================================================================
-- Hypothesis: importer normalizes whitespace before matching aliases. Existing
-- aliases 4643 and 4644 use a DOUBLE space between "Aeronautical" and 
-- "University" (preserving the source data's original spacing). Source rows
-- normalize to single space → no match in importer's lookup.
--
-- Fix: add SINGLE-space variants pointing to the same institution (id=1125,
-- Florida campus, where the existing double-space aliases point). Both 
-- variants will coexist; the matching one will resolve.
--
-- Idempotent: ON CONFLICT DO NOTHING.
-- =============================================================================

BEGIN;

INSERT INTO ref_institution_alias (institution_id, alias)
VALUES
    (1125, 'Embry-Riddle Aeronautical University * - EduCo'),
    (1125, 'Embry-Riddle Aeronautical University *- EduCo/ USA')
ON CONFLICT (alias) DO NOTHING;


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    new_count INT;
BEGIN
    SELECT COUNT(*) INTO new_count
      FROM ref_institution_alias
     WHERE institution_id = 1125
       AND alias IN (
           'Embry-Riddle Aeronautical University * - EduCo',
           'Embry-Riddle Aeronautical University *- EduCo/ USA'
       );

    IF new_count <> 2 THEN
        RAISE EXCEPTION 'Phase 14_17 FAILED: expected 2 single-space variants for id=1125, found %', new_count;
    END IF;

    RAISE NOTICE 'Phase 14_17 OK: 2 single-space variant aliases added pointing to Embry-Riddle Florida (id=1125).';
    RAISE NOTICE 'Should clear UNRESOLVED_INSTITUTION=2 on next import reload.';
END $$;

COMMIT;
