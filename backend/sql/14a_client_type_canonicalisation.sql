-- =============================================================================
-- Migration: 14a_v2_client_type_canonicalisation.sql
-- =============================================================================
-- Purpose:
--   Establish canonical client_type taxonomy with 9 official codes (plus 1
--   sentinel UNRESOLVED) and an alias table to translate raw CRM free-text
--   values to canonical codes.
--
--   v2: A prior abandoned session created ref_client_type_alias with a
--   different schema and 25 rows including ~16 fabricated English aliases
--   (e.g. "Visitor" wrongly mapped to TOURIST_VISA — "Visitor" is actually
--   a separate service code per service spec, not a client_type alias).
--   v2 DROPs that table and rebuilds from scratch with only verified aliases.
--
-- Source documents cited:
--   - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf (June 2024 policy)
--     §I.2 "Các trường hợp cụ thể" — KPI weights per service type
--     §I.5 "Hồ sơ enrolment only" — enrolment-only vs full-service
--     §I.7 "Hồ sơ du học tại chỗ (tại VN)" — Vietnam domestic = Counsellor only
--   - User specification (this session) — 9 canonical client types
--   - Observed CRM data in tx_case (current 129 rows) — 5 alias variants
--
-- Alias seed set (14 rows): every CRM Vietnamese canonical text + every
-- observed case variant in current data. NO invented English aliases.
--
-- Idempotency:
--   DROP IF EXISTS + CREATE for ref_client_type_alias (rebuilt clean)
--   CREATE IF NOT EXISTS for ref_client_type (does not exist yet)
--   ON CONFLICT DO NOTHING on all seed INSERTs
--   CHECK constraint creation wrapped in DO block
--
-- Verification:
--   Self-verification queries at end. RAISE EXCEPTION on mismatch causes
--   transaction rollback.
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 0 — DROP existing ref_client_type_alias (fabricated prior-session data)
-- =============================================================================
-- The prior table mapped raw text to client_type_code as a string with no FK
-- to a parent canonical table. v2 introduces ref_client_type as the parent,
-- and ref_client_type_alias uses an integer FK to it.

DROP TABLE IF EXISTS ref_client_type_alias;


-- =============================================================================
-- STEP 1 — Create ref_client_type (the 9 canonicals + UNRESOLVED)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ref_client_type (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(32)  NOT NULL,
    display_name_vi VARCHAR(128) NOT NULL,
    display_name_en VARCHAR(128) NOT NULL,
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (code, effective_from)
);

DROP TRIGGER IF EXISTS trg_ref_client_type_updated_at ON ref_client_type;
CREATE TRIGGER trg_ref_client_type_updated_at
    BEFORE UPDATE ON ref_client_type
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_updated_at();

-- Seed: 9 canonical client types + UNRESOLVED sentinel.
-- All effective_from = '2020-01-01' (sentinel; user loads data from Jun 2023).

INSERT INTO ref_client_type (code, display_name_vi, display_name_en, effective_from, notes)
VALUES
    ('DU_HOC_FULL',         'Du học (Ghi danh + visa)',  'Full service (enrolment + visa)',
     '2020-01-01', 'StudyLink processes both enrolment and visa.'),

    ('DU_HOC_ENROL_ONLY',   'Du học (Ghi danh)',          'Enrolment only',
     '2020-01-01', 'Per §I.5 — StudyLink handles enrolment; partner or no-one handles visa.'),

    ('SUMMER_STUDY',        'Du học hè',                  'Summer study',
     '2020-01-01', 'Per §I.2 — receives bonus but does NOT count toward KPI target.'),

    ('VIETNAM_DOMESTIC',    'Du học tại chỗ (Vietnam)',  'Vietnam domestic',
     '2020-01-01', 'Per §I.7 — Counsellor only, no CO involvement.'),

    ('GUARDIAN_VISA',       'Visa Giám hộ',               'Guardian visa',
     '2020-01-01', 'Fixed-rate service. KPI weight = 0.'),

    ('TOURIST_VISA',        'Visa Du lịch',               'Tourist visa',
     '2020-01-01', 'Fixed-rate service. KPI weight = 0.'),

    ('MIGRATION_VISA',      'Visa Định cư',               'Migration visa',
     '2020-01-01', 'Fixed-rate service. KPI weight = 0.'),

    ('DEPENDANT_VISA',      'Visa Phụ thuộc',             'Dependant visa',
     '2020-01-01', 'Fixed-rate service. KPI weight = 0.'),

    ('VISA_ONLY_SERVICE',   'Visa Du học only',           'Visa only service',
     '2020-01-01', 'Visa service only, no enrolment by StudyLink. KPI weight = 0.'),

    ('UNRESOLVED',          'Chưa xác định',              'Unresolved — needs review',
     '2020-01-01', 'Sentinel: importer could not resolve raw CRM text. Manual review required.')
ON CONFLICT (code, effective_from) DO NOTHING;


-- =============================================================================
-- STEP 2 — Create ref_client_type_alias (raw CRM text → canonical)
-- =============================================================================

CREATE TABLE ref_client_type_alias (
    id             BIGSERIAL PRIMARY KEY,
    alias_text     VARCHAR(256) NOT NULL UNIQUE,
    client_type_id BIGINT       NOT NULL REFERENCES ref_client_type(id),
    notes          TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_ref_client_type_alias_updated_at ON ref_client_type_alias;
CREATE TRIGGER trg_ref_client_type_alias_updated_at
    BEFORE UPDATE ON ref_client_type_alias
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_updated_at();

-- Seed aliases — 14 rows total:
--   * Vietnamese canonical labels (9, one per code)
--   * Case-variant observed in current 129 tx_case rows (5)
-- NO English fabrications.

-- DU_HOC_FULL (2 aliases)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học (Ghi danh + visa)', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'DU_HOC_FULL'
ON CONFLICT (alias_text) DO NOTHING;

INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học (ghi danh + visa)', id, 'Lowercase g variant. 31 rows in current load.'
  FROM ref_client_type WHERE code = 'DU_HOC_FULL'
ON CONFLICT (alias_text) DO NOTHING;

-- DU_HOC_ENROL_ONLY (2 aliases)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học (Ghi danh)', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'DU_HOC_ENROL_ONLY'
ON CONFLICT (alias_text) DO NOTHING;

INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học (ghi danh)', id, 'Lowercase g variant. 93 rows in current load.'
  FROM ref_client_type WHERE code = 'DU_HOC_ENROL_ONLY'
ON CONFLICT (alias_text) DO NOTHING;

-- SUMMER_STUDY (1 alias)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học hè', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'SUMMER_STUDY'
ON CONFLICT (alias_text) DO NOTHING;

-- VIETNAM_DOMESTIC (1 alias)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học tại chỗ (Vietnam)', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'VIETNAM_DOMESTIC'
ON CONFLICT (alias_text) DO NOTHING;

-- GUARDIAN_VISA (1 alias)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa Giám hộ', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'GUARDIAN_VISA'
ON CONFLICT (alias_text) DO NOTHING;

-- TOURIST_VISA (1 alias)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa Du lịch', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'TOURIST_VISA'
ON CONFLICT (alias_text) DO NOTHING;

-- MIGRATION_VISA (2 aliases)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa Định cư', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'MIGRATION_VISA'
ON CONFLICT (alias_text) DO NOTHING;

INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa định cư', id, 'Lowercase đ variant. 1 row in current load.'
  FROM ref_client_type WHERE code = 'MIGRATION_VISA'
ON CONFLICT (alias_text) DO NOTHING;

-- DEPENDANT_VISA (1 alias)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa Phụ thuộc', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'DEPENDANT_VISA'
ON CONFLICT (alias_text) DO NOTHING;

-- VISA_ONLY_SERVICE (3 aliases)
INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa Du học only', id, 'Canonical Vietnamese label.'
  FROM ref_client_type WHERE code = 'VISA_ONLY_SERVICE'
ON CONFLICT (alias_text) DO NOTHING;

INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Visa du học only', id, 'Lowercase d/h variant. 1 row in current load.'
  FROM ref_client_type WHERE code = 'VISA_ONLY_SERVICE'
ON CONFLICT (alias_text) DO NOTHING;

INSERT INTO ref_client_type_alias (alias_text, client_type_id, notes)
SELECT 'Du học (visa)', id, 'Observed CRM variant. 3 rows in current load including SLC-13618 (Deakin visa renewal).'
  FROM ref_client_type WHERE code = 'VISA_ONLY_SERVICE'
ON CONFLICT (alias_text) DO NOTHING;


-- =============================================================================
-- STEP 3 — Backfill tx_case.client_type_code from raw CRM text to canonical
-- =============================================================================

-- 3a) Map known aliases to canonical codes
UPDATE tx_case tc
   SET client_type_code = rct.code,
       updated_at       = NOW()
  FROM ref_client_type_alias rcta
  JOIN ref_client_type        rct ON rct.id = rcta.client_type_id
 WHERE tc.client_type_code = rcta.alias_text;

-- 3b) Anything left that isn't already a canonical code → UNRESOLVED
UPDATE tx_case
   SET client_type_code = 'UNRESOLVED',
       updated_at       = NOW()
 WHERE client_type_code NOT IN (
        SELECT code FROM ref_client_type
   );


-- =============================================================================
-- STEP 4 — Add CHECK constraint to tx_case.client_type_code
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'chk_tx_case_client_type_code'
    ) THEN
        ALTER TABLE tx_case
            ADD CONSTRAINT chk_tx_case_client_type_code
            CHECK (client_type_code IN (
                'DU_HOC_FULL', 'DU_HOC_ENROL_ONLY', 'SUMMER_STUDY',
                'VIETNAM_DOMESTIC', 'GUARDIAN_VISA', 'TOURIST_VISA',
                'MIGRATION_VISA', 'DEPENDANT_VISA', 'VISA_ONLY_SERVICE',
                'UNRESOLVED'
            ));
    END IF;
END $$;


-- =============================================================================
-- STEP 5 — Self-verification
-- =============================================================================

DO $$
DECLARE
    ct_canon_count    INT;
    ct_alias_count    INT;
    bad_codes_count   INT;
    unresolved_count  INT;
BEGIN
    -- 5a) ref_client_type should have 10 rows (9 canonicals + UNRESOLVED)
    SELECT COUNT(*) INTO ct_canon_count FROM ref_client_type;
    IF ct_canon_count <> 10 THEN
        RAISE EXCEPTION 'ref_client_type has % rows, expected exactly 10', ct_canon_count;
    END IF;

    -- 5b) ref_client_type_alias should have 14 rows
    SELECT COUNT(*) INTO ct_alias_count FROM ref_client_type_alias;
    IF ct_alias_count <> 14 THEN
        RAISE EXCEPTION 'ref_client_type_alias has % rows, expected exactly 14', ct_alias_count;
    END IF;

    -- 5c) No tx_case row should have a non-canonical client_type_code
    SELECT COUNT(*) INTO bad_codes_count
      FROM tx_case
     WHERE client_type_code NOT IN (
            'DU_HOC_FULL', 'DU_HOC_ENROL_ONLY', 'SUMMER_STUDY',
            'VIETNAM_DOMESTIC', 'GUARDIAN_VISA', 'TOURIST_VISA',
            'MIGRATION_VISA', 'DEPENDANT_VISA', 'VISA_ONLY_SERVICE',
            'UNRESOLVED'
       );
    IF bad_codes_count > 0 THEN
        RAISE EXCEPTION 'tx_case has % rows with non-canonical client_type_code', bad_codes_count;
    END IF;

    -- 5d) Report (not fail) on UNRESOLVED count — for human review
    SELECT COUNT(*) INTO unresolved_count
      FROM tx_case
     WHERE client_type_code = 'UNRESOLVED';
    RAISE NOTICE 'tx_case rows flagged UNRESOLVED: %', unresolved_count;
END $$;

COMMIT;


-- =============================================================================
-- POST-COMMIT VERIFICATION QUERIES (run separately to inspect)
-- =============================================================================

-- Canonicals
SELECT id, code, display_name_vi, display_name_en, effective_from
  FROM ref_client_type
 ORDER BY id;

-- Aliases joined to canonical
SELECT rcta.alias_text,
       rct.code AS canonical_code,
       rct.display_name_en
  FROM ref_client_type_alias rcta
  JOIN ref_client_type        rct ON rct.id = rcta.client_type_id
 ORDER BY rct.code, rcta.alias_text;

-- Post-backfill distribution
SELECT client_type_code, COUNT(*) AS row_count
  FROM tx_case
 GROUP BY client_type_code
 ORDER BY row_count DESC, client_type_code;

-- Any UNRESOLVED rows for review (should be 0 given the 5 observed variants
-- are all in the alias seed set)
SELECT id, contract_id, run_year, run_month
  FROM tx_case
 WHERE client_type_code = 'UNRESOLVED'
 ORDER BY id
 LIMIT 50;
