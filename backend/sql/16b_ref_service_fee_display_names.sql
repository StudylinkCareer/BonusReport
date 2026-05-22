-- ============================================================================
-- Phase 16b — ref_service_fee display names + alias seeding
-- ============================================================================
--
-- Adds display_name_vi (NOT NULL) and display_name_en (NULL) to
-- ref_service_fee, mirroring the ref_client_type pattern. Populates
-- display_name_vi for all 37 active rows in Title Case. Seeds
-- ref_service_fee_alias with the user-provided aliases (misspelling
-- tolerance for the importer).
--
-- After this migration:
--   * UI dropdowns query display_name_vi
--   * Engine continues to use service_code for joins
--   * Importer's _resolve_package_from_notes resolves alias text →
--     ref_service_fee.id via ref_service_fee_alias
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. Schema additions
-- ----------------------------------------------------------------------------

ALTER TABLE ref_service_fee
    ADD COLUMN IF NOT EXISTS display_name_vi text,
    ADD COLUMN IF NOT EXISTS display_name_en text;

-- Populate display_name_vi for every active row before applying NOT NULL.
-- One UPDATE per row, by service_code, for explicit auditability.

-- ---- PACKAGE (11 rows) -----------------------------------------------------
UPDATE ref_service_fee SET display_name_vi = 'Standard (Free)'                            WHERE service_code = 'AP_GOI_1_STANDARD';
UPDATE ref_service_fee SET display_name_vi = 'Standard Plus (3tr)'                        WHERE service_code = 'AP_GOI_2_STANDARD_PLUS';
UPDATE ref_service_fee SET display_name_vi = 'Superior Package (6tr)'                     WHERE service_code = 'AP_GOI_3_SUPERIOR';
UPDATE ref_service_fee SET display_name_vi = 'Premium Package (9tr)'                      WHERE service_code = 'AP_GOI_4_PREMIUM_HCM';
UPDATE ref_service_fee SET display_name_vi = 'SDS (7tr5)'                                 WHERE service_code = 'CA_GOI_1_SDS';
UPDATE ref_service_fee SET display_name_vi = 'Standard Package (9tr5)'                    WHERE service_code = 'CA_GOI_2_STANDARD_REGULAR';
UPDATE ref_service_fee SET display_name_vi = 'Premium Canada (14tr)'                      WHERE service_code = 'CA_GOI_3_PREMIUM';
UPDATE ref_service_fee SET display_name_vi = 'Standard Package (16tr)'                    WHERE service_code = 'US_GOI_1_STANDARD_INFULL';
UPDATE ref_service_fee SET display_name_vi = 'Superior Package USA In-Full (45tr)'        WHERE service_code = 'US_GOI_2_SUPERIOR_INFULL';
UPDATE ref_service_fee SET display_name_vi = 'Standard Package USA Out-Full (28tr)'       WHERE service_code = 'US_GOI_3_STANDARD_OUTFULL';
UPDATE ref_service_fee SET display_name_vi = 'Superior Package USA Out-Full (68tr)'       WHERE service_code = 'US_GOI_4_SUPERIOR_OUTFULL';

-- ---- ADDON (2 rows) — both map to 'Difficult Case' per your decision -------
UPDATE ref_service_fee SET display_name_vi = 'Difficult Case'                             WHERE service_code = 'AP_DIFFICULT_CASE_AU';
UPDATE ref_service_fee SET display_name_vi = 'Difficult Case'                             WHERE service_code = 'AP_DIFFICULT_CASE_NZ';

-- ---- CONTRACT (3 rows) -----------------------------------------------------
UPDATE ref_service_fee SET display_name_vi = 'Guardian AU Add-On'                         WHERE service_code = 'GUARDIAN_AU_ADDON';
UPDATE ref_service_fee SET display_name_vi = 'Out-System Full Service (AUS)'              WHERE service_code = 'OUT_SYSTEM_FULL_AUS';
UPDATE ref_service_fee SET display_name_vi = 'Referral (Lovely Cup of Coffee)'            WHERE service_code = 'REFERRAL_LOVELY_COFFEE';

-- ---- SERVICE_FEE (21 rows) -------------------------------------------------
UPDATE ref_service_fee SET display_name_vi = 'Out-System Full Service'                    WHERE service_code = 'OUT_SYSTEM_FULL_SERVICE_30M';
UPDATE ref_service_fee SET display_name_vi = 'Out-System via Master Agent'                WHERE service_code = 'OUT_SYSTEM_MASTER_AGENT_14M';
UPDATE ref_service_fee SET display_name_vi = 'VN Local Enrolment'                         WHERE service_code = 'VN_LOCAL_ENROLMENT';
UPDATE ref_service_fee SET display_name_vi = 'Study Permit Renewal'                       WHERE service_code = 'STUDY_PERMIT_RENEWAL';
UPDATE ref_service_fee SET display_name_vi = 'Student Visa Renewal'                       WHERE service_code = 'VISA_RENEWAL';
UPDATE ref_service_fee SET display_name_vi = 'Visa Only'                                  WHERE service_code = 'VISA_ONLY';
UPDATE ref_service_fee SET display_name_vi = 'Visa 485'                                   WHERE service_code = 'VISA_485';
UPDATE ref_service_fee SET display_name_vi = 'CAQ'                                        WHERE service_code = 'CAQ';
UPDATE ref_service_fee SET display_name_vi = 'Guardian Change'                            WHERE service_code = 'GUARDIAN_CHANGE';
UPDATE ref_service_fee SET display_name_vi = 'Guardian Granted'                           WHERE service_code = 'GUARDIAN_GRANTED';
UPDATE ref_service_fee SET display_name_vi = 'Guardian Refused'                           WHERE service_code = 'GUARDIAN_REFUSED';
UPDATE ref_service_fee SET display_name_vi = 'Guardian Visa'                              WHERE service_code = 'GUARDIAN_VISA';
UPDATE ref_service_fee SET display_name_vi = 'Dependant Granted'                          WHERE service_code = 'DEPENDANT_GRANTED';
UPDATE ref_service_fee SET display_name_vi = 'Dependant Refused'                          WHERE service_code = 'DEPENDANT_REFUSED';
UPDATE ref_service_fee SET display_name_vi = 'Homestay Change'                            WHERE service_code = 'HOMESTAY_CHANGE';
UPDATE ref_service_fee SET display_name_vi = 'Extra School'                               WHERE service_code = 'EXTRA_SCHOOL';
UPDATE ref_service_fee SET display_name_vi = 'Visitor Exchange'                           WHERE service_code = 'VISITOR_EXCHANGE';
UPDATE ref_service_fee SET display_name_vi = 'Cancelled Full Service'                     WHERE service_code = 'CANCELLED_FULL_SERVICE';
UPDATE ref_service_fee SET display_name_vi = 'Transfer (No Commission)'                   WHERE service_code = 'TRANSFER_NO_COMMISSION';
UPDATE ref_service_fee SET display_name_vi = 'Difficult Case (Out-System 20M+)'           WHERE service_code = 'DIFFICULT_CASE';

-- Safety check: no active row should still be NULL on display_name_vi.
-- (Inactive rows can be NULL; only active rows get the NOT NULL guarantee.)
DO $$
DECLARE missing int;
BEGIN
    SELECT COUNT(*) INTO missing
      FROM ref_service_fee
     WHERE is_active = true AND display_name_vi IS NULL;
    IF missing > 0 THEN
        RAISE EXCEPTION 'Missing display_name_vi on % active row(s) — aborting', missing;
    END IF;
END $$;

-- Now lock the column NOT NULL for active rows. Inactive rows can be NULL
-- (we don't care about hidden historical rows). Use a CHECK constraint
-- rather than NOT NULL on the column itself, so inactive rows stay valid.
ALTER TABLE ref_service_fee
    DROP CONSTRAINT IF EXISTS chk_ref_service_fee_active_display_name;
ALTER TABLE ref_service_fee
    ADD CONSTRAINT chk_ref_service_fee_active_display_name
    CHECK (is_active = false OR display_name_vi IS NOT NULL);

-- ----------------------------------------------------------------------------
-- 2. Alias seeding
-- ----------------------------------------------------------------------------
--
-- Aliases from the user's list, NFC-normalised and lower-cased so the
-- importer's _resolve_package_from_notes can match against them.
--
-- Conflict policy: ON CONFLICT DO NOTHING — if an alias already exists,
-- we don't override. Avoids breaking earlier Phase 14c seeding.
--
-- Schema reminder (from resolvers.py): ref_service_fee_alias has columns
-- (alias_text_nfc, service_fee_id). Other columns may exist (id,
-- created_at) — they take defaults.

-- ---- PACKAGE aliases -------------------------------------------------------
-- Standard Plus (3tr) — row 2
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('standard plus',              2),
    ('standard plus (3tr)',        2),
    ('goi 2 ap',                   2),
    ('3tr',                        2)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Superior Package (6tr) — row 3
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('superior',                   3),
    ('superior package',           3),
    ('superior package (6tr)',     3),
    ('superior package 6tr',       3),
    ('goi 3 ap',                   3),
    ('6tr',                        3)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Premium Package (9tr) — row 4
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('premium ap',                 4),
    ('premium package',            4),
    ('premium package (9tr)',      4),
    ('9tr',                        4)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- SDS (7tr5) — row 5
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('sds',                        5),
    ('sds (7tr5)',                 5),
    ('7tr5',                       5),
    ('5tr5',                       5),
    ('goi 1 canada',               5)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Standard Package (9tr5) — row 6
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('standard regular',           6),
    ('standard package (9tr5)',    6),
    ('regular (9tr5)',             6),
    ('9tr5',                       6),
    ('goi 2 canada',               6)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Premium Canada (14tr) — row 7
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('premium canada',             7),
    ('premium canada (14tr)',      7),
    ('14tr',                       7),
    ('goi 3 canada',               7)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Standard Package (16tr) — row 8
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('standard',                   8),
    ('standard package (16tr)',    8),
    ('16tr',                       8),
    ('standard package usa',       8),
    ('goi 1 my',                   8)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Superior Package USA In-Full (45tr) — row 9
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('superior usa in',            9),
    ('superior package usa in-full (45tr)', 9),
    ('45tr',                       9),
    ('goi 2 my',                   9)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Standard Package USA Out-Full (28tr) — row 10
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('standard out',              10),
    ('standard package usa out-full (28tr)', 10),
    ('28tr',                      10),
    ('goi 3 my',                  10)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Superior Package USA Out-Full (68tr) — row 11
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('superior usa out',          11),
    ('superior package usa out-full (68tr)', 11),
    ('68tr',                      11),
    ('goi 4 my',                  11)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- ---- CONTRACT / ADDON aliases (per user's list) ----------------------------
-- Out-system Full AUS — row 50
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('out system full aus',       50),
    ('outsystem aus full',        50),
    ('out-system full service (aus)', 50)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Guardian AU Add-on — row 14
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('guardian au addon',         14),
    ('guardian au',               14),
    ('guardian au add-on',        14)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- Referral Lovely Cup of Coffee — row 51
INSERT INTO ref_service_fee_alias (alias_text_nfc, service_fee_id) VALUES
    ('lovely cup',                51),
    ('referral partner',          51),
    ('lovely cup of coffee',      51),
    ('referral (lovely cup of coffee)', 51)
ON CONFLICT (alias_text_nfc) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 3. Verification
-- ----------------------------------------------------------------------------

-- Confirm every active row has a name
SELECT id, service_code, category, display_name_vi
  FROM ref_service_fee
 WHERE is_active = true
 ORDER BY category, id;

-- Confirm alias count by service_fee
SELECT sf.id, sf.service_code, sf.display_name_vi,
       COUNT(a.alias_text_nfc) AS alias_count
  FROM ref_service_fee sf
  LEFT JOIN ref_service_fee_alias a ON a.service_fee_id = sf.id
 WHERE sf.is_active = true
 GROUP BY sf.id, sf.service_code, sf.display_name_vi
 ORDER BY sf.id;

COMMIT;
