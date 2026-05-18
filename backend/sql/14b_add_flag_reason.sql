-- ============================================================================
-- Migration 14b — Add flag_reason to tx_case (Flagged sub-state of Uploaded)
-- ============================================================================
-- Purpose:
--   Adds a flag_reason column to indicate validation issues. The case stays
--   in workflow_state='uploaded' but flag_reason is non-null. Two valid
--   values: 'CORRECTIONS' (data quality issue) or 'ASSIGNMENTS' (same
--   person in multiple roles on one case).
--
--   When flag_reason IS NULL → clean uploaded row, ready to move to in_review.
--   When flag_reason IS NOT NULL → DQO/Admin must fix before transitioning.
--
-- Design note:
--   We do NOT add 'flagged' as a separate workflow_state value. The state
--   is still 'uploaded'; flag_reason is metadata. This keeps the workflow
--   state machine simple (still 4 states) and lets the UI split the
--   Uploaded pillar into "Clean" vs "Flagged" tabs by filtering on this
--   column.
--
-- Idempotency:
--   ADD COLUMN IF NOT EXISTS + DO block for the CHECK constraint.
--
-- Dependencies:
--   None. Standalone.
-- ============================================================================

BEGIN;

-- 1. Add the column (nullable — most cases will have no flag)
ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS flag_reason TEXT;

-- 2. CHECK constraint limiting values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tx_case_flag_reason_check'
    ) THEN
        ALTER TABLE tx_case
            ADD CONSTRAINT tx_case_flag_reason_check
            CHECK (flag_reason IS NULL OR flag_reason IN ('CORRECTIONS', 'ASSIGNMENTS'));
    END IF;
END $$;

-- 3. Partial index — only over flagged rows (the typical query pattern is
--    "show me everything that needs attention")
CREATE INDEX IF NOT EXISTS idx_tx_case_flagged
    ON tx_case (workflow_state, flag_reason)
    WHERE flag_reason IS NOT NULL;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Column exists with correct definition
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_case'
  AND column_name = 'flag_reason';

-- Count any existing flagged rows (should be 0 immediately after this migration)
SELECT flag_reason, COUNT(*) AS count
FROM tx_case
WHERE flag_reason IS NOT NULL
GROUP BY flag_reason;
