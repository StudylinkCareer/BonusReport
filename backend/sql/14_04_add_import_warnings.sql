-- =====================================================================
-- Migration 14_04: Add import_warnings column to tx_case
-- =====================================================================
--
-- Purpose: The new importer writes free-text warning messages from the
-- transformer (UNRESOLVED_COUNSELLOR, SYSTEM_TYPE_MISMATCH, etc.). The
-- existing flag_reason column has a CHECK constraint restricting it to
-- NULL/CORRECTIONS/ASSIGNMENTS — that column is for workflow tagging,
-- not importer warnings. Add a dedicated column so the two purposes
-- don't collide.
--
-- New column is TEXT NULL, no constraint. The transformer concatenates
-- multiple warnings with '; ' separators.
-- =====================================================================

BEGIN;

ALTER TABLE tx_case
    ADD COLUMN import_warnings TEXT NULL;

COMMENT ON COLUMN tx_case.import_warnings IS
    'Free-text warnings produced by the importer transformer. Multiple '
    'warnings concatenated with "; ". Separate from flag_reason (which '
    'is a workflow tag: CORRECTIONS / ASSIGNMENTS).';

-- Verify
SELECT 'New column' AS check_name,
       column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_case'
  AND column_name = 'import_warnings';

-- =====================================================================
-- If verification shows the new column, COMMIT;
-- Otherwise ROLLBACK;
-- =====================================================================
