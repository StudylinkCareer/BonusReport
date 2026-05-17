-- ============================================================================
-- Phase 17a: User layout variants store
-- ============================================================================
-- Stores per-(acting_as, page_key) named variants of UI layout state.
-- Each row holds: columnOrder, columnPinning, columnVisibility, sorting
-- (and anything else we want to persist in future) as a JSONB blob.
--
-- Keying: acting_as is a hierarchical string emitted by lib/role.ts:
--   'admin'                 — admin persona
--   'persona:director'      — Director role
--   'persona:manager'       — Manager role
--   'persona:quality_officer'
--   'persona:finance_officer'
--   'staff:42'              — real staff member, id=42
--
-- page_key allows future pages to have their own variants. Today only
-- 'import_review' is used.
--
-- One row can be marked is_default=true per (acting_as, page_key) — enforced
-- by a partial unique index. That variant loads automatically when the user
-- visits the page in that persona.
--
-- Run in pgAdmin against the StudyLinkBonusReport server, railway database.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS user_layout (
  id            BIGSERIAL PRIMARY KEY,
  acting_as     VARCHAR(64)   NOT NULL,
  page_key      VARCHAR(64)   NOT NULL,
  variant_name  VARCHAR(64)   NOT NULL,
  is_default    BOOLEAN       NOT NULL DEFAULT false,
  layout_json   JSONB         NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
  CONSTRAINT uq_user_layout_triple UNIQUE (acting_as, page_key, variant_name)
);

-- Fast lookup for the list endpoint (filtered by acting_as + page_key).
CREATE INDEX IF NOT EXISTS idx_user_layout_acting_page
  ON user_layout (acting_as, page_key);

-- At most one default per (acting_as, page_key). Partial index allows
-- multiple rows where is_default=false; only one true-row per pair.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_layout_default
  ON user_layout (acting_as, page_key) WHERE is_default = true;

-- Reuse the existing trigger function (created in earlier migrations).
-- If it doesn't exist in your DB, this migration will fail loudly — that
-- means an earlier migration was skipped and needs running first.
DROP TRIGGER IF EXISTS trg_user_layout_updated_at ON user_layout;
CREATE TRIGGER trg_user_layout_updated_at
BEFORE UPDATE ON user_layout
FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

COMMIT;

-- ============================================================================
-- Verification (run separately after the migration)
-- ============================================================================
-- Should return 4 booleans, all true:

SELECT
  EXISTS(SELECT 1 FROM pg_class    WHERE relname = 'user_layout')                          AS table_created,
  EXISTS(SELECT 1 FROM pg_indexes  WHERE indexname = 'idx_user_layout_acting_page')        AS lookup_idx_created,
  EXISTS(SELECT 1 FROM pg_indexes  WHERE indexname = 'uq_user_layout_default')             AS default_idx_created,
  EXISTS(SELECT 1 FROM pg_trigger  WHERE tgname = 'trg_user_layout_updated_at')            AS trigger_created;
