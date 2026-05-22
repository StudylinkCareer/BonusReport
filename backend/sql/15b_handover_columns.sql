-- ============================================================================
-- Phase 15b — Handover successor columns on tx_case
-- ============================================================================
-- Purpose: support the two-occupant model per slot from BonusReport Design
-- Spec v1.0 §10. Each named slot gains:
--   - <slot>_successor_staff_id: the replacement staff member
--   - <slot>_handover_date:      effective date from which successor is the
--                                active occupant
--
-- Resolution rule (read-side, implemented in engine and queries):
--   if <slot>_handover_date IS NULL OR > today
--     → original <slot>_staff_id is active
--   else
--     → <slot>_successor_staff_id is active
--
-- This migration is purely additive. No data migration required: every
-- existing case has handover_date = NULL, so the resolution rule reads the
-- original staff_id unchanged.
--
-- The 13 departure-policy bonus split rules (Chính_sách §I.6) are NOT
-- implemented in this migration. They are policy logic that runs in the
-- engine. This migration only provides the data shape.
--
-- Idempotent: uses IF NOT EXISTS clauses.
-- ============================================================================

BEGIN;

-- Counsellor handover --------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS counsellor_successor_staff_id  BIGINT,
  ADD COLUMN IF NOT EXISTS counsellor_handover_date       DATE;

-- Case Officer handover ------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS case_officer_successor_staff_id BIGINT,
  ADD COLUMN IF NOT EXISTS case_officer_handover_date      DATE;

-- Pre-sales handover ---------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS pre_sales_successor_staff_id    BIGINT,
  ADD COLUMN IF NOT EXISTS pre_sales_handover_date         DATE;

-- VP handover ----------------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS vp_successor_staff_id           BIGINT,
  ADD COLUMN IF NOT EXISTS vp_handover_date                DATE;

-- Foreign-key constraints to dim_staff (separate ALTERs so they survive if
-- the FK already exists from a prior run; PostgreSQL has no IF NOT EXISTS
-- for ADD CONSTRAINT, so we use a DO block to check first).

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tx_case_counsellor_successor'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT fk_tx_case_counsellor_successor
      FOREIGN KEY (counsellor_successor_staff_id) REFERENCES ref_staff(id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tx_case_case_officer_successor'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT fk_tx_case_case_officer_successor
      FOREIGN KEY (case_officer_successor_staff_id) REFERENCES ref_staff(id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tx_case_pre_sales_successor'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT fk_tx_case_pre_sales_successor
      FOREIGN KEY (pre_sales_successor_staff_id) REFERENCES ref_staff(id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tx_case_vp_successor'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT fk_tx_case_vp_successor
      FOREIGN KEY (vp_successor_staff_id) REFERENCES ref_staff(id);
  END IF;
END $$;

-- Check constraints: successor and handover_date are co-dependent.
-- If a successor is set, a handover date must be set (and vice versa).

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_case_counsellor_handover_pair'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT chk_tx_case_counsellor_handover_pair
      CHECK (
        (counsellor_successor_staff_id IS NULL AND counsellor_handover_date IS NULL)
        OR
        (counsellor_successor_staff_id IS NOT NULL AND counsellor_handover_date IS NOT NULL)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_case_case_officer_handover_pair'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT chk_tx_case_case_officer_handover_pair
      CHECK (
        (case_officer_successor_staff_id IS NULL AND case_officer_handover_date IS NULL)
        OR
        (case_officer_successor_staff_id IS NOT NULL AND case_officer_handover_date IS NOT NULL)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_case_pre_sales_handover_pair'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT chk_tx_case_pre_sales_handover_pair
      CHECK (
        (pre_sales_successor_staff_id IS NULL AND pre_sales_handover_date IS NULL)
        OR
        (pre_sales_successor_staff_id IS NOT NULL AND pre_sales_handover_date IS NOT NULL)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tx_case_vp_handover_pair'
  ) THEN
    ALTER TABLE tx_case
      ADD CONSTRAINT chk_tx_case_vp_handover_pair
      CHECK (
        (vp_successor_staff_id IS NULL AND vp_handover_date IS NULL)
        OR
        (vp_successor_staff_id IS NOT NULL AND vp_handover_date IS NOT NULL)
      );
  END IF;
END $$;

COMMIT;

-- ============================================================================
-- Verification queries
-- ============================================================================

-- 1) Confirm columns exist
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'tx_case'
--   AND (column_name LIKE '%_successor_%' OR column_name LIKE '%_handover_date')
-- ORDER BY ordinal_position;
-- Expected: 8 rows.

-- 2) Confirm FK constraints
-- SELECT conname FROM pg_constraint
-- WHERE conname LIKE 'fk_tx_case_%_successor';
-- Expected: 4 rows.

-- 3) Confirm CHECK constraints
-- SELECT conname FROM pg_constraint
-- WHERE conname LIKE 'chk_tx_case_%_handover_pair';
-- Expected: 4 rows.

-- 4) Confirm no legacy data violates the co-dependency rule
-- SELECT COUNT(*) FROM tx_case
-- WHERE counsellor_successor_staff_id IS NOT NULL
--    OR counsellor_handover_date IS NOT NULL
--    OR case_officer_successor_staff_id IS NOT NULL
--    OR case_officer_handover_date IS NOT NULL
--    OR pre_sales_successor_staff_id IS NOT NULL
--    OR pre_sales_handover_date IS NOT NULL
--    OR vp_successor_staff_id IS NOT NULL
--    OR vp_handover_date IS NOT NULL;
-- Expected: 0 on first deploy.
