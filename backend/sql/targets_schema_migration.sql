-- =============================================================================
-- Phase 0b: ref_staff_target schema migration
-- =============================================================================
-- Wipes the 249 stub rows (Path A — confirmed with user) and extends the
-- schema to support multiple target types per (staff, year, month) so we can
-- load the parsed monthly target files (CONTRACT / ENROLMENT / CANCELLED /
-- TELESALES) into a single table.
--
-- Changes:
--   1. TRUNCATE — wipe existing 249 rows (stubs from earlier incomplete cleanup)
--   2. Add target_type column (NOT NULL, CHECK in 4 values)
--   3. Add target_unit column (NOT NULL DEFAULT 'COUNT', CHECK in 2 values)
--   4. Change target from INTEGER to NUMERIC(6,2) — handles 0.5/1.5/4.5
--   5. Add UNIQUE constraint (staff_id, year, month, target_type)
--      — one row per target type per staff per month
--      — does NOT include role_id/office_id, since those are intrinsic to the
--        staff member (one row per type, regardless of role/office context)
--
-- Run in pgAdmin Query Tool. Wrapped in BEGIN/COMMIT so it's atomic.
-- =============================================================================

BEGIN;

-- Step 1: Wipe existing stub data
TRUNCATE TABLE ref_staff_target RESTART IDENTITY;

-- Step 2: Add new columns
ALTER TABLE ref_staff_target
    ADD COLUMN target_type VARCHAR(16) NOT NULL,
    ADD COLUMN target_unit VARCHAR(8)  NOT NULL DEFAULT 'COUNT';

-- Step 3: Promote target to NUMERIC for fractional values (0.5, 1.5, 4.5)
ALTER TABLE ref_staff_target
    ALTER COLUMN target TYPE NUMERIC(6, 2) USING target::numeric(6, 2);

-- Step 4: Constrain values
ALTER TABLE ref_staff_target
    ADD CONSTRAINT chk_ref_staff_target_type
        CHECK (target_type IN ('CONTRACT', 'ENROLMENT', 'CANCELLED', 'TELESALES'));

ALTER TABLE ref_staff_target
    ADD CONSTRAINT chk_ref_staff_target_unit
        CHECK (target_unit IN ('COUNT', 'PERCENT'));

-- Step 5: One row per (staff, year, month, target_type)
ALTER TABLE ref_staff_target
    ADD CONSTRAINT uq_ref_staff_target_staff_year_month_type
        UNIQUE (staff_id, year, month, target_type);

-- =============================================================================
-- Verification — should return all columns in the new shape
-- =============================================================================
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default,
    character_maximum_length,
    numeric_precision,
    numeric_scale
FROM information_schema.columns
WHERE table_name = 'ref_staff_target'
ORDER BY ordinal_position;

-- And confirm the CHECK + UNIQUE constraints landed
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'ref_staff_target'::regclass
ORDER BY conname;

-- And the table is empty
SELECT COUNT(*) AS row_count_after_truncate FROM ref_staff_target;

COMMIT;
