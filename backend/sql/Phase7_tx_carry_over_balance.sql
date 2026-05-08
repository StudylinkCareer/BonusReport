-- =====================================================================
-- Phase 7 — tx_carry_over_balance
-- Date: 2026-05-05
--
-- Tracks carry-over withholdings (the 50% withheld when status is
-- "Current - Enrolled") with explicit open/closed lifecycle:
--
--   * is_open=TRUE:  the withholding is pending release. Engine looks
--                    these up via prior_withholdings_by_case_staff.
--   * is_open=FALSE: the withholding has been released to a payment
--                    (the released_* columns record where + when).
--
-- One row per (case_id, staff_id, lifecycle): the partial unique index
-- enforces "at most one open balance per (case, staff)" while still
-- allowing many closed balances over a case's full audit history.
--
-- Engine writes to this table via persist_payments(). Carry-over
-- supersede in payment_timing.py reads from it via the data layer
-- loader (load_open_carry_overs).
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS tx_carry_over_balance (
    id                      BIGSERIAL PRIMARY KEY,
    case_id                 BIGINT NOT NULL REFERENCES tx_case(id),
    staff_id                BIGINT NOT NULL REFERENCES ref_staff(id),

    -- Origination ----------------------------------------------------
    withheld_amount         INTEGER  NOT NULL CHECK (withheld_amount > 0),
    withheld_run_year       INTEGER  NOT NULL,
    withheld_run_month      INTEGER  NOT NULL CHECK (withheld_run_month BETWEEN 1 AND 12),
    withheld_status_code    VARCHAR(64) NOT NULL,

    -- Release (filled when carry-over fires) -------------------------
    released_amount         INTEGER,
    released_run_year       INTEGER,
    released_run_month      INTEGER  CHECK (released_run_month IS NULL OR released_run_month BETWEEN 1 AND 12),
    released_status_code    VARCHAR(64),

    is_open                 BOOLEAN NOT NULL DEFAULT TRUE,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Open rows must have NULL release fields; closed rows must have
    -- all release fields populated. Prevents inconsistent states.
    CONSTRAINT chk_carry_over_release_consistency
        CHECK (
            (is_open = TRUE
                AND released_amount IS NULL AND released_run_year IS NULL
                AND released_run_month IS NULL AND released_status_code IS NULL)
         OR (is_open = FALSE
                AND released_amount IS NOT NULL AND released_run_year IS NOT NULL
                AND released_run_month IS NOT NULL AND released_status_code IS NOT NULL)
        )
);

-- Only one open balance per (case, staff). Closed balances unrestricted.
CREATE UNIQUE INDEX IF NOT EXISTS uq_carry_over_open
    ON tx_carry_over_balance (case_id, staff_id)
    WHERE is_open = TRUE;

-- General lookup index for joining by case
CREATE INDEX IF NOT EXISTS idx_carry_over_case
    ON tx_carry_over_balance (case_id);

-- updated_at trigger using the existing convention
CREATE TRIGGER trg_tx_carry_over_balance_set_updated_at
    BEFORE UPDATE ON tx_carry_over_balance
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- =====================================================================
-- Verification
-- =====================================================================

SELECT 'V0: table created' AS check_name;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_carry_over_balance'
ORDER BY ordinal_position;

SELECT 'V1: indexes' AS check_name;
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'tx_carry_over_balance';

SELECT 'V2: row count (expect 0 — fresh table)' AS check_name;
SELECT COUNT(*) AS row_count FROM tx_carry_over_balance;

COMMIT;
