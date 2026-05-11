-- =============================================================================
-- Phase 15: Workflow groundwork (revised after Step 3 approval-rule design)
-- =============================================================================
-- Schema changes:
--   1. tx_case.workflow_state           lifecycle: uploaded → in_review → submitted → closed
--   2. tx_case.pre_sales_staff_id       new role slot (FK ref_staff)
--   3. tx_case_approval                 approval event log (full history, no UNIQUE)
--   4. tx_case_edit_log                 edit + comment audit trail
--
-- Backfill rule: existing rows → workflow_state = 'in_review'
--
-- Key decisions reflected in this revision:
--   - tx_case_approval has NO unique constraint on (case_id, staff_id, role_at_approval).
--     Multiple events per (case, staff, role) are expected (approve → revoke → re-approve).
--     Current state is the latest row by created_at.
--   - decision values are only 'APPROVED' and 'REVOKED'. No 'REJECTED' — withholding
--     approval (not creating a row) is the non-approval signal.
--   - tx_case_edit_log.field_name is NULLABLE so general case-level comments can be
--     recorded (e.g. an approver explains why they're withholding without editing a field).
--
-- All idempotent: safe to re-run.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. workflow_state column on tx_case
-- ---------------------------------------------------------------------------
ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS workflow_state TEXT NOT NULL DEFAULT 'in_review'
        CHECK (workflow_state IN ('uploaded', 'in_review', 'submitted', 'closed'));

CREATE INDEX IF NOT EXISTS ix_tx_case_workflow_state
    ON tx_case (workflow_state);


-- ---------------------------------------------------------------------------
-- 2. pre_sales_staff_id column on tx_case
-- ---------------------------------------------------------------------------
ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS pre_sales_staff_id BIGINT
        REFERENCES ref_staff(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_tx_case_pre_sales_staff
    ON tx_case (pre_sales_staff_id)
    WHERE pre_sales_staff_id IS NOT NULL;


-- ---------------------------------------------------------------------------
-- 3. tx_case_edit_log table (must come before tx_case_approval because the
--    approval table references edit_log via revoked_by_edit)
-- ---------------------------------------------------------------------------
-- One row per audit-worthy mutation on a case. Used for:
--   - field-level edits (field_name, old_value, new_value populated)
--   - state transitions (field_name = 'workflow_state', old/new = states)
--   - reversals (field_name = 'workflow_state' + comment from reverser)
--   - general comments (field_name NULL, comment populated)
--
-- field_name is nullable to support that last case.
-- is_material flags whether this edit auto-revokes APPROVALs for the case
-- (computed by app code based on the material-fields list).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tx_case_edit_log (
    id                    BIGSERIAL PRIMARY KEY,
    case_id               BIGINT      NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    field_name            TEXT,
    old_value             TEXT,
    new_value             TEXT,
    is_material           BOOLEAN     NOT NULL DEFAULT FALSE,
    changed_by_staff_id   BIGINT      REFERENCES ref_staff(id) ON DELETE SET NULL,
    comment               TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tx_case_edit_log_case
    ON tx_case_edit_log (case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_tx_case_edit_log_material
    ON tx_case_edit_log (case_id)
    WHERE is_material = TRUE;


-- ---------------------------------------------------------------------------
-- 4. tx_case_approval table  (event log)
-- ---------------------------------------------------------------------------
-- One row per approval event. To find "is this case currently approved by
-- Counsellor?", take the latest row where case_id=X and role_at_approval=
-- 'COUNSELLOR' and check if decision='APPROVED'.
--
-- role_at_approval is captured at the time of the click; if a staff
-- member's primary role changes later, historical approvals remain
-- attributable to the role they held when they approved.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tx_case_approval (
    id                BIGSERIAL PRIMARY KEY,
    case_id           BIGINT      NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    staff_id          BIGINT      NOT NULL REFERENCES ref_staff(id),
    role_at_approval  TEXT        NOT NULL
        CHECK (role_at_approval IN ('COUNSELLOR', 'CASE_OFFICER', 'PRE_SALES', 'DATA_QUALITY', 'FINANCE', 'SENIOR_MANAGER')),
    decision          TEXT        NOT NULL
        CHECK (decision IN ('APPROVED', 'REVOKED')),
    comment           TEXT,
    revoked_by_edit   BIGINT      REFERENCES tx_case_edit_log(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tx_case_approval_case
    ON tx_case_approval (case_id, role_at_approval, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_tx_case_approval_staff
    ON tx_case_approval (staff_id);


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    col_count   INT;
    tbl_count   INT;
    null_states INT;
    unique_constraint_exists BOOLEAN;
    total_cases INT;
BEGIN
    SELECT COUNT(*) INTO col_count
      FROM information_schema.columns
     WHERE table_name = 'tx_case'
       AND column_name IN ('workflow_state', 'pre_sales_staff_id');
    IF col_count <> 2 THEN
        RAISE EXCEPTION 'Phase 15 FAILED: expected 2 new columns on tx_case, found %', col_count;
    END IF;

    SELECT COUNT(*) INTO tbl_count
      FROM information_schema.tables
     WHERE table_name IN ('tx_case_approval', 'tx_case_edit_log');
    IF tbl_count <> 2 THEN
        RAISE EXCEPTION 'Phase 15 FAILED: expected 2 new tables, found %', tbl_count;
    END IF;

    SELECT COUNT(*) INTO null_states
      FROM tx_case WHERE workflow_state IS NULL;
    IF null_states <> 0 THEN
        RAISE EXCEPTION 'Phase 15 FAILED: % cases have NULL workflow_state', null_states;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM pg_constraint c
          JOIN pg_class t ON t.oid = c.conrelid
         WHERE t.relname = 'tx_case_approval'
           AND c.contype = 'u'
    ) INTO unique_constraint_exists;
    IF unique_constraint_exists THEN
        RAISE EXCEPTION 'Phase 15 FAILED: tx_case_approval has a UNIQUE constraint (event log must allow multiple events per case+staff+role)';
    END IF;

    SELECT COUNT(*) INTO total_cases FROM tx_case;

    RAISE NOTICE '=========================================================';
    RAISE NOTICE 'Phase 15 OK';
    RAISE NOTICE '  - tx_case: +workflow_state, +pre_sales_staff_id';
    RAISE NOTICE '  - tx_case_edit_log: field_name nullable, is_material flag, comment';
    RAISE NOTICE '  - tx_case_approval: event-log (no UNIQUE), APPROVED/REVOKED only';
    RAISE NOTICE '  - All % existing cases backfilled to workflow_state = in_review', total_cases;
    RAISE NOTICE '=========================================================';
END $$;

COMMIT;
