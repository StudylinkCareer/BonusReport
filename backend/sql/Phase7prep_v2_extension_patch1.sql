-- ============================================================================
-- Phase7prep_v2_extension_patch1.sql
--
-- Backdate the migration's effective_from from 2024-01-01 to 2023-01-01.
-- The 2024-01-01 was arbitrary; the actual partner/institution relationships
-- pre-date that. SLC-13615 (signed 2023-12-13) surfaced the issue during
-- importer smoke testing.
--
-- Affects: ref_partner, ref_institution_agreement.
--
-- Idempotent: only updates rows still at 2024-01-01.
-- Single transaction.
-- ============================================================================

BEGIN;

-- ───────────────────────────────────────────────────────────────────────────
-- 1. Backdate ref_partner.effective_from
-- ───────────────────────────────────────────────────────────────────────────

UPDATE ref_partner
   SET effective_from = '2023-01-01'
 WHERE effective_from = '2024-01-01';


-- ───────────────────────────────────────────────────────────────────────────
-- 2. Backdate ref_institution_agreement.effective_from
-- ───────────────────────────────────────────────────────────────────────────

UPDATE ref_institution_agreement
   SET effective_from = '2023-01-01'
 WHERE effective_from = '2024-01-01';


-- ───────────────────────────────────────────────────────────────────────────
-- 3. Verification
-- ───────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_partner_2023      INTEGER;
    n_partner_other     INTEGER;
    n_agree_2023        INTEGER;
    n_agree_other       INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_partner_2023
      FROM ref_partner WHERE effective_from = '2023-01-01';
    SELECT COUNT(*) INTO n_partner_other
      FROM ref_partner WHERE effective_from <> '2023-01-01';

    SELECT COUNT(*) INTO n_agree_2023
      FROM ref_institution_agreement WHERE effective_from = '2023-01-01';
    SELECT COUNT(*) INTO n_agree_other
      FROM ref_institution_agreement WHERE effective_from <> '2023-01-01';

    RAISE NOTICE '=== Phase7prep_v2_extension_patch1 verification ===';
    RAISE NOTICE 'ref_partner rows at 2023-01-01:           %  (expect 27)', n_partner_2023;
    RAISE NOTICE 'ref_partner rows at other date:           %  (expect 0)',  n_partner_other;
    RAISE NOTICE 'ref_institution_agreement rows at 2023-01-01: %  (expect 124)', n_agree_2023;
    RAISE NOTICE 'ref_institution_agreement rows at other date: %  (expect 0)',   n_agree_other;

    IF n_partner_other <> 0 THEN
        RAISE EXCEPTION 'Verification failed: % partners not at 2023-01-01', n_partner_other;
    END IF;
    IF n_agree_other <> 0 THEN
        RAISE EXCEPTION 'Verification failed: % agreements not at 2023-01-01', n_agree_other;
    END IF;

    RAISE NOTICE 'patch1 verification PASSED.';
END$$;

COMMIT;

-- ============================================================================
-- END OF Phase7prep_v2_extension_patch1.sql
-- ============================================================================
