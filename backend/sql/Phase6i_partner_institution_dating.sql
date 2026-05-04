-- =============================================================================
-- Phase 6i — ref_partner_institution dating layer + bare-* link backfill
-- File:    Phase6i_partner_institution_dating.sql
--
-- Purpose:
--   1. Extend ref_partner_institution to support time-bound link history.
--      Institution↔partner relationships are themselves contracts that
--      change over time (a partner may pick up or drop a school year by
--      year), and the engine must be able to ask "which partner did this
--      case route through, given its contract-signed date?".
--
--   2. Backfill the 14 existing rows with the dating columns and a
--      denormalised partner_type so historical re-classification of a
--      partner doesn't retroactively alter past cases.
--
--   3. Seed 4 additional bare-* links discovered in the review file
--      whose routing partner was identified in reviewer prose
--      (distinct_values_for_review.xlsx — Institution Name tab).
--
-- Design choices (locked, see chat):
--   - partner_type is denormalised on the junction even though it duplicates
--     ref_partner.classification. Reason: when a partner's classification
--     changes, historical case routings preserved on this table should
--     reflect what they were at the time, not what the partner is today.
--   - effective_from defaults to '2024-01-01' because that's the earliest
--     case data we plan to import. effective_to NULL means "still active".
--   - Uniqueness is enforced via a PARTIAL UNIQUE INDEX rather than a
--     plain UNIQUE constraint:
--         UNIQUE (partner_id, institution_id) WHERE effective_to IS NULL
--     This prevents two simultaneously-active links for the same pair
--     while permitting any number of historical (effective_to NOT NULL)
--     rows. Plain unique constraints can't be conditional in PostgreSQL,
--     hence the index form.
--   - Bare-* links missing a partner identification (Stott's Colleges,
--     Cape Breton via "ICEAP" which is not in ref_partner) are NOT seeded
--     here. Importer will flag them as UNRESOLVED-PARTNER for review.
--
-- Idempotent. Safe to re-run.
-- =============================================================================

BEGIN;


-- =============================================================================
-- SECTION 1 — Schema extension
-- =============================================================================
-- Strategy: add partner_type as nullable, backfill, then enforce NOT NULL
-- with a CHECK constraint. This is the standard PostgreSQL pattern for
-- adding a NOT NULL column when no static DEFAULT is appropriate.
-- -----------------------------------------------------------------------------

ALTER TABLE ref_partner_institution
    ADD COLUMN IF NOT EXISTS partner_type    VARCHAR(16),
    ADD COLUMN IF NOT EXISTS effective_from  DATE        NOT NULL DEFAULT DATE '2024-01-01',
    ADD COLUMN IF NOT EXISTS effective_to    DATE,
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW();


-- =============================================================================
-- SECTION 2 — Backfill partner_type from ref_partner.classification
-- =============================================================================
-- Existing rows (14 from Phase 6g + earlier) get partner_type populated
-- from their referenced partner's classification.
-- -----------------------------------------------------------------------------

UPDATE ref_partner_institution AS pi
SET partner_type = p.classification
FROM ref_partner AS p
WHERE p.id = pi.partner_id
  AND pi.partner_type IS NULL;


-- =============================================================================
-- SECTION 3 — Apply NOT NULL + CHECK constraints to partner_type
-- =============================================================================
-- Now that all rows have a value, we can lock down the column.
-- Wrapped in a DO block so re-running doesn't error on already-existing
-- constraints.
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    -- Set NOT NULL if not already
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ref_partner_institution'
          AND column_name = 'partner_type'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE ref_partner_institution
            ALTER COLUMN partner_type SET NOT NULL;
    END IF;

    -- Add CHECK constraint if not already
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'chk_pi_partner_type'
          AND table_name = 'ref_partner_institution'
    ) THEN
        ALTER TABLE ref_partner_institution
            ADD CONSTRAINT chk_pi_partner_type
            CHECK (partner_type IN ('GROUP','MASTER_AGENT'));
    END IF;

    -- Add date sanity constraint if not already
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'chk_pi_effective_dates'
          AND table_name = 'ref_partner_institution'
    ) THEN
        ALTER TABLE ref_partner_institution
            ADD CONSTRAINT chk_pi_effective_dates
            CHECK (effective_to IS NULL OR effective_to >= effective_from);
    END IF;
END $$;


-- =============================================================================
-- SECTION 4 — Replace UNIQUE constraint with partial unique index
-- =============================================================================
-- Old:  UNIQUE (partner_id, institution_id)            -- a constraint
-- New:  UNIQUE INDEX (partner_id, institution_id)
--       WHERE effective_to IS NULL                     -- a partial index
--
-- The partial index allows the same (partner_id, institution_id) pair
-- to recur for historical rows (effective_to NOT NULL), but enforces
-- that at most one row per pair can be currently active (effective_to
-- IS NULL).
--
-- Note: PostgreSQL does not support conditional UNIQUE constraints, so
-- we use a partial UNIQUE INDEX. Functionally equivalent for ON CONFLICT
-- and for general uniqueness checking.
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    old_constraint_name TEXT;
BEGIN
    -- Find and drop the auto-generated UNIQUE(partner_id, institution_id)
    SELECT tc.constraint_name INTO old_constraint_name
    FROM information_schema.table_constraints tc
    WHERE tc.table_name = 'ref_partner_institution'
      AND tc.constraint_type = 'UNIQUE'
      AND EXISTS (
          SELECT 1 FROM information_schema.constraint_column_usage ccu
          WHERE ccu.constraint_name = tc.constraint_name
            AND ccu.column_name = 'partner_id'
      )
      AND EXISTS (
          SELECT 1 FROM information_schema.constraint_column_usage ccu
          WHERE ccu.constraint_name = tc.constraint_name
            AND ccu.column_name = 'institution_id'
      )
    LIMIT 1;

    IF old_constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE ref_partner_institution DROP CONSTRAINT %I',
            old_constraint_name
        );
    END IF;
END $$;

-- Create the partial unique index (idempotent via IF NOT EXISTS).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_pi_active_link
    ON ref_partner_institution (partner_id, institution_id)
    WHERE effective_to IS NULL;


-- =============================================================================
-- SECTION 5 — Attach updated_at trigger (codebase convention)
-- =============================================================================
-- The carry-over states all tables use the trg_set_updated_at trigger
-- function defined in earlier phase migrations. Re-bind it here.
-- -----------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_pi_set_updated_at ON ref_partner_institution;
CREATE TRIGGER trg_pi_set_updated_at
    BEFORE UPDATE ON ref_partner_institution
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();


-- =============================================================================
-- SECTION 6 — Seed bare-* links from reviewer prose
-- =============================================================================
-- The Institution Name review tab contained bare-* rows (no " - <partner>"
-- suffix in the CRM). For 4 of these, the reviewer's notes column named
-- the routing partner unambiguously. We seed those links here.
--
-- ON CONFLICT clause uses the partial unique index from Section 4. Since
-- all rows inserted here have effective_to = NULL, conflicts are decided
-- against currently-active rows for the same (partner_id, institution_id).
--
-- Skipped from this seeding (intentionally):
--   * Cape Breton Language Centre → "ICEAP" — ICEAP not present in
--     ref_partner. Adding ICEAP as a Group is a separate decision; left
--     for human action.
--   * Stott's Colleges * — reviewer did not name a partner.
--   * Victoria University - Sydney City Centre * — reviewer flagged it
--     as "just a campus" naming issue, not a partner-routing case.
-- These will surface from the importer as UNRESOLVED-PARTNER.
--
-- Already covered by Phase 6g (no re-insert needed):
--   * Deakin College → Navitas
--   * TAFE International Western Australia → Link2Uni
-- -----------------------------------------------------------------------------

INSERT INTO ref_partner_institution
    (partner_id, institution_id, partner_type, effective_from, effective_to, notes)
SELECT
    p.id,
    i.id,
    p.classification,
    DATE '2024-01-01',
    NULL::DATE,
    'Phase 6i — bare-* institution; partner from reviewer prose: ' || link.src_note
FROM ref_partner AS p
JOIN (VALUES
    -- (partner_canonical_name,    institution_canonical_name,                     reviewer prose excerpt)
    ('Acknowledge Education',      'Melbourne Language Centre (MLC)',              'Belongs to Group: Acknowledge Education'),
    ('Navitas',                    'Edith Cowan College',                          'Belongs to the Navitas group'),
    ('GEEBEE Education',           'University of Dayton',                         'Part of Master Agent: GEEBEE'),
    ('Navitas',                    'Western Sydney University - Sydney City Campus','Part of Navitas Group')
) AS link(partner_name, inst_name, src_note)
    ON p.name = link.partner_name
JOIN ref_institution AS i
    ON i.canonical_name = link.inst_name
ON CONFLICT (partner_id, institution_id) WHERE effective_to IS NULL DO NOTHING;


-- =============================================================================
-- SECTION 7 — Verification
-- =============================================================================
-- Expected after Phase 6i:
--   pi_total_rows                    = 18  (14 pre-existing + 4 new from Section 6)
--   pi_groups + pi_master_agents     = pi_total_rows
--   pi_phase_6i_new_links            = 4
--   pi_with_effective_to             = 0   (all open-ended for now)
--   pi_with_effective_from_2024      = 18
--
-- The second result set lists institutions reachable via more than one
-- active partner. Worth eyeballing — this is the "many-to-many" reality
-- starting to surface.
-- -----------------------------------------------------------------------------

SELECT 'pi_total_rows'                AS metric, count(*)::text AS value FROM ref_partner_institution
UNION ALL
SELECT 'pi_groups',                   count(*)::text FROM ref_partner_institution WHERE partner_type = 'GROUP'
UNION ALL
SELECT 'pi_master_agents',            count(*)::text FROM ref_partner_institution WHERE partner_type = 'MASTER_AGENT'
UNION ALL
SELECT 'pi_phase_6i_new_links',       count(*)::text FROM ref_partner_institution WHERE notes LIKE 'Phase 6i%'
UNION ALL
SELECT 'pi_with_effective_to',        count(*)::text FROM ref_partner_institution WHERE effective_to IS NOT NULL
UNION ALL
SELECT 'pi_with_effective_from_2024', count(*)::text FROM ref_partner_institution WHERE effective_from = DATE '2024-01-01';


-- Institutions with multiple active partner links — many-to-many surfacing
SELECT
    i.canonical_name AS institution,
    count(*)         AS partner_count,
    string_agg(p.name || ' (' || pi.partner_type || ')', ', ' ORDER BY p.name) AS partners
FROM ref_partner_institution AS pi
JOIN ref_institution AS i ON i.id = pi.institution_id
JOIN ref_partner     AS p ON p.id = pi.partner_id
WHERE pi.effective_to IS NULL
GROUP BY i.canonical_name
HAVING count(*) > 1
ORDER BY i.canonical_name;


COMMIT;
