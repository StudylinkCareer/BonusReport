-- =============================================================================
-- Phase 14 Block 5 / 1 — Draft vs Published bonus payments
-- =============================================================================
--
-- Background
-- ----------
-- Until now, every row in tx_bonus_payment was treated as immediately "live"
-- and the engine refused to overwrite existing rows (LivePaymentRowsExistError).
-- This forced users into the heavy reverse-and-rerun flow even for routine
-- "I'd like to redo this calculation" cases, which doesn't match how the
-- Submitted-board review workflow actually wants to work.
--
-- The new model:
--   * Draft     — published_at IS NULL. Total bonus button writes/overwrites
--                 these freely. Visible only on the Submitted board.
--   * Published — published_at IS NOT NULL. Close button sets this. Visible
--                 in /bonus/yyyy/mm reports. Locked against overwrite — to
--                 change them you'd reverse via the existing tx_bonus_reversal
--                 flow.
--
-- One table, one extra column, one flag. The same rows that the Submitted
-- board displays as drafts become the rows the bonus report displays as
-- published, the instant the Close button fires.
--
-- Existing data
-- -------------
-- Rows currently in tx_bonus_payment were written under the old workflow
-- where "calculated == final". This migration leaves them as drafts
-- (published_at = NULL), which means:
--   * If you re-Total-bonus the period they're in, they get overwritten
--     (which is what you want under the new model)
--   * If you don't, they stay invisible to /bonus/yyyy/mm until promoted
--
-- Run mode: idempotent (re-running this script is a no-op).
-- Target DB: Railway Postgres, run via pgAdmin against the live server.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add the published_at column
-- ---------------------------------------------------------------------------
ALTER TABLE tx_bonus_payment
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN tx_bonus_payment.published_at IS
    'Phase 14 Block 5. NULL = draft (Submitted board only). '
    'Set by the Close/Publish endpoint to lock the row and make it '
    'visible at /bonus/yyyy/mm. Once set, the row is protected from '
    'engine overwrite — changes go through tx_bonus_reversal.';

-- ---------------------------------------------------------------------------
-- 2. Partial index for the "draft rows in this period" lookup
-- ---------------------------------------------------------------------------
-- The two hot paths are:
--   a) Engine re-run: "what draft rows exist for (run_year, run_month)?"
--      Used during the Total-bonus overwrite path to know what to wipe
--      and re-insert.
--   b) Bonus report: "give me published rows for (run_year, run_month)"
--      Plain (run_year, run_month) index already covers this if one exists.
--
-- The partial index is small (only covers unpublished rows) and stays
-- useful as historical periods publish and drop out of it.
CREATE INDEX IF NOT EXISTS idx_tx_bonus_payment_draft_period
    ON tx_bonus_payment (run_year, run_month)
    WHERE published_at IS NULL;

-- ---------------------------------------------------------------------------
-- 3. Self-verification — row counts by state
-- ---------------------------------------------------------------------------
-- These SELECTs run last so pgAdmin shows them as the final result tabs.
-- Compare against expectations:
--   * total_rows: matches your pre-migration row count
--   * draft_rows: equals total_rows (every existing row is now a draft)
--   * published_rows: 0 (nothing is published yet — first publish happens
--                        when the Close button fires from the UI)
SELECT 'tx_bonus_payment column added' AS section;
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_bonus_payment'
  AND column_name = 'published_at';

SELECT 'tx_bonus_payment draft index added' AS section;
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'tx_bonus_payment'
  AND indexname = 'idx_tx_bonus_payment_draft_period';

SELECT 'row counts by state' AS section;
SELECT
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE published_at IS NULL)     AS draft_rows,
    COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published_rows
FROM tx_bonus_payment;

SELECT 'row counts by period (drafts only)' AS section;
SELECT
    run_year,
    run_month,
    COUNT(*) AS draft_row_count
FROM tx_bonus_payment
WHERE published_at IS NULL
GROUP BY run_year, run_month
ORDER BY run_year, run_month;

COMMIT;
