-- ============================================================================
-- Phase 12a: Priority bonus 25/25/50 split rule infrastructure (SCHEMA ONLY)
-- ============================================================================
-- Adds the schema needed to support per-priority-group payment timing rules,
-- specifically the new "CURRENT_ENROL_25_25_50" rule that defers half of the
-- at-enrolment priority bonus to the visa-receipt month for cases where:
--   (a) enrolment happens before visa (status: Current-Enrolled), AND
--   (b) the priority partner's annual enrolment quota has not yet been met
--
-- Existing behavior (STANDARD_50_50: 50% at enrolment, 50% at year-end) is
-- preserved as the default — all priority groups (including 2024) keep
-- STANDARD_50_50 unless explicitly updated to the new rule.
--
-- This migration is schema-only. Engine code (payment_timing.py, lookups.py,
-- models.py) ships separately as Phase 12b.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. Rule type per priority group
-- ----------------------------------------------------------------------------
ALTER TABLE ref_priority_group
    ADD COLUMN priority_split_rule_type VARCHAR(32) NOT NULL DEFAULT 'STANDARD_50_50'
        CHECK (priority_split_rule_type IN ('STANDARD_50_50', 'CURRENT_ENROL_25_25_50'));

COMMENT ON COLUMN ref_priority_group.priority_split_rule_type IS
'Determines priority bonus payment schedule for cases under this group. '
'STANDARD_50_50: 50% at enrolment + 50% at year-end KPI completion (default). '
'CURRENT_ENROL_25_25_50: For Current-Enrolled cases where institution quota '
'not yet met, 25% at enrolment + 25% at visa+file-closure + 50% at year-end. '
'Cases under this group that are NOT Current-Enrolled (or are beyond quota) '
'still use the STANDARD timing for the at-enrolment portion.';

-- ----------------------------------------------------------------------------
-- 2. Quota tracker
-- ----------------------------------------------------------------------------
-- Per-institution running enrolment count, scoped via priority_list_institution
-- (which is itself year-effective via the parent ref_priority_list's
-- effective_from/to dates). Direct vs sub counts tracked separately to mirror
-- the institution_target_direct / institution_target_sub on
-- ref_priority_list_institution.
CREATE TABLE tx_priority_quota_tracker (
    id                              BIGSERIAL PRIMARY KEY,
    priority_list_institution_id    BIGINT NOT NULL REFERENCES ref_priority_list_institution(id),
    enrolment_count_direct          INTEGER NOT NULL DEFAULT 0
                                        CHECK (enrolment_count_direct >= 0),
    enrolment_count_sub             INTEGER NOT NULL DEFAULT 0
                                        CHECK (enrolment_count_sub >= 0),
    last_updated_run_year           INTEGER,
    last_updated_run_month          INTEGER
                                        CHECK (last_updated_run_month BETWEEN 1 AND 12),
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (priority_list_institution_id)
);

CREATE TRIGGER trg_tx_priority_quota_tracker_updated_at
    BEFORE UPDATE ON tx_priority_quota_tracker
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE INDEX idx_tx_priority_quota_tracker_pli
    ON tx_priority_quota_tracker(priority_list_institution_id);

COMMENT ON TABLE tx_priority_quota_tracker IS
'Running enrolment count per priority partner per year. Consulted by the '
'engine when CURRENT_ENROL_25_25_50 rule is active: determines whether a new '
'Current-Enrolled case is within quota (triggers 25/25 split) or beyond '
'(standard 50% at enrolment). Year-scoping is implicit via the '
'priority_list_institution row, which lives under a year-effective '
'ref_priority_list. Incremented at first-pay; not decremented on cancellation '
'(per business: a committed enrolment counts toward quota even if it later falls through).';

-- ----------------------------------------------------------------------------
-- 3. Priority schedule columns on tx_bonus_payment
-- ----------------------------------------------------------------------------
ALTER TABLE tx_bonus_payment
    ADD COLUMN priority_withheld_amount INTEGER NOT NULL DEFAULT 0
        CHECK (priority_withheld_amount >= 0),
    ADD COLUMN priority_schedule_type   VARCHAR(24) NOT NULL DEFAULT 'STANDARD'
        CHECK (priority_schedule_type IN ('STANDARD', 'SPLIT_25_25_50'));

COMMENT ON COLUMN tx_bonus_payment.priority_withheld_amount IS
'Amount of priority bonus deferred to the visa-receipt month. Non-zero only '
'for cases on SPLIT_25_25_50 schedule before the carry-over event has fired. '
'When the visa-receipt carry-over runs, this amount is released as a separate '
'priority component of net_payable on the carry-over month''s payment row.';

COMMENT ON COLUMN tx_bonus_payment.priority_schedule_type IS
'Locks the priority payment schedule at first-pay. STANDARD = 50% at '
'enrolment (default, current behavior); SPLIT_25_25_50 = 25% at enrolment + '
'25% at visa carry-over. Once stamped at first-pay, subsequent quota state '
'changes do NOT retroactively reschedule this case.';

-- Partial index — only relevant for cases under the new rule
CREATE INDEX idx_tx_bonus_payment_priority_split
    ON tx_bonus_payment(case_id)
    WHERE priority_schedule_type = 'SPLIT_25_25_50';

COMMIT;

-- ============================================================================
-- Verification queries — run after the COMMIT to confirm the migration.
-- ============================================================================

-- All priority groups should show STANDARD_50_50 (the default).
SELECT id, canonical_name, country_id, effective_from, effective_to,
       priority_split_rule_type
FROM ref_priority_group
ORDER BY effective_from, canonical_name;

-- Tracker table exists and is empty.
SELECT 'tx_priority_quota_tracker' AS table_name, COUNT(*) AS row_count
FROM tx_priority_quota_tracker;

-- New columns on tx_bonus_payment.
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name   = 'tx_bonus_payment'
  AND column_name IN ('priority_withheld_amount', 'priority_schedule_type')
ORDER BY column_name;

-- Partial index registered.
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname = 'idx_tx_bonus_payment_priority_split';
