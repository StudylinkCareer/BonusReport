-- =============================================================================
-- Phase 14_14: Add partner aliases for EduCo International (id=60)
-- =============================================================================
-- Purpose:
--   Future-proof against any case data using "EduCo" or "EduCo/ USA" as a
--   referrer source string by aliasing both to the canonical EduCo International
--   partner (already exists as id=60, MASTER_AGENT classification — locked).
--
-- Idempotent: ON CONFLICT DO NOTHING.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add aliases pointing to the existing EduCo International partner
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner_alias (partner_id, alias)
SELECT p.id, v.alias
  FROM (VALUES
    ('EduCo'),
    ('EduCo/ USA')
  ) AS v(alias)
  CROSS JOIN ref_partner p
 WHERE p.name = 'EduCo International'
   AND p.classification = 'MASTER_AGENT'
ON CONFLICT (alias) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    educo_id    BIGINT;
    alias_count INT;
BEGIN
    SELECT id INTO educo_id
      FROM ref_partner
     WHERE name = 'EduCo International'
       AND classification = 'MASTER_AGENT';

    IF educo_id IS NULL THEN
        RAISE EXCEPTION 'Phase 14_14 FAILED: EduCo International (MASTER_AGENT) not found';
    END IF;

    SELECT COUNT(*) INTO alias_count
      FROM ref_partner_alias
     WHERE partner_id = educo_id
       AND alias IN ('EduCo', 'EduCo/ USA');

    IF alias_count <> 2 THEN
        RAISE EXCEPTION 'Phase 14_14 FAILED: expected 2 aliases for EduCo (id=%), found %',
            educo_id, alias_count;
    END IF;

    RAISE NOTICE 'Phase 14_14 OK: EduCo International (id=%) now has 2 aliases (EduCo, EduCo/ USA).',
        educo_id;
END $$;

COMMIT;

-- =============================================================================
-- Post-run inspection:
--   SELECT p.id, p.name, p.classification, rpa.alias
--     FROM ref_partner p
--     LEFT JOIN ref_partner_alias rpa ON rpa.partner_id = p.id
--    WHERE p.name = 'EduCo International'
--    ORDER BY rpa.alias;
-- =============================================================================
