-- =====================================================================
-- Migration 14_02: Importer v2 schema changes
-- =====================================================================
--
-- Purpose: Schema changes to support the rewritten importer.
--   1. Add application_status_id (FK to ref_status_split.id) — the
--      CANONICAL status. Importer resolves raw text via alias table,
--      stores the resolved id here. Engine joins on this id (not text).
--   2. Add unique constraint on (contract_id, run_year, run_month) —
--      enables UPSERT semantics in the new writer.
--   3. Drop tx_case_notes_staging — warnings now go inline into
--      tx_case.flag_reason.
--
-- Pre-conditions (already verified before writing this):
--   * tx_case has only tx_case_pkey (PRIMARY KEY on id) — no UQ on
--     (contract_id, run_year, run_month) yet
--   * ref_status_split.id is BIGINT NOT NULL (PK)
--   * tx_case is currently EMPTY (Migration 14_01 truncated it)
--   * tx_case_notes_staging is currently EMPTY (truncated by 14_01)
--
-- Wraps in BEGIN/COMMIT. Review the verification output BEFORE running
-- COMMIT. If anything looks wrong, run ROLLBACK and nothing changed.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Step 1: Add application_status_id column to tx_case
-- ---------------------------------------------------------------------

ALTER TABLE tx_case
    ADD COLUMN application_status_id BIGINT NULL
        REFERENCES ref_status_split(id);

COMMENT ON COLUMN tx_case.application_status_id IS
    'Canonical status resolved from raw application_status text via '
    'ref_status_split_alias. Engine reads from this column. '
    'NULL when the raw text could not be resolved (row will have '
    'import_status=''UNRESOLVED'' and flag_reason populated).';

-- Index to make engine JOINs fast
CREATE INDEX IF NOT EXISTS idx_tx_case_application_status_id
    ON tx_case(application_status_id)
    WHERE application_status_id IS NOT NULL;

-- ---------------------------------------------------------------------
-- Step 2: Add unique constraint for UPSERT dedup key
-- ---------------------------------------------------------------------

-- The new writer UPSERTs by (contract_id, run_year, run_month).
-- This constraint enforces one tx_case row per case-per-month.
ALTER TABLE tx_case
    ADD CONSTRAINT uq_tx_case_contract_run
        UNIQUE (contract_id, run_year, run_month);

-- ---------------------------------------------------------------------
-- Step 3: Drop tx_case_notes_staging
-- ---------------------------------------------------------------------

-- This table received orphan notes from skipped/blocked rows.
-- Under the new design, every row lands in tx_case and warnings are
-- written inline to tx_case.flag_reason. No staging needed.
DROP TABLE IF EXISTS tx_case_notes_staging;

-- ---------------------------------------------------------------------
-- Verification — review BEFORE committing
-- ---------------------------------------------------------------------

-- Verify new column exists
SELECT '1. New column' AS check_name,
       column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_case'
  AND column_name = 'application_status_id';

-- Verify FK constraint
SELECT '2. FK constraint' AS check_name,
       con.conname AS name,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'tx_case'
  AND con.contype = 'f'
  AND pg_get_constraintdef(con.oid) LIKE '%ref_status_split%';

-- Verify unique constraint
SELECT '3. Unique constraint' AS check_name,
       con.conname AS name,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'tx_case'
  AND con.contype = 'u';

-- Verify staging table is gone
SELECT '4. Staging table dropped' AS check_name,
       CASE WHEN EXISTS (
         SELECT 1 FROM information_schema.tables
         WHERE table_name = 'tx_case_notes_staging'
       ) THEN 'STILL EXISTS — error'
         ELSE 'gone (good)'
       END AS status;

-- Verify the new index
SELECT '5. New index' AS check_name,
       indexname, indexdef
FROM pg_indexes
WHERE tablename = 'tx_case'
  AND indexname = 'idx_tx_case_application_status_id';

-- =====================================================================
-- If all 5 checks look right, run:    COMMIT;
-- If anything looks wrong, run:        ROLLBACK;
-- =====================================================================
