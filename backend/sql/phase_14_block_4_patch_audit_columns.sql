-- ===========================================================================
-- Phase 14 Block 4 — Patch: add missing audit columns to tx_case_override
--
-- The earlier Phase 14 Block 4 migration's CREATE TABLE IF NOT EXISTS
-- silently skipped because tx_case_override already existed (from a prior
-- attempt) with a stripped-down schema — no created_by_user_id /
-- updated_by_user_id audit columns. This patch adds them.
--
-- Safe to run only when the table is empty. The DO block asserts that.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Refuse to run if the table has data (would create rows with NULL audit
--    fields, then fail at NOT NULL conversion). Hasn't been used yet but
--    defensive in case anyone manually inserted.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    row_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO row_count FROM tx_case_override;
    IF row_count > 0 THEN
        RAISE EXCEPTION 'tx_case_override has % row(s); add columns as nullable then backfill before making them NOT NULL', row_count;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Add the two audit columns. NOT NULL with FK to app_user.
--    IF NOT EXISTS so re-running is a no-op if they're already present
--    (defensive — shouldn't happen but doesn't hurt).
-- ---------------------------------------------------------------------------

ALTER TABLE tx_case_override
ADD COLUMN IF NOT EXISTS created_by_user_id BIGINT NOT NULL REFERENCES app_user(id);

ALTER TABLE tx_case_override
ADD COLUMN IF NOT EXISTS updated_by_user_id BIGINT NOT NULL REFERENCES app_user(id);

COMMENT ON COLUMN tx_case_override.created_by_user_id IS
'app_user.id of whoever first inserted this override row. Mandatory:
audit trail on financially material data.';

COMMENT ON COLUMN tx_case_override.updated_by_user_id IS
'app_user.id of whoever most recently edited this override row. Mandatory.
On INSERT, equals created_by_user_id; on UPDATE, refreshed to the editor.';

-- ---------------------------------------------------------------------------
-- 3. Verification
-- ---------------------------------------------------------------------------

SELECT '--- tx_case_override columns (should now include created_by_user_id + updated_by_user_id) ---' AS section;

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'tx_case_override'
ORDER BY ordinal_position;

SELECT '--- tx_case_override constraints (PK + FKs + UNIQUE + CHECK) ---' AS section;

SELECT con.conname AS constraint_name, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'tx_case_override'
ORDER BY con.conname;

COMMIT;
