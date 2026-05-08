-- ============================================================================
-- Phase 12a SUPPLEMENT — add priority_unlocked_amount column to tx_bonus_payment
-- ============================================================================
--
-- Phase 12a as deployed added two columns to tx_bonus_payment for SPLIT_25_25_50
-- support:
--   * priority_withheld_amount    INT NOT NULL DEFAULT 0
--   * priority_schedule_type      VARCHAR(24) NOT NULL DEFAULT 'STANDARD'
--
-- ENGINE_INTEGRATION.md §3 also requires a third column:
--   * priority_unlocked_amount    INT NOT NULL DEFAULT 0
--
-- The engine's BonusPayment dataclass already exposes this field, and
-- payment_timing writes it into audit_json, but for bao cao reporting and a
-- clean record of the release event it should be a first-class column too.
-- net_payable already includes the unlocked amount; this column just surfaces
-- the breakdown for downstream readers.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS. Safe to re-run.
-- Zero behaviour change on its own — engine doesn't read this column, only
-- writes it. Activates when Phase 12b cli.py integration goes live.
-- ============================================================================

BEGIN;

ALTER TABLE tx_bonus_payment
    ADD COLUMN IF NOT EXISTS priority_unlocked_amount INT NOT NULL DEFAULT 0;

COMMENT ON COLUMN tx_bonus_payment.priority_unlocked_amount IS
    'Phase 12b: priority bonus released this run from a prior withhold under '
    'SPLIT_25_25_50. Set when the carry-over branch (visa receipt) releases '
    'the locked-at-start 25%. net_payable already includes this amount; the '
    'column exists for bao cao reporting and as a record of the release event.';

-- ----------------------------------------------------------------------------
-- Verification
-- ----------------------------------------------------------------------------

-- Should return one row with data_type=integer, default=0, nullable=NO
SELECT column_name, data_type, column_default, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'tx_bonus_payment'
   AND column_name = 'priority_unlocked_amount';

-- Should return zero rows (no historical data has been migrated; default applies)
SELECT COUNT(*) AS rows_with_nonzero_unlocked
  FROM tx_bonus_payment
 WHERE priority_unlocked_amount <> 0;

COMMIT;
