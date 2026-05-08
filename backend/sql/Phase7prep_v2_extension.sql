-- ============================================================================
-- Phase7prep_v2_extension.sql
--
-- Schema reshape to support the agreement-based model:
--   * Drops ref_institution.classification — in-system status now derived
--     from active agreement existence.
--   * Renames ref_partner_institution → ref_institution_agreement.
--   * Adds agreement_type (DIRECT/VIA_PARTNER), kpi_weight, notes.
--   * Makes partner_id nullable (NULL = direct agreement).
--   * Adds effective_from/to to ref_partner (StudyLink↔partner relationship).
--   * Adds bonus_pct_override and weight_override to
--     ref_priority_list_institution (institution-within-list promotions).
--
-- Backfill rules (per locked policy):
--   * Existing ref_partner_institution rows → VIA_PARTNER agreements with
--     kpi_weight = 0.7 (Master Agent) or 1.0 (Group), per ref_partner.classification.
--   * Institutions without any partner link, currently classified IN_SYSTEM
--     or UNVERIFIED → DIRECT agreements with kpi_weight = 1.0.
--   * All migrated agreements get effective dates 2024-01-01 to 2026-12-31.
--   * ref_partner gets the same date range for the StudyLink↔partner relationship.
--
-- Single transaction. Rolls back atomically if anything fails.
-- ============================================================================

BEGIN;

-- ───────────────────────────────────────────────────────────────────────────
-- Section 1. Pre-flight checks
-- ───────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_pi          INTEGER;
    n_inst        INTEGER;
    n_partner     INTEGER;
    has_classif   BOOLEAN;
    has_pi_table  BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_institution' AND column_name = 'classification'
    ) INTO has_classif;
    IF NOT has_classif THEN
        RAISE EXCEPTION 'Pre-flight failed: ref_institution.classification not found. '
                        'Was Phase7prep_v2 deployed? Or is this migration already applied?';
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_name = 'ref_partner_institution'
    ) INTO has_pi_table;
    IF NOT has_pi_table THEN
        RAISE EXCEPTION 'Pre-flight failed: ref_partner_institution table not found. '
                        'Was Phase 6g deployed? Or is this migration already applied?';
    END IF;

    SELECT COUNT(*) INTO n_pi      FROM ref_partner_institution;
    SELECT COUNT(*) INTO n_inst    FROM ref_institution WHERE merged_into_id IS NULL;
    SELECT COUNT(*) INTO n_partner FROM ref_partner;

    RAISE NOTICE 'Pre-flight: ref_partner_institution rows = %', n_pi;
    RAISE NOTICE 'Pre-flight: ref_institution rows (active) = %', n_inst;
    RAISE NOTICE 'Pre-flight: ref_partner rows = %', n_partner;
END$$;


-- ───────────────────────────────────────────────────────────────────────────
-- Section 2. Add validity period columns to ref_partner (Q1-B)
-- ───────────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_partner' AND column_name = 'effective_from'
    ) THEN
        ALTER TABLE ref_partner
            ADD COLUMN effective_from DATE NOT NULL DEFAULT '2024-01-01';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_partner' AND column_name = 'effective_to'
    ) THEN
        ALTER TABLE ref_partner ADD COLUMN effective_to DATE;
    END IF;
END$$;

UPDATE ref_partner
   SET effective_to = '2026-12-31'
 WHERE effective_to IS NULL;


-- ───────────────────────────────────────────────────────────────────────────
-- Section 3. Rename ref_partner_institution → ref_institution_agreement
--            and reshape its columns.
-- ───────────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ref_partner_institution')
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ref_institution_agreement')
    THEN
        ALTER TABLE ref_partner_institution RENAME TO ref_institution_agreement;
    END IF;
END$$;

-- Make partner_id nullable (DIRECT agreements have NULL partner)
ALTER TABLE ref_institution_agreement
    ALTER COLUMN partner_id DROP NOT NULL;

-- Drop the redundant partner_type column. Its values matched ref_partner.classification
-- 100% across all existing rows; agreement_type + partner_id now serve the same purpose.
ALTER TABLE ref_institution_agreement
    DROP COLUMN IF EXISTS partner_type;

-- Add agreement_type (nullable for now, populated then made NOT NULL)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_institution_agreement'
           AND column_name = 'agreement_type'
    ) THEN
        ALTER TABLE ref_institution_agreement
            ADD COLUMN agreement_type VARCHAR(16);
    END IF;
END$$;

UPDATE ref_institution_agreement
   SET agreement_type = 'VIA_PARTNER'
 WHERE partner_id IS NOT NULL
   AND agreement_type IS NULL;

-- Add CHECK constraints (idempotent — drop-then-add ensures clean state)
ALTER TABLE ref_institution_agreement
    ALTER COLUMN agreement_type SET NOT NULL;

ALTER TABLE ref_institution_agreement
    DROP CONSTRAINT IF EXISTS chk_agreement_type;
ALTER TABLE ref_institution_agreement
    ADD CONSTRAINT chk_agreement_type
        CHECK (agreement_type IN ('DIRECT', 'VIA_PARTNER'));

ALTER TABLE ref_institution_agreement
    DROP CONSTRAINT IF EXISTS chk_agreement_consistency;
ALTER TABLE ref_institution_agreement
    ADD CONSTRAINT chk_agreement_consistency
        CHECK (
            (agreement_type = 'DIRECT'      AND partner_id IS NULL)
         OR (agreement_type = 'VIA_PARTNER' AND partner_id IS NOT NULL)
        );

-- Add kpi_weight (nullable for now, populated then made NOT NULL)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_institution_agreement'
           AND column_name = 'kpi_weight'
    ) THEN
        ALTER TABLE ref_institution_agreement
            ADD COLUMN kpi_weight DECIMAL(3,2);
    END IF;
END$$;

-- Backfill kpi_weight from partner classification
UPDATE ref_institution_agreement ria
   SET kpi_weight = CASE
       WHEN p.classification = 'MASTER_AGENT' THEN 0.7
       WHEN p.classification = 'GROUP'        THEN 1.0
   END
  FROM ref_partner p
 WHERE ria.partner_id = p.id
   AND ria.kpi_weight IS NULL;

-- All rows should now have kpi_weight; enforce NOT NULL and add CHECK
ALTER TABLE ref_institution_agreement
    ALTER COLUMN kpi_weight SET NOT NULL;

ALTER TABLE ref_institution_agreement
    DROP CONSTRAINT IF EXISTS chk_kpi_weight;
ALTER TABLE ref_institution_agreement
    ADD CONSTRAINT chk_kpi_weight
        CHECK (kpi_weight >= 0 AND kpi_weight <= 9.99);

-- Add notes column for audit trail (idempotent — column already exists from
-- ref_partner_institution in some deployments, so guard it).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_institution_agreement'
           AND column_name = 'notes'
    ) THEN
        ALTER TABLE ref_institution_agreement ADD COLUMN notes TEXT;
    END IF;
END$$;

-- Set default effective_from/effective_to for existing rows where missing
UPDATE ref_institution_agreement
   SET effective_from = '2024-01-01'
 WHERE effective_from IS NULL;

UPDATE ref_institution_agreement
   SET effective_to = '2026-12-31'
 WHERE effective_to IS NULL;

-- Add a note on existing rows
UPDATE ref_institution_agreement
   SET notes = 'Migrated from ref_partner_institution by Phase7prep_v2_extension'
 WHERE notes IS NULL;


-- ───────────────────────────────────────────────────────────────────────────
-- Section 4. Insert DIRECT agreements for institutions with no partner link
--            (currently classified IN_SYSTEM or UNVERIFIED)
-- ───────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    has_classif BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_institution' AND column_name = 'classification'
    ) INTO has_classif;

    IF has_classif THEN
        -- First-time migration: filter to IN_SYSTEM / UNVERIFIED institutions
        EXECUTE $sql$
            INSERT INTO ref_institution_agreement
                (institution_id, agreement_type, partner_id, kpi_weight,
                 effective_from, effective_to, notes)
            SELECT i.id, 'DIRECT', NULL, 1.0,
                   DATE '2024-01-01', DATE '2026-12-31',
                   'Phase7prep_v2_extension: direct StudyLink-institution agreement '
                   'for institution with no Master-Agent or Group partnership at migration time.'
              FROM ref_institution i
             WHERE i.merged_into_id IS NULL
               AND i.classification IN ('IN_SYSTEM', 'UNVERIFIED')
               AND NOT EXISTS (
                   SELECT 1 FROM ref_institution_agreement ria
                    WHERE ria.institution_id = i.id
                      AND ria.effective_to IS NOT NULL
                      AND ria.effective_to >= DATE '2024-01-01'
               )
        $sql$;
    ELSE
        -- Re-run after classification dropped: insert DIRECT for any active
        -- institution that still has no agreement
        EXECUTE $sql$
            INSERT INTO ref_institution_agreement
                (institution_id, agreement_type, partner_id, kpi_weight,
                 effective_from, effective_to, notes)
            SELECT i.id, 'DIRECT', NULL, 1.0,
                   DATE '2024-01-01', DATE '2026-12-31',
                   'Phase7prep_v2_extension re-run: direct StudyLink-institution '
                   'agreement (classification column already dropped).'
              FROM ref_institution i
             WHERE i.merged_into_id IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM ref_institution_agreement ria
                    WHERE ria.institution_id = i.id
                      AND ria.effective_to IS NOT NULL
                      AND ria.effective_to >= DATE '2024-01-01'
               )
        $sql$;
    END IF;
END$$;


-- ───────────────────────────────────────────────────────────────────────────
-- Section 5. Drop ref_institution.classification — superseded by agreements
-- ───────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_institution DROP COLUMN IF EXISTS classification;


-- ───────────────────────────────────────────────────────────────────────────
-- Section 6. Add override columns to ref_priority_list_institution
-- ───────────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_priority_list_institution'
           AND column_name = 'bonus_pct_override'
    ) THEN
        ALTER TABLE ref_priority_list_institution
            ADD COLUMN bonus_pct_override DECIMAL(4,3)
                CHECK (bonus_pct_override IS NULL
                    OR (bonus_pct_override >= 0 AND bonus_pct_override <= 9.999));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_priority_list_institution'
           AND column_name = 'weight_override'
    ) THEN
        ALTER TABLE ref_priority_list_institution
            ADD COLUMN weight_override DECIMAL(3,2)
                CHECK (weight_override IS NULL
                    OR (weight_override >= 0 AND weight_override <= 9.99));
    END IF;
END$$;


-- ───────────────────────────────────────────────────────────────────────────
-- Section 7. Update legacy code references (nothing to do in DB; flagged for
--            transformer.py and resolvers.py to be updated post-deploy)
-- ───────────────────────────────────────────────────────────────────────────

-- (No SQL — code update is out-of-band.)


-- ───────────────────────────────────────────────────────────────────────────
-- Section 8. Verification
-- ───────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_via_partner       INTEGER;
    n_direct            INTEGER;
    n_total_agreements  INTEGER;
    n_active_inst       INTEGER;
    n_inst_with_agr     INTEGER;
    n_inst_without_agr  INTEGER;
    n_partner_dates     INTEGER;
    n_priority_overrides INTEGER;
    classif_still_there BOOLEAN;
    weight_07_count     INTEGER;
    weight_10_count     INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_via_partner
      FROM ref_institution_agreement
     WHERE agreement_type = 'VIA_PARTNER';

    SELECT COUNT(*) INTO n_direct
      FROM ref_institution_agreement
     WHERE agreement_type = 'DIRECT';

    n_total_agreements := n_via_partner + n_direct;

    SELECT COUNT(*) INTO n_active_inst
      FROM ref_institution
     WHERE merged_into_id IS NULL;

    SELECT COUNT(DISTINCT institution_id) INTO n_inst_with_agr
      FROM ref_institution_agreement
     WHERE effective_to IS NOT NULL AND effective_to >= DATE '2024-01-01';

    n_inst_without_agr := n_active_inst - n_inst_with_agr;

    SELECT COUNT(*) INTO n_partner_dates
      FROM ref_partner
     WHERE effective_from = DATE '2024-01-01' AND effective_to = DATE '2026-12-31';

    SELECT COUNT(*) INTO n_priority_overrides
      FROM information_schema.columns
     WHERE table_name = 'ref_priority_list_institution'
       AND column_name IN ('bonus_pct_override', 'weight_override');

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'ref_institution' AND column_name = 'classification'
    ) INTO classif_still_there;

    SELECT COUNT(*) INTO weight_07_count
      FROM ref_institution_agreement WHERE kpi_weight = 0.7;

    SELECT COUNT(*) INTO weight_10_count
      FROM ref_institution_agreement WHERE kpi_weight = 1.0;

    RAISE NOTICE '=== Phase7prep_v2_extension verification ===';
    RAISE NOTICE 'Total agreements created: %', n_total_agreements;
    RAISE NOTICE '  VIA_PARTNER agreements:  %', n_via_partner;
    RAISE NOTICE '  DIRECT agreements:       %', n_direct;
    RAISE NOTICE '  Weight 0.7 (Master Agent): %', weight_07_count;
    RAISE NOTICE '  Weight 1.0 (Direct/Group): %', weight_10_count;
    RAISE NOTICE 'Active institutions:        %', n_active_inst;
    RAISE NOTICE '  With ≥1 agreement:        %', n_inst_with_agr;
    RAISE NOTICE '  Without any agreement:    %', n_inst_without_agr;
    RAISE NOTICE 'ref_partner rows w/ correct dates: %', n_partner_dates;
    RAISE NOTICE 'Override columns added (expect 2): %', n_priority_overrides;
    RAISE NOTICE 'classification column dropped: %', NOT classif_still_there;

    -- Hard assertions
    IF n_inst_without_agr > 0 THEN
        RAISE EXCEPTION 'Verification failed: % active institutions have no agreement', n_inst_without_agr;
    END IF;

    IF n_priority_overrides <> 2 THEN
        RAISE EXCEPTION 'Verification failed: expected 2 override columns, got %', n_priority_overrides;
    END IF;

    IF classif_still_there THEN
        RAISE EXCEPTION 'Verification failed: ref_institution.classification still exists';
    END IF;

    IF weight_07_count + weight_10_count <> n_total_agreements THEN
        RAISE EXCEPTION 'Verification failed: agreement weight values not all 0.7 or 1.0';
    END IF;

    RAISE NOTICE 'Phase7prep_v2_extension verification PASSED.';
END$$;

COMMIT;

-- ============================================================================
-- END OF Phase7prep_v2_extension.sql
-- ============================================================================
