-- ============================================================================
-- Migration: 13_02_create_ref_status_alias.sql
-- Date:      2026-05-20
-- Purpose:   Add ref_status_alias table to map CRM-variant status strings
--            to the canonical status in ref_status_split.
--
-- Background: The CRM exports application statuses with minor variations
--   (whitespace, punctuation, parenthesised vs phrased forms). When the
--   importer writes these into tx_case.application_status verbatim, the
--   engine fails to look them up in ref_status_split.
--
--   Example: ref_status_split has 'Closed - Visa granted then enrolled'
--   but 99 tx_case rows store 'Closed - Visa granted, then enrolled'
--   (comma'd variant). The engine raises StatusSplitNotFoundError on
--   all 99 cases.
--
--   Solution: an alias table that the data loader uses to expand the
--   in-memory status_splits dict so EVERY known variant resolves to
--   the same canonical row data, without touching the underlying
--   tx_case data (preserves CRM audit trail).
--
-- Schema:
--   alias_text:    the CRM/external variant as seen in tx_case
--   canonical_status: the canonical status (FK to ref_status_split.status)
--
-- Effective-dating: not used here — status spellings don't change over
--   time meaningfully. If a variant gets retired, just delete its row.
--
-- Idempotent: re-runs safely (ON CONFLICT DO NOTHING on the seed inserts;
--   CREATE TABLE IF NOT EXISTS).
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS ref_status_alias (
    id                BIGSERIAL PRIMARY KEY,
    alias_text        TEXT NOT NULL UNIQUE,
    canonical_status  TEXT NOT NULL,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ref_status_alias_canonical_fk
        FOREIGN KEY (canonical_status)
        REFERENCES ref_status_split(status)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ref_status_alias_canonical
    ON ref_status_alias(canonical_status);

-- Standard updated_at trigger
DROP TRIGGER IF EXISTS trg_ref_status_alias_updated_at ON ref_status_alias;
CREATE TRIGGER trg_ref_status_alias_updated_at
    BEFORE UPDATE ON ref_status_alias
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_updated_at();

-- ----------------------------------------------------------------------------
-- Seed known aliases
-- ----------------------------------------------------------------------------
-- 'Closed - Visa granted, then enrolled' (comma) → canonical without comma.
-- This is the dominant variant in tx_case (99 rows vs 1 of the canonical
-- spelling). We keep the canonical row in ref_status_split untouched and
-- declare the comma'd version as the alias for it.
INSERT INTO ref_status_alias (alias_text, canonical_status, notes) VALUES
    ('Closed - Visa granted, then enrolled',
     'Closed - Visa granted then enrolled',
     'Comma variant exported by CRM; 99/100 tx_case rows use this spelling'),
    ('Closed - Visa granted (plus enrolled)',
     'Closed - Visa granted then enrolled',
     'Parenthesised variant; 1 tx_case row uses this spelling — possibly an old CRM form')
ON CONFLICT (alias_text) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Self-verification
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    alias_count       INTEGER;
    unmatched_count   INTEGER;
BEGIN
    SELECT COUNT(*) INTO alias_count FROM ref_status_alias;
    RAISE NOTICE 'ref_status_alias row count: %', alias_count;

    -- Sanity check: every alias's canonical_status should resolve in ref_status_split
    SELECT COUNT(*) INTO unmatched_count
    FROM ref_status_alias a
    LEFT JOIN ref_status_split s ON s.status = a.canonical_status
    WHERE s.status IS NULL;
    IF unmatched_count > 0 THEN
        RAISE EXCEPTION 'Found % aliases whose canonical_status does not exist in ref_status_split', unmatched_count;
    END IF;

    -- Coverage check: how many tx_case rows currently can't resolve their status?
    -- (post-alias, including aliases)
    SELECT COUNT(DISTINCT c.application_status) INTO unmatched_count
    FROM tx_case c
    WHERE c.application_status IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM ref_status_split s WHERE s.status = c.application_status)
      AND NOT EXISTS (SELECT 1 FROM ref_status_alias a WHERE a.alias_text = c.application_status);
    RAISE NOTICE 'Distinct unmatched tx_case statuses remaining post-alias: %', unmatched_count;
END $$;

COMMIT;

-- ============================================================================
-- Manual verification queries (run after commit):
-- ============================================================================
-- All aliases:
--   SELECT alias_text, canonical_status, notes FROM ref_status_alias ORDER BY alias_text;
--
-- Any tx_case statuses still unmatched after alias expansion?
--   SELECT c.application_status, COUNT(*) AS n
--   FROM tx_case c
--   WHERE c.application_status IS NOT NULL
--     AND NOT EXISTS (SELECT 1 FROM ref_status_split s WHERE s.status = c.application_status)
--     AND NOT EXISTS (SELECT 1 FROM ref_status_alias a WHERE a.alias_text = c.application_status)
--   GROUP BY c.application_status ORDER BY n DESC;
