-- ============================================================================
-- Phase 15c — Engine audit tables
-- ============================================================================
-- Purpose: per BonusReport Design Spec v1.0 §11, create the two-table audit
-- trail for every engine invocation:
--   - tx_engine_run:       one row per engine invocation, captures the
--                          run-level context (trigger, scope, counts).
--   - tx_engine_row_write: one row per payment row considered, captures
--                          before/after snapshots even when no change was
--                          made (NO_CHANGE entries support forensic queries).
--
-- The instrumentation is added before any behavioural change to the engine
-- (per spec §16 step 2), so we have a forensic baseline against the existing
-- period-wide-rewrite behaviour before refactoring it.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- tx_engine_run
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tx_engine_run (
  id                    BIGSERIAL PRIMARY KEY,

  -- The kind of run. Constrained by CHECK below.
  -- ORIGINAL  - first-time calc for a case (currently: period-wide rewrite
  --             during transition; eventually: case-scoped auto-recalc on
  --             entry to Submitted)
  -- RECALC    - manual mgmt recompute on selected cases or staff-period
  -- PROFORMA  - preview-only, no writes (still gets an audit row for the
  --             read-compute work and so user actions are traceable)
  -- DELTA     - month-end delta run (§8)
  -- REVERSAL  - engine-run rollback per §12.3
  run_type              VARCHAR(16) NOT NULL,

  -- The user who triggered this run. NULL = system/automatic trigger
  -- (auto-recalc on Submitted entry).
  triggered_by_user_id  BIGINT,

  -- Human-readable description of why the run fired. Examples:
  --   "auto-promote of SLC-13399 to Submitted"
  --   "mgmt manual recalc of staff_id=9 period 2024-01"
  --   "delta run for period 2024-01 triggered by mgmt"
  --   "rollback of engine_run_id=42"
  trigger_reason        TEXT NOT NULL,

  -- The trigger inputs. JSON arrays for forensic query.
  --   case_ids_scope:      case_ids passed as the trigger (the user's intent)
  --   staff_ids_affected:  the staff fanned out to (the actual blast radius)
  case_ids_scope        JSONB NOT NULL DEFAULT '[]'::jsonb,
  staff_ids_affected    JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- The period this run operates on. For DELTA runs, this is the source
  -- period being reconciled (not the run period where the addendum pays).
  period_year           INTEGER,
  period_month          INTEGER,

  -- Timing
  started_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at          TIMESTAMPTZ,

  -- Outcome counts. Populated when the run finishes. The three numbers
  -- should equal the count of tx_engine_row_write entries with each action.
  rows_inserted         INTEGER NOT NULL DEFAULT 0,
  rows_updated          INTEGER NOT NULL DEFAULT 0,
  rows_unchanged        INTEGER NOT NULL DEFAULT 0,

  -- Error capture. If the run failed, status describes the outcome.
  --   SUCCESS    - completed without error
  --   FAILED     - aborted; rows_* counts may be partial
  --   IN_PROGRESS - started, not yet completed (transient state)
  status                VARCHAR(16) NOT NULL DEFAULT 'IN_PROGRESS',
  error_message         TEXT,

  -- Rollback marker. When non-NULL, this run has been rolled back via a
  -- subsequent REVERSAL run. The reversal run's id is in rolled_back_by_run_id.
  rolled_back_at        TIMESTAMPTZ,
  rolled_back_by_run_id BIGINT REFERENCES tx_engine_run(id),

  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_engine_run_type CHECK (
    run_type IN ('ORIGINAL', 'RECALC', 'PROFORMA', 'DELTA', 'REVERSAL')
  ),
  CONSTRAINT chk_engine_run_status CHECK (
    status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED')
  )
);

-- Trigger to maintain updated_at on UPDATE.
DROP TRIGGER IF EXISTS trg_tx_engine_run_set_updated_at ON tx_engine_run;
CREATE TRIGGER trg_tx_engine_run_set_updated_at
  BEFORE UPDATE ON tx_engine_run
  FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- Indexes ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tx_engine_run_period
  ON tx_engine_run (period_year, period_month, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_tx_engine_run_user
  ON tx_engine_run (triggered_by_user_id, started_at DESC)
  WHERE triggered_by_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tx_engine_run_type
  ON tx_engine_run (run_type, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_tx_engine_run_in_progress
  ON tx_engine_run (started_at)
  WHERE status = 'IN_PROGRESS';

-- ----------------------------------------------------------------------------
-- tx_engine_row_write
-- ----------------------------------------------------------------------------
-- One entry per payment row considered. INSERT/UPDATE/NO_CHANGE actions
-- all get an entry; NO_CHANGE entries prove the engine considered the row
-- and chose not to change it.

CREATE TABLE IF NOT EXISTS tx_engine_row_write (
  id                BIGSERIAL PRIMARY KEY,

  engine_run_id     BIGINT NOT NULL REFERENCES tx_engine_run(id),

  -- The payment row affected. For INSERT, this is the id of the newly-
  -- created row (set after the INSERT). For UPDATE/NO_CHANGE, the existing
  -- row id.
  bonus_payment_id  BIGINT NOT NULL REFERENCES tx_bonus_payment(id),

  action            VARCHAR(12) NOT NULL,

  -- Snapshot of the row's full state before the write. NULL for INSERT
  -- (no prior state). Captures everything needed to reconstruct the row
  -- if rollback is requested (§12.3).
  old_value_json    JSONB,

  -- Snapshot after the write. For NO_CHANGE, this equals old_value_json.
  new_value_json    JSONB NOT NULL,

  -- True if mgmt_override_amount was carried forward from old to new.
  -- Audit clarity: explicitly state when the engine respected an existing
  -- override vs. when no override was present.
  override_preserved BOOLEAN NOT NULL DEFAULT FALSE,

  written_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_engine_row_write_action CHECK (
    action IN ('INSERT', 'UPDATE', 'NO_CHANGE')
  ),

  -- INSERT must not have old_value_json. UPDATE/NO_CHANGE must.
  CONSTRAINT chk_engine_row_write_old_value_presence CHECK (
    (action = 'INSERT' AND old_value_json IS NULL)
    OR
    (action IN ('UPDATE', 'NO_CHANGE') AND old_value_json IS NOT NULL)
  )
);

-- Indexes ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tx_engine_row_write_run
  ON tx_engine_row_write (engine_run_id, action);

CREATE INDEX IF NOT EXISTS idx_tx_engine_row_write_payment
  ON tx_engine_row_write (bonus_payment_id, written_at DESC);

-- Partial index for the common "show me actual changes" forensic query
CREATE INDEX IF NOT EXISTS idx_tx_engine_row_write_changes
  ON tx_engine_row_write (engine_run_id, written_at)
  WHERE action != 'NO_CHANGE';

COMMIT;

-- ============================================================================
-- Verification queries
-- ============================================================================

-- 1) Confirm tables exist
-- SELECT table_name FROM information_schema.tables
-- WHERE table_name IN ('tx_engine_run', 'tx_engine_row_write');
-- Expected: 2 rows.

-- 2) Confirm trigger exists on tx_engine_run
-- SELECT tgname FROM pg_trigger
-- WHERE tgname = 'trg_tx_engine_run_set_updated_at';
-- Expected: 1 row.

-- 3) Confirm CHECK constraints
-- SELECT conname FROM pg_constraint
-- WHERE conrelid IN ('tx_engine_run'::regclass, 'tx_engine_row_write'::regclass)
--   AND contype = 'c';
-- Expected: 3 rows (chk_engine_run_type, chk_engine_run_status,
--           chk_engine_row_write_action, chk_engine_row_write_old_value_presence
--           — actually 4).

-- 4) Insert a smoke-test row to confirm the schema accepts what the engine
--    code will write. Roll back so we leave no test data.
-- BEGIN;
-- INSERT INTO tx_engine_run (run_type, trigger_reason, case_ids_scope, period_year, period_month)
-- VALUES ('PROFORMA', 'schema smoke test', '[1,2,3]'::jsonb, 2024, 1);
-- SELECT * FROM tx_engine_run WHERE trigger_reason = 'schema smoke test';
-- ROLLBACK;
