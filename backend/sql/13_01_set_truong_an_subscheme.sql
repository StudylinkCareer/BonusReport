-- Migration: Set Lê Thị Trường An's CO_SUB subscheme to ENROL_PLUS_VISA
-- Date: 2026-05-20
-- Reason: Per Bonus_Splits_on_Client_Types_and_Application_Status.xlsx,
--   Trường An's bao caos consistently show the 50/50 split pattern
--   on Current-Enrolled cases (paying ~half at enrolment, half at visa
--   granted later). This matches the ENROL_PLUS_VISA rate card.
--   Subscheme was previously NULL for all 48 of her ref_staff_target rows.
-- Verified by:
--   - SLC-13687 (Macquarie): 550,000 M01 + 550,000 M05 = 1,100,000 total
--   - SLC-13588, SLC-13360, SLC-13544, SLC-13617, SLC-13460, SLC-13640 etc.
-- Cross-staff comparison: Lợi (ENROL_ONLY_VISA_ONLY) gets the single-service
--   rate card; Trường An gets the full-service rate card.

BEGIN;

-- Pre-check: how many rows will be affected
DO $$
DECLARE
    affected_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO affected_count
    FROM ref_staff_target
    WHERE staff_id = 1
      AND role_id = 18
      AND co_sub_subscheme IS NULL;
    RAISE NOTICE 'Rows to update: %', affected_count;
END $$;

-- The update itself
UPDATE ref_staff_target
SET co_sub_subscheme = 'ENROL_PLUS_VISA',
    updated_at = NOW()
WHERE staff_id = 1            -- Lê Thị Trường An
  AND role_id = 18            -- CO_SUB
  AND co_sub_subscheme IS NULL;

-- Post-check: confirm the change took effect
DO $$
DECLARE
    null_count INTEGER;
    set_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM ref_staff_target
    WHERE staff_id = 1 AND role_id = 18 AND co_sub_subscheme IS NULL;
    SELECT COUNT(*) INTO set_count
    FROM ref_staff_target
    WHERE staff_id = 1 AND role_id = 18 AND co_sub_subscheme = 'ENROL_PLUS_VISA';
    RAISE NOTICE 'After update: % NULL, % ENROL_PLUS_VISA', null_count, set_count;
    IF null_count > 0 THEN
        RAISE EXCEPTION 'Some rows still NULL after update — aborting';
    END IF;
END $$;

COMMIT;

-- Manual verification query (run separately after commit):
-- SELECT year, month, target, co_sub_subscheme, updated_at
-- FROM ref_staff_target
-- WHERE staff_id = 1 AND role_id = 18
-- ORDER BY year, month;
