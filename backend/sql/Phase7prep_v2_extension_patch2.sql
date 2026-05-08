-- ============================================================================
-- Phase7prep_v2_extension_patch2.sql
--
-- Reverses the Brisbane/Gold Coast disambiguation from
-- Phase7prep_v2_patch1. Merges institution 310 (Brisbane) back into
-- 130 (canonical), restores canonical name to "Griffith College",
-- and removes the Brisbane-specific data created by patch1.
--
-- Per user direction (this conversation): Griffith College's two
-- campuses are operationally one institution. The carve-out vs
-- aggregate-membership question is handled at the priority-junction
-- level, not by splitting the institution into two rows.
--
-- After this patch:
--   - id=130 has canonical_name='Griffith College'
--   - id=310 is marked as merged (merged_into_id=130) and is excluded
--     from active institution queries
--   - The aggregate "Other Navitas AU" loses Brisbane (it now has 7
--     members instead of 8)
--   - GC's single-institution List "Griffith College (Navitas)" remains
--     and continues to point at id=130 with target=2
--
-- The single List + aggregate-without-GC arrangement preserves the
-- priority document structure literally. If GC needs to also appear
-- as an aggregate member (e.g. when its individual target lapses),
-- that's handled by adding a junction row in the aggregate at that
-- time — not by splitting the institution.
--
-- Single transaction. Rolls back atomically if anything fails.
-- ============================================================================

BEGIN;

-- ───────────────────────────────────────────────────────────────────────────
-- 1. Verify pre-state
-- ───────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_brisbane          INTEGER;
    n_goldcoast         INTEGER;
    n_brisbane_jcts     INTEGER;
    n_brisbane_agreements INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_brisbane
      FROM ref_institution
     WHERE id = 310 AND canonical_name = 'Griffith College - Brisbane';

    SELECT COUNT(*) INTO n_goldcoast
      FROM ref_institution
     WHERE id = 130 AND canonical_name = 'Griffith College - Gold Coast';

    IF n_brisbane = 0 THEN
        RAISE NOTICE 'Brisbane row (id=310) not found — patch may already be applied or never deployed.';
    END IF;
    IF n_goldcoast = 0 THEN
        RAISE NOTICE 'Gold Coast row (id=130 with name "Griffith College - Gold Coast") not found.';
    END IF;

    SELECT COUNT(*) INTO n_brisbane_jcts
      FROM ref_priority_list_institution
     WHERE institution_id = 310;

    SELECT COUNT(*) INTO n_brisbane_agreements
      FROM ref_institution_agreement
     WHERE institution_id = 310;

    RAISE NOTICE 'Pre-state: Brisbane junctions=%, Brisbane agreements=%',
                 n_brisbane_jcts, n_brisbane_agreements;
END$$;


-- ───────────────────────────────────────────────────────────────────────────
-- 2. Restore canonical name on id=130
-- ───────────────────────────────────────────────────────────────────────────

UPDATE ref_institution
   SET canonical_name = 'Griffith College',
       notes = COALESCE(notes || E'\n', '') ||
               'Phase7prep_v2_extension_patch2: restored canonical_name from "Griffith College - Gold Coast" '
               || 'after merging the Brisbane campus row (id=310) back. Both campuses are operationally one institution.'
 WHERE id = 130
   AND canonical_name = 'Griffith College - Gold Coast';


-- ───────────────────────────────────────────────────────────────────────────
-- 3. Migrate any aliases that pointed to Brisbane (id=310) to Gold Coast (id=130)
-- ───────────────────────────────────────────────────────────────────────────

-- Move alias rows by updating institution_id (no-op if alias already exists for 130)
UPDATE ref_institution_alias
   SET institution_id = 130
 WHERE institution_id = 310
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution_alias a2
        WHERE a2.institution_id = 130
          AND LOWER(a2.alias) = LOWER(ref_institution_alias.alias)
   );

-- Drop any Brisbane aliases that are now duplicates of Gold Coast aliases
DELETE FROM ref_institution_alias
 WHERE institution_id = 310;


-- ───────────────────────────────────────────────────────────────────────────
-- 4. Remove Brisbane's junction row from the aggregate
-- ───────────────────────────────────────────────────────────────────────────

DELETE FROM ref_priority_list_institution
 WHERE institution_id = 310;


-- ───────────────────────────────────────────────────────────────────────────
-- 5. Remove Brisbane's agreement row(s)
-- ───────────────────────────────────────────────────────────────────────────

DELETE FROM ref_institution_agreement
 WHERE institution_id = 310;


-- ───────────────────────────────────────────────────────────────────────────
-- 6. Mark Brisbane as merged into Gold Coast
-- ───────────────────────────────────────────────────────────────────────────

UPDATE ref_institution
   SET merged_into_id = 130,
       notes = COALESCE(notes || E'\n', '') ||
               'Phase7prep_v2_extension_patch2: merged into id=130 (Griffith College). '
               || 'Brisbane and Gold Coast campuses are operationally one institution.'
 WHERE id = 310;


-- ───────────────────────────────────────────────────────────────────────────
-- 7. Verification
-- ───────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_canonical_gc          INTEGER;
    n_brisbane_active       INTEGER;
    n_brisbane_merged       INTEGER;
    n_gc_jcts               INTEGER;
    n_gc_agreements         INTEGER;
    n_aggregate_members     INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_canonical_gc
      FROM ref_institution
     WHERE id = 130
       AND canonical_name = 'Griffith College'
       AND merged_into_id IS NULL;

    SELECT COUNT(*) INTO n_brisbane_active
      FROM ref_institution
     WHERE id = 310 AND merged_into_id IS NULL;

    SELECT COUNT(*) INTO n_brisbane_merged
      FROM ref_institution
     WHERE id = 310 AND merged_into_id = 130;

    SELECT COUNT(*) INTO n_gc_jcts
      FROM ref_priority_list_institution
     WHERE institution_id = 130;

    SELECT COUNT(*) INTO n_gc_agreements
      FROM ref_institution_agreement
     WHERE institution_id = 130;

    SELECT COUNT(*) INTO n_aggregate_members
      FROM ref_priority_list_institution rpli
      JOIN ref_priority_list rpl ON rpl.id = rpli.priority_list_id
     WHERE rpl.canonical_name = 'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'
       AND rpli.effective_to IS NULL;

    RAISE NOTICE '=== patch2 verification ===';
    RAISE NOTICE 'Griffith College canonical (id=130, active): % (expect 1)', n_canonical_gc;
    RAISE NOTICE 'Brisbane active (id=310 with merged_into_id NULL): % (expect 0)', n_brisbane_active;
    RAISE NOTICE 'Brisbane merged into 130: % (expect 1)', n_brisbane_merged;
    RAISE NOTICE 'GC junction memberships (active): % (expect >= 1)', n_gc_jcts;
    RAISE NOTICE 'GC agreements: % (expect >= 1)', n_gc_agreements;
    RAISE NOTICE 'Aggregate "Other Navitas AU" members (active): % (expect 7)', n_aggregate_members;

    IF n_canonical_gc <> 1 THEN
        RAISE EXCEPTION 'Verification failed: Griffith College not found at id=130';
    END IF;
    IF n_brisbane_active <> 0 THEN
        RAISE EXCEPTION 'Verification failed: Brisbane (id=310) is still active';
    END IF;
    IF n_brisbane_merged <> 1 THEN
        RAISE EXCEPTION 'Verification failed: Brisbane (id=310) not marked merged_into_id=130';
    END IF;
    IF n_gc_jcts < 1 THEN
        RAISE EXCEPTION 'Verification failed: Griffith College has no priority junction memberships';
    END IF;
    IF n_gc_agreements < 1 THEN
        RAISE EXCEPTION 'Verification failed: Griffith College has no agreements';
    END IF;
    IF n_aggregate_members <> 7 THEN
        RAISE EXCEPTION 'Verification failed: aggregate has % members, expected 7', n_aggregate_members;
    END IF;

    RAISE NOTICE 'patch2 verification PASSED.';
END$$;

COMMIT;

-- ============================================================================
-- END OF Phase7prep_v2_extension_patch2.sql
-- ============================================================================
