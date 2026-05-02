-- =============================================================================
-- Phase 6c — Clawback Balance Tracking
-- File:    Phase6c_clawback_balance.sql
-- Purpose: Add tx_clawback_balance table to track running clawback per staff
--          per run-month. Required by §I.5.3 retrospective clawback rule.
-- Target:  PostgreSQL 15+
-- Run:     Once, against the Railway 'railway' database.
-- =============================================================================
-- Background:
--   - §I.5.3 retrospective clawback: when a previously-paid case retroactively
--     fails (visa rejected after payment, customer cancels, partner doesn't
--     pay commission), the bonus that was paid must be clawed back.
--   - The clawback applies against future months' bonuses. If no future
--     bonus is available, staff owes a bank transfer (engine flags this;
--     finance handles collection).
--   - Per Q11.10, clawback persists post-resignation — applies against
--     the §I.6.4 deferred pool.
--   - Pair/team over-target bonus is also subject to clawback per §I.5.3
--     wording "kể cả bonus vượt chỉ tiêu của cặp, đội".
--
-- Design:
--   - One row per (staff_id, run_year, run_month).
--   - balance_owed = positive integer (đồng) — what staff still owes
--   - balance_owed = 0 means clean for that month
--   - The latest month's balance is "current" — engine reads it,
--     applies it to current run's payable, writes the new balance
-- =============================================================================

-- For clean reapplication during development:
-- DROP TABLE IF EXISTS tx_clawback_balance CASCADE;


CREATE TABLE tx_clawback_balance (
    id                  BIGSERIAL PRIMARY KEY,
    staff_id            BIGINT NOT NULL REFERENCES ref_staff(id),
    run_year            INTEGER NOT NULL CHECK (run_year BETWEEN 2020 AND 2099),
    run_month           INTEGER NOT NULL CHECK (run_month BETWEEN 1 AND 12),

    -- Running balance at end of this run-month, in đồng. Always >= 0.
    -- A non-zero balance means: clawback was triggered but no current-month
    -- bonus was available to fully offset it. The remaining amount carries
    -- forward to subsequent months.
    balance_owed        INTEGER NOT NULL DEFAULT 0 CHECK (balance_owed >= 0),

    -- Amount of clawback applied this run (clawed from this month's payable)
    clawback_applied    INTEGER NOT NULL DEFAULT 0 CHECK (clawback_applied >= 0),

    -- Amount of new clawback added this run (cases that retrospectively
    -- failed since the prior run)
    clawback_added      INTEGER NOT NULL DEFAULT 0 CHECK (clawback_added >= 0),

    -- When balance_owed > 0 AND staff has no future bonus to apply against,
    -- finance issues a bank transfer demand. This flag indicates that.
    bank_transfer_required BOOLEAN NOT NULL DEFAULT FALSE,

    -- Audit
    notes               TEXT,
    run_id              BIGINT REFERENCES tx_run(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One row per (staff, run_year, run_month).
    UNIQUE (staff_id, run_year, run_month)
);

CREATE TRIGGER trg_tx_clawback_balance_updated BEFORE UPDATE ON tx_clawback_balance
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE INDEX idx_tx_clawback_balance_staff
    ON tx_clawback_balance (staff_id, run_year DESC, run_month DESC);

COMMENT ON TABLE tx_clawback_balance IS
    '§I.5.3 — Running clawback balance per staff per run-month. '
    'Engine reads latest balance, applies to current month payable, writes new balance.';
COMMENT ON COLUMN tx_clawback_balance.balance_owed IS
    'Amount staff still owes after this month''s clawback application. '
    'Carries forward to next month.';
COMMENT ON COLUMN tx_clawback_balance.bank_transfer_required IS
    'TRUE when balance_owed > 0 and staff has insufficient future bonus to offset. '
    'Finance issues bank transfer demand.';

-- =============================================================================
-- End of Phase 6c
-- =============================================================================
