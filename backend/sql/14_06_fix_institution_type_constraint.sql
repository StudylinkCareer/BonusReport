-- =============================================================================
-- Migration 14_06: Replace tx_case.institution_type CHECK constraint
-- =============================================================================
--
-- The old constraint accepted routing-style values (DIRECT, MASTER_AGENT,
-- GROUP, OUT_OF_SYSTEM, RMIT_VN, OTHER_VN) which conflated two concepts:
--   1. Is the institution in our agreement network?  (system status)
--   2. How was this case routed?                     (routing detail)
--
-- Under the new model (Phase 1 of the long-term institution-classification
-- strategy):
--   * tx_case.institution_type holds the system status, sourced authoritatively
--     from ref_institution_agreement.system_status (IN_SYSTEM / OUT_OF_SYSTEM).
--   * Routing detail (via master agent, via group, direct) is captured via
--     tx_case.referring_partner_id and tx_case.referring_source_type.
--
-- This migration:
--   1. Drops the old constraint
--   2. Adds a new constraint accepting only IN_SYSTEM / OUT_OF_SYSTEM (or NULL)
--   3. Verifies no existing rows would violate the new constraint
-- =============================================================================

BEGIN;

-- Drop the old constraint
ALTER TABLE tx_case
  DROP CONSTRAINT IF EXISTS tx_case_institution_type_chk;

-- Add the new one
ALTER TABLE tx_case
  ADD CONSTRAINT tx_case_institution_type_chk
  CHECK (institution_type IS NULL
         OR institution_type IN ('IN_SYSTEM', 'OUT_OF_SYSTEM'));

-- Verification: any rows that would have violated this? Should return 0.
SELECT
  COUNT(*) AS rows_with_bad_institution_type,
  STRING_AGG(DISTINCT institution_type, ', ') AS bad_values
FROM tx_case
WHERE institution_type IS NOT NULL
  AND institution_type NOT IN ('IN_SYSTEM', 'OUT_OF_SYSTEM');

-- Verification: confirm the new constraint exists with the expected definition
SELECT pg_get_constraintdef(oid) AS new_constraint_def
FROM pg_constraint
WHERE conname = 'tx_case_institution_type_chk';

COMMIT;
