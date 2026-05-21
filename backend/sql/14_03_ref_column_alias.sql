-- =====================================================================
-- Migration 14_03: ref_column_alias — header-text alias table
-- =====================================================================
--
-- Purpose: Shield the importer from header-text drift in source files.
-- The May 2024 Trường An file has 'Student File::Refer Source Agent'
-- where January has plain 'Refer Source Agent'. SBS prefixes table
-- names onto column headers in some export configurations.
--
-- Design:
--   * One canonical name per source-file column (15 currently)
--   * Self-aliasing seed rows — canonical Contract ID also lives as
--     an alias "Contract ID" → "Contract ID"
--   * Plus known drift variants ("Student File::Refer Source Agent")
--   * Reader: case-insensitive, whitespace-tolerant lookup
--
-- Unknown headers (no alias match) pass through as-is. The transformer
-- then treats them as unrecognised columns (their data is ignored, the
-- canonical fields become NULL). No row is rejected for this reason.
--
-- Wraps in BEGIN/COMMIT. Review verification at the bottom before COMMIT.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Table
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ref_column_alias (
    id              BIGSERIAL PRIMARY KEY,
    alias           TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Case-insensitive uniqueness on alias. LOWER+TRIM handles the
-- "case-insensitive with whitespace tolerance" requirement.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ref_column_alias_alias_lower
    ON ref_column_alias (LOWER(TRIM(alias)));

-- Lookup index on the canonical_name for diagnostics
CREATE INDEX IF NOT EXISTS idx_ref_column_alias_canonical
    ON ref_column_alias (canonical_name);

COMMENT ON TABLE ref_column_alias IS
    'Source-file column-header aliases. Maps the literal header text '
    'as it appears in CRM export files to the canonical column name '
    'the code uses. Lookup is case-insensitive and whitespace-tolerant.';

COMMENT ON COLUMN ref_column_alias.alias IS
    'Header text as it appears in a source xlsx file (any case, any '
    'whitespace).';

COMMENT ON COLUMN ref_column_alias.canonical_name IS
    'Canonical column name. The transformer code references columns '
    'by this name.';

-- ---------------------------------------------------------------------
-- Seed data: 15 canonical columns, each self-aliasing,
-- plus known variants
-- ---------------------------------------------------------------------

INSERT INTO ref_column_alias (alias, canonical_name, notes) VALUES
    -- 1. No.
    ('No.',                                  'No.',                       'Self-alias'),
    -- 2. Student Name
    ('Student Name',                         'Student Name',              'Self-alias'),
    ('Student File::Student Name',           'Student Name',              'SBS table-prefix variant'),
    -- 3. Student ID
    ('Student ID',                           'Student ID',                'Self-alias'),
    ('Student File::Student ID',             'Student ID',                'SBS table-prefix variant'),
    -- 4. Contract ID
    ('Contract ID',                          'Contract ID',               'Self-alias'),
    ('Student File::Contract ID',            'Contract ID',               'SBS table-prefix variant'),
    -- 5. Contract Signed Date
    ('Contract Signed Date',                 'Contract Signed Date',      'Self-alias'),
    ('Student File::Contract Signed Date',   'Contract Signed Date',      'SBS table-prefix variant'),
    -- 6. Client Type
    ('Client Type',                          'Client Type',               'Self-alias'),
    ('Student File::Client Type',            'Client Type',               'SBS table-prefix variant'),
    -- 7. Country of Study
    ('Country of Study',                     'Country of Study',          'Self-alias'),
    ('Student File::Country of Study',       'Country of Study',          'SBS table-prefix variant'),
    -- 8. Refer Source Agent  ← observed variant in Trường An May 2024
    ('Refer Source Agent',                   'Refer Source Agent',        'Self-alias'),
    ('Student File::Refer Source Agent',     'Refer Source Agent',        'SBS table-prefix variant; observed in Trường An May 2024'),
    -- 9. System Type
    ('System Type',                          'System Type',               'Self-alias'),
    ('Student File::System Type',            'System Type',               'SBS table-prefix variant'),
    -- 10. Application Report Status
    ('Application Report Status',            'Application Report Status', 'Self-alias'),
    ('Student File::Application Report Status', 'Application Report Status', 'SBS table-prefix variant'),
    -- 11. Visa Received Date
    ('Visa Received Date',                   'Visa Received Date',        'Self-alias'),
    ('Student File::Visa Received Date',     'Visa Received Date',        'SBS table-prefix variant'),
    -- 12. Institution Name
    ('Institution Name',                     'Institution Name',          'Self-alias'),
    ('Student File::Institution Name',       'Institution Name',          'SBS table-prefix variant'),
    -- 13. Course Start Date
    ('Course Start Date',                    'Course Start Date',         'Self-alias'),
    ('Student File::Course Start Date',      'Course Start Date',         'SBS table-prefix variant'),
    -- 14. Course Status  (observed in Trường An May 2024)
    ('Course Status',                        'Course Status',             'Self-alias'),
    ('Student File::Course Status',          'Course Status',             'SBS table-prefix variant'),
    -- 15. Counsellor Name
    ('Counsellor Name',                      'Counsellor Name',           'Self-alias'),
    ('Student File::Counsellor Name',        'Counsellor Name',           'SBS table-prefix variant'),
    -- 16. Case Officer Name
    ('Case Officer Name',                    'Case Officer Name',         'Self-alias'),
    ('Student File::Case Officer Name',      'Case Officer Name',         'SBS table-prefix variant'),
    -- 17. Pre-sales Name (optional column, present in some files)
    ('Pre-sales Name',                       'Pre-sales Name',            'Self-alias'),
    ('Student File::Pre-sales Name',         'Pre-sales Name',            'SBS table-prefix variant'),
    -- 18. Notes (optional column)
    ('Notes',                                'Notes',                     'Self-alias'),
    ('Student File::Notes',                  'Notes',                     'SBS table-prefix variant'),
    -- 19. Customer Incentive >= VND5000000 (18-column file variant)
    --     The transformer uses a prefix match (startswith "Customer Incentive")
    --     so any tail variant works without needing aliases. We seed the
    --     known forms anyway for clarity.
    ('Customer Incentive >= VND5000000',     'Customer Incentive >= VND5000000', 'Self-alias'),
    ('Student File::Customer Incentive >= VND5000000', 'Customer Incentive >= VND5000000', 'SBS table-prefix variant')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------
-- Updated-at trigger (matches the convention used elsewhere)
-- ---------------------------------------------------------------------

-- Reuse the shared trigger function if it exists; create only if missing.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'trg_set_updated_at') THEN
        CREATE FUNCTION trg_set_updated_at() RETURNS TRIGGER AS $body$
        BEGIN
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $body$ LANGUAGE plpgsql;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_ref_column_alias_updated ON ref_column_alias;
CREATE TRIGGER trg_ref_column_alias_updated
    BEFORE UPDATE ON ref_column_alias
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_updated_at();

-- ---------------------------------------------------------------------
-- Verification
-- ---------------------------------------------------------------------

-- Count seeded rows
SELECT 'Total aliases seeded' AS check_name, COUNT(*) AS n
FROM ref_column_alias;

-- Distinct canonical names (should be 19)
SELECT 'Distinct canonical names' AS check_name, COUNT(DISTINCT canonical_name) AS n
FROM ref_column_alias;

-- Spot check: Refer Source Agent variants
SELECT 'Refer Source Agent variants' AS check_name,
       alias, canonical_name
FROM ref_column_alias
WHERE canonical_name = 'Refer Source Agent';

-- Spot check: case-insensitive uniqueness — try resolving a lowercase
-- variant to confirm the LOWER(TRIM(...)) index works
SELECT 'Case-insensitive lookup test' AS check_name,
       alias, canonical_name
FROM ref_column_alias
WHERE LOWER(TRIM(alias)) = LOWER(TRIM('  STUDENT FILE::REFER SOURCE AGENT  '));

-- =====================================================================
-- If verification looks right, run:    COMMIT;
-- If anything looks wrong, run:        ROLLBACK;
-- =====================================================================
