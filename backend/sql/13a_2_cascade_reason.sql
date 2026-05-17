-- =============================================================================
-- Phase 13a-2: Cascade reversal reason code
-- Adds the reason code used by api_runner.run_engine_cascade_api when it
-- auto-reverses other staff whose priority bonuses become stale due to a
-- staff-scoped re-run.
-- =============================================================================

BEGIN;

INSERT INTO ref_reversal_reason (code, display_name, display_order) VALUES
  ('CASCADE_FROM_PRIORITY_IMPACT', 'Cascade from priority impact', 50)
ON CONFLICT (code) DO NOTHING;

-- Verification: should show 4 active reason codes after this migration
SELECT code, display_name, display_order, active
  FROM ref_reversal_reason
 ORDER BY display_order;

COMMIT;
