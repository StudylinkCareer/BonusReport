-- ============================================================================
-- Migration 14e — Create dim_app_role + seed the 5 roles
-- ============================================================================
-- Purpose:
--   Reference table for application-level roles (separate from dim_role which
--   is for staff role assignments on cases — Counsellor, CO, Pre-sales, etc.)
--
--   Seeded with the 5 roles agreed for the workflow:
--     DIRECTOR  — most-privileged operational role
--     ADMIN     — system administration + everything Director can do
--     FO        — Financial Officer; triggers engine, applies overrides
--     DQO       — Data Quality Officer; owns uploads + validation
--     STAFF     — staff members; scoped to cases where they have a role
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS + ON CONFLICT for the seed inserts.
--
-- Dependencies:
--   None — must come BEFORE 14f (which references this table).
-- ============================================================================

BEGIN;

-- 1. The roles table itself
CREATE TABLE IF NOT EXISTS dim_app_role (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,
    display_name    TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. updated_at trigger (reuses existing trg_set_updated_at function)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'set_updated_at_dim_app_role'
    ) THEN
        CREATE TRIGGER set_updated_at_dim_app_role
            BEFORE UPDATE ON dim_app_role
            FOR EACH ROW
            EXECUTE FUNCTION trg_set_updated_at();
    END IF;
END $$;

-- 3. Seed the 5 roles
INSERT INTO dim_app_role (code, display_name, description) VALUES
    ('DIRECTOR', 'Director',
     'Senior operational authority. Edits in Submitted, applies management overrides, triggers Close.'),
    ('ADMIN',    'Administrator',
     'System administration plus all Director permissions. Manages users and roles.'),
    ('FO',       'Financial Officer',
     'Triggers the bonus engine for a period, applies management overrides, reviews queries from staff.'),
    ('DQO',      'Data Quality Officer',
     'Uploads monthly files, edits Uploaded and Flagged cases, resolves validation flags, moves cases to In Review.'),
    ('STAFF',    'Staff Member',
     'Scoped to cases where the staff member has a role assignment. Edits in In Review, approves own role, views own bonuses.')
ON CONFLICT (code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description  = EXCLUDED.description,
    updated_at   = NOW();

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Expect 5 rows
SELECT id, code, display_name, LEFT(description, 60) AS description_preview
FROM dim_app_role
ORDER BY id;
