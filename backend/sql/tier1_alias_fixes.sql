-- =============================================================================
-- Tier 1 Alias Fixes
--
-- Targets the easy-win categories from the post-import warning audit:
--   1A. Staff: 5 INSERTs + 3 aliases (~205 of 207 staff cases)
--   1B. Country: new ref_country_alias table + 3 aliases (141 of 143 cases)
--   1C. Application Status 'Current' canonical + alias (12 cases)
--
-- Total expected reduction: ~358 of the 822 warnings, plus secondary drop
-- in NO_RESOLVABLE_OFFICE since that fires when staff resolution fails.
--
-- Run end-to-end in pgAdmin. Idempotent: safe to re-run if you stop partway.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1A. STAFF
-- -----------------------------------------------------------------------------
-- Default new staff to LEFT/HCM/CO_DIR; /* VERIFY role + office for each */
-- once business confirms current employment + role assignments.
-- HCM = office_id 16, CO_DIR = role_id 17, COUNS_DIR = role_id 16.

INSERT INTO ref_staff (canonical_name, employment_status, home_office_id, primary_role_id)
SELECT canonical_name, employment_status, home_office_id, primary_role_id
FROM (VALUES
    ('Đặng Bảo Ngọc',         'LEFT', 16, 17),
    ('Nguyễn Thị Ngọc Tuyền', 'LEFT', 16, 17),
    ('Nhiêu Mỹ Như',          'LEFT', 16, 17),
    ('Cao Thị Phương Thảo',   'LEFT', 16, 17),
    ('Tạ Vũ Phương Anh',      'LEFT', 16, 17)
) AS v(canonical_name, employment_status, home_office_id, primary_role_id)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_staff s WHERE s.canonical_name = v.canonical_name
);

-- Aliases for existing staff (variants in the CRM that don't match canonical)
INSERT INTO ref_staff_alias (alias, staff_id)
SELECT alias, staff_id
FROM (VALUES
    ('Nguyễn Ngọc Hà B',     19),  -- "B" suffix variant for Nguyễn Ngọc Hà
    ('Trương Thị Mạc Đan B', 26),  -- "B" suffix variant for Trương Thị Mạc Đan
    ('Thái Thị Huỳnh Anh',    8)   -- Long-form name for Huỳnh Anh
) AS v(alias, staff_id)
WHERE NOT EXISTS (
    SELECT 1 FROM ref_staff_alias a WHERE a.alias = v.alias
);


-- -----------------------------------------------------------------------------
-- 1B. COUNTRY ALIAS TABLE + ENTRIES
-- -----------------------------------------------------------------------------
-- New table mirroring the other ref_*_alias pattern. Resolver code change
-- in resolvers.py makes resolve_country() check this table first, falling
-- back to dim_country.name/code for direct matches.

CREATE TABLE IF NOT EXISTS ref_country_alias (
    id          BIGSERIAL PRIMARY KEY,
    alias       VARCHAR(255) NOT NULL UNIQUE,
    country_id  BIGINT       NOT NULL REFERENCES dim_country(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ref_country_alias_lower
    ON ref_country_alias (LOWER(alias));

-- Apply the project's standard updated_at trigger
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_ref_country_alias_updated_at'
    ) THEN
        CREATE TRIGGER trg_ref_country_alias_updated_at
        BEFORE UPDATE ON ref_country_alias
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
    END IF;
END $$;

-- Aliases for the three high-volume CRM variants
INSERT INTO ref_country_alias (alias, country_id) VALUES
    ('USA',        57),  -- United States
    ('UK',         59),  -- United Kingdom
    ('Switzeland', 62)   -- Switzerland (typo in CRM)
ON CONFLICT (alias) DO NOTHING;


-- -----------------------------------------------------------------------------
-- 1C. APPLICATION STATUS 'Current'
-- -----------------------------------------------------------------------------
-- 'Current' means: open contract, no enrolment/visa event yet.
-- Bonus splits all zero; is_zero_bonus=true so the engine pays nothing
-- until status progresses to an event-bearing one.

INSERT INTO ref_status_split (
    status, counts_as_enrolled,
    split_couns_pct, split_co_dir_pct, split_co_sub_pct,
    is_carry_over, is_current_enrolled, is_zero_bonus,
    fees_paid_non_enrolled, is_visa_granted, is_visa_only_paid,
    deduplication_rank, notes
)
SELECT
    'Current', false,
    0, 0, 0,
    false, false, true,
    false, false, false,
    0,
    'Open contract, no enrolment/visa event yet. No bonus payable until status progresses.'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_status_split WHERE status = 'Current'
);

INSERT INTO ref_status_split_alias (alias, status_id)
SELECT 'Current', s.id
FROM ref_status_split s
WHERE s.status = 'Current'
  AND NOT EXISTS (
      SELECT 1 FROM ref_status_split_alias WHERE alias = 'Current'
  );


-- -----------------------------------------------------------------------------
-- Verification (one row per fix category — should each return >= expected count)
-- -----------------------------------------------------------------------------
SELECT '1A staff inserted' AS what, COUNT(*) AS n, 5 AS expected
FROM ref_staff WHERE canonical_name IN (
    'Đặng Bảo Ngọc', 'Nguyễn Thị Ngọc Tuyền', 'Nhiêu Mỹ Như',
    'Cao Thị Phương Thảo', 'Tạ Vũ Phương Anh'
)
UNION ALL
SELECT '1A staff aliases', COUNT(*), 3
FROM ref_staff_alias
WHERE alias IN ('Nguyễn Ngọc Hà B', 'Trương Thị Mạc Đan B', 'Thái Thị Huỳnh Anh')
UNION ALL
SELECT '1B country aliases', COUNT(*), 3 FROM ref_country_alias
UNION ALL
SELECT '1C Current status row', COUNT(*), 1 FROM ref_status_split WHERE status = 'Current'
UNION ALL
SELECT '1C Current status alias', COUNT(*), 1 FROM ref_status_split_alias WHERE alias = 'Current'
ORDER BY what;

COMMIT;
