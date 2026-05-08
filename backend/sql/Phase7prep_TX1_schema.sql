-- =============================================================================
-- Phase 7-prep: Partner / Priority Redesign
-- =============================================================================
--
-- Combines what was originally Phase 6l (alias backfill from regression test)
-- with a structural redesign of partner classification and priority hierarchies
-- mandated by management clarifications received in this session.
--
-- This migration runs in TWO transactions to avoid PostgreSQL catalog-visibility
-- errors when seeding columns added in the same transaction (lesson from 6i).
--
-- TRANSACTION 1 — Schema (DDL)
-- TRANSACTION 2 — Data (DML + seeding + reclassification + Phase 6l fixes)
--
-- =============================================================================
-- WHAT THIS MIGRATION DOES
-- =============================================================================
--
-- A. SCHEMA
--   1. ref_staff.secondary_role_id            — supports dual-role staff (Lợi)
--   2. ref_partner_classification (NEW)        — effective-dated partner category
--                                                (GROUP / MA_OOS / MA_GENUINE),
--                                                weight, bonus model
--   3. ref_partner_flat_rate (NEW)             — flat rates for MA_GENUINE,
--                                                effective-dated, by office × role
--   4. ref_priority_group (NEW)                — informational top level
--                                                (Navitas, INTO, etc.)
--   5. ref_priority_partner.effective_from/to  — effective-date the List rows
--   6. ref_priority_target — REBUILD as effective-dated (drop year column,
--                            add effective_from / effective_to)
--   7. ref_priority_partner_institution (NEW)  — effective-dated junction:
--                                                Institution → List
--                                                replaces ref_institution.
--                                                aggregate_priority_partner_id
--   8. ref_priority_group_partner (NEW)        — effective-dated junction:
--                                                List → Group
--   9. ref_institution.classification CHECK    — drop OUT_SYSTEM_GROUP and
--                                                OUT_SYSTEM_MASTER_AGENT;
--                                                rename IN_SYSTEM_REGULAR →
--                                                IN_SYSTEM
--
-- B. DATA
--   1. Translate existing ref_institution.aggregate_priority_partner_id values
--      → ref_priority_partner_institution rows, effective 2024-01-01
--   2. Drop ref_institution.aggregate_priority_partner_id column
--   3. Reclassify all existing OUT_SYSTEM_GROUP institutions → IN_SYSTEM
--   4. Reclassify all IN_SYSTEM_REGULAR institutions → IN_SYSTEM (rename)
--   5. Migrate existing ref_priority_target rows: year=Y → effective_from=Y-01-01,
--      effective_to=Y-12-31
--   6. Seed ref_partner_classification: 27 rows × possibly multiple periods
--   7. Seed ref_partner_flat_rate: ApplyBoard + Can-Achieve × 3 offices × 2 roles
--   8. Set Lợi's ref_staff.secondary_role_id = CO_DIR
--   9. Seed ref_priority_group from Doc 6 + management clarifications
--  10. Seed/update ref_priority_partner from PRIORITY 2025 image (38 Lists)
--  11. Seed ref_priority_target for 2024 (real bonus_pct) + 2025 (0% paused)
--  12. Seed ref_priority_partner_institution for 2024 onward
--  13. Seed ref_priority_group_partner for Navitas's Lists
--
-- C. PHASE 6L DATA FIXES (folded in)
--   1. 6 sub-agent canonical inserts + self-aliases
--   2. 4 institution canonical inserts + aliases:
--      - International Language Academy (+ ILAC partner link)
--      - Education Queensland International (EQI) — also a priority List
--      - Wesley College — IN_SYSTEM, no priority
--      - Northern Territory Government - Department of Education — IN_SYSTEM
--   3. Victoria University aliases (Melbourne, VU) → existing canonical id 288
--
-- =============================================================================
-- WHAT THIS MIGRATION DOES NOT DO
-- =============================================================================
--
--   - Does NOT modify the importer code. The importer's *-/**-handling and
--     classification-writing logic must be updated separately, AFTER this
--     migration deploys. (See accompanying ImporterChanges.md.)
--   - Does NOT modify the engine. Engine reads the new tables in Phase 7.
--   - Does NOT seed group-level Navitas member-list distributions for Lists
--     beyond the four named (Griffith College, WSU College, ICM, Toronto Met
--     Intl) — the "Other Navitas AU/CA/NZ" Lists' per-institution sub-targets
--     await management's enriched data file.
--
-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- Each section ends with a SELECT that returns expected row counts. If any
-- count is off, the migration aborts (use a backup/restore to retry).
-- =============================================================================


-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║                          TRANSACTION 1 — SCHEMA                            ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. ref_staff.secondary_role_id
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_staff
    ADD COLUMN IF NOT EXISTS secondary_role_id BIGINT REFERENCES dim_role(id);

COMMENT ON COLUMN ref_staff.secondary_role_id IS
'Optional second role; supports staff acting in multiple capacities (e.g. CO_SUB
+ CO_DIR for Lợi as the lone DN sales representative). Engine derives effective
role per case from the case context, not from this column.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. ref_partner_classification
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ref_partner_classification (
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

CREATE UNIQUE INDEX IF NOT EXISTS uniq_partner_classif_active
    ON ref_partner_classification (partner_id)
    WHERE effective_to IS NULL;

COMMENT ON TABLE ref_partner_classification IS
'Effective-dated category for a partner. category drives KPI weight (1.0 vs 0.7)
and bonus model (TIER vs FLAT). Multiple rows per partner over time.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. ref_partner_flat_rate
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ref_partner_flat_rate (
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

CREATE UNIQUE INDEX IF NOT EXISTS uniq_partner_flat_rate_active
    ON ref_partner_flat_rate (partner_id, office_id, role_id)
    WHERE effective_to IS NULL;

COMMENT ON TABLE ref_partner_flat_rate IS
'Flat per-case rates for partners with bonus_model = FLAT (e.g. ApplyBoard,
Can-Achieve). Rates vary by office and role and are effective-dated.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. ref_priority_group
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ref_priority_group (
    id                 BIGSERIAL PRIMARY KEY,
    name               VARCHAR(255) NOT NULL,
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

CREATE UNIQUE INDEX IF NOT EXISTS uniq_priority_group_name_active
    ON ref_priority_group (name)
    WHERE effective_to IS NULL;

COMMENT ON TABLE ref_priority_group IS
'Top-level commercial relationship grouping (e.g. Navitas). Reporting/
contractual aggregation only. NOT used for bonus math — bonus is calculated
at List (ref_priority_partner) level.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. ref_priority_partner — add effective_from / effective_to
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_priority_partner
    ADD COLUMN IF NOT EXISTS effective_from DATE,
    ADD COLUMN IF NOT EXISTS effective_to   DATE;

COMMENT ON COLUMN ref_priority_partner.effective_from IS
'Date this List began. Backfilled to 2024-01-01 for pre-existing rows.';
COMMENT ON COLUMN ref_priority_partner.effective_to IS
'Date this List ended. NULL = still active.';

-- Backfill all existing rows so the NOT NULL constraint we add next succeeds.
UPDATE ref_priority_partner
   SET effective_from = DATE '2024-01-01'
 WHERE effective_from IS NULL;

ALTER TABLE ref_priority_partner
    ALTER COLUMN effective_from SET NOT NULL,
    ADD CONSTRAINT chk_priority_partner_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from);

-- ref_priority_partner.name is currently UNIQUE. Replace with a partial-unique
-- index allowing reused names across non-overlapping periods.
ALTER TABLE ref_priority_partner DROP CONSTRAINT IF EXISTS ref_priority_partner_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_priority_partner_name_active
    ON ref_priority_partner (name)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. ref_priority_target — REBUILD as effective-dated
--
--    Drop year, add effective_from/effective_to. Existing data migrated:
--    year=Y → effective_from=Y-01-01, effective_to=Y-12-31.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_priority_target
    ADD COLUMN IF NOT EXISTS effective_from DATE,
    ADD COLUMN IF NOT EXISTS effective_to   DATE;

UPDATE ref_priority_target
   SET effective_from = MAKE_DATE(year, 1, 1),
       effective_to   = MAKE_DATE(year, 12, 31)
 WHERE effective_from IS NULL;

ALTER TABLE ref_priority_target
    ALTER COLUMN effective_from SET NOT NULL,
    ADD CONSTRAINT chk_priority_target_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from);

ALTER TABLE ref_priority_target DROP CONSTRAINT IF EXISTS ref_priority_target_priority_partner_id_year_key;
ALTER TABLE ref_priority_target DROP COLUMN IF EXISTS year;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_priority_target_active
    ON ref_priority_target (priority_partner_id)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. ref_priority_partner_institution
--    Effective-dated junction: Institution → List.
--    Replaces ref_institution.aggregate_priority_partner_id (dropped in TX2).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ref_priority_partner_institution (
    id                   BIGSERIAL PRIMARY KEY,
    priority_partner_id  BIGINT NOT NULL REFERENCES ref_priority_partner(id),
    institution_id       BIGINT NOT NULL REFERENCES ref_institution(id),
    -- Per-institution sub-targets within the List (optional). When present,
    -- engine uses these as the per-institution KPI; when NULL, engine treats
    -- the List as undifferentiated.
    institution_target_direct INTEGER CHECK (institution_target_direct IS NULL OR institution_target_direct >= 0),
    institution_target_sub    INTEGER CHECK (institution_target_sub    IS NULL OR institution_target_sub    >= 0),
    effective_from       DATE NOT NULL,
    effective_to         DATE,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TRIGGER trg_priority_partner_institution_updated
    BEFORE UPDATE ON ref_priority_partner_institution
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

CREATE UNIQUE INDEX IF NOT EXISTS uniq_priority_partner_inst_active
    ON ref_priority_partner_institution (priority_partner_id, institution_id)
    WHERE effective_to IS NULL;

CREATE INDEX IF NOT EXISTS idx_priority_partner_inst_inst
    ON ref_priority_partner_institution (institution_id)
    WHERE effective_to IS NULL;

COMMENT ON TABLE ref_priority_partner_institution IS
'Effective-dated membership: an institution belongs to a priority List during
a date range. Replaces the static FK on ref_institution.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 8. ref_priority_group_partner
--    Effective-dated junction: List → Group.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ref_priority_group_partner (
    id                   BIGSERIAL PRIMARY KEY,
    priority_group_id    BIGINT NOT NULL REFERENCES ref_priority_group(id),
    priority_partner_id  BIGINT NOT NULL REFERENCES ref_priority_partner(id),
    effective_from       DATE NOT NULL,
    effective_to         DATE,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TRIGGER trg_priority_group_partner_updated
    BEFORE UPDATE ON ref_priority_group_partner
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- A List belongs to at most one active Group at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_priority_group_partner_active
    ON ref_priority_group_partner (priority_partner_id)
    WHERE effective_to IS NULL;

CREATE INDEX IF NOT EXISTS idx_priority_group_partner_group
    ON ref_priority_group_partner (priority_group_id)
    WHERE effective_to IS NULL;

COMMENT ON TABLE ref_priority_group_partner IS
'Effective-dated membership: a List belongs to a Group during a date range.
Group level is informational; bonus math operates at List level only.';


-- ─────────────────────────────────────────────────────────────────────────────
-- 8b. ref_institution.is_priority_member — fast cached flag
--
--    Set to TRUE for any institution with an active row in
--    ref_priority_partner_institution. Backfilled in TX2.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_institution
    ADD COLUMN IF NOT EXISTS is_priority_member BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN ref_institution.is_priority_member IS
'Cached flag: TRUE if this institution belongs to at least one active
ref_priority_partner_institution row. Maintained alongside the junction
table; engine reads this for fast filtering.';

CREATE INDEX IF NOT EXISTS idx_ref_institution_priority_member
    ON ref_institution (is_priority_member)
    WHERE is_priority_member = TRUE;


-- ─────────────────────────────────────────────────────────────────────────────
-- 9. ref_institution.classification — simplify to {IN_SYSTEM, UNVERIFIED}
--
--    Priority status is now captured by is_priority_member (set in TX2 from
--    junction table membership). The classification column is reduced to a
--    binary distinction: is this institution recognised in our system, or not?
--
--    The new check temporarily accepts the legacy values too, so existing rows
--    survive into TX2, where they are reclassified. We tighten the constraint
--    again at the end of TX2.
-- ─────────────────────────────────────────────────────────────────────────────

-- Drop the old constraint (whatever its name; introspect if needed)
DO $$
DECLARE
    cn TEXT;
BEGIN
    SELECT conname INTO cn
    FROM   pg_constraint
    WHERE  conrelid = 'ref_institution'::regclass
      AND  contype  = 'c'
      AND  pg_get_constraintdef(oid) ILIKE '%classification%IN%';
    IF cn IS NOT NULL THEN
        EXECUTE format('ALTER TABLE ref_institution DROP CONSTRAINT %I', cn);
    END IF;
END$$;

-- Re-add as a permissive interim constraint allowing both old and new values.
ALTER TABLE ref_institution
    ADD CONSTRAINT chk_ref_institution_classification_interim CHECK (
        classification IN (
            'IN_SYSTEM',
            'UNVERIFIED',
            -- legacy values still allowed during TX2 reclassification
            'IN_SYSTEM_REGULAR',
            'IN_SYSTEM_PRIORITY',
            'OUT_SYSTEM_GROUP',
            'OUT_SYSTEM_MASTER_AGENT'
        )
    );


-- ─────────────────────────────────────────────────────────────────────────────
-- TX1 verification
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_tables   INTEGER;
    has_2nd    BOOLEAN;
    has_eff_pp BOOLEAN;
    has_eff_pt BOOLEAN;
    no_year    BOOLEAN;
BEGIN
    SELECT COUNT(*)
      INTO n_tables
      FROM information_schema.tables
     WHERE table_name IN (
        'ref_partner_classification',
        'ref_partner_flat_rate',
        'ref_priority_group',
        'ref_priority_partner_institution',
        'ref_priority_group_partner'
     );

    SELECT EXISTS(SELECT 1 FROM information_schema.columns
                   WHERE table_name='ref_staff' AND column_name='secondary_role_id')
      INTO has_2nd;

    SELECT EXISTS(SELECT 1 FROM information_schema.columns
                   WHERE table_name='ref_priority_partner' AND column_name='effective_from')
      INTO has_eff_pp;

    SELECT EXISTS(SELECT 1 FROM information_schema.columns
                   WHERE table_name='ref_priority_target' AND column_name='effective_from')
      INTO has_eff_pt;

    SELECT NOT EXISTS(SELECT 1 FROM information_schema.columns
                       WHERE table_name='ref_priority_target' AND column_name='year')
      INTO no_year;

    IF n_tables   <> 5    THEN RAISE EXCEPTION 'TX1 verify: expected 5 new tables, got %', n_tables; END IF;
    IF NOT has_2nd        THEN RAISE EXCEPTION 'TX1 verify: ref_staff.secondary_role_id missing'; END IF;
    IF NOT has_eff_pp     THEN RAISE EXCEPTION 'TX1 verify: ref_priority_partner.effective_from missing'; END IF;
    IF NOT has_eff_pt     THEN RAISE EXCEPTION 'TX1 verify: ref_priority_target.effective_from missing'; END IF;
    IF NOT no_year        THEN RAISE EXCEPTION 'TX1 verify: ref_priority_target.year still present'; END IF;

    RAISE NOTICE 'TX1 schema changes verified.';
END$$;

COMMIT;

-- =============================================================================
-- END OF TX1. After successful run, proceed to Phase7prep_TX2_data.sql
-- =============================================================================
