-- ============================================================================
-- Migration 14f — Create app_user table for authentication
-- ============================================================================
-- Purpose:
--   System users with login credentials. Distinct from ref_staff (which is
--   for staff members appearing on cases). A staff member who also logs in
--   has an app_user row whose staff_id points to their ref_staff row.
--   Non-staff users (e.g., a dedicated FO who doesn't appear on cases) have
--   staff_id = NULL.
--
--   password_hash is nullable for now because:
--     1. The auth library isn't chosen until Block 2.
--     2. Seed users (Migration 14k) are inserted with NULL hashes;
--        Block 2 sets real ones via the chosen library (passlib/bcrypt).
--   Once a user has a real hash, they can log in. Until then, login fails
--   cleanly with "no password set" (no security risk).
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, DO block trigger.
--
-- Dependencies:
--   ref_staff must exist (it does — Phase 5). dim_app_role must exist (14e).
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS app_user (
    id                  BIGSERIAL PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    password_hash       TEXT,                       -- nullable; filled in Block 2
    display_name        TEXT NOT NULL,
    staff_id            INTEGER REFERENCES ref_staff(id),
    employment_status   TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (employment_status IN ('ACTIVE', 'INACTIVE')),
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for the most common lookup: by email (login)
CREATE INDEX IF NOT EXISTS idx_app_user_email
    ON app_user (email)
    WHERE employment_status = 'ACTIVE';

-- Index for "find the user account for this staff member"
CREATE INDEX IF NOT EXISTS idx_app_user_staff_id
    ON app_user (staff_id)
    WHERE staff_id IS NOT NULL;

-- updated_at trigger
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'set_updated_at_app_user'
    ) THEN
        CREATE TRIGGER set_updated_at_app_user
            BEFORE UPDATE ON app_user
            FOR EACH ROW
            EXECUTE FUNCTION trg_set_updated_at();
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Table structure
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'app_user'
ORDER BY ordinal_position;
