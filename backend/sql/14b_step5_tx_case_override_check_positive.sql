-- =============================================================================
-- Migration: Enforce positive amounts on tx_case_override
-- =============================================================================
--
-- Rationale:
--   tx_case_override is for MANAGEMENT OVERRIDES only (discretionary, additive,
--   manager-approved bonus adjustments tied to a specific case+staff pair).
--
--   Clawback (policy-driven reversals per Chính_sách §I.5.3) is a separate
--   concept and lives in tx_clawback_balance (per-staff running balance,
--   month-by-month accounting).
--
--   This constraint makes that architectural decision permanent in the schema:
--   negative amounts in tx_case_override are forbidden.
--
-- Source: Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.5.3 (clawback policy)
-- =============================================================================

BEGIN;

-- Idempotent: only add the constraint if it doesn't already exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_constraint
     WHERE conname = 'chk_tx_case_override_amount_positive'
       AND conrelid = 'tx_case_override'::regclass
  ) THEN
    ALTER TABLE tx_case_override
      ADD CONSTRAINT chk_tx_case_override_amount_positive
      CHECK (amount > 0);
  END IF;
END $$;

-- Verify: should return 0 rows (no violations possible since the only existing
-- row is +825,000)
SELECT id, case_id, staff_id, amount, reason
  FROM tx_case_override
 WHERE amount <= 0;

-- Verify: constraint should now exist
SELECT conname, pg_get_constraintdef(oid) AS definition
  FROM pg_constraint
 WHERE conname = 'chk_tx_case_override_amount_positive'
   AND conrelid = 'tx_case_override'::regclass;

COMMIT;
