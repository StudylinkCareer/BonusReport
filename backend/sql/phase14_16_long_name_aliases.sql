-- =============================================================================
-- Phase 14_16: Add full-name aliases for UNRESOLVED_REFER_SOURCE
-- =============================================================================
-- After Phase 14_11/12/13 added short canonical names + matching aliases, the
-- source data still uses LONG company names. Adding those long names as
-- additional aliases pointing to the existing canonical partners.
--
-- 8 distinct aliases covering 14 cases:
--   VIRASIMEX (5):  long Vietnamese name → existing canonical "VIRASIMEX"
--   HADO (2):       full IELTS center name → existing "HADO IELTS Center"
--   Âu-Úc-Mỹ (2):   full Vietnamese name → existing "Âu-Úc-Mỹ Int'l Education"
--   SACE (1):       full name with abbrev → existing sentinel "(Qualification — Not Partner)"
--   HT (2 variants): two casing variants → existing "HT International Manpower"
--   StudyLink HN (1): full Vietnamese branch name → existing sentinel "(StudyLink Internal — Own Org)"
--   PTNELC (1):     full company name → existing "PTNELC Education"
--
-- Idempotent: ON CONFLICT DO NOTHING.
-- =============================================================================

BEGIN;

INSERT INTO ref_partner_alias (partner_id, alias)
SELECT p.id, v.alias
  FROM (VALUES
    ('Công ty Cổ Phần Phát Triển Việc Làm Và Xuất Khẩu Lao Động VIRASIMEX', 'VIRASIMEX'),
    ('Trung tâm luyện thi IELTS HADO (Hà Đô)',                             'HADO IELTS Center'),
    ('Công Ty Cổ Phần Đầu Tư Giáo Dục Quốc Tế Âu - Úc - Mỹ',               'Âu-Úc-Mỹ Int''l Education'),
    ('South Australian Certificate of Education (SACE)',                    '(Qualification — Not Partner)'),
    ('Công ty TNHH Cung Ứng Nhân Lực Quốc Tế HT',                          'HT International Manpower'),
    ('Công ty TNHH cung ứng nhân lực quốc tế HT',                          'HT International Manpower'),
    ('StudyLink International (văn phòng chi nhánh Hà Nội)',                '(StudyLink Internal — Own Org)'),
    ('Công ty TNHH Giáo dục PTNELC',                                        'PTNELC Education')
  ) AS v(alias, canonical_name)
  JOIN ref_partner p ON p.name = v.canonical_name
ON CONFLICT (alias) DO NOTHING;


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    new_count INT;
BEGIN
    SELECT COUNT(*) INTO new_count
      FROM ref_partner_alias
     WHERE alias IN (
        'Công ty Cổ Phần Phát Triển Việc Làm Và Xuất Khẩu Lao Động VIRASIMEX',
        'Trung tâm luyện thi IELTS HADO (Hà Đô)',
        'Công Ty Cổ Phần Đầu Tư Giáo Dục Quốc Tế Âu - Úc - Mỹ',
        'South Australian Certificate of Education (SACE)',
        'Công ty TNHH Cung Ứng Nhân Lực Quốc Tế HT',
        'Công ty TNHH cung ứng nhân lực quốc tế HT',
        'StudyLink International (văn phòng chi nhánh Hà Nội)',
        'Công ty TNHH Giáo dục PTNELC'
     );

    IF new_count <> 8 THEN
        RAISE EXCEPTION 'Phase 14_16 FAILED: expected 8 aliases linked, found %', new_count;
    END IF;

    RAISE NOTICE 'Phase 14_16 OK: % long-name aliases linked to existing canonical partners.', new_count;
    RAISE NOTICE 'Should clear all 14 remaining UNRESOLVED_REFER_SOURCE cases on next import reload.';
END $$;

COMMIT;
