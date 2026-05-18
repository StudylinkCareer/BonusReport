-- ============================================================================
-- Migration 14h — Create audit_change_log for field-level change tracking
-- ============================================================================
-- Purpose:
--   Records every field-level change made via PATCH endpoints — old value,
--   new value, who changed it, when. The "all staff can review changes and
--   change records" requirement from In Review phase relies on this.
--
--   Generic by design: works for any table + record id. Backend wraps PATCH
--   endpoints with a helper that diffs old vs new values and inserts one
--   row per changed field.
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.
--
-- Dependencies:
--   14f (app_user). The changed_by_user_id FK references it.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS audit_change_log (
    id                  BIGSERIAL PRIMARY KEY,
    table_name          TEXT NOT NULL,
    record_id           BIGINT NOT NULL,
    field_name          TEXT NOT NULL,
    old_value           TEXT,
    new_value           TEXT,
    changed_by_user_id  BIGINT REFERENCES app_user(id),
    changed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Most common query: "show me all changes to this case"
CREATE INDEX IF NOT EXISTS idx_audit_change_log_record
    ON audit_change_log (table_name, record_id, changed_at DESC);

-- Secondary: "what has this user changed?" (compliance reviews)
CREATE INDEX IF NOT EXISTS idx_audit_change_log_user
    ON audit_change_log (changed_by_user_id, changed_at DESC)
    WHERE changed_by_user_id IS NOT NULL;

-- Tertiary: time-range queries (anomaly detection, daily reports)
CREATE INDEX IF NOT EXISTS idx_audit_change_log_time
    ON audit_change_log (changed_at DESC);

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'audit_change_log'
ORDER BY ordinal_position;

-- Should be empty immediately after migration
SELECT COUNT(*) AS initial_row_count FROM audit_change_log;
