-- ============================================================================
-- backend/sql/13b_hotfix_partial_unique_index.sql
--
-- Phase 13b hotfix: tx_bonus_payment uniqueness must allow reversed rows
-- to coexist with new live rows.
--
-- THE BUG:
--   The original unique constraint
--     UNIQUE (case_id, slot, run_year, run_month)
--   was created in Phase 5 when payment rows were assumed to be immutable
--   per (case, slot, period). Phase 13b introduced soft-reversal: rows are
--   flagged with reversal_id but stay in the table for audit. After a
--   cascade reverse + re-run, the engine tries to INSERT new rows for the
--   same (case, slot, period) and the unconditional unique constraint
--   rejects them, even though the existing rows are reversed and no longer
--   "live".
--
-- THE FIX:
--   Replace the unconditional UNIQUE constraint with a partial unique
--   index that only enforces uniqueness on live rows (reversal_id IS NULL).
--   Reversed rows can stack indefinitely for audit history; live rows must
--   still be unique per (case, slot, period).
--
-- SAFETY:
--   - Idempotent (uses IF EXISTS / IF NOT EXISTS).
--   - Self-verifies at end via RAISE EXCEPTION on failure.
--   - Wrapped in BEGIN/COMMIT so partial state is impossible.
--   - Does NOT touch existing data; only the constraint/index definition.
--
-- PRE-CONDITIONS:
--   - All existing rows have reversal_id IS NULL (no reversals yet, since
--     Phase 13b hasn't successfully run). If there were already-reversed
--     rows that violated the new partial index, this migration would
--     fail at the CREATE INDEX step.
--
-- ============================================================================

BEGIN;

-- Step 1: drop the unconditional unique constraint.
-- The auto-generated name from Phase 5's UNIQUE column constraint is
-- tx_bonus_payment_case_id_slot_run_year_run_month_key.
ALTER TABLE tx_bonus_payment
    DROP CONSTRAINT IF EXISTS tx_bonus_payment_case_id_slot_run_year_run_month_key;

-- Step 2: create a partial unique index covering only live rows.
-- Live = reversal_id IS NULL. Reversed rows are exempt from uniqueness
-- and can coexist with new live rows for the same (case, slot, period).
CREATE UNIQUE INDEX IF NOT EXISTS tx_bonus_payment_live_unique_idx
    ON tx_bonus_payment (case_id, slot, run_year, run_month)
    WHERE reversal_id IS NULL;

-- Step 3: self-verify.
DO $$
DECLARE
    old_constraint_exists boolean;
    new_index_exists boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'tx_bonus_payment_case_id_slot_run_year_run_month_key'
    ) INTO old_constraint_exists;

    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
         WHERE indexname = 'tx_bonus_payment_live_unique_idx'
    ) INTO new_index_exists;

    IF old_constraint_exists THEN
        RAISE EXCEPTION
            'Migration failed: old unique constraint % still present',
            'tx_bonus_payment_case_id_slot_run_year_run_month_key';
    END IF;

    IF NOT new_index_exists THEN
        RAISE EXCEPTION
            'Migration failed: new partial unique index % not created',
            'tx_bonus_payment_live_unique_idx';
    END IF;

    RAISE NOTICE
        'Migration 13b_hotfix successful: old unique constraint dropped, '
        'partial unique index tx_bonus_payment_live_unique_idx created '
        '(applies only when reversal_id IS NULL).';
END $$;

COMMIT;

-- ============================================================================
-- POST-MIGRATION VERIFICATION (run as a separate query in pgAdmin):
-- ============================================================================
--
-- SELECT indexname, indexdef
--   FROM pg_indexes
--  WHERE tablename = 'tx_bonus_payment'
--  ORDER BY indexname;
--
-- Expected: tx_bonus_payment_live_unique_idx with definition including
--   "WHERE (reversal_id IS NULL)".
--
-- ============================================================================
