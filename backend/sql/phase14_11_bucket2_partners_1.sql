-- =============================================================================
-- Phase 14_11: Load Bucket 2 partners as-is (acronyms, full names pending)
-- =============================================================================
-- Purpose:
--   Clear 11 of the 38 UNRESOLVED_REFER_SOURCE warnings by adding the 5 Bucket 2
--   referrer values as canonical partners. Per user decision, load with the
--   source string as the canonical name (no full-name resolution attempted).
--
-- Schema (verified via information_schema 2026-05-10):
--   ref_partner( id bigint PK,
--                name varchar UNIQUE NOT NULL,
--                classification varchar NOT NULL,
--                is_active boolean NOT NULL DEFAULT TRUE,
--                notes text,
--                effective_from date NOT NULL DEFAULT '2024-01-01',
--                effective_to date,
--                created_at, updated_at )
--   ref_partner_alias( id bigint PK,
--                      partner_id bigint NOT NULL FK -> ref_partner.id,
--                      alias varchar UNIQUE NOT NULL,
--                      created_at )
--
-- Classification: GROUP for all (none appear in the 9 hardcoded Master Agents).
-- Idempotent: ON CONFLICT DO NOTHING on both partner and alias.
--
-- Affected source values (count from diagnostic):
--   KNT                       3 cases
--   TNC                       3 cases
--   VAN (Melbourne)           3 cases
--   TMC Academy (Phương)      2 cases
--   Hoàng Lê – VP Mel         1 case
--                            ---
--                             11 cases total
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Insert canonical partners
--    `notes` carries provenance so future-you knows these were loaded as-is.
--    `is_active` defaults TRUE; `effective_from` defaults '2024-01-01'.
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner (name, classification, notes)
VALUES
    ('KNT',                  'GROUP', 'Phase 14_11: loaded as-is, full name pending resolution'),
    ('TNC',                  'GROUP', 'Phase 14_11: loaded as-is, full name pending resolution'),
    ('VAN (Melbourne)',      'GROUP', 'Phase 14_11: loaded as-is, full name pending resolution'),
    ('TMC Academy (Phương)', 'GROUP', 'Phase 14_11: loaded as-is, "Phương" likely contact identifier'),
    ('Hoàng Lê – VP Mel',    'GROUP', 'Phase 14_11: loaded as-is, "VP Mel" likely Văn Phòng Melbourne')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Insert aliases (one per canonical, mirroring the name).
--    Lookup-by-name pattern works whether the row was just inserted above
--    or already existed from a prior run.
-- ---------------------------------------------------------------------------
INSERT INTO ref_partner_alias (partner_id, alias)
SELECT p.id, p.name
  FROM ref_partner p
 WHERE p.name IN (
    'KNT',
    'TNC',
    'VAN (Melbourne)',
    'TMC Academy (Phương)',
    'Hoàng Lê – VP Mel'
 )
ON CONFLICT (alias) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Self-verification — fail loudly if anything didn't land
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    expected_names TEXT[] := ARRAY[
        'KNT',
        'TNC',
        'VAN (Melbourne)',
        'TMC Academy (Phương)',
        'Hoàng Lê – VP Mel'
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
       AND p.name = rpa.alias;   -- confirms FK linkage too

    IF partner_count <> 5 THEN
        RAISE EXCEPTION 'Phase 14_11 FAILED: expected 5 GROUP partners, found %', partner_count;
    END IF;

    IF alias_count <> 5 THEN
        RAISE EXCEPTION 'Phase 14_11 FAILED: expected 5 linked aliases, found %', alias_count;
    END IF;

    RAISE NOTICE 'Phase 14_11 OK: % partners + % aliases inserted (or already present).',
        partner_count, alias_count;
END $$;

COMMIT;

-- =============================================================================
-- Post-run inspection (run separately if you want to eyeball the result):
--
--   SELECT p.id, p.name, p.classification, p.notes, rpa.alias
--     FROM ref_partner p
--     LEFT JOIN ref_partner_alias rpa ON rpa.partner_id = p.id
--    WHERE p.name IN
--          ('KNT','TNC','VAN (Melbourne)','TMC Academy (Phương)','Hoàng Lê – VP Mel')
--    ORDER BY p.name;
--
-- Expected: 5 rows, each partner paired with its single alias.
-- =============================================================================
