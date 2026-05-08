-- ============================================================================
-- Data fix 14b (REVISED): Enforce "name only in earning slot" rule
--
-- Per locked rule: a slot column on tx_case should only carry a staff name
-- when that slot earns bonus on the case. For visa-only paid contracts
-- (485 etc.) the counsellor slot doesn't earn — only the case officer does
-- the visa work. So counsellor_staff_id must be NULL on these cases.
--
-- This replaces the earlier 14b draft that tried to fix the double-pay
-- by setting split_couns_pct=0. That approach conflicts with the locked
-- rule (it tolerates dirty slot data instead of enforcing the rule).
--
-- For SLC-14372 specifically: tx_case currently has Mẫn in both
-- counsellor_staff_id and case_officer_staff_id. Setting counsellor_staff_id
-- to NULL means engine produces only the case_officer payment row,
-- matching BC's 600k.
--
-- (No splits change. ref_status_split for 'Closed - Visa Only Paid' stays
-- at 1.0/1.0/1.0, consistent with Closed - Enrolled.)
-- ============================================================================

BEGIN;

-- Pre-update audit
SELECT contract_id, application_status,
       counsellor_staff_id, counsellor_role_id,
       case_officer_staff_id, case_officer_role_id
FROM tx_case
WHERE contract_id = 'SLC-14372';

-- Clear counsellor slot (and its role_id) for the visa-only case
UPDATE tx_case
SET counsellor_staff_id = NULL,
    counsellor_role_id = NULL,
    updated_at = NOW()
WHERE contract_id = 'SLC-14372'
AND application_status = 'Closed - Visa Only Paid'
AND counsellor_staff_id IS NOT NULL;  -- defensive

-- Post-update verification
SELECT contract_id, application_status,
       counsellor_staff_id, counsellor_role_id,
       case_officer_staff_id, case_officer_role_id
FROM tx_case
WHERE contract_id = 'SLC-14372';
-- Expected: counsellor_staff_id and counsellor_role_id are NULL

COMMIT;
