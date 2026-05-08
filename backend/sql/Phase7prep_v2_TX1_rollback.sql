-- =============================================================================
-- Phase7prep v2 — clean rewrite
-- =============================================================================
--
-- Replaces Phase7prep_TX1_schema.sql + Phase7prep_TX2_data.sql.
-- Phase7prep_TX1 deployed earlier introduced a partial schema that doesn't
-- match the final design we converged on. This migration:
--   1. Reverses the schema changes from the deployed Phase7prep_TX1
--   2. Rebuilds the schema with the agreed Group → List → Institution model
--   3. Seeds data including 38 priority Lists, their Groups, targets for 2024
--      and 2025, and all the Phase 6l data fixes
--
-- THREE TRANSACTIONS for safety:
--   TX1 — Rollback: undo what the previous TX1 deployed
--   TX2 — Rebuild schema: create the correct shape
--   TX3 — Seed data
--
-- Run them in pgAdmin one at a time. Verify each NOTICE block before proceeding.
--
-- =============================================================================
-- WHAT THIS MIGRATION DOES — END STATE
-- =============================================================================
--
-- Tables (new or modified):
--
--   ref_priority_group           — every priority Group (includes Navitas, ENZ,
--                                  AND 27 single-institution Groups for
--                                  standalone priority institutions like
--                                  "Macquarie University")
--
--   ref_priority_group_alias     — NEW. Alternative names for Groups.
--
--   ref_priority_list            — RENAMED from ref_priority_partner. Lists are
--                                  the bonus-bearing entities. Every List
--                                  belongs to a Group (no NULL group_id).
--
--   ref_priority_list_alias      — NEW. Alternative names for Lists. Holds the
--                                  9 old name forms (EQI, JCUB, etc.) we found
--                                  in pre-existing data.
--
--   ref_priority_target          — Effective-dated targets per List
--                                  (total/direct/sub/bonus_pct)
--
--   ref_priority_partner_institution — RENAMED to ref_priority_list_institution.
--                                  Effective-dated junction: institution
--                                  belongs to a List during a date range.
--
--   ref_priority_group_partner   — DROPPED. Group membership is now
--                                  ref_priority_list.group_id (every List
--                                  belongs to exactly one Group).
--
--   ref_institution              — is_priority_member column DROPPED. Priority
--                                  status derived from junction + active
--                                  target row.
--
--   ref_partner_classification   — same as previous TX1 design
--   ref_partner_flat_rate        — same as previous TX1 design
--   ref_staff.secondary_role_id  — same as previous TX1 design
--
-- Data:
--   - 27 partner classifications + 12 flat rates (ApplyBoard / Can-Achieve)
--   - 27 single-institution Groups (Macquarie, Curtin, Deakin, etc.)
--   - 2 multi-List Groups (Navitas, ENZ)
--   - 38 Lists across all 29 Groups
--   - 38 List-targets for 2024 (with real bonus_pct from Doc 6)
--   - 38 List-targets for 2025 (with 0% bonus_pct, program paused)
--   - List membership for each non-aggregate List (junction rows)
--   - 9 old name forms moved to ref_priority_list_alias
--   - All 6 Phase 6l sub-agent canonicals + self-aliases
--   - All 4 Phase 6l institution canonicals + aliases (ILA, EQI, Wesley, NT DET)
--   - Victoria University aliases
--   - Lợi.secondary_role_id = CO_DIR
--
-- =============================================================================


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  TRANSACTION 1 — ROLLBACK previously-deployed TX1                          ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1.1 Drop tables that previous TX1 created
-- ─────────────────────────────────────────────────────────────────────────────

DROP TABLE IF EXISTS ref_priority_group_partner;
DROP TABLE IF EXISTS ref_priority_partner_institution;
DROP TABLE IF EXISTS ref_priority_group;
DROP TABLE IF EXISTS ref_partner_flat_rate;
DROP TABLE IF EXISTS ref_partner_classification;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1.2 Drop columns added by previous TX1 to existing tables
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_staff DROP COLUMN IF EXISTS secondary_role_id;
ALTER TABLE ref_institution DROP COLUMN IF EXISTS is_priority_member;
DROP INDEX IF EXISTS idx_ref_institution_priority_member;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1.3 Revert ref_priority_partner.effective_from / effective_to
-- ─────────────────────────────────────────────────────────────────────────────

DROP INDEX IF EXISTS uniq_priority_partner_name_active;

ALTER TABLE ref_priority_partner
    DROP CONSTRAINT IF EXISTS chk_priority_partner_dates;

ALTER TABLE ref_priority_partner
    DROP COLUMN IF EXISTS effective_from,
    DROP COLUMN IF EXISTS effective_to;

-- Restore the unique constraint on name (was dropped by previous TX1)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ref_priority_partner'::regclass
          AND conname = 'ref_priority_partner_name_key'
    ) THEN
        ALTER TABLE ref_priority_partner ADD CONSTRAINT ref_priority_partner_name_key UNIQUE (name);
    END IF;
END$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1.4 Revert ref_priority_target effective-dating
--     Restore the year column (it was dropped) so we can rebuild fresh in TX2
-- ─────────────────────────────────────────────────────────────────────────────

DROP INDEX IF EXISTS uniq_priority_target_active;

ALTER TABLE ref_priority_target
    DROP CONSTRAINT IF EXISTS chk_priority_target_dates;

ALTER TABLE ref_priority_target
    DROP COLUMN IF EXISTS effective_from,
    DROP COLUMN IF EXISTS effective_to;

-- Restore the year column. Since data exists, we set year=2024 for all
-- pre-existing rows (matching pre-flight Check 8 which showed all rows
-- were year=2024).
ALTER TABLE ref_priority_target
    ADD COLUMN IF NOT EXISTS year INTEGER;

UPDATE ref_priority_target SET year = 2024 WHERE year IS NULL;

ALTER TABLE ref_priority_target
    ALTER COLUMN year SET NOT NULL;

-- Restore the original unique constraint on (priority_partner_id, year)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ref_priority_target'::regclass
          AND conname = 'ref_priority_target_priority_partner_id_year_key'
    ) THEN
        ALTER TABLE ref_priority_target
            ADD CONSTRAINT ref_priority_target_priority_partner_id_year_key
            UNIQUE (priority_partner_id, year);
    END IF;
END$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1.5 Revert ref_institution.classification CHECK constraint changes
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_institution
    DROP CONSTRAINT IF EXISTS chk_ref_institution_classification;
ALTER TABLE ref_institution
    DROP CONSTRAINT IF EXISTS chk_ref_institution_classification_interim;

-- Re-add the original check (matches pre-flight Check 9 which showed values
-- IN_SYSTEM_PRIORITY, IN_SYSTEM_REGULAR, OUT_SYSTEM_GROUP, OUT_SYSTEM_MASTER_AGENT)
ALTER TABLE ref_institution
    ADD CONSTRAINT ref_institution_classification_check CHECK (
        classification IN (
            'IN_SYSTEM_REGULAR',
            'IN_SYSTEM_PRIORITY',
            'OUT_SYSTEM_GROUP',
            'OUT_SYSTEM_MASTER_AGENT',
            'UNVERIFIED'
        )
    );


-- ─────────────────────────────────────────────────────────────────────────────
-- TX1 verification — confirm rollback complete
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_dropped INTEGER;
    n_cols    INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_dropped
      FROM information_schema.tables
     WHERE table_name IN (
         'ref_priority_group',
         'ref_priority_group_partner',
         'ref_priority_partner_institution',
         'ref_partner_classification',
         'ref_partner_flat_rate'
     );

    SELECT COUNT(*) INTO n_cols
      FROM information_schema.columns
     WHERE (table_name='ref_staff' AND column_name='secondary_role_id')
        OR (table_name='ref_institution' AND column_name='is_priority_member')
        OR (table_name='ref_priority_partner' AND column_name='effective_from')
        OR (table_name='ref_priority_target' AND column_name='effective_from');

    IF n_dropped <> 0 THEN RAISE EXCEPTION 'TX1 verify: % previous-TX1 tables still present', n_dropped; END IF;
    IF n_cols    <> 0 THEN RAISE EXCEPTION 'TX1 verify: % previous-TX1 columns still present', n_cols; END IF;

    RAISE NOTICE 'TX1 rollback verified — ready for TX2.';
END$$;

COMMIT;

-- =============================================================================
-- END OF TX1. Verify NOTICE 'TX1 rollback verified' before running TX2.
-- =============================================================================
