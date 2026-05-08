-- =========================================================================
-- Phase 10b: Management override columns on tx_bonus_payment
-- =========================================================================
-- For cases where management approves a payment that differs from the
-- engine's calculated value (e.g. SLC-13399, SLC-13349 paid 100% at
-- enrolment instead of the standard 50% Current-Enrolled split).
--
-- Override is ADDITIVE: final paid = net_payable + COALESCE(mgmt_override_amount, 0)
-- Positive = extra paid; negative = reduction.
--
-- The engine continues to produce its policy-driven calculation in
-- net_payable; the override is layered on top so audit shows both.
--
-- Constraint: if amount is set, reason must also be set. Approved_by/at
-- are optional but strongly recommended for audit.
-- =========================================================================

BEGIN;

ALTER TABLE tx_bonus_payment
    ADD COLUMN mgmt_override_amount       INTEGER,
    ADD COLUMN mgmt_override_reason       TEXT,
    ADD COLUMN mgmt_override_approved_by  VARCHAR(128),
    ADD COLUMN mgmt_override_approved_at  TIMESTAMPTZ;

ALTER TABLE tx_bonus_payment
    ADD CONSTRAINT chk_tx_bonus_payment_override_amount_with_reason
    CHECK (
        mgmt_override_amount IS NULL
        OR (mgmt_override_amount IS NOT NULL AND mgmt_override_reason IS NOT NULL)
    );

-- Partial index for finding overridden payments quickly (small footprint —
-- only indexes rows where an override exists, which will be rare)
CREATE INDEX idx_tx_bonus_payment_overridden
ON tx_bonus_payment (case_id, staff_id)
WHERE mgmt_override_amount IS NOT NULL;

-- Verification: should report new columns and constraint
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_bonus_payment'
  AND column_name LIKE 'mgmt_override%'
ORDER BY column_name;

COMMIT;

-- After commit, to verify and use:
--
-- 1. View columns:
-- \d tx_bonus_payment
--
-- 2. Apply an override (example: SLC-13399):
-- UPDATE tx_bonus_payment
-- SET mgmt_override_amount       = 550000,
--     mgmt_override_reason       = 'Manual approval Jan 2024: paid 100% at enrolment instead of standard 50% split',
--     mgmt_override_approved_by  = '<manager name>',
--     mgmt_override_approved_at  = NOW()
-- WHERE case_id = (SELECT id FROM tx_case WHERE contract_id = 'SLC-13399' AND run_year = 2024 AND run_month = 1)
--   AND staff_id = (SELECT id FROM ref_staff WHERE canonical_name = 'Phạm Thị Lợi');
--
-- 3. Find all overridden payments:
-- SELECT bp.case_id, c.contract_id, s.canonical_name, bp.net_payable,
--        bp.mgmt_override_amount, bp.mgmt_override_reason,
--        bp.net_payable + COALESCE(bp.mgmt_override_amount, 0) AS final_paid
-- FROM tx_bonus_payment bp
-- JOIN tx_case c ON c.id = bp.case_id
-- JOIN ref_staff s ON s.id = bp.staff_id
-- WHERE bp.mgmt_override_amount IS NOT NULL;
