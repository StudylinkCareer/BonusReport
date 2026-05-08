-- =============================================================================
-- Phase7prep_v2_TX2_rebuild_schema.sql
-- Run AFTER Phase7prep_v2_TX1_rollback.sql succeeded.
-- =============================================================================

-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  TRANSACTION 2 — REBUILD SCHEMA correctly                                  ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2.1 ref_staff.secondary_role_id (re-added)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_staff
    ADD COLUMN secondary_role_id BIGINT REFERENCES dim_role(id);

COMMENT ON COLUMN ref_staff.secondary_role_id IS
'Optional second role; supports staff acting in multiple capacities (e.g. Lợi
as both CO_SUB and CO_DIR in the DN office). Engine derives effective role per
case from the case context, not from this column directly.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.2 ref_partner_classification
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ref_partner_classification (
    id                 BIGSERIAL PRIMARY KEY,
    partner_id         BIGINT NOT NULL REFERENCES ref_partner(id),
    category           VARCHAR(24) NOT NULL CHECK (category IN (
                          'GROUP',
                          'MASTER_AGENT_OOS',
                          'MASTER_AGENT_GENUINE'
                       )),
    kpi_weight         DECIMAL(3,2) NOT NULL CHECK (kpi_weight BETWEEN 0 AND 1),
    bonus_model        VARCHAR(8) NOT NULL CHECK (bonus_model IN ('TIER','FLAT')),
    effective_from     DATE NOT NULL,
    effective_to       DATE,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TRIGGER trg_ref_partner_classification_updated
    BEFORE UPDATE ON ref_partner_classification
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE UNIQUE INDEX uniq_partner_classif_active
    ON ref_partner_classification (partner_id)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.3 ref_partner_flat_rate
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ref_partner_flat_rate (
    id                 BIGSERIAL PRIMARY KEY,
    partner_id         BIGINT NOT NULL REFERENCES ref_partner(id),
    office_id          BIGINT NOT NULL REFERENCES dim_office(id),
    role_id            BIGINT NOT NULL REFERENCES dim_role(id),
    amount             INTEGER NOT NULL CHECK (amount >= 0),
    effective_from     DATE NOT NULL,
    effective_to       DATE,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TRIGGER trg_ref_partner_flat_rate_updated
    BEFORE UPDATE ON ref_partner_flat_rate
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE UNIQUE INDEX uniq_partner_flat_rate_active
    ON ref_partner_flat_rate (partner_id, office_id, role_id)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.4 ref_priority_group
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ref_priority_group (
    id                 BIGSERIAL PRIMARY KEY,
    canonical_name     VARCHAR(255) NOT NULL,
    country_id         BIGINT REFERENCES dim_country(id),
    notes              TEXT,
    effective_from     DATE NOT NULL,
    effective_to       DATE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TRIGGER trg_ref_priority_group_updated
    BEFORE UPDATE ON ref_priority_group
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE UNIQUE INDEX uniq_priority_group_canonical_active
    ON ref_priority_group (canonical_name)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.5 ref_priority_group_alias
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ref_priority_group_alias (
    id                 BIGSERIAL PRIMARY KEY,
    priority_group_id  BIGINT NOT NULL REFERENCES ref_priority_group(id),
    alias              VARCHAR(255) NOT NULL UNIQUE,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_ref_priority_group_alias_updated
    BEFORE UPDATE ON ref_priority_group_alias
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.6 ref_priority_list (renamed from ref_priority_partner)
--
--    Every List belongs to a Group. group_id is NOT NULL.
--    Each List has a country_id (already on ref_priority_partner).
--    is_aggregate stays as-is for reporting.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_priority_partner
    RENAME TO ref_priority_list;

-- Standardise: use canonical_name to match other ref tables
ALTER TABLE ref_priority_list
    RENAME COLUMN name TO canonical_name;

-- Replace constraint name to match new table name
ALTER TABLE ref_priority_list
    RENAME CONSTRAINT ref_priority_partner_name_key TO ref_priority_list_canonical_name_key;

-- group_id added, NOT NULL after seed
ALTER TABLE ref_priority_list
    ADD COLUMN group_id BIGINT REFERENCES ref_priority_group(id),
    ADD COLUMN effective_from DATE,
    ADD COLUMN effective_to DATE;

COMMENT ON TABLE ref_priority_list IS
'Priority Lists. Every List belongs to a Group via group_id. Lists are the
bonus-bearing entity in priority math. is_aggregate is informational only.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.7 ref_priority_list_alias
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ref_priority_list_alias (
    id                 BIGSERIAL PRIMARY KEY,
    priority_list_id   BIGINT NOT NULL REFERENCES ref_priority_list(id),
    alias              VARCHAR(255) NOT NULL UNIQUE,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_ref_priority_list_alias_updated
    BEFORE UPDATE ON ref_priority_list_alias
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.8 ref_priority_list_institution
--    Effective-dated junction: which institutions belong to which List.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE ref_priority_list_institution (
    id                        BIGSERIAL PRIMARY KEY,
    priority_list_id          BIGINT NOT NULL REFERENCES ref_priority_list(id),
    institution_id            BIGINT NOT NULL REFERENCES ref_institution(id),
    institution_target_direct INTEGER CHECK (institution_target_direct IS NULL OR institution_target_direct >= 0),
    institution_target_sub    INTEGER CHECK (institution_target_sub    IS NULL OR institution_target_sub    >= 0),
    effective_from            DATE NOT NULL,
    effective_to              DATE,
    notes                     TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TRIGGER trg_ref_priority_list_institution_updated
    BEFORE UPDATE ON ref_priority_list_institution
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE UNIQUE INDEX uniq_priority_list_inst_active
    ON ref_priority_list_institution (priority_list_id, institution_id)
    WHERE effective_to IS NULL;

CREATE INDEX idx_priority_list_inst_inst
    ON ref_priority_list_institution (institution_id)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.9 ref_priority_target — effective-dated targets
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_priority_target
    ADD COLUMN effective_from DATE,
    ADD COLUMN effective_to   DATE;

UPDATE ref_priority_target
   SET effective_from = MAKE_DATE(year, 1, 1),
       effective_to   = MAKE_DATE(year, 12, 31)
 WHERE effective_from IS NULL;

ALTER TABLE ref_priority_target
    ALTER COLUMN effective_from SET NOT NULL,
    ADD CONSTRAINT chk_priority_target_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from);

ALTER TABLE ref_priority_target DROP CONSTRAINT IF EXISTS ref_priority_target_priority_partner_id_year_key;
ALTER TABLE ref_priority_target DROP COLUMN year;

-- The FK column is named priority_partner_id from before the rename. Rename
-- it to match the new table.
ALTER TABLE ref_priority_target
    RENAME COLUMN priority_partner_id TO priority_list_id;

CREATE UNIQUE INDEX uniq_priority_target_active
    ON ref_priority_target (priority_list_id)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.10 Drop legacy columns on ref_institution
-- ─────────────────────────────────────────────────────────────────────────────

-- Drop classification check first (refers to priority_partner_id)
DO $$
DECLARE cn TEXT;
BEGIN
    FOR cn IN
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = 'ref_institution'::regclass
           AND contype  = 'c'
           AND pg_get_constraintdef(oid) ILIKE '%priority_partner_id%'
    LOOP
        EXECUTE format('ALTER TABLE ref_institution DROP CONSTRAINT %I', cn);
    END LOOP;
END$$;

-- Drop FK columns; junction table replaces them
ALTER TABLE ref_institution DROP COLUMN IF EXISTS aggregate_priority_partner_id;
ALTER TABLE ref_institution DROP COLUMN IF EXISTS priority_partner_id;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2.11 ref_institution.classification — simplify
--      Priority status now derived from junction membership; only IN_SYSTEM
--      and UNVERIFIED needed.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_institution
    DROP CONSTRAINT IF EXISTS ref_institution_classification_check;

-- Permissive interim constraint (TX3 reclassifies, then we tighten there)
ALTER TABLE ref_institution
    ADD CONSTRAINT chk_ref_institution_classification_interim CHECK (
        classification IN (
            'IN_SYSTEM',
            'UNVERIFIED',
            -- legacy values still allowed during TX3 reclassification
            'IN_SYSTEM_REGULAR',
            'IN_SYSTEM_PRIORITY',
            'OUT_SYSTEM_GROUP',
            'OUT_SYSTEM_MASTER_AGENT'
        )
    );


-- ─────────────────────────────────────────────────────────────────────────────
-- TX2 verification
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_new_tables  INTEGER;
    has_secondary BOOLEAN;
    has_group_id  BOOLEAN;
    has_alias_t   BOOLEAN;
BEGIN
    SELECT COUNT(*) INTO n_new_tables
      FROM information_schema.tables
     WHERE table_name IN (
        'ref_partner_classification',
        'ref_partner_flat_rate',
        'ref_priority_group',
        'ref_priority_group_alias',
        'ref_priority_list_alias',
        'ref_priority_list_institution'
     );

    SELECT EXISTS(SELECT 1 FROM information_schema.columns
                   WHERE table_name='ref_staff' AND column_name='secondary_role_id')
      INTO has_secondary;

    SELECT EXISTS(SELECT 1 FROM information_schema.columns
                   WHERE table_name='ref_priority_list' AND column_name='group_id')
      INTO has_group_id;

    SELECT EXISTS(SELECT 1 FROM information_schema.tables
                   WHERE table_name='ref_priority_list')
      INTO has_alias_t;

    IF n_new_tables  <> 6  THEN RAISE EXCEPTION 'TX2 verify: expected 6 new tables, got %', n_new_tables; END IF;
    IF NOT has_secondary   THEN RAISE EXCEPTION 'TX2 verify: ref_staff.secondary_role_id missing'; END IF;
    IF NOT has_group_id    THEN RAISE EXCEPTION 'TX2 verify: ref_priority_list.group_id missing'; END IF;
    IF NOT has_alias_t     THEN RAISE EXCEPTION 'TX2 verify: ref_priority_list table missing'; END IF;

    RAISE NOTICE 'TX2 schema rebuild verified — ready for TX3.';
END$$;

COMMIT;

-- =============================================================================
-- END OF TX2. Verify NOTICE 'TX2 schema rebuild verified' before running TX3.
-- =============================================================================
