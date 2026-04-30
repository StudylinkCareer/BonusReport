-- =============================================================================
-- StudyLink Vietnam Bonus Engine — Staff and Targets
-- File:    03_staff_data.sql
-- Purpose: Populate ref_staff, ref_staff_alias, and ref_staff_target.
-- Target:  PostgreSQL 15+
-- Order:   Run AFTER 02_reference_data.sql.
-- =============================================================================
-- Sources:
--   D5.R1, D5.R2: Doc 5 monthly targets for 2024 and 2025
--   D5.R3: Loi (Phạm Thị Lợi) target = 10/month CO_SUB (user-confirmed; not in Doc 5)
--   D5.R6 + Phase 3 user confirmation: Lê Thị Trường An home office = HCM (canonical)
--   Phase 3: Loi operates at home office DN as CO_SUB; also operates as VP_DN on
--            certain cases (recorded at case-slot level, not staff record)
--   BC files: Hoàng Yến, Trúc Quỳnh hold targets in multiple offices simultaneously
--
-- AMBIG flagged in notes columns where Doc 5 entries are unclear:
--   - 2025 Hoàng Yến "w/Vinh" / "w/Hân" pairs (D5.R4): split by Counsellor partner
--   - Trường An office not stated in Doc 5 (D5.R6): assumed HCM per BC pattern
-- =============================================================================


-- =============================================================================
-- ref_staff — staff registry
-- =============================================================================
-- 9 staff who appear in BC files + 2 from Doc 5 (Trúc Quỳnh, Huỳnh Anh)
-- Note: home_office_id and primary_role_id are DEFAULTS only. Per design, calc
-- uses the case's office × the slot's role, not staff defaults.

INSERT INTO ref_staff (canonical_name, home_office_id, primary_role_id, employment_status, notes) VALUES
    -- HCM staff (Counsellor + CO Direct + CO Sub)
    ('Lê Thị Trường An',     (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_SUB'),    'ACTIVE', 'D5.R6 office not stated; HCM per Phase 3 user confirmation. CO_SUB scheme = ENROL_ONLY_VISA_ONLY. Target 13/month.'),
    ('Quan Hoàng Yến',       (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'ACTIVE', 'D5.R1/R2 multi-office: HCM target 6 AND HN target 2 simultaneously in 2024. 2025 partner-split structure (w/Vinh, w/Hân).'),
    ('Đoàn Ngọc Trúc Quỳnh', (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'ACTIVE', 'D5.R1/R2 multi-office: HCM and HN simultaneously.'),
    ('Trần Thanh Gia Mẫn',   (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'ACTIVE', 'D5.R1/R2 starts Dec 2024 HCM; 2025 ramps up.'),
    ('Nguyễn Thành Vinh',    (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'ACTIVE', 'BC files. 2025 paired with Hoàng Yến (D5.R4).'),
    ('Nguyễn Thị Mỹ Ly',     (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'ACTIVE', 'BC files 2025 only (no 2024 BCs found).'),
    ('Phạm Thị Ngọc Thảo',   (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'ACTIVE', 'BC files.'),
    ('Huỳnh Anh',            (SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'ACTIVE', 'D5.R2 starts Nov 2025 HCM.'),
    -- DN staff
    ('Phạm Thị Lợi',         (SELECT id FROM dim_office WHERE code='DN'),  (SELECT id FROM dim_role WHERE code='CO_SUB'),    'ACTIVE', 'D5.R3: not in Doc 5; user-confirmed target 10/month CO_SUB ENROL_ONLY_VISA_ONLY. Also operates as VP_DN on certain cases (recorded at case slot, not staff record).');


-- =============================================================================
-- ref_staff_alias — name variants
-- =============================================================================
-- Common aliases observed in BC filenames and prior session use.

INSERT INTO ref_staff_alias (staff_id, alias, notes) VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Lê Thị Trường An'),     'Trường An',          'Common short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Lê Thị Trường An'),     'Truong An',          'No-diacritics variant'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Lê Thị Trường An'),     'Le Thi Truong An',   'No-diacritics filename variant'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'),       'Hoàng Yến',          'Common short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'),       'Hoang Yen',          'No-diacritics'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'),       'Quan Hoang Yen',     'No-diacritics filename'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), 'Trúc Quỳnh',         'Short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), 'Truc Quynh',         'No-diacritics'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), 'Doan Ngoc Truc Quynh','Filename variant'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), 'ĐoànNgọcTrúcQuỳnh',  'No-space filename variant'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Trần Thanh Gia Mẫn'),   'Gia Mẫn',            'Short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Trần Thanh Gia Mẫn'),   'Gia Man',            'No-diacritics'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Trần Thanh Gia Mẫn'),   'Tran Thanh Gia Man', 'Filename'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Nguyễn Thành Vinh'),    'Vinh',               'Short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Nguyễn Thành Vinh'),    'Nguyen Thanh Vinh',  'Filename'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Nguyễn Thị Mỹ Ly'),     'Mỹ Ly',              'Short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Nguyễn Thị Mỹ Ly'),     'My Ly',              'No-diacritics'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Nguyễn Thị Mỹ Ly'),     'Nguyen Thi My Ly',   'Filename'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Ngọc Thảo'),   'Ngọc Thảo',          'Short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Ngọc Thảo'),   'Ngoc Thao',          'No-diacritics'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Ngọc Thảo'),   'Pham Thi Ngoc Thao', 'Filename'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Huỳnh Anh'),            'Huynh Anh',          'No-diacritics'),

    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Lợi'),         'Lợi',                'Short form'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Lợi'),         'Loi',                'No-diacritics'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Lợi'),         'Pham Thi Loi',       'Filename'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Lợi'),         'Pham Thi Lợi',       'Mixed-diacritic variant');


-- =============================================================================
-- ref_staff_target — 2024 monthly targets (D5.R1)
-- =============================================================================
-- Lê Thị Trường An: 13/month all year, CO_SUB, ENROL_ONLY_VISA_ONLY scheme, HCM
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, co_sub_subscheme, notes)
SELECT
    (SELECT id FROM ref_staff WHERE canonical_name='Lê Thị Trường An'),
    (SELECT id FROM dim_role WHERE code='CO_SUB'),
    (SELECT id FROM dim_office WHERE code='HCM'),
    2024, m, 13, 'ENROL_ONLY_VISA_ONLY',
    'D5.R1 2024 Trường An 13/month CO_SUB. Office HCM per Phase 3 user confirmation.'
FROM generate_series(1,12) AS m;

-- Phạm Thị Lợi: 10/month all year, CO_SUB, ENROL_ONLY_VISA_ONLY, DN (user-confirmed; not in Doc 5)
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, co_sub_subscheme, notes)
SELECT
    (SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Lợi'),
    (SELECT id FROM dim_role WHERE code='CO_SUB'),
    (SELECT id FROM dim_office WHERE code='DN'),
    2024, m, 10, 'ENROL_ONLY_VISA_ONLY',
    'D5.R3 user-confirmed: Loi target 10/month CO_SUB (not in Doc 5).'
FROM generate_series(1,12) AS m;

-- Quan Hoàng Yến: HCM 6/Jan-Aug, 5/Sep-Dec
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes)
VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 1,  6, 'D5.R1 2024 Hoàng Yến HCM Jan'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 2,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 3,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 4,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 5,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 6,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 7,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 8,  6, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 9,  5, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024,10,  5, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024,11,  5, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024,12,  5, 'D5.R1'),
    -- Quan Hoàng Yến HN Jan-Feb 2024 only (multi-office target same staff)
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 1,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 2,  2, 'D5.R1 multi-office HN');

-- Đoàn Ngọc Trúc Quỳnh: HCM Mar-Sep target=1, Oct-Dec target=2
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes) VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 3,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 4,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 5,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 6,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 7,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 8,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 9,  1, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024,10,  2, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024,11,  2, 'D5.R1'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024,12,  2, 'D5.R1'),
    -- Đoàn Ngọc Trúc Quỳnh HN Mar-Aug 2024 target=2; Dec target=1
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 3,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 4,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 5,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 6,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 7,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024, 8,  2, 'D5.R1 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'),  2024,12,  1, 'D5.R1 multi-office HN');

-- Trần Thanh Gia Mẫn: HCM Dec 2024 target=2 only
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes) VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Trần Thanh Gia Mẫn'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2024, 12, 2, 'D5.R1');


-- =============================================================================
-- ref_staff_target — 2025 monthly targets (D5.R2)
-- =============================================================================
-- Lê Thị Trường An: 13/month all year (continues)
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, co_sub_subscheme, notes)
SELECT
    (SELECT id FROM ref_staff WHERE canonical_name='Lê Thị Trường An'),
    (SELECT id FROM dim_role WHERE code='CO_SUB'),
    (SELECT id FROM dim_office WHERE code='HCM'),
    2025, m, 13, 'ENROL_ONLY_VISA_ONLY', 'D5.R2 2025'
FROM generate_series(1,12) AS m;

-- Phạm Thị Lợi: assume 10/month continues (user-confirmed pattern)
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, co_sub_subscheme, notes)
SELECT
    (SELECT id FROM ref_staff WHERE canonical_name='Phạm Thị Lợi'),
    (SELECT id FROM dim_role WHERE code='CO_SUB'),
    (SELECT id FROM dim_office WHERE code='DN'),
    2025, m, 10, 'ENROL_ONLY_VISA_ONLY', 'D5.R3 user-confirmed continues 2025.'
FROM generate_series(1,12) AS m;

-- Quan Hoàng Yến w/Vinh: 4/Jan-Mar, 3/Apr, 2/May-Dec
-- (D5.R4 ambiguity — for now, store partner pair targets as TWO separate rows
--  per pair; Counsellor partner identification would happen at case slot.
--  Here we record total monthly target for Hoàng Yến HCM, summing both pairs.)
-- Combined HCM targets for Hoàng Yến = w/Vinh + w/Hân:
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes) VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 1,  4, 'D5.R2 2025 Jan w/Vinh=4, w/Hân=0 → total 4'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 2,  4, 'D5.R2 Feb w/Vinh=4'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 3,  4, 'D5.R2 Mar w/Vinh=4'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 4,  3, 'D5.R2 Apr w/Vinh=3'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 5,  4, 'D5.R2 May w/Vinh=2 + w/Hân=2'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 6,  4, 'D5.R2 Jun w/Vinh=2 + w/Hân=2'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 7,  4, 'D5.R2 Jul w/Vinh=2 + w/Hân=2'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 8,  4, 'D5.R2 Aug w/Vinh=2 + w/Hân=2'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025, 9,  5, 'D5.R2 Sep w/Vinh=2 + w/Hân=3'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025,10,  5, 'D5.R2 Oct w/Vinh=2 + w/Hân=3'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025,11,  5, 'D5.R2 Nov w/Vinh=2 + w/Hân=3'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Quan Hoàng Yến'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025,12,  5, 'D5.R2 Dec w/Vinh=2 + w/Hân=3');

-- Đoàn Ngọc Trúc Quỳnh: HCM 2/month all year
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes)
SELECT
    (SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'),
    (SELECT id FROM dim_role WHERE code='CO_DIR'),
    (SELECT id FROM dim_office WHERE code='HCM'),
    2025, m, 2, 'D5.R2 2025 HCM 2/month'
FROM generate_series(1,12) AS m;

-- Đoàn Ngọc Trúc Quỳnh: HN Jan-Feb=1, Mar-Dec=2
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes) VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 1, 1, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 2, 1, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 3, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 4, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 5, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 6, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 7, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 8, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025, 9, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025,10, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025,11, 2, 'D5.R2 multi-office HN'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Đoàn Ngọc Trúc Quỳnh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HN'), 2025,12, 2, 'D5.R2 multi-office HN');

-- Trần Thanh Gia Mẫn: HCM Feb-Dec target=2 (Jan blank)
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes)
SELECT
    (SELECT id FROM ref_staff WHERE canonical_name='Trần Thanh Gia Mẫn'),
    (SELECT id FROM dim_role WHERE code='CO_DIR'),
    (SELECT id FROM dim_office WHERE code='HCM'),
    2025, m, 2, 'D5.R2 2025 HCM 2/month (Feb-Dec)'
FROM generate_series(2,12) AS m;

-- Huỳnh Anh: HCM Nov-Dec 2025 target=2
INSERT INTO ref_staff_target (staff_id, role_id, office_id, year, month, target, notes) VALUES
    ((SELECT id FROM ref_staff WHERE canonical_name='Huỳnh Anh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025,11, 2, 'D5.R2'),
    ((SELECT id FROM ref_staff WHERE canonical_name='Huỳnh Anh'), (SELECT id FROM dim_role WHERE code='CO_DIR'), (SELECT id FROM dim_office WHERE code='HCM'), 2025,12, 2, 'D5.R2');


-- =============================================================================
-- END OF STAFF DATA
-- =============================================================================
-- Note: Staff appearing in BC files but not in D5 (Vinh, Mỹ Ly, Ngọc Thảo) are
-- registered in ref_staff for slot-resolution purposes but have no targets in
-- ref_staff_target. Their targets (if any) live in their COUNS_DIR scheme,
-- which is contract-target rather than enrolment-target (D1.R28).
--
-- VP role targets: not yet defined per design discussion. Add when VP scheme
-- is finalised — at that point INSERT rows with role_id = VP and a separate
-- "office" indicating the VP scope (DN for VP_DN, MEL for VP_MEL).
-- =============================================================================
