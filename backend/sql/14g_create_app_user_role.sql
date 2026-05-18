-- ============================================================================
-- Migration 14g — Create app_user_role junction table
-- ============================================================================
-- Purpose:
--   Many-to-many between app_user and dim_app_role. A user can hold
--   multiple roles (e.g., FO who is also Admin). Permissions are the
--   UNION of all the user's roles.
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS + composite PK prevents duplicate rows.
--
-- Dependencies:
--   14e (dim_app_role), 14f (app_user).
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS app_user_role (
    user_id         BIGINT  NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_id         INTEGER NOT NULL REFERENCES dim_app_role(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by_user_id BIGINT REFERENCES app_user(id),
    PRIMARY KEY (user_id, role_id)
);

-- Index for "what roles does this user have?" (the role-check middleware)
CREATE INDEX IF NOT EXISTS idx_app_user_role_user
    ON app_user_role (user_id);

-- Index for "who has this role?" (admin queries)
CREATE INDEX IF NOT EXISTS idx_app_user_role_role
    ON app_user_role (role_id);

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Structure
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'app_user_role'
ORDER BY ordinal_position;

-- Confirm constraints (composite PK + 2 FKs)
SELECT con.conname, con.contype, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class cls ON cls.oid = con.conrelid
WHERE cls.relname = 'app_user_role'
ORDER BY con.contype, con.conname;
