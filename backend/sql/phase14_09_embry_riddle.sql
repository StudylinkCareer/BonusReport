-- =============================================================================
-- Phase 14_09: Embry-Riddle Aeronautical University — institute parent + cleanup
-- =============================================================================
-- Purpose:
--   Per user decision (2026-05-10):
--     - Add a parent canonical "Embry-Riddle Aeronautical University" (no campus)
--       to enable institute-level financial agreements
--     - Keep existing campus-level institutions intact (id=1124 Arizona, id=1125 Florida)
--     - Clean up 2 spurious cross-linking aliases that pointed each campus's
--       name to the OTHER campus (rows 1789 and 1791 in the diagnostic snapshot)
--
--   The 2 EduCo source-string aliases already exist on id=1125 (Florida) from a
--   prior session — no action needed for those; importer warnings will clear on
--   next reload.
--
-- Asterisk convention (corrected):
--   (none) = In system; * = via Group OR Master Agent; ** = OOS via Master Agent
--
-- Schema (verified): same as before.
-- Idempotent: ON CONFLICT DO NOTHING for inserts; DELETEs are safe to re-run
-- (will simply find 0 rows on second run).
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Insert parent canonical (institute-level, no campus suffix)
--    country_id=57 confirmed = "United States" via dim_country
-- ---------------------------------------------------------------------------
INSERT INTO ref_institution (canonical_name, country_id, verification_status, notes)
VALUES (
    'Embry-Riddle Aeronautical University',
    57,
    'VERIFIED',
    'Phase 14.09: institute-level parent. Two campus-level institutions exist ' ||
    'separately (Arizona id=1124, Florida id=1125) and are NOT merged into this ' ||
    'parent — both remain independently verifiable. This parent exists so ' ||
    'institute-level financial agreements can attach here while campus-specific ' ||
    'agreements stay on the campus rows.'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Self-alias the new parent so any source string equal to the bare
--    canonical name resolves to it
-- ---------------------------------------------------------------------------
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT i.id, 'Embry-Riddle Aeronautical University'
  FROM ref_institution i
 WHERE i.canonical_name = 'Embry-Riddle Aeronautical University'
ON CONFLICT (alias) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Delete the 2 cross-linking aliases (rows 1789 and 1791 in diagnostic):
--      - "Embry-Riddle ... Arizona" was wrongly linked to Florida (1125)
--      - "Embry-Riddle ... Florida" was wrongly linked to Arizona (1124)
--    Identifying by alias + institution_id rather than hardcoded id, so this
--    survives any future re-numbering.
-- ---------------------------------------------------------------------------
DELETE FROM ref_institution_alias
 WHERE alias = 'Embry-Riddle Aeronautical University, Arizona'
   AND institution_id = (
       SELECT id FROM ref_institution
        WHERE canonical_name = 'Embry-Riddle Aeronautical University, Florida'
   );

DELETE FROM ref_institution_alias
 WHERE alias = 'Embry-Riddle Aeronautical University, Florida'
   AND institution_id = (
       SELECT id FROM ref_institution
        WHERE canonical_name = 'Embry-Riddle Aeronautical University, Arizona'
   );

-- ---------------------------------------------------------------------------
-- 4. Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    parent_id        BIGINT;
    parent_self_alias INT;
    az_id            BIGINT;
    fl_id            BIGINT;
    az_aliases       INT;
    fl_aliases       INT;
BEGIN
    SELECT id INTO parent_id
      FROM ref_institution
     WHERE canonical_name = 'Embry-Riddle Aeronautical University';

    IF parent_id IS NULL THEN
        RAISE EXCEPTION 'Phase 14.09 FAILED: parent canonical not found';
    END IF;

    SELECT COUNT(*) INTO parent_self_alias
      FROM ref_institution_alias
     WHERE institution_id = parent_id
       AND alias = 'Embry-Riddle Aeronautical University';

    IF parent_self_alias <> 1 THEN
        RAISE EXCEPTION 'Phase 14.09 FAILED: expected 1 self-alias on parent, found %', parent_self_alias;
    END IF;

    -- Verify cross-links are gone
    SELECT id INTO az_id FROM ref_institution
        WHERE canonical_name = 'Embry-Riddle Aeronautical University, Arizona';
    SELECT id INTO fl_id FROM ref_institution
        WHERE canonical_name = 'Embry-Riddle Aeronautical University, Florida';

    SELECT COUNT(*) INTO az_aliases
      FROM ref_institution_alias
     WHERE institution_id = az_id
       AND alias = 'Embry-Riddle Aeronautical University, Florida';

    SELECT COUNT(*) INTO fl_aliases
      FROM ref_institution_alias
     WHERE institution_id = fl_id
       AND alias = 'Embry-Riddle Aeronautical University, Arizona';

    IF az_aliases <> 0 OR fl_aliases <> 0 THEN
        RAISE EXCEPTION 'Phase 14.09 FAILED: cross-linking aliases still present (az→fl=%, fl→az=%)',
            az_aliases, fl_aliases;
    END IF;

    RAISE NOTICE 'Phase 14.09 OK: parent id=% (with self-alias), cross-links cleaned (az_id=%, fl_id=%).',
        parent_id, az_id, fl_id;
END $$;

COMMIT;

-- =============================================================================
-- Post-run inspection — should show parent + 2 campuses + their legitimate aliases:
--   SELECT i.id, i.canonical_name, ria.alias
--     FROM ref_institution i
--     LEFT JOIN ref_institution_alias ria ON ria.institution_id = i.id
--    WHERE i.canonical_name LIKE 'Embry-Riddle%'
--    ORDER BY i.canonical_name, ria.alias;
-- =============================================================================
