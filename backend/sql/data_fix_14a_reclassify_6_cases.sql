-- ============================================================================
-- Data fix 14a: Reclassify 6 confirmed cases per DD-§I.6 triage
--
-- Run AFTER migration_14a_paid_cancelled_statuses.sql has succeeded.
-- Run BEFORE re-running the engine for affected months.
--
-- 5 cases → "Closed - Paid Cancelled" (study abroad, fees paid, BC paid 400k)
-- 1 case  → "Closed - Visa Only Paid" (485 visa-only, BC paid 600k)
--
-- All 6 contracts are confirmed via bao cao note review. Each note explicitly
-- documents the bonus rate the BC paid (Out-system / Visa 485).
-- ============================================================================

BEGIN;

-- Pre-update audit: confirm we're about to update exactly the right rows
SELECT id, contract_id, run_year, run_month, application_status, 
       institution_id, client_type_code, student_name
FROM tx_case
WHERE contract_id IN (
    'SLC-12130',  -- Trần Thanh Thủy, 2024-01, Yến HCM, BC paid 400k (Vancouver SB cancel)
    'SLC-12956',  -- Tan Nhật Anh, 2024-12, Yến/Vinh, BC paid 400k (Hết hạn bảo lưu)
    'SLC-13253',  -- Lê Thị Mỹ Lệ, 2024-09, Yến HCM, BC paid 400k (English not improving)
    'SLC-13293',  -- Nguyễn Thị Hương, 2024-12, Yến/Vinh, BC paid 400k (Hết hạn bảo lưu)
    'SLC-13701',  -- Phan Thành Thái, 2024-06, Yến, BC paid 400k (Job in VN)
    'SLC-14372'   -- Phương Gia Hoàng, 2025-09, Mẫn HCM, BC paid 600k (485 visa)
)
ORDER BY contract_id;

-- Update the 5 study-abroad fees-paid cases → Closed - Paid Cancelled
UPDATE tx_case
SET application_status = 'Closed - Paid Cancelled',
    updated_at = NOW()
WHERE contract_id IN (
    'SLC-12130',
    'SLC-12956',
    'SLC-13253',
    'SLC-13293',
    'SLC-13701'
)
AND application_status = 'Closed - Cancelled';  -- Defensive: only update if still in original state

-- Update the 1 visa-only case → Closed - Visa Only Paid
UPDATE tx_case
SET application_status = 'Closed - Visa Only Paid',
    updated_at = NOW()
WHERE contract_id = 'SLC-14372'
AND application_status = 'Closed - Cancelled';

-- Post-update verification
SELECT id, contract_id, run_year, run_month, application_status, institution_id, student_name
FROM tx_case
WHERE contract_id IN (
    'SLC-12130', 'SLC-12956', 'SLC-13253', 'SLC-13293', 'SLC-13701', 'SLC-14372'
)
ORDER BY contract_id;

-- Expected: 5 rows show 'Closed - Paid Cancelled', 1 row shows 'Closed - Visa Only Paid'
-- If counts wrong, ROLLBACK before COMMIT.

COMMIT;
