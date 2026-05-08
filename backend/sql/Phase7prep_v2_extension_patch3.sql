-- =====================================================================
-- Phase 7 prep v2 extension — patch 3 (CORRECTED)
-- Date: 2026-05-05
--
-- TWO FIXES IN ONE MIGRATION:
--
--   A) Griffith College (id=130) is currently in carve-out List 146
--      only and not in aggregate List 150. Per dual-membership policy:
--      a carve-out institution must also be a member of its parent List
--      so that when the carve-out's effective_to lapses, the engine
--      naturally falls back to the aggregate via Rule 9 multi-membership
--      tie-breaking. This patch adds the missing junction row.
--
--   B) Three ref_institution rows exist for what is one real-world
--      entity (Western Sydney University International College / WSU
--      College / WSU Sydney City Campus). Consolidating to id=140 as
--      canonical:
--        - id=131 is an orphan (no agreements, no junctions, no tx_case
--          refs). Mark merged.
--        - id=286 has a duplicate VIA_PARTNER agreement, two aliases,
--          and one live tx_case row. Migrate everything to 140, then
--          mark merged.
--        - Add additional canonical aliases on 140 to cover the various
--          short-form names that appear in CRM data.
--
-- CORRECTION FROM PRIOR VERSION:
--   ref_institution_alias has a GLOBAL unique constraint on alias text
--   (not on the composite (institution_id, alias)). The earlier version
--   tried to INSERT before DELETE and collided. This version deletes
--   stale alias rows on 131/286 first, then INSERTs the full set on 140
--   with global existence checks.
--
-- All operations idempotent; safe to re-run.
-- Verification rows at end.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Section A: Add Griffith College to the Navitas AU aggregate
-- ---------------------------------------------------------------------
INSERT INTO ref_priority_list_institution (
    priority_list_id, institution_id,
    effective_from, effective_to,
    notes, created_at, updated_at
)
SELECT 150, 130,
       DATE '2024-01-01', NULL,
       'Dual-membership for auto-rollback from carve-out List 146 (Griffith College)',
       NOW(), NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution
    WHERE priority_list_id = 150 AND institution_id = 130
);

-- ---------------------------------------------------------------------
-- Section B1: Re-point tx_case rows from 131/286 to 140
-- ---------------------------------------------------------------------
UPDATE tx_case
SET institution_id = 140,
    updated_at = NOW()
WHERE institution_id IN (131, 286);

-- ---------------------------------------------------------------------
-- Section B2: Clear stale aliases on 131/286 BEFORE re-inserting on 140
-- ---------------------------------------------------------------------
-- Global unique constraint on alias text means we must delete first.

DELETE FROM ref_institution_alias
WHERE institution_id IN (131, 286);

-- ---------------------------------------------------------------------
-- Section B3: Insert canonical alias set on inst 140
-- ---------------------------------------------------------------------
-- Includes:
--   - the two strings previously held by inst 286
--   - additional short-form variants that appear in CRM data
-- Idempotent via global NOT EXISTS check (respects unique-on-alias).
-- Existing alias on 140 ("WSU College/WSU-Sydney City campus (Navitas)")
-- stays in place.

INSERT INTO ref_institution_alias (institution_id, alias, created_at)
SELECT 140, x.alias, NOW()
FROM (VALUES
    ('Western Sydney University - Sydney City Campus'),
    ('Western Sydney University - Sydney City Campus *'),
    ('WSU College'),
    ('WSUIC'),
    ('WSU - Sydney City campus'),
    ('WSU Sydney City Campus'),
    ('WSU Sydney City'),
    ('Western Sydney University College')
) AS x(alias)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution_alias WHERE alias = x.alias
);

-- ---------------------------------------------------------------------
-- Section B4: Migrate or drop agreements on 131/286
-- ---------------------------------------------------------------------
-- Inst 131 has no agreements (verified Q4). Inst 286's agreement is a
-- duplicate of 140's (same partner_id, type, dates, kpi_weight per Q4).
-- Migrate any non-duplicate first (defensive), then drop everything on
-- 131/286.

INSERT INTO ref_institution_agreement (
    institution_id, agreement_type, partner_id, kpi_weight,
    effective_from, effective_to, notes, created_at, updated_at
)
SELECT 140, a.agreement_type, a.partner_id, a.kpi_weight,
       a.effective_from, a.effective_to,
       COALESCE(a.notes, '') || ' [migrated from inst ' || a.institution_id || ']',
       NOW(), NOW()
FROM ref_institution_agreement a
WHERE a.institution_id IN (131, 286)
  AND NOT EXISTS (
      SELECT 1 FROM ref_institution_agreement b
      WHERE b.institution_id = 140
        AND b.agreement_type = a.agreement_type
        AND b.partner_id IS NOT DISTINCT FROM a.partner_id
        AND b.effective_from = a.effective_from
        AND b.effective_to IS NOT DISTINCT FROM a.effective_to
  );

DELETE FROM ref_institution_agreement
WHERE institution_id IN (131, 286);

-- ---------------------------------------------------------------------
-- Section B5: Mark 131 and 286 as merged into 140
-- ---------------------------------------------------------------------
UPDATE ref_institution
SET merged_into_id = 140,
    notes = COALESCE(notes, '')
            || CASE WHEN COALESCE(notes,'') = '' THEN '' ELSE ' | ' END
            || 'Merged into id=140 (canonical: Western Sydney University International College) on 2026-05-05',
    updated_at = NOW()
WHERE id IN (131, 286)
  AND (merged_into_id IS NULL OR merged_into_id <> 140);

-- =====================================================================
-- Verification
-- =====================================================================

-- V1: GC now in aggregate (expect 1 row)
SELECT 'V1: GC in aggregate List 150' AS check_name,
       COUNT(*) AS rows_found
FROM ref_priority_list_institution
WHERE priority_list_id = 150 AND institution_id = 130;

-- V2: All three WSU institutions and their merge state
SELECT 'V2: WSU consolidation' AS check_name,
       id, canonical_name, merged_into_id
FROM ref_institution
WHERE id IN (131, 140, 286)
ORDER BY id;

-- V3: No tx_case rows still pointing at 131 or 286 (expect 0)
SELECT 'V3: stale tx_case refs' AS check_name,
       COUNT(*) AS rows_remaining
FROM tx_case WHERE institution_id IN (131, 286);

-- V4: All aliases now consolidated on 140
SELECT 'V4: aliases on 140' AS check_name,
       alias
FROM ref_institution_alias
WHERE institution_id = 140
ORDER BY alias;

-- V5: No agreements on 131 or 286 (expect 0)
SELECT 'V5: stale agreements' AS check_name,
       COUNT(*) AS rows_remaining
FROM ref_institution_agreement WHERE institution_id IN (131, 286);

-- V6: Aggregate List 150 full membership (expect 8 rows: 7 original + GC)
SELECT 'V6: aggregate members' AS check_name,
       i.id, i.canonical_name
FROM ref_priority_list_institution pli
JOIN ref_institution i ON pli.institution_id = i.id
WHERE pli.priority_list_id = 150
ORDER BY i.canonical_name;

COMMIT;
