-- =============================================================================
-- Phase7prep_v2_patch1.sql
-- =============================================================================
--
-- Populates ref_priority_list_institution junction rows for Lists that were
-- left empty by the main Phase7prep_v2 migration:
--
--   1. 5 single-institution Lists where the canonical name didn't match an
--      existing ref_institution row exactly (auto-link in TX3 missed them):
--        - Griffith College (Navitas)            → existing id 130 (renamed to "Griffith College - Gold Coast")
--        - WSU College / WSU Sydney City (Navitas) → existing id 140
--        - JCUB                                  → existing id 104
--        - VIC DET (Dept of Education...)        → existing id 119
--        - Toronto Met Uni Intl College (Navitas)→ existing id 133
--
--   2. 3 aggregate Lists:
--        - Other Navitas AU: 8 member institutions (Eynesbury, CC, ECUC, SAIBT,
--          DC, LC, WSUIC, GC)
--          GC = Griffith College Brisbane (new row, created in this migration)
--        - Other Navitas CA: 3 member institutions (FIC, ULIC, WLIC)
--        - Other Navitas NZ: 1 member institution (UCIC)
--
--   3. Renames the existing Griffith College row (id 130) to disambiguate
--      between the two physical campuses. Creates a new row for Brisbane.
--
-- ENZL is intentionally left empty — no NZ public schools seeded yet.
-- =============================================================================
--
-- Single transaction. Rolls back atomically if anything fails.
--
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Disambiguate Griffith College: rename id 130 → Gold Coast, add Brisbane
-- ─────────────────────────────────────────────────────────────────────────────

-- Rename existing row to Gold Coast
UPDATE ref_institution
   SET canonical_name = 'Griffith College - Gold Coast',
       notes = COALESCE(notes || E'\n', '') ||
               'Phase7prep_v2_patch1: renamed from "Griffith College" to disambiguate from the Brisbane campus.'
 WHERE id = 130
   AND canonical_name = 'Griffith College';

-- Preserve old name as an alias on the renamed row
INSERT INTO ref_institution_alias (institution_id, alias)
VALUES (130, 'Griffith College')
ON CONFLICT (alias) DO NOTHING;

-- Insert Brisbane campus as new institution row
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Griffith College - Brisbane', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep_v2_patch1. Brisbane City campus (333 Ann Street, since Oct 2024;
        previously Mt Gravatt). Member of Other Navitas AU aggregate.'
  FROM dim_country c
 WHERE c.code = 'AU'
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution
        WHERE canonical_name = 'Griffith College - Brisbane'
          AND merged_into_id IS NULL
   );

-- Self-alias the Brisbane row so future imports of "Griffith College - Brisbane"
-- resolve correctly
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, 'Griffith College - Brisbane'
  FROM ref_institution
 WHERE canonical_name = 'Griffith College - Brisbane'
   AND merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Single-institution List linkages (5 Lists)
-- ─────────────────────────────────────────────────────────────────────────────

-- 2a. Griffith College (Navitas) List → Griffith College - Gold Coast (id 130)
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list WHERE canonical_name = 'Griffith College (Navitas)' AND effective_to IS NULL),
    130,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: Gold Coast campus is the priority single-institution List.'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list WHERE canonical_name = 'Griffith College (Navitas)' AND effective_to IS NULL)
       AND rpli.institution_id = 130
       AND rpli.effective_to IS NULL
);

-- 2b. WSU College / WSU Sydney City (Navitas) List → id 140
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list WHERE canonical_name = 'WSU College / WSU Sydney City (Navitas)' AND effective_to IS NULL),
    140,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: linked via existing canonical "Western Sydney University International College".'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list WHERE canonical_name = 'WSU College / WSU Sydney City (Navitas)' AND effective_to IS NULL)
       AND rpli.institution_id = 140
       AND rpli.effective_to IS NULL
);

-- 2c. JCUB List → id 104 (institution canonical_name = "JCUB")
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list WHERE canonical_name = 'James Cook University Brisbane (JCUB)' AND effective_to IS NULL),
    104,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: institution stored under abbreviated form "JCUB".'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list WHERE canonical_name = 'James Cook University Brisbane (JCUB)' AND effective_to IS NULL)
       AND rpli.institution_id = 104
       AND rpli.effective_to IS NULL
);

-- 2d. VIC DET List → id 119
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list WHERE canonical_name = 'VIC DET (Dept of Education & Training, VIC)' AND effective_to IS NULL),
    119,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: institution stored under abbreviated form "VIC DET".'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list WHERE canonical_name = 'VIC DET (Dept of Education & Training, VIC)' AND effective_to IS NULL)
       AND rpli.institution_id = 119
       AND rpli.effective_to IS NULL
);

-- 2e. Toronto Met Uni Intl College (Navitas) List → id 133
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list WHERE canonical_name = 'Toronto Met Uni Intl College (Navitas)' AND effective_to IS NULL),
    133,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: institution canonical name has the longer "Metropolitan" form.'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list WHERE canonical_name = 'Toronto Met Uni Intl College (Navitas)' AND effective_to IS NULL)
       AND rpli.institution_id = 133
       AND rpli.effective_to IS NULL
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Aggregate List linkages
-- ─────────────────────────────────────────────────────────────────────────────

-- 3a. Other Navitas AU: 8 institutions
--     Eynesbury (134), Curtin College (135), Edith Cowan College (136),
--     SAIBT (137), Deakin College (138), La Trobe College (139),
--     WSUIC (140), Griffith College - Brisbane (new id, looked up by name)
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list
      WHERE canonical_name = 'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'
        AND effective_to IS NULL),
    inst.id,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: ' || inst.label
  FROM (VALUES
    (134, 'Eynesbury'),
    (135, 'CC = Curtin College'),
    (136, 'ECUC = Edith Cowan College'),
    (137, 'SAIBT = South Australian Institute of Business and Technology'),
    (138, 'DC = Deakin College'),
    (139, 'LC = La Trobe College'),
    (140, 'WSUIC = Western Sydney University International College')
  ) AS inst(id, label)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list
                                     WHERE canonical_name = 'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'
                                       AND effective_to IS NULL)
       AND rpli.institution_id = inst.id
       AND rpli.effective_to IS NULL
);

-- Add Griffith College - Brisbane to the aggregate (looked up by name since
-- the row was just inserted in section 1)
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list
      WHERE canonical_name = 'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'
        AND effective_to IS NULL),
    (SELECT id FROM ref_institution
      WHERE canonical_name = 'Griffith College - Brisbane'
        AND merged_into_id IS NULL),
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: GC = Griffith College Brisbane campus'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list
                                     WHERE canonical_name = 'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'
                                       AND effective_to IS NULL)
       AND rpli.institution_id = (SELECT id FROM ref_institution
                                   WHERE canonical_name = 'Griffith College - Brisbane'
                                     AND merged_into_id IS NULL)
       AND rpli.effective_to IS NULL
);


-- 3b. Other Navitas CA: 3 institutions
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list
      WHERE canonical_name = 'Other Navitas CA: FIC, ULIC, WLIC'
        AND effective_to IS NULL),
    inst.id,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: ' || inst.label
  FROM (VALUES
    (142, 'FIC = Fraser International College'),
    (143, 'ULIC = University of Lethbridge International College'),
    (144, 'WLIC = Wilfrid Laurier International College')
  ) AS inst(id, label)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list
                                     WHERE canonical_name = 'Other Navitas CA: FIC, ULIC, WLIC'
                                       AND effective_to IS NULL)
       AND rpli.institution_id = inst.id
       AND rpli.effective_to IS NULL
);


-- 3c. Other Navitas NZ: 1 institution
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list
      WHERE canonical_name = 'Other Navitas NZ: UCIC'
        AND effective_to IS NULL),
    145,
    DATE '2024-01-01',
    'Phase7prep_v2_patch1: UCIC = University of Canterbury International College'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list
                                     WHERE canonical_name = 'Other Navitas NZ: UCIC'
                                       AND effective_to IS NULL)
       AND rpli.institution_id = 145
       AND rpli.effective_to IS NULL
);


-- ─────────────────────────────────────────────────────────────────────────────
-- Verification
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_griff_bris       INTEGER;
    n_griff_gc         INTEGER;
    n_griff_orig       INTEGER;
    n_singles_with_mem INTEGER;
    n_singles_empty    INTEGER;
    n_navitas_au       INTEGER;
    n_navitas_ca       INTEGER;
    n_navitas_nz       INTEGER;
    n_enzl             INTEGER;
BEGIN
    -- Griffith disambiguation
    SELECT COUNT(*) INTO n_griff_bris FROM ref_institution
      WHERE canonical_name = 'Griffith College - Brisbane' AND merged_into_id IS NULL;
    SELECT COUNT(*) INTO n_griff_gc   FROM ref_institution
      WHERE canonical_name = 'Griffith College - Gold Coast' AND merged_into_id IS NULL;
    SELECT COUNT(*) INTO n_griff_orig FROM ref_institution
      WHERE canonical_name = 'Griffith College' AND merged_into_id IS NULL;

    -- Single-institution Lists (is_aggregate = FALSE) with at least one member
    SELECT COUNT(*) INTO n_singles_with_mem
      FROM ref_priority_list rpl
     WHERE rpl.effective_to IS NULL
       AND rpl.is_aggregate = FALSE
       AND EXISTS (
           SELECT 1 FROM ref_priority_list_institution rpli
            WHERE rpli.priority_list_id = rpl.id
              AND rpli.effective_to IS NULL
       );

    -- Single-institution Lists with NO members (expect ENZL only)
    SELECT COUNT(*) INTO n_singles_empty
      FROM ref_priority_list rpl
     WHERE rpl.effective_to IS NULL
       AND rpl.is_aggregate = FALSE
       AND NOT EXISTS (
           SELECT 1 FROM ref_priority_list_institution rpli
            WHERE rpli.priority_list_id = rpl.id
              AND rpli.effective_to IS NULL
       );

    -- Aggregate List membership counts
    SELECT COUNT(*) INTO n_navitas_au
      FROM ref_priority_list_institution rpli
      JOIN ref_priority_list rpl ON rpl.id = rpli.priority_list_id
     WHERE rpl.canonical_name = 'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'
       AND rpl.effective_to IS NULL
       AND rpli.effective_to IS NULL;

    SELECT COUNT(*) INTO n_navitas_ca
      FROM ref_priority_list_institution rpli
      JOIN ref_priority_list rpl ON rpl.id = rpli.priority_list_id
     WHERE rpl.canonical_name = 'Other Navitas CA: FIC, ULIC, WLIC'
       AND rpl.effective_to IS NULL
       AND rpli.effective_to IS NULL;

    SELECT COUNT(*) INTO n_navitas_nz
      FROM ref_priority_list_institution rpli
      JOIN ref_priority_list rpl ON rpl.id = rpli.priority_list_id
     WHERE rpl.canonical_name = 'Other Navitas NZ: UCIC'
       AND rpl.effective_to IS NULL
       AND rpli.effective_to IS NULL;

    SELECT COUNT(*) INTO n_enzl
      FROM ref_priority_list_institution rpli
      JOIN ref_priority_list rpl ON rpl.id = rpli.priority_list_id
     WHERE rpl.canonical_name = 'ENZL'
       AND rpl.effective_to IS NULL
       AND rpli.effective_to IS NULL;

    RAISE NOTICE 'patch1 results:';
    RAISE NOTICE '  Griffith College - Gold Coast (active):  %', n_griff_gc;
    RAISE NOTICE '  Griffith College - Brisbane  (active):   %', n_griff_bris;
    RAISE NOTICE '  Griffith College plain (must be 0):      %', n_griff_orig;
    RAISE NOTICE '  Single Lists with at least 1 member:     %', n_singles_with_mem;
    RAISE NOTICE '  Single Lists with NO members (ENZL only):%', n_singles_empty;
    RAISE NOTICE '  Other Navitas AU members:                %  (expect 8)', n_navitas_au;
    RAISE NOTICE '  Other Navitas CA members:                %  (expect 3)', n_navitas_ca;
    RAISE NOTICE '  Other Navitas NZ members:                %  (expect 1)', n_navitas_nz;
    RAISE NOTICE '  ENZL members (expect 0):                 %', n_enzl;

    IF n_griff_gc       <> 1  THEN RAISE EXCEPTION 'Expected 1 active Griffith College - Gold Coast, got %', n_griff_gc; END IF;
    IF n_griff_bris     <> 1  THEN RAISE EXCEPTION 'Expected 1 active Griffith College - Brisbane, got %', n_griff_bris; END IF;
    IF n_griff_orig     <> 0  THEN RAISE EXCEPTION 'Expected 0 active "Griffith College" (plain), got %', n_griff_orig; END IF;
    IF n_singles_with_mem <> 34 THEN RAISE EXCEPTION 'Expected 34 single Lists with members (35 singles minus ENZL), got %', n_singles_with_mem; END IF;
    IF n_singles_empty   <> 1 THEN RAISE EXCEPTION 'Expected 1 empty single List (ENZL), got %', n_singles_empty; END IF;
    IF n_navitas_au      <> 8 THEN RAISE EXCEPTION 'Expected 8 Other Navitas AU members, got %', n_navitas_au; END IF;
    IF n_navitas_ca      <> 3 THEN RAISE EXCEPTION 'Expected 3 Other Navitas CA members, got %', n_navitas_ca; END IF;
    IF n_navitas_nz      <> 1 THEN RAISE EXCEPTION 'Expected 1 Other Navitas NZ member, got %', n_navitas_nz; END IF;
    IF n_enzl            <> 0 THEN RAISE EXCEPTION 'Expected 0 ENZL members, got %', n_enzl; END IF;

    RAISE NOTICE 'patch1 verification PASSED.';
END$$;

COMMIT;

-- =============================================================================
-- END OF Phase7prep_v2_patch1.sql
-- =============================================================================
