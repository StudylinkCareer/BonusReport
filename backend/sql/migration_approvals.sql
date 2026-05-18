-- ===========================================================================
-- Phase 14 Block 3 — Approval system (B)
--
-- Adds:
--   1. dim_role.requires_case_approval BOOLEAN (default FALSE)
--      Marks which roles need to approve cases they're on. Counsellor + CO
--      roles are seeded TRUE; everyone else stays FALSE (auto-pass).
--
--   2. tx_case_approval.is_override BOOLEAN + override_reason TEXT
--      Distinguishes self-approval from a manager approving on behalf
--      (DQO/Director override). The CHECK constraint enforces three valid
--      states: pending, self-approved, or overridden-with-reason.
--
-- Idempotent (uses IF NOT EXISTS) so it's safe to re-run.
-- Verification at end uses SELECT-as-label (pgAdmin-friendly) instead of
-- psql \echo meta-commands.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. dim_role.requires_case_approval
-- ---------------------------------------------------------------------------

ALTER TABLE dim_role
ADD COLUMN IF NOT EXISTS requires_case_approval BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN dim_role.requires_case_approval IS
'When TRUE, staff assigned to this role on a case must approve the case
before it can advance from in_review to submitted. PRESALES, VP, and
TARGET_OWNER auto-pass (FALSE). DQO/Director can always override.';

-- Seed Counsellor + Case Officer roles to TRUE.
-- Pattern matches all variants (COUNS, COUNS_DIR, CO_DIR, CO_SUB, etc.)
UPDATE dim_role
SET requires_case_approval = TRUE
WHERE code ILIKE 'COUNS%'
   OR code ILIKE 'CO\_%' ESCAPE '\'  -- CO_DIR, CO_SUB
   OR code = 'CO';

-- ---------------------------------------------------------------------------
-- 2. tx_case_approval override columns
-- ---------------------------------------------------------------------------

ALTER TABLE tx_case_approval
ADD COLUMN IF NOT EXISTS is_override BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tx_case_approval
ADD COLUMN IF NOT EXISTS override_reason TEXT;

COMMENT ON COLUMN tx_case_approval.is_override IS
'TRUE when this approval was made by a manager (DQO/ADMIN/DIRECTOR/FO) on
behalf of the slot owner instead of the slot owner self-approving.
Requires override_reason to be populated and non-empty.';

COMMENT ON COLUMN tx_case_approval.override_reason IS
'Mandatory reason when is_override = TRUE. Why did the manager approve on
behalf? Examples: "staff on leave", "ex-employee", "operational urgency".';

-- ---------------------------------------------------------------------------
-- 3. Rewrite CHECK constraint to handle three valid states
-- ---------------------------------------------------------------------------

ALTER TABLE tx_case_approval DROP CONSTRAINT IF EXISTS tx_case_approval_check;

ALTER TABLE tx_case_approval ADD CONSTRAINT tx_case_approval_check CHECK (
    -- State A: pending. No approval recorded.
    (
        approved = false
        AND approved_at IS NULL
        AND approved_by_user_id IS NULL
        AND is_override = false
        AND override_reason IS NULL
    )
    -- State B: self-approval. Staff approved themselves.
    -- (approved_by_user_id MAY be NULL to match pre-existing constraint
    -- permissiveness — though Phase 14 endpoints will always populate it.)
    OR (
        approved = true
        AND approved_at IS NOT NULL
        AND is_override = false
        AND override_reason IS NULL
    )
    -- State C: managerial override. Reason and approver required.
    OR (
        approved = true
        AND approved_at IS NOT NULL
        AND approved_by_user_id IS NOT NULL
        AND is_override = true
        AND override_reason IS NOT NULL
        AND length(trim(override_reason)) > 0
    )
);

-- ---------------------------------------------------------------------------
-- 4. Ensure updated_at trigger is wired (idempotent)
-- ---------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_tx_case_approval_updated_at ON tx_case_approval;
CREATE TRIGGER trg_tx_case_approval_updated_at
BEFORE UPDATE ON tx_case_approval
FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- ---------------------------------------------------------------------------
-- 5. Verification — these SELECTs run inside the transaction so they show
--    the new state. If anything looks wrong, ROLLBACK before COMMIT.
--
--    Each label-SELECT below produces its own result tab in pgAdmin so you
--    can tell the three verification queries apart.
-- ---------------------------------------------------------------------------

SELECT '--- dim_role rows (requires_case_approval should be TRUE for Counsellor + CO) ---' AS section;

SELECT id, code, name, requires_case_approval
FROM dim_role
ORDER BY id;

SELECT '--- tx_case_approval columns (should now include is_override + override_reason) ---' AS section;

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'tx_case_approval'
ORDER BY ordinal_position;

SELECT '--- New CHECK constraint definition ---' AS section;

SELECT pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
WHERE rel.relname = 'tx_case_approval'
  AND con.conname = 'tx_case_approval_check';

COMMIT;
