-- ============================================================================
-- Migration 14c — Add applies_to gating column to ref_service_fee
--                 + add CONTRACT category if not already present
-- ============================================================================
-- Purpose:
--   The 09_SERVICE_FEE_RATES table (v5.3) gates rate rows by InstitutionType:
--     ALL          — fires for any case
--     DIRECT       — only when tx_case.institution_type='DIRECT'
--     OUT_OF_SYSTEM — only when institution_type='OUT_OF_SYSTEM'
--     MASTER_AGENT — only when institution_type='MASTER_AGENT'
--     PACKAGE      — alias rows used by the engine internally
--
--   We need this column on ref_service_fee so the engine can apply the
--   correct rate based on the case's institution type.
--
--   Also adds 'CONTRACT' as a valid category (used by 3 rows in the v5.3
--   table — OUT_SYSTEM_FULL_AUS, GUARDIAN_AU_ADDON, REFERRAL_LOVELY_COFFEE).
--
-- Idempotency:
--   ADD COLUMN IF NOT EXISTS; defensive constraint replacement using DO block.
--
-- Dependencies:
--   Run BEFORE 14d (which UPSERTs rate rows using this column).
-- ============================================================================

BEGIN;

-- 1. Add the applies_to column with a safe default
ALTER TABLE ref_service_fee
    ADD COLUMN IF NOT EXISTS applies_to VARCHAR(16) NOT NULL DEFAULT 'ALL';

-- 2. CHECK constraint on applies_to
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ref_service_fee_applies_to_check'
    ) THEN
        ALTER TABLE ref_service_fee
            ADD CONSTRAINT ref_service_fee_applies_to_check
            CHECK (applies_to IN ('ALL', 'DIRECT', 'OUT_OF_SYSTEM', 'MASTER_AGENT', 'PACKAGE'));
    END IF;
END $$;

-- 3. Update the category CHECK constraint to include 'CONTRACT'.
--    We do this defensively: find existing constraint, drop, recreate.
DO $$
DECLARE
    existing_constraint_name TEXT;
BEGIN
    -- Find any existing CHECK constraint on the category column
    SELECT con.conname INTO existing_constraint_name
    FROM pg_constraint con
    JOIN pg_class cls ON cls.oid = con.conrelid
    WHERE cls.relname = 'ref_service_fee'
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) LIKE '%category%'
    LIMIT 1;

    -- Drop it if found
    IF existing_constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE ref_service_fee DROP CONSTRAINT %I', existing_constraint_name);
    END IF;

    -- Add the new constraint with CONTRACT included
    ALTER TABLE ref_service_fee
        ADD CONSTRAINT ref_service_fee_category_check
        CHECK (category IN ('SERVICE_FEE', 'ADDON', 'PACKAGE', 'CONTRACT'));
END $$;

-- 4. Index on applies_to for join performance when the engine looks up rates
CREATE INDEX IF NOT EXISTS idx_ref_service_fee_applies_to
    ON ref_service_fee (applies_to, is_active)
    WHERE is_active = TRUE;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- New column visible with correct definition
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'ref_service_fee'
  AND column_name = 'applies_to';

-- All categories present in current data still valid against new constraint
SELECT category, COUNT(*) AS row_count
FROM ref_service_fee
GROUP BY category
ORDER BY category;
