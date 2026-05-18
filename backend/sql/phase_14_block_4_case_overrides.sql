-- ===========================================================================
-- Phase 14 Block 4 — Per-slot case overrides (Phase 1: schema)
--
-- Adds:
--   1. tx_case_override — a 1-to-many child table of tx_case capturing
--      management overrides on a per-staff (per-slot) basis. Modeled on
--      tx_case_service: the case carries multiple override rows, each tied
--      to a staff member assigned to the case.
--
--      Constraint UNIQUE(case_id, staff_id) ensures at most one override
--      per staff per case. "Max 3" is implicit — only counsellor,
--      case_officer, and pre_sales slot columns exist on tx_case today;
--      future slot types extend naturally.
--
--      Staff_id must match one of the case's assigned slots — that's
--      enforced at the BACKEND (Phase 2), not the DB. Encoding it as a
--      DB constraint would require a trigger and rules around slot
--      reassignment edge cases; cleaner to keep it in app logic.
--
--   2. tx_case.calculated_at — timestamp set when the engine writes
--      tx_bonus_payment rows for this case. NULL means "not yet
--      calculated"; populated means "payment rows exist for this case".
--      The frontend uses this to enable/disable the Override editor and
--      the Finalize action on the Submitted board.
--
-- Audit attribution (created_by_user_id, updated_by_user_id) is mandatory:
-- overrides are financially material, we always want to know who set them.
--
-- Idempotent (uses IF NOT EXISTS) so safe to re-run.
-- Verification at end uses SELECT-as-label (pgAdmin-friendly).
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. tx_case_override table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tx_case_override (
    id                   BIGSERIAL PRIMARY KEY,
    case_id              BIGINT  NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    staff_id             INTEGER NOT NULL REFERENCES ref_staff(id),
    amount               INTEGER NOT NULL,
    reason               TEXT    NOT NULL CHECK (length(trim(reason)) > 0),
    created_by_user_id   BIGINT  NOT NULL REFERENCES app_user(id),
    updated_by_user_id   BIGINT  NOT NULL REFERENCES app_user(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, staff_id)
);

CREATE INDEX IF NOT EXISTS idx_tx_case_override_case
    ON tx_case_override (case_id);

COMMENT ON TABLE tx_case_override IS
'Per-staff management overrides on a case, decided pre-calc on the
Submitted board. Engine reads this table at calc time and copies each
row''s amount + reason onto the matching tx_bonus_payment row. Editing
an existing override + re-running Calculate updates the payment row
accordingly.';

COMMENT ON COLUMN tx_case_override.amount IS
'Signed delta in dong. Positive = top-up, negative = clawback. Applied
on top of the engine-calculated net_payable for the matching slot.';

COMMENT ON COLUMN tx_case_override.staff_id IS
'Must match one of counsellor_staff_id, case_officer_staff_id, or
pre_sales_staff_id on the parent tx_case. Backend enforces this.';

-- Wire the updated_at trigger using the existing helper function.
DROP TRIGGER IF EXISTS trg_tx_case_override_updated_at ON tx_case_override;
CREATE TRIGGER trg_tx_case_override_updated_at
BEFORE UPDATE ON tx_case_override
FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- ---------------------------------------------------------------------------
-- 2. tx_case.calculated_at column
-- ---------------------------------------------------------------------------

ALTER TABLE tx_case
ADD COLUMN IF NOT EXISTS calculated_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN tx_case.calculated_at IS
'Set by the engine writer when tx_bonus_payment rows exist for this case.
NULL = engine has not yet calculated this case (no payment rows).
Populated = payment rows exist and overrides can be applied/finalized.
Cleared back to NULL when payment rows are deleted (e.g. before re-calc).';

-- Partial index on calculated cases — useful for the Submitted board which
-- frequently filters/sorts by this flag.
CREATE INDEX IF NOT EXISTS idx_tx_case_calculated
    ON tx_case (calculated_at)
    WHERE calculated_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. Verification — each label-SELECT produces its own result tab in pgAdmin.
--    Run, eyeball, ROLLBACK if anything looks wrong; otherwise COMMIT.
-- ---------------------------------------------------------------------------

SELECT '--- tx_case_override columns ---' AS section;

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'tx_case_override'
ORDER BY ordinal_position;

SELECT '--- tx_case_override constraints (PK, FKs, UNIQUE, CHECK) ---' AS section;

SELECT con.conname AS constraint_name, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'tx_case_override'
ORDER BY con.conname;

SELECT '--- tx_case_override indexes ---' AS section;

SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'tx_case_override'
ORDER BY indexname;

SELECT '--- tx_case_override trigger ---' AS section;

SELECT tgname AS trigger_name
FROM pg_trigger
WHERE tgrelid = 'tx_case_override'::regclass
  AND NOT tgisinternal
ORDER BY tgname;

SELECT '--- tx_case.calculated_at column ---' AS section;

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'tx_case'
  AND column_name = 'calculated_at';

SELECT '--- tx_case partial index on calculated_at ---' AS section;

SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'tx_case'
  AND indexname = 'idx_tx_case_calculated';

COMMIT;
