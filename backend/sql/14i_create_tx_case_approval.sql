-- ============================================================================
-- Migration 14i (v2) — Create tx_case_approval for multi-party sign-off
-- ============================================================================
-- Purpose:
--   Tracks per-role approvals on each case during the In Review phase.
--   When a case enters In Review, one row is created per (role, staff)
--   from tx_case_role_assignment. Each row tracks whether that specific
--   staff member in that specific role has approved.
--
--   Auto-transition rule: when COUNT(*) FILTER (WHERE NOT approved)
--   for a case drops to zero, the case advances to 'submitted'.
--
--   Per locked design decision: edits do NOT reset approvals.
--   Anyone reviewing changes uses audit_change_log.
--
-- v2 changes:
--   Detects and replaces a pre-existing (stale) tx_case_approval table
--   from earlier experiments. The v1 used CREATE TABLE IF NOT EXISTS,
--   which silently skipped when an older table with a different schema
--   was already present, leading to "column 'approved' does not exist"
--   on the subsequent index.
--
--   Safety guard: refuses to DROP if the existing table has rows.
--
-- Idempotency:
--   Safe to re-run. DROP IF EXISTS handles missing table.
--
-- Dependencies:
--   tx_case, dim_role, ref_staff (exist). 14f (app_user).
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. Safety check + drop the stale table (if any)
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    existing_row_count INTEGER;
    table_exists BOOLEAN;
BEGIN
    -- Check if the table currently exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'tx_case_approval'
    ) INTO table_exists;

    IF table_exists THEN
        -- Count rows in the existing table
        EXECUTE 'SELECT COUNT(*) FROM tx_case_approval' INTO existing_row_count;

        IF existing_row_count > 0 THEN
            RAISE EXCEPTION
                'Refusing to drop tx_case_approval: it has % rows. '
                'Review what is in there before re-running this migration. '
                'If those rows are safe to discard, manually run: '
                'DROP TABLE tx_case_approval CASCADE;',
                existing_row_count;
        END IF;

        -- Table exists but is empty — safe to drop
        DROP TABLE tx_case_approval CASCADE;
        RAISE NOTICE 'Dropped stale (empty) tx_case_approval table.';
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 2. Create the table with the correct schema
-- ----------------------------------------------------------------------------
CREATE TABLE tx_case_approval (
    id                      BIGSERIAL PRIMARY KEY,
    case_id                 BIGINT  NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    role_id                 INTEGER NOT NULL REFERENCES dim_role(id),
    staff_id                INTEGER NOT NULL REFERENCES ref_staff(id),
    approved                BOOLEAN NOT NULL DEFAULT FALSE,
    approved_at             TIMESTAMPTZ,
    approved_by_user_id     BIGINT  REFERENCES app_user(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, role_id, staff_id),
    CHECK ((approved = FALSE AND approved_at IS NULL AND approved_by_user_id IS NULL)
        OR (approved = TRUE  AND approved_at IS NOT NULL))
);

-- ----------------------------------------------------------------------------
-- 3. Indexes
-- ----------------------------------------------------------------------------
CREATE INDEX idx_tx_case_approval_case
    ON tx_case_approval (case_id);

CREATE INDEX idx_tx_case_approval_outstanding
    ON tx_case_approval (case_id)
    WHERE approved = FALSE;

CREATE INDEX idx_tx_case_approval_staff
    ON tx_case_approval (staff_id, approved);

-- ----------------------------------------------------------------------------
-- 4. updated_at trigger
-- ----------------------------------------------------------------------------
CREATE TRIGGER set_updated_at_tx_case_approval
    BEFORE UPDATE ON tx_case_approval
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_updated_at();

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_case_approval'
ORDER BY ordinal_position;

SELECT COUNT(*) AS initial_row_count FROM tx_case_approval;
