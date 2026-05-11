-- =============================================================================
-- Phase 14_18: Group 2 mass fix — flip OUT_OF_SYSTEM → IN_SYSTEM for
--              institutions where all mismatched cases say "Trong hệ thống"
-- =============================================================================
-- Pattern: institution has only OUT_OF_SYSTEM/DIRECT agreements (typically
-- added by Phase 14.10C trust-CRM based on old CRM=Ngoài cases), but the
-- current CRM data has Trong cases for the same institution. CRM is
-- internally inconsistent — net signal favours IN_SYSTEM.
--
-- 11 institutions, all currently OUT_OF_SYSTEM/DIRECT. Flipping to IN_SYSTEM
-- and adjusting kpi_weight to the standard in-system DIRECT weight (1.0).
--
-- Note: this may surface NEW Ngoài-cases-vs-IN_SYSTEM mismatches on next
-- import for any of these institutions that have OOS cases in CRM. Those
-- are then operator-review items (Group 4-style).
-- =============================================================================

BEGIN;

UPDATE ref_institution_agreement
   SET system_status = 'IN_SYSTEM',
       kpi_weight    = 1.0,
       notes = 'Phase 14_18: flipped OUT_OF_SYSTEM→IN_SYSTEM, weight 0→1.0. '
            || '100% of CRM-flagged cases say Trong; net CRM signal favours '
            || 'in-system. Original: ' || COALESCE(notes, '')
 WHERE institution_id IN (
         713,   -- Cambrian Academy
         2021,  -- Mount Royal University
         705,   -- California State University, Fullerton
         1125,  -- Embry-Riddle Aeronautical University, Florida
         2810,  -- Swinburne University of Technology - Sarawak
         3411,  -- York University
         474,   -- Auckland Institute of Studies (AIS)
         1183,  -- Florida International University
         2517,  -- San Jose State University
         3219,  -- University of the Sunshine Coast
         3180   -- University of Victoria
       )
   AND system_status = 'OUT_OF_SYSTEM'
   AND agreement_type = 'DIRECT';


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    flipped_count INT;
BEGIN
    SELECT COUNT(*) INTO flipped_count
      FROM ref_institution_agreement
     WHERE institution_id IN (713, 2021, 705, 1125, 2810, 3411, 474, 1183, 2517, 3219, 3180)
       AND notes LIKE 'Phase 14_18%';

    IF flipped_count <> 11 THEN
        RAISE EXCEPTION 'Phase 14_18 FAILED: expected 11 flipped agreements, found %', flipped_count;
    END IF;

    RAISE NOTICE '====================================================';
    RAISE NOTICE 'Phase 14_18 OK: % agreements flipped to IN_SYSTEM/1.0', flipped_count;
    RAISE NOTICE 'Should drop SYSTEM_TYPE_MISMATCH by ~20 cases on next reload.';
    RAISE NOTICE 'Remaining ~41 cases need operator review (Groups 1, 3, 4, 5).';
    RAISE NOTICE '====================================================';
END $$;

COMMIT;
