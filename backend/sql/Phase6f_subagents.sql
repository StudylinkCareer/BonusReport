-- =============================================================================
-- Phase 6f — Sub-agent seed from CRM review
-- File:    Phase6f_subagents.sql
-- Purpose: Insert sub-agents identified in the distinct-value review of
--          historical closed-file reports. Each canonical entry gets a
--          matching alias row so the importer can resolve raw CRM text.
--
-- Source: distinct_values_for_review.xlsx — "Refer Source Agent" tab
--         tagged "OK SUBAGENT" by reviewer.
--
-- Total: 64 distinct strings → 61 canonical sub-agents + 64 alias rows
--        (3 strings are case/spacing variants of existing entries and
--         become additional aliases on the same canonical row).
--
-- Notes on consolidation decisions:
--   - 'Edunetwork Việt Nam' and 'Edunetwork' → one canonical
--     'Edunetwork Việt Nam'; both as aliases.
--   - 'Edutime' and 'eDUTIME' → one canonical 'Edutime'; both as aliases.
--   - 'Công ty TNHH tư vấn di trú định cư HALI' and the title-case
--     variant → one canonical (title-case); both as aliases.
--   - 'Ngoài hệ thống' is included per reviewer tag despite being a
--     System Type value. Marked verification_status='UNVERIFIED' so it
--     surfaces in QM review. Likely a CRM data-entry error.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Insert canonical sub-agents.
-- -----------------------------------------------------------------------------
-- Idempotent via ON CONFLICT — re-running won't duplicate.
-- country_id left NULL — sub-agents may operate across multiple countries
-- and we don't have country attribution for these from the source data.

INSERT INTO ref_sub_agent (canonical_name, verification_status, notes)
VALUES
    ('Đức Anh Hà Nội',                                                                          'VERIFIED', 'Phase 6f. High volume (212 occurrences in historical data).'),
    ('Edunetwork Việt Nam',                                                                     'VERIFIED', 'Phase 6f. Aliases include short form "Edunetwork".'),
    ('Chìa khoá Du học (Key for Oversea Studies - KFO)',                                        'VERIFIED', 'Phase 6f.'),
    ('Hop Nhat We Connect Company Limited',                                                     'VERIFIED', 'Phase 6f.'),
    ('Studyland Co., Ltd.',                                                                     'VERIFIED', 'Phase 6f.'),
    ('TNSS',                                                                                    'VERIFIED', 'Phase 6f.'),
    ('G''Connect Education',                                                                    'VERIFIED', 'Phase 6f.'),
    ('CÔNG TY TNHH TƯ VẤN THƯƠNG MẠI DỊCH VỤ ATP (ATP STC CO.,LTD)',                            'VERIFIED', 'Phase 6f.'),
    ('Student life care (SLC)',                                                                 'VERIFIED', 'Phase 6f.'),
    ('Successful Migration & Education Services (SMES)',                                        'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH - DV Nhật Anh',                                                              'VERIFIED', 'Phase 6f.'),
    ('Viet Nam Professional Consultancy Company',                                               'VERIFIED', 'Phase 6f.'),
    ('AVI Education',                                                                           'VERIFIED', 'Phase 6f.'),
    ('Edutime',                                                                                 'VERIFIED', 'Phase 6f. Alias: "eDUTIME".'),
    ('InspriEdu & Career (Công ty TNHH Tư vấn Giáo dục và Hướng Nghiệp Nguồn Cảm Hứng)',        'VERIFIED', 'Phase 6f.'),
    ('TNT Consulting Company Ltd.',                                                             'VERIFIED', 'Phase 6f.'),
    ('AE&T Co.,Ltd.',                                                                           'VERIFIED', 'Phase 6f.'),
    ('Sunrise VietNam (Công ty TNHH Thái Dương Việt Nam)',                                      'VERIFIED', 'Phase 6f.'),
    ('CÔNG TY TNHH DỊCH VỤ TƯ VẤN QCA',                                                         'VERIFIED', 'Phase 6f.'),
    ('New Pathway., JSC',                                                                       'VERIFIED', 'Phase 6f.'),
    ('Thái An',                                                                                 'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH Tư Vấn Di Trú Định Cư HALI',                                                 'VERIFIED', 'Phase 6f. Alias: lower-case spelling variant.'),
    ('IDC Vietnam',                                                                             'VERIFIED', 'Phase 6f.'),
    ('L&V',                                                                                     'VERIFIED', 'Phase 6f.'),
    ('ATEC',                                                                                    'VERIFIED', 'Phase 6f.'),
    ('Du học Nam Phong',                                                                        'VERIFIED', 'Phase 6f.'),
    ('G7 Education',                                                                            'VERIFIED', 'Phase 6f.'),
    ('ISC UKEAS',                                                                               'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH Ni Hao',                                                                     'VERIFIED', 'Phase 6f.'),
    ('IVision Overseas Study Office',                                                           'VERIFIED', 'Phase 6f.'),
    ('New Study Edu',                                                                           'VERIFIED', 'Phase 6f.'),
    ('VINVISA CO.,LTD',                                                                         'VERIFIED', 'Phase 6f.'),
    ('CÔNG TY CỔ PHẦN HỢP TÁC QUỐC TẾ HTC GROUP (Du học TH True Edu)',                          'VERIFIED', 'Phase 6f.'),
    ('Công ty SET - Education',                                                                 'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH Tư vấn EFS',                                                                 'VERIFIED', 'Phase 6f.'),
    ('Hoang Kim Phat Service Co.Ltd',                                                           'VERIFIED', 'Phase 6f.'),
    ('NEEC',                                                                                    'VERIFIED', 'Phase 6f.'),
    ('Nhật Anh Hà Nội',                                                                         'VERIFIED', 'Phase 6f.'),
    ('TRANG VIET ANH LTD. CO.',                                                                 'VERIFIED', 'Phase 6f.'),
    ('Công ty Cổ Phần Tư Vấn Phát Triển Nguồn Nhân Lực Toàn Cầu GMS',                           'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH du học Âu Mỹ (AMOS CO.,LTD)',                                                'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH Tư Vấn Du Học và Anh Ngữ Alice',                                             'VERIFIED', 'Phase 6f.'),
    ('Du học Úc AVSS HCM',                                                                      'VERIFIED', 'Phase 6f.'),
    ('Ngoài hệ thống',                                                                          'UNVERIFIED', 'Phase 6f. CRM data-entry error suspected — System Type value used as referrer. Surface in QM review.'),
    ('Thái Binh Dương',                                                                         'VERIFIED', 'Phase 6f.'),
    ('Tin Phu International Co.,Ltd',                                                           'VERIFIED', 'Phase 6f.'),
    ('Trung Tâm Huấn Luyệ Kỹ Năng Thế Hệ Trẻ - Pathfinder',                                     'VERIFIED', 'Phase 6f.'),
    ('We Study',                                                                                'VERIFIED', 'Phase 6f.'),
    ('CMD Edu',                                                                                 'VERIFIED', 'Phase 6f.'),
    ('Công ty Joy Study',                                                                       'VERIFIED', 'Phase 6f.'),
    ('Công ty TNHH Giáo Dục Quốc Tế Thiên Thần (ANIE CO., LTD)',                                'VERIFIED', 'Phase 6f.'),
    ('Du lịch Hoàng Thiên',                                                                     'VERIFIED', 'Phase 6f.'),
    ('Duy Tan Study Abroad',                                                                    'VERIFIED', 'Phase 6f.'),
    ('Huấn Nghệ',                                                                               'VERIFIED', 'Phase 6f.'),
    ('ICCS - CÔNG TY TNHH DỊCH VỤ VĂN HÓA GIAO ĐIỂM QUỐC TẾ',                                   'VERIFIED', 'Phase 6f.'),
    ('INEC',                                                                                    'VERIFIED', 'Phase 6f.'),
    ('PS Education & Training Consultanting Co., Ltd',                                          'VERIFIED', 'Phase 6f.'),
    ('The Education Company',                                                                   'VERIFIED', 'Phase 6f.'),
    ('TRI TIEN CONSULTING TRADING SERVICE CO.LTD',                                              'VERIFIED', 'Phase 6f.'),
    ('WE1',                                                                                     'VERIFIED', 'Phase 6f.'),
    ('YES',                                                                                     'VERIFIED', 'Phase 6f.')
ON CONFLICT (canonical_name) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 2. Insert aliases — one row per raw-text variant seen in the CRM.
-- -----------------------------------------------------------------------------
-- The alias's job: when the importer sees the raw CRM string, it can
-- resolve to the canonical sub_agent_id via this table.
--
-- For most sub-agents, alias = canonical_name (one-to-one).
-- For the three consolidations, the canonical also gets a second alias
-- mapping the variant spelling to the same canonical row.

-- Generate self-aliases for every canonical row inserted above.
-- This pattern resolves the canonical text → its own canonical_id.
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias, notes)
SELECT id, canonical_name, 'Phase 6f self-alias.'
FROM ref_sub_agent
WHERE canonical_name IN (
    'Đức Anh Hà Nội',
    'Edunetwork Việt Nam',
    'Chìa khoá Du học (Key for Oversea Studies - KFO)',
    'Hop Nhat We Connect Company Limited',
    'Studyland Co., Ltd.',
    'TNSS',
    'G''Connect Education',
    'CÔNG TY TNHH TƯ VẤN THƯƠNG MẠI DỊCH VỤ ATP (ATP STC CO.,LTD)',
    'Student life care (SLC)',
    'Successful Migration & Education Services (SMES)',
    'Công ty TNHH - DV Nhật Anh',
    'Viet Nam Professional Consultancy Company',
    'AVI Education',
    'Edutime',
    'InspriEdu & Career (Công ty TNHH Tư vấn Giáo dục và Hướng Nghiệp Nguồn Cảm Hứng)',
    'TNT Consulting Company Ltd.',
    'AE&T Co.,Ltd.',
    'Sunrise VietNam (Công ty TNHH Thái Dương Việt Nam)',
    'CÔNG TY TNHH DỊCH VỤ TƯ VẤN QCA',
    'New Pathway., JSC',
    'Thái An',
    'Công ty TNHH Tư Vấn Di Trú Định Cư HALI',
    'IDC Vietnam',
    'L&V',
    'ATEC',
    'Du học Nam Phong',
    'G7 Education',
    'ISC UKEAS',
    'Công ty TNHH Ni Hao',
    'IVision Overseas Study Office',
    'New Study Edu',
    'VINVISA CO.,LTD',
    'CÔNG TY CỔ PHẦN HỢP TÁC QUỐC TẾ HTC GROUP (Du học TH True Edu)',
    'Công ty SET - Education',
    'Công ty TNHH Tư vấn EFS',
    'Hoang Kim Phat Service Co.Ltd',
    'NEEC',
    'Nhật Anh Hà Nội',
    'TRANG VIET ANH LTD. CO.',
    'Công ty Cổ Phần Tư Vấn Phát Triển Nguồn Nhân Lực Toàn Cầu GMS',
    'Công ty TNHH du học Âu Mỹ (AMOS CO.,LTD)',
    'Công ty TNHH Tư Vấn Du Học và Anh Ngữ Alice',
    'Du học Úc AVSS HCM',
    'Ngoài hệ thống',
    'Thái Binh Dương',
    'Tin Phu International Co.,Ltd',
    'Trung Tâm Huấn Luyệ Kỹ Năng Thế Hệ Trẻ - Pathfinder',
    'We Study',
    'CMD Edu',
    'Công ty Joy Study',
    'Công ty TNHH Giáo Dục Quốc Tế Thiên Thần (ANIE CO., LTD)',
    'Du lịch Hoàng Thiên',
    'Duy Tan Study Abroad',
    'Huấn Nghệ',
    'ICCS - CÔNG TY TNHH DỊCH VỤ VĂN HÓA GIAO ĐIỂM QUỐC TẾ',
    'INEC',
    'PS Education & Training Consultanting Co., Ltd',
    'The Education Company',
    'TRI TIEN CONSULTING TRADING SERVICE CO.LTD',
    'WE1',
    'YES'
)
ON CONFLICT (alias) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 3. Variant aliases for the three consolidation pairs.
-- -----------------------------------------------------------------------------

-- 'Edunetwork' → resolves to 'Edunetwork Việt Nam'
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias, notes)
SELECT id, 'Edunetwork', 'Phase 6f. Short-form variant — 47 occurrences in historical data.'
FROM ref_sub_agent
WHERE canonical_name = 'Edunetwork Việt Nam'
ON CONFLICT (alias) DO NOTHING;

-- 'eDUTIME' → resolves to 'Edutime'
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias, notes)
SELECT id, 'eDUTIME', 'Phase 6f. Casing variant.'
FROM ref_sub_agent
WHERE canonical_name = 'Edutime'
ON CONFLICT (alias) DO NOTHING;

-- 'Công ty TNHH tư vấn di trú định cư HALI' (lowercase) → resolves to
-- 'Công ty TNHH Tư Vấn Di Trú Định Cư HALI' (title case)
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias, notes)
SELECT id, 'Công ty TNHH tư vấn di trú định cư HALI', 'Phase 6f. Casing variant.'
FROM ref_sub_agent
WHERE canonical_name = 'Công ty TNHH Tư Vấn Di Trú Định Cư HALI'
ON CONFLICT (alias) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 4. Verification.
-- -----------------------------------------------------------------------------
-- Expected: 61 canonical sub-agents from this phase, 64 aliases.

SELECT 'sub_agents_phase6f' AS metric, count(*) AS actual, 61 AS expected
FROM ref_sub_agent
WHERE notes LIKE 'Phase 6f%'

UNION ALL

SELECT 'aliases_phase6f' AS metric, count(*) AS actual, 64 AS expected
FROM ref_sub_agent_alias
WHERE notes LIKE 'Phase 6f%';

COMMIT;
