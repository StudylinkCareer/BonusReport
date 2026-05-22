-- ============================================================================
-- Phase 15a — Sign-off recording columns on tx_case
-- ============================================================================
-- Purpose: support the per-slot sign-off model from BonusReport Design Spec
-- v1.0 §5. Adds columns to tx_case for each named slot capturing:
--   - signed_off_at:        timestamp when the active occupant signed off
--   - signed_off_by:        the user_id who performed the action (may differ
--                           from the slot occupant if a reviewer signed on
--                           behalf)
--   - signoff_snapshot_hash: SHA-256 hash of material case-level facts at
--                           sign-off time, used for the revocation rule
--                           (§5.3). When a material edit changes the facts,
--                           the hash no longer matches and the sign-off is
--                           treated as superseded.
--
-- The four named slots per the existing schema are:
--   counsellor, case_officer, pre_sales, vp
-- (Note: tx_case has both `presales_staff_id` and `pre_sales_staff_id`
-- columns — a known schema duplication. This migration uses the underscored
-- form `pre_sales_*` for consistency with the workflow column naming.
-- A future cleanup migration should consolidate the duplicate.)
--
-- All columns nullable. NULL signed_off_at = not yet signed off.
--
-- Idempotent: uses IF NOT EXISTS clauses.
-- ============================================================================

BEGIN;

-- Counsellor slot ------------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS counsellor_signed_off_at      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS counsellor_signed_off_by      BIGINT,
  ADD COLUMN IF NOT EXISTS counsellor_signoff_snapshot   VARCHAR(64);

-- Case Officer slot ----------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS case_officer_signed_off_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS case_officer_signed_off_by    BIGINT,
  ADD COLUMN IF NOT EXISTS case_officer_signoff_snapshot VARCHAR(64);

-- Pre-sales slot -------------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS pre_sales_signed_off_at       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS pre_sales_signed_off_by       BIGINT,
  ADD COLUMN IF NOT EXISTS pre_sales_signoff_snapshot    VARCHAR(64);

-- VP slot --------------------------------------------------------------------
ALTER TABLE tx_case
  ADD COLUMN IF NOT EXISTS vp_signed_off_at              TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS vp_signed_off_by              BIGINT,
  ADD COLUMN IF NOT EXISTS vp_signoff_snapshot           VARCHAR(64);

-- Indexes to support "find cases awaiting sign-off" queries ------------------
-- One per slot, partial (only rows where the slot is populated AND not yet
-- signed off). Keeps indexes small.

CREATE INDEX IF NOT EXISTS idx_tx_case_counsellor_signoff_pending
  ON tx_case (counsellor_staff_id, workflow_state)
  WHERE counsellor_staff_id IS NOT NULL
    AND counsellor_signed_off_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tx_case_case_officer_signoff_pending
  ON tx_case (case_officer_staff_id, workflow_state)
  WHERE case_officer_staff_id IS NOT NULL
    AND case_officer_signed_off_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tx_case_pre_sales_signoff_pending
  ON tx_case (pre_sales_staff_id, workflow_state)
  WHERE pre_sales_staff_id IS NOT NULL
    AND pre_sales_signed_off_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tx_case_vp_signoff_pending
  ON tx_case (vp_staff_id, workflow_state)
  WHERE vp_staff_id IS NOT NULL
    AND vp_signed_off_at IS NULL;

COMMIT;

-- ============================================================================
-- Verification queries — run these manually after deploy.
-- ============================================================================

-- 1) Confirm columns exist on tx_case
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'tx_case'
--   AND column_name LIKE '%signed_off%' OR column_name LIKE '%signoff%'
-- ORDER BY ordinal_position;
-- Expected: 12 rows (3 columns × 4 slots).

-- 2) Confirm indexes exist
-- SELECT indexname FROM pg_indexes
-- WHERE tablename = 'tx_case'
--   AND indexname LIKE 'idx_tx_case_%_signoff_pending';
-- Expected: 4 rows.

-- 3) Confirm all existing rows have NULL signoff columns (no signed-off cases
--    in legacy data; everything starts fresh).
-- SELECT
--   COUNT(*) FILTER (WHERE counsellor_signed_off_at IS NOT NULL)    AS counsellor_signed,
--   COUNT(*) FILTER (WHERE case_officer_signed_off_at IS NOT NULL)  AS case_officer_signed,
--   COUNT(*) FILTER (WHERE pre_sales_signed_off_at IS NOT NULL)     AS pre_sales_signed,
--   COUNT(*) FILTER (WHERE vp_signed_off_at IS NOT NULL)            AS vp_signed
-- FROM tx_case;
-- Expected: all zero on first deploy.
