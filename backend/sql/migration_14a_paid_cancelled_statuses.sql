-- ============================================================================
-- Migration 14a: Add Closed-Paid-Cancelled and Closed-Visa-Only-Paid statuses
--
-- Design Decision DD-§I.6:
--   Cases where fees were paid but no enrolment occurred fall into two
--   distinct categories that pay different rates:
--     1. Study abroad with fees paid + cancelled  → OUT_SYSTEM tier rate
--     2. Visa-only contract (485, etc.) with fees → VISA_ONLY tier rate
--   These are tracked as two separate application_status values for
--   reporting clarity (per business team).
--
-- Affects:
--   - ref_status_split (new column + two rows)
--   - tx_case (no schema change; data fix in separate script)
--   - engine code (calc_tier.py, adapter.py — separate patches)
-- ============================================================================

BEGIN;

-- 1. Add the new flag column (idempotent)
ALTER TABLE ref_status_split 
ADD COLUMN IF NOT EXISTS is_visa_only_paid BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN ref_status_split.is_visa_only_paid IS 
'TRUE for visa-only contracts (485, etc.) where fees were paid. Engine pays at TIER_VISA_ONLY rate. Per DD-§I.6.';

-- 2. Insert "Closed - Paid Cancelled" (study-abroad fees-paid pattern)
INSERT INTO ref_status_split (
    status, counts_as_enrolled,
    split_couns_pct, split_co_dir_pct, split_co_sub_pct,
    is_carry_over, is_current_enrolled, is_zero_bonus,
    fees_paid_non_enrolled, is_visa_granted, is_visa_only_paid,
    deduplication_rank, notes
)
VALUES (
    'Closed - Paid Cancelled',
    false,  -- counts_as_enrolled
    1.0, 1.0, 1.0,  -- splits: full payment per tier rate
    false,  -- is_carry_over
    false,  -- is_current_enrolled
    false,  -- is_zero_bonus  ← NOT zero, this status pays
    true,   -- fees_paid_non_enrolled  ← TRIGGERS OUT_SYSTEM tier in engine
    false,  -- is_visa_granted
    false,  -- is_visa_only_paid
    100,    -- deduplication_rank
    'DD-§I.6 — Study abroad case cancelled after service fees collected. Engine pays at OUT_SYSTEM tier rate per role/office.'
)
ON CONFLICT (status) DO NOTHING;

-- 3. Insert "Closed - Visa Only Paid" (visa-only contract, e.g., 485)
INSERT INTO ref_status_split (
    status, counts_as_enrolled,
    split_couns_pct, split_co_dir_pct, split_co_sub_pct,
    is_carry_over, is_current_enrolled, is_zero_bonus,
    fees_paid_non_enrolled, is_visa_granted, is_visa_only_paid,
    deduplication_rank, notes
)
VALUES (
    'Closed - Visa Only Paid',
    false,  -- counts_as_enrolled
    1.0, 1.0, 1.0,  -- splits
    false,  -- is_carry_over
    false,
    false,  -- is_zero_bonus  ← NOT zero
    false,  -- fees_paid_non_enrolled (this is a separate branch)
    false,  -- is_visa_granted  
    true,   -- is_visa_only_paid  ← TRIGGERS VISA_ONLY tier
    100,
    'DD-§I.6 — Visa-only contract (485 work visa, etc.) with service fees paid. Engine pays at VISA_ONLY tier rate per role/office. Institution_id may be NULL.'
)
ON CONFLICT (status) DO NOTHING;

-- 4. Verify
SELECT status, fees_paid_non_enrolled, is_visa_only_paid, is_zero_bonus, notes
FROM ref_status_split
WHERE status IN ('Closed - Paid Cancelled', 'Closed - Visa Only Paid');

COMMIT;
