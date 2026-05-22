-- ============================================================================
-- Phase 15d — Delta-run marking columns on tx_bonus_payment
-- ============================================================================
-- Purpose: per BonusReport Design Spec v1.0 §8, support month-end delta runs
-- by distinguishing rows produced by an original-period run from rows
-- produced by a later delta reconciliation.
--
-- New columns on tx_bonus_payment:
--   source_period_year, source_period_month
--     The period this row attributes to. For normal rows this equals
--     (run_year, run_month). For delta rows, source_period is the closed
--     period being reconciled while (run_year, run_month) is the current
--     period where the addendum pays.
--
--   adjustment_type
--     Discriminator for the kind of row.
--     - NORMAL              : original-run row, source_period = run_period
--     - DELTA_LATE_CASE     : late case picked up by a delta run
--     - DELTA_TIER_UPLIFT   : retroactive tier delta on a previously-paid
--                              row (case_id may be NULL — see §8.3)
--     - DELTA_PRIORITY_UPLIFT : retroactive priority KPI uplift
--
-- Existing rows are backfilled to NORMAL with source_period = run_period.
--
-- Idempotent: uses IF NOT EXISTS and conditional ALTER.
-- ============================================================================

BEGIN;

-- Add columns ----------------------------------------------------------------
ALTER TABLE tx_bonus_payment
  ADD COLUMN IF NOT EXISTS source_period_year  INTEGER,
  ADD COLUMN IF NOT EXISTS source_period_month INTEGER,
  ADD COLUMN IF NOT EXISTS adjustment_type     VARCHAR(32);

-- Backfill existing rows -----------------------------------------------------
-- Every existing row is a normal-run row; its source equals its run period.
UPDATE tx_bonus_payment
SET source_period_year  = run_year,
    source_period_month = run_month,
    adjustment_type     = 'NORMAL'
WHERE adjustment_type IS NULL;

-- Make NOT NULL after backfill ------------------------------------------------
-- These are set in two steps so the backfill above can run safely on a
-- live system. The NOT NULL is enforced for future inserts.

ALTER TABLE tx_bonus_payment
  ALTER COLUMN source_period_year  SET NOT NULL,
  ALTER COLUMN source_period_month SET NOT NULL,
  ALTER COLUMN adjustment_type     SET NOT NULL;

-- Set default for new rows ---------------------------------------------------
-- adjustment_type defaults to NORMAL. The engine writer must explicitly set
-- non-default values for delta rows.
ALTER TABLE tx_bonus_payment
  ALTER COLUMN adjustment_type SET DEFAULT 'NORMAL';

-- CHECK constraint on adjustment_type ----------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_bonus_payment_adjustment_type'
  ) THEN
    ALTER TABLE tx_bonus_payment
      ADD CONSTRAINT chk_tx_bonus_payment_adjustment_type
      CHECK (adjustment_type IN (
        'NORMAL',
        'DELTA_LATE_CASE',
        'DELTA_TIER_UPLIFT',
        'DELTA_PRIORITY_UPLIFT'
      ));
  END IF;
END $$;

-- CHECK constraint: NORMAL rows have source = run ----------------------------
-- This catches engine bugs that would mis-attribute a normal row.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_bonus_payment_normal_source_eq_run'
  ) THEN
    ALTER TABLE tx_bonus_payment
      ADD CONSTRAINT chk_tx_bonus_payment_normal_source_eq_run
      CHECK (
        adjustment_type != 'NORMAL'
        OR
        (source_period_year = run_year AND source_period_month = run_month)
      );
  END IF;
END $$;

-- CHECK constraint: month is 1..12 -------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_bonus_payment_source_month_range'
  ) THEN
    ALTER TABLE tx_bonus_payment
      ADD CONSTRAINT chk_tx_bonus_payment_source_month_range
      CHECK (source_period_month BETWEEN 1 AND 12);
  END IF;
END $$;

-- Indexes --------------------------------------------------------------------
-- Source-period queries are the main forensic pattern: "show me everything
-- attributed to period X, regardless of when it was paid out."
CREATE INDEX IF NOT EXISTS idx_tx_bonus_payment_source_period
  ON tx_bonus_payment (source_period_year, source_period_month, staff_id);

-- Delta-only index for the addendum-report query path
CREATE INDEX IF NOT EXISTS idx_tx_bonus_payment_delta_rows
  ON tx_bonus_payment (source_period_year, source_period_month, adjustment_type)
  WHERE adjustment_type != 'NORMAL';

COMMIT;

-- ============================================================================
-- Verification queries
-- ============================================================================

-- 1) Confirm columns exist and are NOT NULL
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'tx_bonus_payment'
--   AND column_name IN ('source_period_year', 'source_period_month', 'adjustment_type');
-- Expected: 3 rows, all is_nullable = 'NO'.

-- 2) Confirm backfill: every row should have NORMAL adjustment_type
-- SELECT adjustment_type, COUNT(*)
-- FROM tx_bonus_payment
-- GROUP BY adjustment_type
-- ORDER BY adjustment_type;
-- Expected: one row, 'NORMAL', count = total tx_bonus_payment rows.

-- 3) Confirm source_period = run_period for all backfilled rows
-- SELECT COUNT(*) FROM tx_bonus_payment
-- WHERE source_period_year != run_year OR source_period_month != run_month;
-- Expected: 0.

-- 4) Confirm constraints
-- SELECT conname FROM pg_constraint
-- WHERE conname LIKE 'chk_tx_bonus_payment_%';
-- Expected: at least 3 (adjustment_type, normal_source_eq_run, source_month_range).

-- 5) Confirm indexes
-- SELECT indexname FROM pg_indexes
-- WHERE tablename = 'tx_bonus_payment'
--   AND indexname LIKE '%source_period%' OR indexname LIKE '%delta_rows%';
-- Expected: 2 rows.
