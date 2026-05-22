-- ============================================================================
-- Phase 14c: Package taxonomy cleanup (FINAL — verified against live schema)
-- ============================================================================
-- Verified column names (from information_schema query 2026-05-21):
--   tx_case.package_fee_id              (NOT package_service_fee_id)
--   ref_service_fee.service_code        (NOT fee_code)
--   ref_service_fee.refund_on_visa_refused (NOT refund_if_visa_refused)
--   dim_country.code values: AU=55, CA=56, US=57, NZ=58, SG=60
--   dim_role.id 18 = CO_SUB
--
-- Source authority:
--   Tổng_hợp_chương_trình_quà_tặng_gói_dịch_vụ_AP_1.pdf
--   Tổng_hợp_chương_trình_quà_tặng_gói_dịch_vụ_Canada_1.pdf
--   Tổng_hợp_gói_dịch_vụ_Mỹ_1.pdf
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 0. Schema preconditions — fail loud if anything's drifted
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    country_count INT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tx_case' AND column_name = 'package_fee_id'
    ) THEN
        RAISE EXCEPTION 'Precondition failed: tx_case.package_fee_id missing.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ref_service_fee' AND column_name = 'service_code'
    ) THEN
        RAISE EXCEPTION 'Precondition failed: ref_service_fee.service_code missing.';
    END IF;

    SELECT COUNT(*) INTO country_count
    FROM dim_country WHERE code IN ('AU', 'CA', 'US', 'NZ', 'SG');
    IF country_count != 5 THEN
        RAISE EXCEPTION 'Precondition failed: expected 5 country codes AU/CA/US/NZ/SG, found %.', country_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'trg_set_updated_at'
    ) THEN
        RAISE EXCEPTION 'Precondition failed: trigger function trg_set_updated_at missing.';
    END IF;
END $$;


-- ----------------------------------------------------------------------------
-- 1. Junction table for package↔country many-to-many
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_service_fee_country (
    service_fee_id BIGINT NOT NULL
        REFERENCES ref_service_fee(id) ON DELETE CASCADE,
    country_id BIGINT NOT NULL
        REFERENCES dim_country(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (service_fee_id, country_id)
);

CREATE INDEX IF NOT EXISTS idx_ref_service_fee_country_country
    ON ref_service_fee_country(country_id);

DROP TRIGGER IF EXISTS trg_ref_service_fee_country_updated_at
    ON ref_service_fee_country;
CREATE TRIGGER trg_ref_service_fee_country_updated_at
    BEFORE UPDATE ON ref_service_fee_country
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

COMMENT ON TABLE ref_service_fee_country IS
    'Many-to-many: which countries each ref_service_fee row applies to. '
    'AP packages span AU+NZ+SG; CA/US packages bind to single country. '
    'Replaces the deprecated ref_service_fee.country_id column.';


-- ----------------------------------------------------------------------------
-- 2. Alias table — drop messy existing version, rebuild clean
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS ref_service_fee_alias CASCADE;

CREATE TABLE ref_service_fee_alias (
    id BIGSERIAL PRIMARY KEY,
    service_fee_id BIGINT NOT NULL
        REFERENCES ref_service_fee(id) ON DELETE CASCADE,
    alias_text_nfc TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ref_service_fee_alias_text UNIQUE (alias_text_nfc),
    CONSTRAINT chk_ref_service_fee_alias_lowercase
        CHECK (alias_text_nfc = LOWER(alias_text_nfc))
);

CREATE INDEX idx_ref_service_fee_alias_target
    ON ref_service_fee_alias(service_fee_id);

CREATE TRIGGER trg_ref_service_fee_alias_updated_at
    BEFORE UPDATE ON ref_service_fee_alias
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

COMMENT ON TABLE ref_service_fee_alias IS
    'Aliases for ref_service_fee.service_code. alias_text_nfc is stored '
    'NFC-normalized and lowercased — enforced by CHECK constraint. Callers '
    'must normalize input before querying. Used by transformer.py to '
    'resolve free-text package mentions to canonical service_fee_id.';

COMMENT ON COLUMN ref_service_fee_alias.alias_text_nfc IS
    'NFC-normalized, lowercased, trimmed alias text. CHECK constraint '
    'enforces lowercase at write time. NFC normalization is the caller''s '
    'responsibility (Python unicodedata.normalize("NFC", ...)).';


-- ----------------------------------------------------------------------------
-- 3. Fix Canada SDS canonical fee (id=5: 7,000,000 → 7,500,000)
-- ----------------------------------------------------------------------------
UPDATE ref_service_fee
SET fee_amount = 7500000,
    notes = 'CA Gói 1 SDS — 7.5M fee per Canada PDF. No bonus payable.'
WHERE id = 5
  AND service_code = 'CA_GOI_1_SDS';


-- ----------------------------------------------------------------------------
-- 4. Migrate existing single-country bindings (Canada + US) into junction
-- ----------------------------------------------------------------------------
INSERT INTO ref_service_fee_country (service_fee_id, country_id)
SELECT id, country_id
FROM ref_service_fee
WHERE category = 'PACKAGE'
  AND country_id IS NOT NULL
  AND id BETWEEN 1 AND 11
ON CONFLICT DO NOTHING;


-- ----------------------------------------------------------------------------
-- 5. Insert AP package junction rows (AP_GOI_1..4 × {AU, NZ, SG})
-- ----------------------------------------------------------------------------
INSERT INTO ref_service_fee_country (service_fee_id, country_id)
SELECT sf.id, c.id
FROM ref_service_fee sf
CROSS JOIN dim_country c
WHERE sf.service_code IN (
        'AP_GOI_1_STANDARD',
        'AP_GOI_2_STANDARD_PLUS',
        'AP_GOI_3_SUPERIOR',
        'AP_GOI_4_PREMIUM_HCM'
      )
  AND c.code IN ('AU', 'NZ', 'SG')
ON CONFLICT DO NOTHING;


-- ----------------------------------------------------------------------------
-- 6. Populate ref_service_fee_alias with validated package aliases
-- ----------------------------------------------------------------------------

-- AP Standard Plus → canonical id=2
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (2, 'standard plus (3tr)', 'Bracketed fee variant'),
    (2, 'standard plus 3tr',   'Observed in source notes (no brackets)'),
    (2, 'standard plus',       'Short form'),
    (2, 'goi 2 ap',            'Procedural doc reference');

-- AP Superior → canonical id=3
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (3, 'superior package (6tr)', 'Bracketed fee variant'),
    (3, 'superior package 6tr',   'Observed in source notes (no brackets)'),
    (3, 'goi 3 ap',               'Procedural doc reference');

-- AP Premium → canonical id=4
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (4, 'premium package (9tr)', 'Bracketed fee variant'),
    (4, 'premium package 9tr',   'Observed in source notes (no brackets)'),
    (4, 'premium package',       'Short form'),
    (4, 'premium ap',            'Disambiguating (vs Premium Canada)'),
    (4, 'goi 4 ap',              'Procedural doc reference');

-- Canada SDS → canonical id=5
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (5, 'sds (7tr5)',     'Bracketed fee variant'),
    (5, 'sds 7tr5',       'Observed in source notes (current fee)'),
    (5, 'goi sds 7tr5',   'Observed: "chuyển sang gói SDS 7tr5"'),
    (5, 'sds (5tr5)',     'Legacy fee variant (5,500,000)'),
    (5, 'sds 5tr5',       'Legacy fee shorthand'),
    (5, 'sds',            'Short form'),
    (5, 'goi 1 canada',   'Procedural doc reference');

-- Canada Standard Regular → canonical id=6
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (6, 'standard package (9tr5)', 'Bracketed fee variant'),
    (6, 'standard package 9tr5',   'Observed in source notes (no brackets)'),
    (6, 'regular (9tr5)',          'Legacy form'),
    (6, 'standard regular 9tr5',   'Observed in source notes'),
    (6, 'standard regular',        'Short form'),
    (6, 'goi 2 canada',            'Procedural doc reference');

-- Canada Premium → canonical id=7
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (7, 'premium canada (14tr)', 'Bracketed fee variant'),
    (7, 'premium canada 14tr',   'Observed in source notes (no brackets)'),
    (7, 'premium canada',        'Short form'),
    (7, 'goi 3 canada',          'Procedural doc reference');

-- US Standard In-Full → canonical id=8
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (8, 'standard package (16tr)', 'Bracketed fee variant'),
    (8, 'standard package 16tr',   'Observed (most common US form)'),
    (8, 'standard package usa',    'Disambiguating (vs Standard Regular Canada)'),
    (8, 'goi 1 my',                'Procedural doc reference');

-- US Superior In-Full → canonical id=9
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (9, 'superior package usa in-full (45tr)', 'Bracketed fee variant'),
    (9, 'superior package usa in-full 45tr',   'Observed (no brackets)'),
    (9, 'superior usa in',                     'Short form'),
    (9, 'goi 2 my',                            'Procedural doc reference');

-- US Standard Out-Full → canonical id=10
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (10, 'standard package usa out-full (28tr)', 'Bracketed fee variant'),
    (10, 'standard package usa out-full 28tr',   'Observed (no brackets)'),
    (10, 'standard out',                         'Short form'),
    (10, 'goi 3 my',                             'Procedural doc reference');

-- US Superior Out-Full → canonical id=11
INSERT INTO ref_service_fee_alias (service_fee_id, alias_text_nfc, notes) VALUES
    (11, 'superior package usa out-full (68tr)', 'Bracketed fee variant'),
    (11, 'superior package usa out-full 68tr',   'Observed (no brackets)'),
    (11, 'superior usa out',                     'Short form'),
    (11, 'goi 4 my',                             'Procedural doc reference');


-- ----------------------------------------------------------------------------
-- 7. Safety check: no tx_case currently references duplicates by FK
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    orphan_count INT;
BEGIN
    SELECT COUNT(*) INTO orphan_count
    FROM tx_case
    WHERE package_fee_id IN (37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49);

    IF orphan_count > 0 THEN
        RAISE EXCEPTION
            'Cannot delete duplicate PACKAGE rows: % tx_case row(s) still '
            'reference them via package_fee_id.', orphan_count;
    END IF;
END $$;


-- ----------------------------------------------------------------------------
-- 8. Delete duplicate PACKAGE rows
-- ----------------------------------------------------------------------------
DELETE FROM ref_service_fee
WHERE id IN (37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49)
  AND category = 'PACKAGE';


-- ----------------------------------------------------------------------------
-- 9. Verification
-- ----------------------------------------------------------------------------

DO $$
DECLARE
    pkg_count INT;
BEGIN
    SELECT COUNT(*) INTO pkg_count
    FROM ref_service_fee
    WHERE category = 'PACKAGE' AND is_active = TRUE;

    IF pkg_count != 11 THEN
        RAISE EXCEPTION 'Expected 11 canonical PACKAGE rows, found %.', pkg_count;
    END IF;
END $$;

DO $$
DECLARE
    unbound_count INT;
BEGIN
    SELECT COUNT(*) INTO unbound_count
    FROM ref_service_fee sf
    WHERE sf.category = 'PACKAGE' AND sf.is_active = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM ref_service_fee_country sfc
          WHERE sfc.service_fee_id = sf.id
      );

    IF unbound_count > 0 THEN
        RAISE EXCEPTION 'Found % PACKAGE row(s) with no country binding.', unbound_count;
    END IF;
END $$;

DO $$
DECLARE
    ap_row RECORD;
    binding_count INT;
BEGIN
    FOR ap_row IN
        SELECT id FROM ref_service_fee
        WHERE service_code IN (
            'AP_GOI_1_STANDARD', 'AP_GOI_2_STANDARD_PLUS',
            'AP_GOI_3_SUPERIOR', 'AP_GOI_4_PREMIUM_HCM'
        )
    LOOP
        SELECT COUNT(*) INTO binding_count
        FROM ref_service_fee_country
        WHERE service_fee_id = ap_row.id;

        IF binding_count != 3 THEN
            RAISE EXCEPTION
                'AP row id=% should have 3 country bindings, has %.',
                ap_row.id, binding_count;
        END IF;
    END LOOP;
END $$;

DO $$
DECLARE
    sds_fee BIGINT;
BEGIN
    SELECT fee_amount INTO sds_fee
    FROM ref_service_fee WHERE id = 5;

    IF sds_fee != 7500000 THEN
        RAISE EXCEPTION 'Canada SDS (id=5) fee should be 7,500,000 but is %.', sds_fee;
    END IF;
END $$;


-- ----------------------------------------------------------------------------
-- 10. Display final state for human review
-- ----------------------------------------------------------------------------
SELECT
    sf.id,
    sf.service_code,
    sf.fee_amount,
    sf.counsellor_signing_bonus AS coun_signing,
    sf.co_signing_bonus AS co_signing,
    sf.refund_on_visa_refused AS refund_refused,
    ARRAY_AGG(DISTINCT c.code ORDER BY c.code) AS countries,
    (SELECT COUNT(*) FROM ref_service_fee_alias a
     WHERE a.service_fee_id = sf.id) AS alias_count
FROM ref_service_fee sf
LEFT JOIN ref_service_fee_country sfc ON sfc.service_fee_id = sf.id
LEFT JOIN dim_country c ON c.id = sfc.country_id
WHERE sf.category = 'PACKAGE' AND sf.is_active = TRUE
GROUP BY sf.id
ORDER BY sf.id;

COMMIT;
