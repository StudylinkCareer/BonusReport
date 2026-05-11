-- =============================================================================
-- Phase 14_12: Load Bucket 1 partners (11 named, all GROUP classification)
-- =============================================================================
-- Purpose:
--   Clear 24 of the remaining 27 UNRESOLVED_REFER_SOURCE warnings (38 originally,
--   minus 11 already cleared by Phase 14_11 Bucket 2).
--
-- Classification: GROUP for all (none appear in the 9 hardcoded Master Agents).
-- Schema (verified): same as Phase 14_11.
-- Idempotent: ON CONFLICT DO NOTHING on both partner and alias.
--
-- Affected source values (count from diagnostic):
--   VIRASIMEX                              ?
--   SOUTHERN EAGLES JSC                    ?
--   Âu-Úc-Mỹ Int'l Education               ?
--   Công ty Giáo Dục Toàn Cầu              ?
--   Glodor English                         ?
--   HADO IELTS Center                      ?
--   HT International Manpower              ? (2 casing variants per journal)
--   PTNELC Education                       ?
--   Du học VStar                           ?
--   MEWORLD EDU                            ?
--   Vietlink                               ?
--                                          ---
--                                          24 cases total
--
-- NOTE on HT International Manpower: journal mentions "2 casing variants" but
-- doesn't specify what the second variant looks like. This migration adds the
-- canonical form + 1 alias mirroring it. After the next importer reload, if
-- HT International Manpower still appears in UNRESOLVED warnings under a
-- different casing, add a second alias row with the exact string seen — e.g.
--   INSERT INTO ref_partner_alias (partner_id, alias)
--   SELECT id, 'HT INTERNATIONAL MANPOWER' FROM ref_partner
--    WHERE name = 'HT International Manpower'
--   ON CONFLICT (alias) DO NOTHING;
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Insert canonical partners
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner (name, classification, notes)
VALUES
    ('VIRASIMEX',                 'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('SOUTHERN EAGLES JSC',       'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('Âu-Úc-Mỹ Int''l Education', 'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('Công ty Giáo Dục Toàn Cầu', 'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('Glodor English',            'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('HADO IELTS Center',         'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('HT International Manpower', 'GROUP', 'Phase 14_12: Bucket 1 named partner. Journal notes 2 casing variants — add second alias if importer still reports unresolved after reload.'),
    ('PTNELC Education',          'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('Du học VStar',              'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('MEWORLD EDU',               'GROUP', 'Phase 14_12: Bucket 1 named partner.'),
    ('Vietlink',                  'GROUP', 'Phase 14_12: Bucket 1 named partner.')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Insert aliases (one per canonical, mirroring the name)
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner_alias (partner_id, alias)
SELECT p.id, p.name
  FROM ref_partner p
 WHERE p.name IN (
    'VIRASIMEX',
    'SOUTHERN EAGLES JSC',
    'Âu-Úc-Mỹ Int''l Education',
    'Công ty Giáo Dục Toàn Cầu',
    'Glodor English',
    'HADO IELTS Center',
    'HT International Manpower',
    'PTNELC Education',
    'Du học VStar',
    'MEWORLD EDU',
    'Vietlink'
 )
ON CONFLICT (alias) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    expected_names TEXT[] := ARRAY[
        'VIRASIMEX',
        'SOUTHERN EAGLES JSC',
        'Âu-Úc-Mỹ Int''l Education',
        'Công ty Giáo Dục Toàn Cầu',
        'Glodor English',
        'HADO IELTS Center',
        'HT International Manpower',
        'PTNELC Education',
        'Du học VStar',
        'MEWORLD EDU',
        'Vietlink'
    ];
    partner_count INT;
    alias_count   INT;
BEGIN
    SELECT COUNT(*) INTO partner_count
      FROM ref_partner
     WHERE name = ANY(expected_names)
       AND classification = 'GROUP';

    SELECT COUNT(*) INTO alias_count
      FROM ref_partner_alias rpa
      JOIN ref_partner p ON p.id = rpa.partner_id
     WHERE rpa.alias = ANY(expected_names)
       AND p.name = rpa.alias;

    IF partner_count <> 11 THEN
        RAISE EXCEPTION 'Phase 14_12 FAILED: expected 11 GROUP partners, found %', partner_count;
    END IF;

    IF alias_count <> 11 THEN
        RAISE EXCEPTION 'Phase 14_12 FAILED: expected 11 linked aliases, found %', alias_count;
    END IF;

    RAISE NOTICE 'Phase 14_12 OK: % partners + % aliases inserted (or already present).',
        partner_count, alias_count;
END $$;

COMMIT;
