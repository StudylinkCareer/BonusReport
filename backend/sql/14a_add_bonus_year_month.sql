-- ============================================================================
-- Migration 14a — Add bonus_year_month tag to tx_case
-- ============================================================================
-- Purpose:
--   New column on tx_case to tag every case with the bonus period it belongs
--   to ('YYYY-MM' format). Used for filtering, grouping, and the period
--   dashboard. Distinct from run_year/run_month which the engine uses
--   internally — these can differ in catch-up scenarios.
--
-- Idempotency:
--   Uses ADD COLUMN IF NOT EXISTS. Re-running is safe.
--
-- Dependencies:
--   None. Standalone.
-- ============================================================================

BEGIN;

-- 1. Add the column as nullable first so we can back-fill existing rows
ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS bonus_year_month CHAR(7);

-- 2. Back-fill existing rows from run_year + run_month
--    Format: 'YYYY-MM' with zero-padded month
UPDATE tx_case
SET bonus_year_month =
    LPAD(run_year::text, 4, '0') || '-' || LPAD(run_month::text, 2, '0')
WHERE bonus_year_month IS NULL;

-- 3. Now make it NOT NULL (will fail loudly if any row is still NULL)
ALTER TABLE tx_case
    ALTER COLUMN bonus_year_month SET NOT NULL;

-- 4. Add CHECK constraint enforcing 'YYYY-MM' format
--    Use DO block for idempotency since ADD CONSTRAINT has no IF NOT EXISTS
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tx_case_bonus_year_month_format_check'
    ) THEN
        ALTER TABLE tx_case
            ADD CONSTRAINT tx_case_bonus_year_month_format_check
            CHECK (bonus_year_month ~ '^[0-9]{4}-[0-9]{2}$');
    END IF;
END $$;

-- 5. Index for filtering by period (the most common query pattern)
CREATE INDEX IF NOT EXISTS idx_tx_case_bonus_year_month
    ON tx_case (bonus_year_month);

COMMIT;

-- ============================================================================
-- Verification — run after the migration to confirm everything's right
-- ============================================================================

-- Should return all rows; bonus_year_month populated for every case
SELECT
    bonus_year_month,
    COUNT(*) AS case_count,
    MIN(run_year::text || '-' || LPAD(run_month::text, 2, '0')) AS earliest_run,
    MAX(run_year::text || '-' || LPAD(run_month::text, 2, '0')) AS latest_run
FROM tx_case
GROUP BY bonus_year_month
ORDER BY bonus_year_month;

-- Sanity check: no NULL bonus_year_month
SELECT COUNT(*) AS null_count_should_be_zero
FROM tx_case
WHERE bonus_year_month IS NULL;
