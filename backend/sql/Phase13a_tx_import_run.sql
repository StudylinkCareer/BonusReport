-- =============================================================================
-- Phase 13a — tx_import_run
-- =============================================================================
-- Tracks every CRM xlsx upload to the Railway volume.
--
-- Workflow columns are intentionally minimal (just current_state with a
-- 'pending' default). The full 4-party workflow (Data Quality → Staff →
-- Finance → Senior Manager) will be added in a later migration once spec
-- is finalised. For now, every uploaded file lands in 'pending' and the
-- Review screen reads it the same way.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS tx_import_run (
    id                       BIGSERIAL PRIMARY KEY,
    file_path                TEXT NOT NULL,
    original_filename        VARCHAR(500) NOT NULL,
    run_year                 INT NOT NULL CHECK (run_year BETWEEN 2020 AND 2099),
    run_month                INT NOT NULL CHECK (run_month BETWEEN 1 AND 12),
    uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    inserted_count           INT NOT NULL DEFAULT 0,
    updated_count            INT NOT NULL DEFAULT 0,
    rows_skipped_count       INT NOT NULL DEFAULT 0,
    notes_attached_count     INT NOT NULL DEFAULT 0,
    notes_orphan_count       INT NOT NULL DEFAULT 0,
    error_count              INT NOT NULL DEFAULT 0,
    errors_json              JSONB,
    current_state            VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tx_import_run_period 
    ON tx_import_run (run_year, run_month);

CREATE INDEX IF NOT EXISTS idx_tx_import_run_uploaded_at 
    ON tx_import_run (uploaded_at DESC);

CREATE INDEX IF NOT EXISTS idx_tx_import_run_state 
    ON tx_import_run (current_state);

-- Updated-at trigger (reusing the standard project function)
DROP TRIGGER IF EXISTS trg_tx_import_run_updated_at ON tx_import_run;
CREATE TRIGGER trg_tx_import_run_updated_at
    BEFORE UPDATE ON tx_import_run
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

COMMIT;

-- =============================================================================
-- Verification — should return 1
-- =============================================================================
SELECT COUNT(*) AS table_created
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'tx_import_run';
