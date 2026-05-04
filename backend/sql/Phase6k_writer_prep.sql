-- =============================================================================
-- Phase 6k — Schema prep for writer.py
-- File:    Phase6k_writer_prep.sql
--
-- Three small changes:
--
-- 1. tx_case_notes_staging.case_id becomes NULLable. Orphan notes (warnings
--    for rows that were skipped during import — missing contract_id, no
--    resolvable office, etc.) need to be persisted but have no case row to
--    attach to. Per chat 2026-05-03 (Q3 = Option A).
--
-- 2. tx_case_notes_staging gains run_year and run_month columns. Without
--    them, orphan notes lose run context entirely (notes attached to a
--    case_id can join through tx_case to find the run; orphans have no
--    such link). Both nullable to preserve backward compatibility with
--    any existing rows.
--
-- 3. tx_case gains a UNIQUE constraint on (contract_id, run_year, run_month).
--    Per chat (Q1 = Option B): re-importing a row should UPDATE the existing
--    tx_case row in place. ON CONFLICT requires a unique constraint to
--    target. Implemented as a unique index for symmetry with Phase 6i/6j.
--
-- Idempotent. Safe to re-run.
-- =============================================================================

BEGIN;


-- ---- Section 1 — staging.case_id becomes nullable -------------------------

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tx_case_notes_staging'
          AND column_name = 'case_id'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE tx_case_notes_staging
            ALTER COLUMN case_id DROP NOT NULL;
    END IF;
END $$;


-- ---- Section 2 — staging gains run_year + run_month -----------------------

ALTER TABLE tx_case_notes_staging
    ADD COLUMN IF NOT EXISTS run_year  INTEGER,
    ADD COLUMN IF NOT EXISTS run_month INTEGER;


-- ---- Section 3 — UNIQUE on tx_case for ON CONFLICT ------------------------
-- The writer's idempotency design uses ON CONFLICT (contract_id, run_year,
-- run_month) DO UPDATE. This unique index is what ON CONFLICT targets.
--
-- If existing tx_case rows already violate this uniqueness, this CREATE
-- will fail loudly — the operator will need to clean up duplicates first.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_tx_case_contract_run
    ON tx_case (contract_id, run_year, run_month);


COMMIT;


-- =============================================================================
-- Verification
-- =============================================================================

SELECT 'staging_case_id_nullable' AS metric,
       (CASE WHEN is_nullable = 'YES' THEN 'YES' ELSE 'NO' END) AS value
FROM information_schema.columns
WHERE table_name = 'tx_case_notes_staging' AND column_name = 'case_id'

UNION ALL

SELECT 'staging_has_run_year', count(*)::text
FROM information_schema.columns
WHERE table_name = 'tx_case_notes_staging' AND column_name = 'run_year'

UNION ALL

SELECT 'staging_has_run_month', count(*)::text
FROM information_schema.columns
WHERE table_name = 'tx_case_notes_staging' AND column_name = 'run_month'

UNION ALL

SELECT 'tx_case_unique_index_exists', count(*)::text
FROM pg_indexes
WHERE tablename = 'tx_case' AND indexname = 'uniq_tx_case_contract_run'

UNION ALL

SELECT 'tx_case_total_rows', count(*)::text FROM tx_case
UNION ALL
SELECT 'staging_total_rows',  count(*)::text FROM tx_case_notes_staging;
