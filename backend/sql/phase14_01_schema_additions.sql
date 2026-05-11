-- ============================================================
-- Phase 14 Migration 1: Schema additions for institution master list
-- Generated: 2026-05-10T05:53:31.287828
-- 
-- Adds:
--   1. UNIQUE constraint on ref_institution.canonical_name
--   2. system_status VARCHAR column on ref_institution_agreement
--   3. Unique index on ref_institution_agreement for idempotent inserts
--
-- Idempotent: yes (uses IF NOT EXISTS / DO blocks)
-- ============================================================

BEGIN;

-- 1. UNIQUE constraint on ref_institution.canonical_name
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_ref_institution_canonical_name'
      AND conrelid = 'ref_institution'::regclass
  ) THEN
    ALTER TABLE ref_institution
      ADD CONSTRAINT uq_ref_institution_canonical_name UNIQUE (canonical_name);
  END IF;
END $$;

-- 2. system_status column on ref_institution_agreement
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'ref_institution_agreement'
      AND column_name = 'system_status'
  ) THEN
    ALTER TABLE ref_institution_agreement
      ADD COLUMN system_status VARCHAR(16) NOT NULL DEFAULT 'IN_SYSTEM';
  END IF;
END $$;

-- 3. CHECK constraint on system_status values
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chk_system_status'
      AND conrelid = 'ref_institution_agreement'::regclass
  ) THEN
    ALTER TABLE ref_institution_agreement
      ADD CONSTRAINT chk_system_status
      CHECK (system_status IN ('IN_SYSTEM', 'OUT_OF_SYSTEM'));
  END IF;
END $$;

-- 4. Unique index on (institution_id, partner_id-or-direct, effective_from)
--    Enables ON CONFLICT for idempotent inserts in Migration 5
CREATE UNIQUE INDEX IF NOT EXISTS uq_ref_institution_agreement_natural
  ON ref_institution_agreement (institution_id, COALESCE(partner_id, 0), effective_from);

COMMIT;

-- ============================================================
-- Verification queries (run these after the migration)
-- ============================================================

-- Should return 1: UNIQUE on canonical_name
SELECT COUNT(*) AS unique_constraint_present
FROM pg_constraint
WHERE conname = 'uq_ref_institution_canonical_name';

-- Should return 1: system_status column exists with default 'IN_SYSTEM'
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'ref_institution_agreement'
  AND column_name = 'system_status';

-- Should return 1: CHECK constraint exists
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname = 'chk_system_status';

-- Should return 1: unique index exists
SELECT indexname FROM pg_indexes
WHERE tablename = 'ref_institution_agreement'
  AND indexname = 'uq_ref_institution_agreement_natural';

-- Sanity: existing 122 rows should all show system_status='IN_SYSTEM' (the default)
SELECT system_status, COUNT(*) FROM ref_institution_agreement GROUP BY system_status;
