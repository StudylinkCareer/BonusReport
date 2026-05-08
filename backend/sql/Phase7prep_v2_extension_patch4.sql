-- =====================================================================
-- Phase 7 prep v2 extension — patch 4
-- Date: 2026-05-05
--
-- CO_SUB slot policy migration.
--
-- Per the locked decision: CO_SUB staff always populate case_officer
-- slot, never counsellor slot, regardless of which Excel column they
-- appeared in. The earlier importer (pre-patch4) wrote whatever was
-- in the Counsellor Name column to counsellor_staff_id, even when that
-- person was CO_SUB — leading to the engine emitting two BonusPayment
-- rows per case (one per slot, both for the same person).
--
-- This patch retroactively clears the counsellor slot for any tx_case
-- row where counsellor_role_id = 18 (CO_SUB), preserving the
-- case_officer assignment via COALESCE.
--
-- One UPDATE handles all three cases:
--   1. Same CO_SUB person in both slots → COALESCE keeps case_officer
--      as-is; counsellor cleared.
--   2. CO_SUB in counsellor + case_officer NULL → COALESCE migrates
--      to case_officer; counsellor cleared.
--   3. CO_SUB in counsellor + different person in case_officer →
--      COALESCE keeps the different person; CO_SUB person dropped
--      from counsellor. Verification block at end surfaces these
--      cases for manual inspection.
--
-- Idempotent: re-running finds no counsellor_role_id = 18 rows and is
-- a no-op.
-- =====================================================================

BEGIN;

-- Pre-state visibility
SELECT 'V0: Before — rows with CO_SUB in counsellor slot' AS check_name,
       COUNT(*) AS rows_to_fix
FROM tx_case
WHERE counsellor_role_id = 18;

-- The fix
UPDATE tx_case
   SET case_officer_staff_id = COALESCE(case_officer_staff_id, counsellor_staff_id),
       case_officer_role_id  = COALESCE(case_officer_role_id,  counsellor_role_id),
       counsellor_staff_id   = NULL,
       counsellor_role_id    = NULL,
       updated_at            = NOW()
 WHERE counsellor_role_id = 18;  -- ROLE_ID_CO_SUB

-- =====================================================================
-- Verification
-- =====================================================================

-- V1: No rows should remain with CO_SUB in counsellor slot
SELECT 'V1: After — rows with CO_SUB in counsellor slot (expect 0)' AS check_name,
       COUNT(*) AS rows_remaining
FROM tx_case
WHERE counsellor_role_id = 18;

-- V2: Show all affected rows (case_officer = CO_SUB), so operator can
-- spot-check the migration looks right. For Lợi April 2025 expect 7 rows.
SELECT 'V2: rows now correctly placing CO_SUB in case_officer slot' AS check_name;

SELECT id, contract_id, run_year, run_month,
       counsellor_staff_id, counsellor_role_id,
       case_officer_staff_id, case_officer_role_id
FROM tx_case
WHERE case_officer_role_id = 18
ORDER BY run_year, run_month, id;

COMMIT;
