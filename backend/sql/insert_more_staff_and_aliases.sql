-- Phase 1 prep: 6 more staff + 3 aliases discovered in CRM consolidated file
-- All inferred role/office; mark with /* VERIFY */ for HR follow-up
-- Departure dates are best guesses based on last appearance in CRM data

BEGIN;

-- =========================================================================
-- Part 1: New staff inserts
-- =========================================================================

-- Đặng Bảo Ngọc: 56 cases as counsellor + 59 as CO; 2023-2024 only
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Đặng Bảo Ngọc',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR') /* VERIFY */,
  (SELECT id FROM dim_office WHERE code = 'HCM') /* VERIFY */,
  'LEFT',
  DATE '2024-04-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- Hồ Thị Mỹ Yến: 1 case as counsellor only
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Hồ Thị Mỹ Yến',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR') /* VERIFY */,
  (SELECT id FROM dim_office WHERE code = 'HCM') /* VERIFY */,
  'LEFT',
  DATE '2024-04-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- Nguyễn Hồng Hà: 1 case only — confirm not duplicate of Nguyễn Ngọc Hà
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Hồng Hà',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR') /* VERIFY */,
  (SELECT id FROM dim_office WHERE code = 'HCM') /* VERIFY */,
  'LEFT',
  DATE '2024-04-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- Nguyễn Thị Ngọc Tuyền: 10 cases as CO only
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Thị Ngọc Tuyền',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR') /* VERIFY */,
  (SELECT id FROM dim_office WHERE code = 'HCM') /* VERIFY */,
  'LEFT',
  DATE '2024-04-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- Nhiêu Mỹ Như: 9 cases as CO; bao caos exist for May-Sep 2024
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nhiêu Mỹ Như',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR') /* VERIFY */,
  (SELECT id FROM dim_office WHERE code = 'HCM') /* VERIFY */,
  'LEFT',
  DATE '2024-09-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- Tạ Vũ Phương Anh: 2 cases as CO; bao cao exists for Aug 2023
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Tạ Vũ Phương Anh',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR') /* VERIFY */,
  (SELECT id FROM dim_office WHERE code = 'HCM') /* VERIFY */,
  'LEFT',
  DATE '2023-08-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- =========================================================================
-- Part 2: Aliases (resolves CRM name variants to canonical staff)
-- =========================================================================

-- Non-breaking space variant
INSERT INTO ref_staff_alias (alias, staff_id)
VALUES (
  'Nguyễn Tấn Thủy Chung',
  (SELECT id FROM ref_staff WHERE canonical_name = 'Nguyễn Tấn Thủy Chung')
)
ON CONFLICT DO NOTHING;

-- B suffix variant
INSERT INTO ref_staff_alias (alias, staff_id)
VALUES (
  'Nguyễn Ngọc Hà B',
  (SELECT id FROM ref_staff WHERE canonical_name = 'Nguyễn Ngọc Hà')
)
ON CONFLICT DO NOTHING;

-- B suffix variant — assumed by symmetry; flag if wrong
INSERT INTO ref_staff_alias (alias, staff_id)
VALUES (
  'Trương Thị Mạc Đan B',
  (SELECT id FROM ref_staff WHERE canonical_name = 'Trương Thị Mạc Đan')
)
ON CONFLICT DO NOTHING;

-- =========================================================================
-- Verification
-- =========================================================================

-- Confirm new staff present
SELECT id, canonical_name, employment_status, departure_date
FROM ref_staff
WHERE canonical_name IN (
  'Đặng Bảo Ngọc', 'Hồ Thị Mỹ Yến', 'Nguyễn Hồng Hà',
  'Nguyễn Thị Ngọc Tuyền', 'Nhiêu Mỹ Như', 'Tạ Vũ Phương Anh'
)
ORDER BY canonical_name;

-- Confirm aliases present
SELECT a.alias, s.canonical_name
FROM ref_staff_alias a JOIN ref_staff s ON s.id = a.staff_id
WHERE s.canonical_name IN ('Nguyễn Tấn Thủy Chung', 'Nguyễn Ngọc Hà', 'Trương Thị Mạc Đan');

COMMIT;
