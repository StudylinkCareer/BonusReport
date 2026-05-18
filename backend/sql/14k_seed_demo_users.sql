-- ============================================================================
-- Migration 14k (v2) — Seed demo users (1 per role + linked staff users)
-- ============================================================================
-- Purpose:
--   Insert placeholder user accounts so the demo can show role-based access
--   the moment Block 2 (auth) is in place. Password hashes are NULL —
--   Block 2 will set them using passlib/bcrypt once the library is chosen.
--
-- v2 fix:
--   Section 3 (function-role grants) had a forward reference: it JOINed
--   dim_app_role using role_grant.role_code before the role_grant subquery
--   was declared. JOIN clauses are processed left-to-right; the alias has
--   to appear before any reference to its columns. Fixed by reordering.
--
-- Idempotency:
--   ON CONFLICT (email) DO UPDATE for users.
--   ON CONFLICT (user_id, role_id) DO NOTHING for role grants.
--
-- Dependencies:
--   14e (dim_app_role), 14f (app_user), 14g (app_user_role), ref_staff.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. Function-role users (not tied to any ref_staff row)
-- ----------------------------------------------------------------------------

INSERT INTO app_user (email, password_hash, display_name, staff_id, employment_status)
VALUES
    ('director@studylink.test', NULL, 'Demo Director',              NULL, 'ACTIVE'),
    ('admin@studylink.test',    NULL, 'Demo Administrator',         NULL, 'ACTIVE'),
    ('fo@studylink.test',       NULL, 'Demo Financial Officer',     NULL, 'ACTIVE'),
    ('dqo@studylink.test',      NULL, 'Demo Data Quality Officer',  NULL, 'ACTIVE')
ON CONFLICT (email) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    updated_at   = NOW();

-- ----------------------------------------------------------------------------
-- 2. Staff users — one per active counsellor/CO, linked via canonical_name
-- ----------------------------------------------------------------------------

INSERT INTO app_user (email, password_hash, display_name, staff_id, employment_status)
SELECT
    user_email,
    NULL,
    display_name_val,
    rs.id,
    'ACTIVE'
FROM (VALUES
    -- email                          display_name              canonical_name (must match ref_staff)
    ('loi@studylink.test',             'Phạm Thị Lợi',           'Phạm Thị Lợi'),
    ('truongan@studylink.test',        'Lê Thị Trường An',       'Lê Thị Trường An'),
    ('hoangyen@studylink.test',        'Quan Hoàng Yến',         'Quan Hoàng Yến'),
    ('trucquynh@studylink.test',       'Đoàn Ngọc Trúc Quỳnh',   'Đoàn Ngọc Trúc Quỳnh'),
    ('giaman@studylink.test',          'Trần Thanh Gia Mẫn',     'Trần Thanh Gia Mẫn'),
    ('vinh@studylink.test',            'Nguyễn Thành Vinh',      'Nguyễn Thành Vinh'),
    ('myly@studylink.test',            'Nguyễn Thị Mỹ Ly',       'Nguyễn Thị Mỹ Ly'),
    ('honghanh@studylink.test',        'Nguyễn Thị Hồng Hạnh',   'Nguyễn Thị Hồng Hạnh'),
    ('khietoanh@studylink.test',       'Trần Khiết Oanh',        'Trần Khiết Oanh'),
    ('tatthanh@studylink.test',        'La Tất Thành',           'La Tất Thành')
) AS seed(user_email, display_name_val, canonical_name)
LEFT JOIN ref_staff rs ON rs.canonical_name = seed.canonical_name
ON CONFLICT (email) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    staff_id     = COALESCE(EXCLUDED.staff_id, app_user.staff_id),
    updated_at   = NOW();

-- ----------------------------------------------------------------------------
-- 3. Grant roles to function users
--    v2 fix: role_grant subquery is JOINed FIRST so dim_app_role can
--    reference role_grant.role_code afterwards.
-- ----------------------------------------------------------------------------

INSERT INTO app_user_role (user_id, role_id)
SELECT u.id, r.id
FROM app_user u
JOIN (VALUES
    ('director@studylink.test', 'DIRECTOR'),
    ('admin@studylink.test',    'ADMIN'),
    ('fo@studylink.test',       'FO'),
    ('dqo@studylink.test',      'DQO')
) AS role_grant(email, role_code) ON role_grant.email = u.email
JOIN dim_app_role r ON r.code = role_grant.role_code
ON CONFLICT (user_id, role_id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 4. Grant STAFF role to staff users
-- ----------------------------------------------------------------------------

INSERT INTO app_user_role (user_id, role_id)
SELECT u.id, r.id
FROM app_user u
CROSS JOIN dim_app_role r
WHERE r.code = 'STAFF'
  AND u.email IN (
      'loi@studylink.test',
      'truongan@studylink.test',
      'hoangyen@studylink.test',
      'trucquynh@studylink.test',
      'giaman@studylink.test',
      'vinh@studylink.test',
      'myly@studylink.test',
      'honghanh@studylink.test',
      'khietoanh@studylink.test',
      'tatthanh@studylink.test'
  )
ON CONFLICT (user_id, role_id) DO NOTHING;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Users with their roles
SELECT
    u.email,
    u.display_name,
    rs.canonical_name AS linked_staff_name,
    STRING_AGG(r.code, ', ' ORDER BY r.code) AS roles,
    CASE WHEN u.password_hash IS NULL THEN 'NOT SET' ELSE 'set' END AS password_status
FROM app_user u
LEFT JOIN ref_staff rs            ON rs.id = u.staff_id
LEFT JOIN app_user_role aur       ON aur.user_id = u.id
LEFT JOIN dim_app_role r          ON r.id = aur.role_id
WHERE u.email LIKE '%@studylink.test'
GROUP BY u.id, u.email, u.display_name, rs.canonical_name, u.password_hash
ORDER BY
    CASE WHEN rs.canonical_name IS NULL THEN 0 ELSE 1 END,
    u.email;

-- Any staff users that failed to link to ref_staff (fix manually if any)
SELECT email, display_name
FROM app_user
WHERE email LIKE '%@studylink.test'
  AND staff_id IS NULL
  AND email NOT IN ('director@studylink.test', 'admin@studylink.test',
                    'fo@studylink.test', 'dqo@studylink.test');
