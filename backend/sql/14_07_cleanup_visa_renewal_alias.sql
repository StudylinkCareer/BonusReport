-- =============================================================================
-- Migration 14_07: Clean up duplicate STUDENT_VISA_RENEWAL service-fee row
-- =============================================================================
--
-- The dropdown that shows service fees on a case is rendered from
-- ref_service_fee.description. Row id=35 was created with
-- service_code='STUDENT_VISA_RENEWAL' and description='Alias for VISA_RENEWAL'
-- — a placeholder alias incorrectly stored in the canonical table instead
-- of in ref_service_fee_alias. It appears as a selectable option in the
-- UI as "Alias for VISA_RENEWAL", which is junk.
--
-- The real entry is id=20 (service_code='VISA_RENEWAL', description='Student
-- visa renewal AUS/NZ').
--
-- This migration:
--   1. Re-points any tx_case_service rows currently linked to id=35 → id=20
--   2. Inserts an alias row mapping 'STUDENT_VISA_RENEWAL' to id=20 so that
--      anything looking up that code still resolves correctly
--   3. Deletes id=35 from ref_service_fee
--   4. Verifies the dropdown universe no longer contains "Alias for"
-- =============================================================================

BEGIN;

-- Step 1: Remove duplicate tx_case_service rows linked to id=35.
-- We can't UPDATE to service_fee_id=20 because the (case_id, service_fee_id)
-- unique constraint blocks it — these cases already have a row for id=20.
-- DELETE is correct: id=35 was always a duplicate of id=20; removing it just
-- collapses the two tags into one (the canonical one).
DELETE FROM tx_case_service
 WHERE service_fee_id = 35;

-- Step 2: Add alias mapping so STUDENT_VISA_RENEWAL still resolves.
-- ON CONFLICT DO NOTHING in case the alias already exists.
INSERT INTO ref_service_fee_alias (alias, service_fee_id)
VALUES ('STUDENT_VISA_RENEWAL', 20)
ON CONFLICT (alias) DO NOTHING;

-- Step 3: Same for tx_case (the one-to-one column). If a case has
-- service_fee_id=35, just clear it — the tx_case_service junction is
-- the authoritative link, and that's already been cleaned.
UPDATE tx_case
   SET service_fee_id = NULL,
       updated_at = NOW()
 WHERE service_fee_id = 35;

-- Step 4: Delete the duplicate canonical row.
DELETE FROM ref_service_fee
 WHERE id = 35;

-- Verifications:
-- (a) Nothing should remain linked to id=35
SELECT 'tx_case' AS source, COUNT(*) AS rows_still_on_35
FROM tx_case WHERE service_fee_id = 35
UNION ALL
SELECT 'tx_case_service', COUNT(*)
FROM tx_case_service WHERE service_fee_id = 35;

-- (b) The dropdown source should no longer contain "Alias for"
SELECT id, service_code, description
FROM ref_service_fee
WHERE description ILIKE '%alias for%';

-- (c) The alias mapping should now exist
SELECT a.alias, s.service_code, s.description
FROM ref_service_fee_alias a
JOIN ref_service_fee s ON s.id = a.service_fee_id
WHERE a.alias = 'STUDENT_VISA_RENEWAL';

COMMIT;
