-- =============================================================================
-- Phase 14_13: Bucket 3 sentinel partners (data quality oddities)
-- =============================================================================
-- Purpose:
--   Clear the last 4 UNRESOLVED_REFER_SOURCE warnings by aliasing 3 oddball
--   source values to sentinel partners. These are NOT real partners:
--     - "Trong hệ thống" — Vietnamese CRM system metadata leakage (2 cases)
--     - "StudyLink International Hanoi branch" — own organization (1 case)
--     - "SACE" — South Australian Certificate of Education, a qualification (1 case)
--
-- Sentinel naming uses parenthesized prefix to make non-real partners obvious
-- in any report or KPI rollup.
--
-- Classification: GROUP for all (avoids needing a new SYSTEM enum value).
-- Add `is_active = FALSE` so any future KPI math correctly excludes them
-- from partner attribution counts.
--
-- Schema (verified): same as Phase 14_11 / 14_12.
-- Idempotent: ON CONFLICT DO NOTHING.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Insert sentinel partners (marked is_active=FALSE so they don't count
--    in active-partner KPIs)
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner (name, classification, is_active, notes)
VALUES
    ('(System Metadata Leakage)',
     'GROUP', FALSE,
     'Phase 14_13 sentinel: catches "Trong hệ thống" — CRM system metadata that ' ||
     'leaked into the referrer source field. Not a real partner.'),

    ('(StudyLink Internal — Own Org)',
     'GROUP', FALSE,
     'Phase 14_13 sentinel: catches own-organization references like ' ||
     '"StudyLink International Hanoi branch". Not an external partner.'),

    ('(Qualification — Not Partner)',
     'GROUP', FALSE,
     'Phase 14_13 sentinel: catches qualification names mistakenly entered as ' ||
     'referrer (e.g. "SACE" = South Australian Certificate of Education).')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Insert aliases pointing to the appropriate sentinels
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner_alias (partner_id, alias)
SELECT p.id, v.alias
  FROM (VALUES
    ('Trong hệ thống',                         '(System Metadata Leakage)'),
    ('StudyLink International Hanoi branch',   '(StudyLink Internal — Own Org)'),
    ('SACE',                                   '(Qualification — Not Partner)')
  ) AS v(alias, sentinel_name)
  JOIN ref_partner p ON p.name = v.sentinel_name
ON CONFLICT (alias) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    sentinel_count INT;
    alias_count    INT;
BEGIN
    SELECT COUNT(*) INTO sentinel_count
      FROM ref_partner
     WHERE name IN (
         '(System Metadata Leakage)',
         '(StudyLink Internal — Own Org)',
         '(Qualification — Not Partner)'
     )
       AND classification = 'GROUP'
       AND is_active = FALSE;

    SELECT COUNT(*) INTO alias_count
      FROM ref_partner_alias
     WHERE alias IN (
         'Trong hệ thống',
         'StudyLink International Hanoi branch',
         'SACE'
     );

    IF sentinel_count <> 3 THEN
        RAISE EXCEPTION 'Phase 14_13 FAILED: expected 3 inactive sentinels, found %', sentinel_count;
    END IF;

    IF alias_count <> 3 THEN
        RAISE EXCEPTION 'Phase 14_13 FAILED: expected 3 sentinel aliases, found %', alias_count;
    END IF;

    RAISE NOTICE 'Phase 14_13 OK: % sentinels + % aliases inserted (or already present).',
        sentinel_count, alias_count;
END $$;

COMMIT;

-- =============================================================================
-- Post-run inspection:
--   SELECT p.id, p.name, p.is_active, rpa.alias
--     FROM ref_partner p
--     LEFT JOIN ref_partner_alias rpa ON rpa.partner_id = p.id
--    WHERE p.name LIKE '(%)'
--    ORDER BY p.name, rpa.alias;
-- =============================================================================
