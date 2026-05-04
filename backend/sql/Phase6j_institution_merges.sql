-- =============================================================================
-- Phase 6j — Institution duplicate merges
-- File:    Phase6j_institution_merges.sql
--
-- Purpose:
--   Five duplicate institution rows surfaced from Phase 6i verification.
--   This migration folds the loser into a winner per the user's decisions
--   (chat 2026-05-03), preserving aliases and partner_institution links.
--
-- Mergers (loser -> winner):
--   1. "Griffith College" (id 141) -> 130
--      Winner renamed from "Griffith College (Navitas)" to "Griffith College".
--      Winner reclassified IN_SYSTEM_PRIORITY -> OUT_SYSTEM_GROUP.
--      priority_partner_id / aggregate_priority_partner_id NULLed on winner.
--
--   2. "SAIBT - South Australian Institute of Business and Technology" (id 277) -> 137
--      Winner renamed from "SAIBT" to "South Australian Institute of Business
--      and Technology". Old canonicals preserved as aliases.
--
--   3. "WSU College/WSU-Sydney City campus (Navitas)" (id 131) -> 140
--      Winner already named "Western Sydney University International College".
--      No reclassification. Loser's priority FKs are intentionally LEFT
--      INTACT — see "Constraint note" below.
--
--   4. "Macquarie University - MQ" -> "Macquarie University"
--      Both looked up by canonical_name. No reclassification.
--
--   5. "Victoria University - Sydney City Centre" -> "Victoria University"
--      Both looked up by canonical_name. No reclassification.
--
-- Constraint note:
--   ref_institution has a CHECK constraint (ref_institution_check) that
--   requires priority_partner_id NOT NULL when classification is
--   'IN_SYSTEM_PRIORITY'. We never null priority FKs on a loser because
--   the loser keeps its original classification (it's marked MERGED but
--   its row is otherwise frozen for history). We only null priority FKs
--   on a WINNER when we're deliberately reclassifying that winner away
--   from IN_SYSTEM_PRIORITY (see Merge 1).
--
-- Mechanics for every merge:
--   a. Move aliases from loser to winner (ON CONFLICT DO NOTHING).
--   b. Move partner_institution links: try INSERT into winner (skip on
--      conflict via the partial unique index from Phase 6i); UPDATE any
--      historical rows (effective_to NOT NULL) directly; then DELETE
--      loser's links.
--   c. Add loser's old canonical_name as alias of winner.
--   d. Mark loser merged: merged_into_id = winner_id,
--      verification_status = 'MERGED'. Other columns untouched.
--   e. Where applicable, rename / reclassify winner.
--
-- Schema change required: ref_institution.canonical_name UNIQUE constraint
--   becomes a partial unique index (excludes merged rows). Done in
--   Transaction 1; merges done in Transaction 2.
--
-- Idempotent. Safe to re-run.
-- =============================================================================


-- =============================================================================
-- TRANSACTION 1 — Replace canonical_name UNIQUE constraint with partial index
-- =============================================================================

BEGIN;

DO $$
DECLARE
    old_constraint_name TEXT;
BEGIN
    SELECT tc.constraint_name INTO old_constraint_name
    FROM information_schema.table_constraints tc
    WHERE tc.table_name = 'ref_institution'
      AND tc.constraint_type = 'UNIQUE'
      AND EXISTS (
          SELECT 1 FROM information_schema.constraint_column_usage ccu
          WHERE ccu.constraint_name = tc.constraint_name
            AND ccu.column_name = 'canonical_name'
      )
    LIMIT 1;

    IF old_constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE ref_institution DROP CONSTRAINT %I',
            old_constraint_name
        );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_ref_inst_canonical_active
    ON ref_institution (canonical_name)
    WHERE merged_into_id IS NULL;

COMMIT;


-- =============================================================================
-- TRANSACTION 2 — Execute the five merges
-- =============================================================================

BEGIN;


-- =============================================================================
-- MERGE 1 — Griffith College (141) -> Griffith College (Navitas) (130)
--           Winner renamed to "Griffith College" + reclassified OUT_SYSTEM_GROUP
-- =============================================================================

DO $$
DECLARE
    loser_id  BIGINT;
    winner_id BIGINT;
    loser_old_name  TEXT;
    winner_old_name TEXT;
BEGIN
    SELECT id, canonical_name INTO loser_id,  loser_old_name
        FROM ref_institution WHERE canonical_name = 'Griffith College'                AND merged_into_id IS NULL;
    SELECT id, canonical_name INTO winner_id, winner_old_name
        FROM ref_institution WHERE canonical_name = 'Griffith College (Navitas)'      AND merged_into_id IS NULL;

    IF loser_id IS NULL OR winner_id IS NULL THEN
        RAISE NOTICE 'Merge 1 (Griffith) — no-op: loser_id=% winner_id=% (already merged or not present)', loser_id, winner_id;
    ELSE
        INSERT INTO ref_institution_alias (institution_id, alias)
            SELECT winner_id, alias FROM ref_institution_alias WHERE institution_id = loser_id
            ON CONFLICT (alias) DO NOTHING;
        DELETE FROM ref_institution_alias WHERE institution_id = loser_id;

        INSERT INTO ref_partner_institution (partner_id, institution_id, partner_type, effective_from, effective_to, notes)
            SELECT partner_id, winner_id, partner_type, effective_from, effective_to,
                   COALESCE(notes,'') || ' [Phase 6j: re-pointed from merged inst ' || loser_id || ']'
            FROM ref_partner_institution
            WHERE institution_id = loser_id AND effective_to IS NULL
            ON CONFLICT (partner_id, institution_id) WHERE effective_to IS NULL DO NOTHING;
        UPDATE ref_partner_institution SET institution_id = winner_id
            WHERE institution_id = loser_id AND effective_to IS NOT NULL;
        DELETE FROM ref_partner_institution WHERE institution_id = loser_id;

        INSERT INTO ref_institution_alias (institution_id, alias) VALUES
            (winner_id, loser_old_name),
            (winner_id, winner_old_name)
            ON CONFLICT (alias) DO NOTHING;

        UPDATE ref_institution
            SET merged_into_id = winner_id,
                verification_status = 'MERGED',
                updated_at = NOW()
            WHERE id = loser_id;

        UPDATE ref_institution
            SET canonical_name             = 'Griffith College',
                classification             = 'OUT_SYSTEM_GROUP',
                priority_partner_id        = NULL,
                aggregate_priority_partner_id = NULL,
                updated_at                 = NOW()
            WHERE id = winner_id;

        RAISE NOTICE 'Merge 1 (Griffith): loser % -> winner %', loser_id, winner_id;
    END IF;
END $$;


-- =============================================================================
-- MERGE 2 — "SAIBT - South Australian..." (277) -> "SAIBT" (137)
--           Winner renamed to "South Australian Institute of Business and Technology"
-- =============================================================================

DO $$
DECLARE
    loser_id  BIGINT;
    winner_id BIGINT;
    loser_old_name  TEXT;
    winner_old_name TEXT;
BEGIN
    SELECT id, canonical_name INTO loser_id,  loser_old_name
        FROM ref_institution
        WHERE canonical_name = 'SAIBT - South Australian Institute of Business and Technology'
          AND merged_into_id IS NULL;
    SELECT id, canonical_name INTO winner_id, winner_old_name
        FROM ref_institution WHERE canonical_name = 'SAIBT' AND merged_into_id IS NULL;

    IF loser_id IS NULL OR winner_id IS NULL THEN
        RAISE NOTICE 'Merge 2 (SAIBT) — no-op: loser_id=% winner_id=% (already merged or not present)', loser_id, winner_id;
    ELSE
        INSERT INTO ref_institution_alias (institution_id, alias)
            SELECT winner_id, alias FROM ref_institution_alias WHERE institution_id = loser_id
            ON CONFLICT (alias) DO NOTHING;
        DELETE FROM ref_institution_alias WHERE institution_id = loser_id;

        INSERT INTO ref_partner_institution (partner_id, institution_id, partner_type, effective_from, effective_to, notes)
            SELECT partner_id, winner_id, partner_type, effective_from, effective_to,
                   COALESCE(notes,'') || ' [Phase 6j: re-pointed from merged inst ' || loser_id || ']'
            FROM ref_partner_institution
            WHERE institution_id = loser_id AND effective_to IS NULL
            ON CONFLICT (partner_id, institution_id) WHERE effective_to IS NULL DO NOTHING;
        UPDATE ref_partner_institution SET institution_id = winner_id
            WHERE institution_id = loser_id AND effective_to IS NOT NULL;
        DELETE FROM ref_partner_institution WHERE institution_id = loser_id;

        INSERT INTO ref_institution_alias (institution_id, alias) VALUES
            (winner_id, loser_old_name),
            (winner_id, winner_old_name)
            ON CONFLICT (alias) DO NOTHING;

        UPDATE ref_institution
            SET merged_into_id = winner_id,
                verification_status = 'MERGED',
                updated_at = NOW()
            WHERE id = loser_id;

        UPDATE ref_institution
            SET canonical_name = 'South Australian Institute of Business and Technology',
                updated_at     = NOW()
            WHERE id = winner_id;

        RAISE NOTICE 'Merge 2 (SAIBT): loser % -> winner %', loser_id, winner_id;
    END IF;
END $$;


-- =============================================================================
-- MERGE 3 — "WSU College/WSU-Sydney City campus (Navitas)" (131)
--           -> "Western Sydney University International College" (140)
--
-- Note: loser's priority FKs are LEFT INTACT to satisfy the
-- ref_institution_check CHECK constraint (IN_SYSTEM_PRIORITY rows must
-- have priority_partner_id NOT NULL). The merged_into_id chain takes
-- care of routing.
-- =============================================================================

DO $$
DECLARE
    loser_id  BIGINT;
    winner_id BIGINT;
    loser_old_name  TEXT;
BEGIN
    SELECT id, canonical_name INTO loser_id, loser_old_name
        FROM ref_institution
        WHERE canonical_name = 'WSU College/WSU-Sydney City campus (Navitas)'
          AND merged_into_id IS NULL;
    SELECT id INTO winner_id
        FROM ref_institution
        WHERE canonical_name = 'Western Sydney University International College'
          AND merged_into_id IS NULL;

    IF loser_id IS NULL OR winner_id IS NULL THEN
        RAISE NOTICE 'Merge 3 (WSU) — no-op: loser_id=% winner_id=% (already merged or not present)', loser_id, winner_id;
    ELSE
        INSERT INTO ref_institution_alias (institution_id, alias)
            SELECT winner_id, alias FROM ref_institution_alias WHERE institution_id = loser_id
            ON CONFLICT (alias) DO NOTHING;
        DELETE FROM ref_institution_alias WHERE institution_id = loser_id;

        INSERT INTO ref_partner_institution (partner_id, institution_id, partner_type, effective_from, effective_to, notes)
            SELECT partner_id, winner_id, partner_type, effective_from, effective_to,
                   COALESCE(notes,'') || ' [Phase 6j: re-pointed from merged inst ' || loser_id || ']'
            FROM ref_partner_institution
            WHERE institution_id = loser_id AND effective_to IS NULL
            ON CONFLICT (partner_id, institution_id) WHERE effective_to IS NULL DO NOTHING;
        UPDATE ref_partner_institution SET institution_id = winner_id
            WHERE institution_id = loser_id AND effective_to IS NOT NULL;
        DELETE FROM ref_partner_institution WHERE institution_id = loser_id;

        INSERT INTO ref_institution_alias (institution_id, alias)
            VALUES (winner_id, loser_old_name)
            ON CONFLICT (alias) DO NOTHING;

        -- Mark loser merged. priority FKs intentionally not changed.
        UPDATE ref_institution
            SET merged_into_id = winner_id,
                verification_status = 'MERGED',
                updated_at = NOW()
            WHERE id = loser_id;

        RAISE NOTICE 'Merge 3 (WSU): loser % -> winner %', loser_id, winner_id;
    END IF;
END $$;


-- =============================================================================
-- MERGE 4 — "Macquarie University - MQ" -> "Macquarie University"
-- =============================================================================

DO $$
DECLARE
    loser_id  BIGINT;
    winner_id BIGINT;
    loser_old_name TEXT;
BEGIN
    SELECT id, canonical_name INTO loser_id, loser_old_name
        FROM ref_institution WHERE canonical_name = 'Macquarie University - MQ' AND merged_into_id IS NULL;
    SELECT id INTO winner_id
        FROM ref_institution WHERE canonical_name = 'Macquarie University'      AND merged_into_id IS NULL;

    IF loser_id IS NULL OR winner_id IS NULL THEN
        RAISE NOTICE 'Merge 4 (Macquarie) — no-op: loser_id=% winner_id=% (already merged or not present)', loser_id, winner_id;
    ELSE
        INSERT INTO ref_institution_alias (institution_id, alias)
            SELECT winner_id, alias FROM ref_institution_alias WHERE institution_id = loser_id
            ON CONFLICT (alias) DO NOTHING;
        DELETE FROM ref_institution_alias WHERE institution_id = loser_id;

        INSERT INTO ref_partner_institution (partner_id, institution_id, partner_type, effective_from, effective_to, notes)
            SELECT partner_id, winner_id, partner_type, effective_from, effective_to,
                   COALESCE(notes,'') || ' [Phase 6j: re-pointed from merged inst ' || loser_id || ']'
            FROM ref_partner_institution
            WHERE institution_id = loser_id AND effective_to IS NULL
            ON CONFLICT (partner_id, institution_id) WHERE effective_to IS NULL DO NOTHING;
        UPDATE ref_partner_institution SET institution_id = winner_id
            WHERE institution_id = loser_id AND effective_to IS NOT NULL;
        DELETE FROM ref_partner_institution WHERE institution_id = loser_id;

        INSERT INTO ref_institution_alias (institution_id, alias)
            VALUES (winner_id, loser_old_name)
            ON CONFLICT (alias) DO NOTHING;

        UPDATE ref_institution
            SET merged_into_id = winner_id,
                verification_status = 'MERGED',
                updated_at = NOW()
            WHERE id = loser_id;

        RAISE NOTICE 'Merge 4 (Macquarie): loser % -> winner %', loser_id, winner_id;
    END IF;
END $$;


-- =============================================================================
-- MERGE 5 — "Victoria University - Sydney City Centre" -> "Victoria University"
-- =============================================================================

DO $$
DECLARE
    loser_id  BIGINT;
    winner_id BIGINT;
    loser_old_name TEXT;
BEGIN
    SELECT id, canonical_name INTO loser_id, loser_old_name
        FROM ref_institution
        WHERE canonical_name = 'Victoria University - Sydney City Centre'
          AND merged_into_id IS NULL;
    SELECT id INTO winner_id
        FROM ref_institution
        WHERE canonical_name = 'Victoria University'
          AND merged_into_id IS NULL;

    IF loser_id IS NULL OR winner_id IS NULL THEN
        RAISE NOTICE 'Merge 5 (Victoria) — no-op: loser_id=% winner_id=% (already merged or not present)', loser_id, winner_id;
    ELSE
        INSERT INTO ref_institution_alias (institution_id, alias)
            SELECT winner_id, alias FROM ref_institution_alias WHERE institution_id = loser_id
            ON CONFLICT (alias) DO NOTHING;
        DELETE FROM ref_institution_alias WHERE institution_id = loser_id;

        INSERT INTO ref_partner_institution (partner_id, institution_id, partner_type, effective_from, effective_to, notes)
            SELECT partner_id, winner_id, partner_type, effective_from, effective_to,
                   COALESCE(notes,'') || ' [Phase 6j: re-pointed from merged inst ' || loser_id || ']'
            FROM ref_partner_institution
            WHERE institution_id = loser_id AND effective_to IS NULL
            ON CONFLICT (partner_id, institution_id) WHERE effective_to IS NULL DO NOTHING;
        UPDATE ref_partner_institution SET institution_id = winner_id
            WHERE institution_id = loser_id AND effective_to IS NOT NULL;
        DELETE FROM ref_partner_institution WHERE institution_id = loser_id;

        INSERT INTO ref_institution_alias (institution_id, alias)
            VALUES (winner_id, loser_old_name)
            ON CONFLICT (alias) DO NOTHING;

        UPDATE ref_institution
            SET merged_into_id = winner_id,
                verification_status = 'MERGED',
                updated_at = NOW()
            WHERE id = loser_id;

        RAISE NOTICE 'Merge 5 (Victoria): loser % -> winner %', loser_id, winner_id;
    END IF;
END $$;


COMMIT;


-- =============================================================================
-- VERIFICATION (outside any transaction)
-- =============================================================================

SELECT 'institutions_total'              AS metric, count(*)::text AS value FROM ref_institution
UNION ALL
SELECT 'institutions_merged',             count(*)::text FROM ref_institution WHERE merged_into_id IS NOT NULL
UNION ALL
SELECT 'institutions_active',             count(*)::text FROM ref_institution WHERE merged_into_id IS NULL
UNION ALL
SELECT 'aliases_total',                   count(*)::text FROM ref_institution_alias
UNION ALL
SELECT 'partner_inst_total',              count(*)::text FROM ref_partner_institution
UNION ALL
SELECT 'phase_6j_repointed_pi_links',     count(*)::text FROM ref_partner_institution WHERE notes LIKE '%Phase 6j%';

SELECT i.id, i.canonical_name, i.verification_status, i.merged_into_id,
       w.canonical_name AS winner_name
FROM ref_institution i
LEFT JOIN ref_institution w ON w.id = i.merged_into_id
WHERE i.verification_status = 'MERGED'
ORDER BY i.id;

SELECT id, canonical_name, classification, priority_partner_id, aggregate_priority_partner_id
FROM ref_institution
WHERE canonical_name IN (
    'Griffith College',
    'South Australian Institute of Business and Technology',
    'Western Sydney University International College',
    'Macquarie University',
    'Victoria University'
)
ORDER BY canonical_name;

SELECT canonical_name, count(*) AS dup_count
FROM ref_institution
WHERE merged_into_id IS NULL
GROUP BY canonical_name
HAVING count(*) > 1;
