-- =============================================================================
-- Phase 6d — tx_case import-tracking columns and notes_staging table
-- File:    Phase6d_import_tracking.sql
-- Purpose: Add the columns the importer needs to handle real-world CRM data
--          where some values are unresolvable, misfiled, or scrappable.
--
-- New columns on tx_case:
--   1. referring_source_type — categorises the referral channel
--   2. import_status         — flags rows for human review
--
-- New table:
--   3. tx_case_notes_staging — human-readable warnings the importer surfaces
--                              for QM/business review during regression.
--
-- Design rationale:
--   - The existing referring_partner_id and referring_sub_agent_id columns
--     allow only "MA partner" or "sub-agent" — but real CRM rows include
--     other patterns: office-only references, asterisks where the specific
--     partner is unknown, and pure direct cases. referring_source_type
--     captures the intent so the engine knows what to do (or skip).
--   - import_status = 'OK' means the importer fully resolved the row.
--     Anything else surfaces in a regression review queue.
--   - notes_staging is a one-many table. A single tx_case row may collect
--     several warnings during import (e.g. system-type mismatch + unresolved
--     institution). Each warning is its own row.
--
-- This migration is non-destructive — pure ADD COLUMN / CREATE TABLE — so it
-- runs cleanly against existing tx_case data (currently empty in this DB).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. referring_source_type — required for every row.
-- -----------------------------------------------------------------------------
-- Values:
--   'PARTNER'      — referring_partner_id is set (Master Agent or Group)
--   'SUB_AGENT'    — referring_sub_agent_id is set (CO_SUB-routed external referrer)
--   'OFFICE_ONLY'  — case originated from a StudyLink office (DN/HN/HCM)
--                    with no external partner; partner/sub_agent both NULL
--   'UNRESOLVED'   — the raw text in referring_agent_text_raw didn't match
--                    any alias; partner/sub_agent both NULL; surfaces for review
--   'NONE'         — direct in-system case, no referrer involved at all
--
-- Default 'NONE' so the importer must explicitly choose; a defaulted-NONE
-- combined with non-NULL referring_*_id signals a logic bug worth catching.

ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS referring_source_type VARCHAR(16) NOT NULL
        DEFAULT 'NONE'
        CHECK (referring_source_type IN ('PARTNER','SUB_AGENT','OFFICE_ONLY','UNRESOLVED','NONE'));

COMMENT ON COLUMN tx_case.referring_source_type IS
    'Type of referral channel for this case. PARTNER = Master Agent or Group; '
    'SUB_AGENT = external CO_SUB referrer; OFFICE_ONLY = office-internal reference; '
    'UNRESOLVED = raw text could not be matched to a partner or sub-agent; '
    'NONE = direct in-system case, no external referrer.';


-- Cross-check: source_type and referring_*_id must agree.
-- (PARTNER ↔ referring_partner_id NOT NULL; SUB_AGENT ↔ referring_sub_agent_id NOT NULL;
--  OFFICE_ONLY/UNRESOLVED/NONE ↔ both NULL.)

ALTER TABLE tx_case
    ADD CONSTRAINT chk_tx_case_source_type_consistency
    CHECK (
        (referring_source_type = 'PARTNER'     AND referring_partner_id   IS NOT NULL AND referring_sub_agent_id IS NULL)
     OR (referring_source_type = 'SUB_AGENT'   AND referring_sub_agent_id IS NOT NULL AND referring_partner_id   IS NULL)
     OR (referring_source_type IN ('OFFICE_ONLY','UNRESOLVED','NONE')
         AND referring_partner_id IS NULL AND referring_sub_agent_id IS NULL)
    );


-- -----------------------------------------------------------------------------
-- 2. import_status — flags rows the importer couldn't fully resolve.
-- -----------------------------------------------------------------------------
-- Values:
--   'OK'                  — fully resolved, engine processes normally
--   'UNRESOLVED'          — at least one column could not be resolved to canonical
--                            (e.g. unknown institution); engine SHOULD NOT process
--   'UNRESOLVED-PARTNER'  — institution carries ** (master agent) suffix but the
--                            specific master agent is not identifiable; engine
--                            cannot apply correct rate; surfaces for review
--   'SCRAP'               — row contains data-entry garbage (date in name field,
--                            etc.); engine SKIPS entirely
--   'WARN-MISMATCH'       — row resolved but with a soft-validation flag
--                            (e.g. system_type implied OUT but institution is
--                            classified IN_SYSTEM); engine processes but the
--                            warning surfaces in regression review

ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS import_status VARCHAR(24) NOT NULL
        DEFAULT 'OK'
        CHECK (import_status IN ('OK','UNRESOLVED','UNRESOLVED-PARTNER','SCRAP','WARN-MISMATCH'));

COMMENT ON COLUMN tx_case.import_status IS
    'Flags how cleanly this row was resolved during import. OK = engine processes; '
    'UNRESOLVED / UNRESOLVED-PARTNER = engine skips, surface for review; '
    'SCRAP = data-entry garbage, ignore; WARN-MISMATCH = engine processes with warning.';


-- Index for queries that filter to "things needing review".
CREATE INDEX IF NOT EXISTS idx_tx_case_import_status
    ON tx_case(import_status)
    WHERE import_status <> 'OK';


-- -----------------------------------------------------------------------------
-- 3. tx_case_notes_staging — multi-warning store per case.
-- -----------------------------------------------------------------------------
-- Each row is one warning the importer wants to surface. A single tx_case
-- may have zero, one, or many notes. Free-form text plus a warning_type code
-- so reviewers can filter.
--
-- Examples of warning_type:
--   'UNRESOLVED_INSTITUTION'   — raw institution text didn't match any alias
--   'UNRESOLVED_PARTNER'       — ** suffix but no partner derivable
--   'SYSTEM_TYPE_MISMATCH'     — System Type column conflicts with institution classification
--   'DEPARTED_STAFF'           — staff member referenced is no longer at company
--   'SCRAP_DATE_IN_TEXT_FIELD' — date value in a text-only field
--   'COUNSELLOR_ROLE_MISFILED' — staff in counsellor column has CO_SUB / CO_DIR role
--   'FREE_TEXT'                — generic note from importer

CREATE TABLE IF NOT EXISTS tx_case_notes_staging (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    warning_type    VARCHAR(32) NOT NULL,
    raw_value       VARCHAR(512),
    note            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tx_case_notes_case   ON tx_case_notes_staging(case_id);
CREATE INDEX IF NOT EXISTS idx_tx_case_notes_type   ON tx_case_notes_staging(warning_type);

COMMENT ON TABLE tx_case_notes_staging IS
    'Per-case warnings emitted by the importer for QM/business regression review. '
    'A single tx_case can have multiple notes. warning_type supports filtering.';


-- -----------------------------------------------------------------------------
-- 4. Verification.
-- -----------------------------------------------------------------------------

SELECT 'tx_case_columns_added' AS metric, count(*)::text AS value
FROM information_schema.columns
WHERE table_name = 'tx_case'
  AND column_name IN ('referring_source_type', 'import_status')

UNION ALL

SELECT 'tx_case_constraints_added', count(*)::text
FROM information_schema.table_constraints
WHERE table_name = 'tx_case'
  AND constraint_name IN ('chk_tx_case_source_type_consistency')

UNION ALL

SELECT 'notes_staging_table_exists', count(*)::text
FROM information_schema.tables
WHERE table_name = 'tx_case_notes_staging'

UNION ALL

SELECT 'notes_staging_indexes', count(*)::text
FROM pg_indexes
WHERE tablename = 'tx_case_notes_staging';

COMMIT;
