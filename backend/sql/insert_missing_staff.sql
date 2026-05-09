-- Missing staff INSERTs for targets reload (after merge decisions)
-- Generated from Staff_member_names_-_corrected.xlsx with merges:
--   • Thái Thị Huỳnh Anh → existing Huỳnh Anh (id=8) — alias only, no insert
--   • Ngọc Hạ + bare Ngọc Hà → Nguyễn Ngọc Hà (single insert)
--
-- BEFORE RUNNING:
--   1. Replace any 'COUNS_DIR' /* VERIFY */ (1 row: Hương Ly)
--   2. Replace any 'HCM' /* VERIFY */ (5 rows: Lâm Hà, Ngọc Vy, khánh linh, NGUYEN Hoang Thuy An, VÕ Ngọc Bảo Trân, Hương Ly)
--   3. Spot-check departure_date values — set to last day of final target month
--

BEGIN;

-- 1. Hoàng Trần Uyên Phương  (aliases: Uyên Phương)
--    Targets: CON=1 ENR=0 CAN=0 TEL=0   Active: 2024-06 → 2024-08
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Hoàng Trần Uyên Phương',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HN'),
  'LEFT',
  DATE '2024-08-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 2. Lâm Hà  (aliases: Lâm Hà)
--    Targets: CON=1 ENR=0 CAN=0 TEL=0   Active: 2024-09 → 2024-10
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Lâm Hà',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM' /* VERIFY */),
  'LEFT',
  DATE '2024-10-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 3. Lê Hoàng  (aliases: Lê Hoàng)
--    Targets: CON=1 ENR=1 CAN=1 TEL=0   Active: 2023-07 → 2026-04
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Lê Hoàng',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'MEL'),
  'ACTIVE',
  NULL
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 4. Nguyễn Ngọc Hà  (aliases: Ngọc Hà, Ngọc Hạ)
--    Targets: CON=1 ENR=1 CAN=0 TEL=1   Active: 2023-07 → 2025-03
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Ngọc Hà',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'DN'),
  'LEFT',
  DATE '2025-03-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 5. Nguyễn Ngọc Hân  (aliases: Ngọc Hân)
--    Targets: CON=1 ENR=1 CAN=0 TEL=0   Active: 2025-03 → 2026-03
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Ngọc Hân',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'ACTIVE',
  NULL
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 6. Nguyễn Phúc Lâm  (aliases: Phúc Lâm)
--    Targets: CON=1 ENR=1 CAN=0 TEL=0   Active: 2024-04 → 2026-02
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Phúc Lâm',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2026-02-28'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 7. Nguyễn Thị Diễm Hồng  (aliases: Diễm Hồng)
--    Targets: CON=1 ENR=1 CAN=0 TEL=1   Active: 2023-07 → 2024-06
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Thị Diễm Hồng',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-06-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 8. Nguyễn Thị Kim Dung  (aliases: Kim Dung)
--    Targets: CON=1 ENR=1 CAN=1 TEL=1   Active: 2023-07 → 2025-04
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Thị Kim Dung',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HN'),
  'LEFT',
  DATE '2025-04-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 9. Nguyễn Thị Lan Anh  (aliases: Lan Anh)
--    Targets: CON=1 ENR=1 CAN=1 TEL=1   Active: 2023-07 → 2024-02
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Thị Lan Anh',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-02-29'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 10. Ngọc Vy  (aliases: Ngọc Vy)
--    Targets: CON=1 ENR=0 CAN=0 TEL=0   Active: 2025-03 → 2025-04
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Ngọc Vy',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM' /* VERIFY */),
  'LEFT',
  DATE '2025-04-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 11. Trương Thị Mạc Đan  (aliases: Mạc Đan)
--    Targets: CON=1 ENR=1 CAN=0 TEL=1   Active: 2023-07 → 2024-06
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Trương Thị Mạc Đan',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-06-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 12. Trần Hà Diễm My  (aliases: Diễm My)
--    Targets: CON=1 ENR=1 CAN=0 TEL=0   Active: 2023-07 → 2024-02
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Trần Hà Diễm My',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-02-29'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 13. Vũ Thị Hòa  (aliases: Vũ Hòa)
--    Targets: CON=1 ENR=1 CAN=1 TEL=1   Active: 2023-07 → 2024-06
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Vũ Thị Hòa',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-06-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 14. khánh linh  (aliases: Khánh Linh)
--    Targets: CON=1 ENR=1 CAN=1 TEL=0   Active: 2024-12 → 2025-02
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'khánh linh',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM' /* VERIFY */),
  'LEFT',
  DATE '2025-02-28'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 15. Đào Ngọc Sơn  (aliases: Ngọc Sơn)
--    Targets: CON=1 ENR=1 CAN=1 TEL=0   Active: 2024-12 → 2026-02
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Đào Ngọc Sơn',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HN'),
  'LEFT',
  DATE '2026-02-28'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 16. Lê Bá Thục Nhi  (aliases: Thục Nhi)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2023-11 → 2024-05
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Lê Bá Thục Nhi',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-05-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 17. NGUYEN Hoang Thuy An  (aliases: Thúy An)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2026-01 → 2026-04
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'NGUYEN Hoang Thuy An',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM' /* VERIFY */),
  'ACTIVE',
  NULL
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 18. Nguyễn Thế Hiền  (aliases: Thế Hiền)
--    Targets: CON=0 ENR=1 CAN=1 TEL=0   Active: 2024-06 → 2024-10
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Thế Hiền',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-10-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 19. Nguyễn Thị Bảo Trâm  (aliases: Bảo Trâm)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2023-10 → 2024-06
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Thị Bảo Trâm',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2024-06-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 20. Nguyễn Tấn Thủy Chung  (aliases: Thủy Chung)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2024-09 → 2025-09
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Nguyễn Tấn Thủy Chung',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2025-09-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 21. Phan Thị Thảnh  (aliases: Phan Thảnh)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2023-07 → 2023-09
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Phan Thị Thảnh',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2023-09-30'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 22. VÕ, Ngọc Bảo Trân  (aliases: Bảo Trân)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2023-08 → 2023-08
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'VÕ, Ngọc Bảo Trân',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM' /* VERIFY */),
  'LEFT',
  DATE '2023-08-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 23. Võ Mỹ Vi  (aliases: Mỹ Vi)
--    Targets: CON=0 ENR=1 CAN=0 TEL=0   Active: 2023-07 → 2023-07
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Võ Mỹ Vi',
  (SELECT id FROM dim_role   WHERE code = 'CO_DIR'),
  (SELECT id FROM dim_office WHERE code = 'HCM'),
  'LEFT',
  DATE '2023-07-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- 24. Hương Ly  (aliases: Hương Ly)
--    Targets: CON=0 ENR=0 CAN=0 TEL=1   Active: 2023-12 → 2023-12
INSERT INTO ref_staff (canonical_name, primary_role_id, home_office_id, employment_status, departure_date)
VALUES (
  'Hương Ly',
  (SELECT id FROM dim_role   WHERE code = 'COUNS_DIR' /* VERIFY */),
  (SELECT id FROM dim_office WHERE code = 'HCM' /* VERIFY */),
  'LEFT',
  DATE '2023-12-31'
)
ON CONFLICT (canonical_name) DO NOTHING;

-- Verify all expected staff now present
SELECT id, canonical_name, employment_status, departure_date
FROM ref_staff ORDER BY canonical_name;

COMMIT;
