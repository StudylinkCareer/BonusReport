-- =============================================================================
-- StudyLink Vietnam Bonus Engine — Database Schema
-- File:    01_schema.sql
-- Purpose: Create all reference, transactional, and audit tables.
-- Target:  PostgreSQL 15+
-- Usage:   psql -d studylink_bonus -f 01_schema.sql
-- Order:   Run BEFORE 02_reference_data.sql and 03_staff_data.sql.
-- =============================================================================
-- Naming:
--   dim_*  = dimensional (small, slow-changing vocabulary)
--   ref_*  = reference data (rates, classifications, configurations)
--   tx_*   = transactional (cases, calculations, audit)
--
-- Conventions:
--   - PK is BIGSERIAL named 'id'
--   - All tables have created_at + updated_at TIMESTAMPTZ
--   - Effective-dated tables use effective_from/effective_to (NULL = current)
--   - Aliases live in per-entity *_alias tables (option B from design)
-- =============================================================================

-- Drop in reverse dependency order if re-running on dirty database.
-- Comment out the DROP block for production deploys.
DROP TABLE IF EXISTS tx_review_log              CASCADE;
DROP TABLE IF EXISTS tx_team_excess_distribution CASCADE;
DROP TABLE IF EXISTS tx_team_excess_period      CASCADE;
DROP TABLE IF EXISTS tx_bonus_payment           CASCADE;
DROP TABLE IF EXISTS tx_case                    CASCADE;
DROP TABLE IF EXISTS tx_run                     CASCADE;
DROP TABLE IF EXISTS ref_complaint_deduction    CASCADE;
DROP TABLE IF EXISTS ref_departure_rule         CASCADE;
DROP TABLE IF EXISTS ref_team_excess_bonus      CASCADE;
DROP TABLE IF EXISTS ref_contract_package_eligibility CASCADE;
DROP TABLE IF EXISTS ref_contract_target_tier   CASCADE;
DROP TABLE IF EXISTS ref_local_enrolment_bonus  CASCADE;
DROP TABLE IF EXISTS ref_service_fee_alias      CASCADE;
DROP TABLE IF EXISTS ref_service_fee            CASCADE;
DROP TABLE IF EXISTS ref_calculation_param      CASCADE;
DROP TABLE IF EXISTS ref_rate                   CASCADE;
DROP TABLE IF EXISTS ref_client_type_alias      CASCADE;
DROP TABLE IF EXISTS ref_client_weight          CASCADE;
DROP TABLE IF EXISTS ref_status_split           CASCADE;
DROP TABLE IF EXISTS ref_partner_institution    CASCADE;
DROP TABLE IF EXISTS ref_institution_alias      CASCADE;
DROP TABLE IF EXISTS ref_institution            CASCADE;
DROP TABLE IF EXISTS ref_partner_alias          CASCADE;
DROP TABLE IF EXISTS ref_partner                CASCADE;
DROP TABLE IF EXISTS ref_sub_agent_alias        CASCADE;
DROP TABLE IF EXISTS ref_sub_agent              CASCADE;
DROP TABLE IF EXISTS ref_priority_target        CASCADE;
DROP TABLE IF EXISTS ref_priority_partner       CASCADE;
DROP TABLE IF EXISTS ref_staff_target           CASCADE;
DROP TABLE IF EXISTS ref_staff_alias            CASCADE;
DROP TABLE IF EXISTS ref_staff                  CASCADE;
DROP TABLE IF EXISTS dim_country_alias          CASCADE;
DROP TABLE IF EXISTS dim_country                CASCADE;
DROP TABLE IF EXISTS dim_role_office_allowed    CASCADE;
DROP TABLE IF EXISTS dim_role                   CASCADE;
DROP TABLE IF EXISTS dim_office                 CASCADE;

-- Reusable trigger function: bumps updated_at on any UPDATE.
CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- SECTION 1 — DIMENSIONAL TABLES
-- =============================================================================

-- 1.1 dim_office --------------------------------------------------------------
CREATE TABLE dim_office (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(8)  NOT NULL UNIQUE,
    name            VARCHAR(64) NOT NULL,
    country_code    VARCHAR(2)  NOT NULL,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_dim_office_updated BEFORE UPDATE ON dim_office
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON TABLE  dim_office IS 'Operating offices: HCM, HN, DN, MEL, future HK.';
COMMENT ON COLUMN dim_office.country_code IS 'ISO-2; anchors office to a country (drives VN-domestic rule scope).';

-- 1.2 dim_role ----------------------------------------------------------------
CREATE TABLE dim_role (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(16) NOT NULL UNIQUE,
    name            VARCHAR(64) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_dim_role_updated BEFORE UPDATE ON dim_role
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON TABLE dim_role IS 'Five roles: COUNS_DIR, CO_DIR, CO_SUB, PRESALES, VP. VP scheme variation by office.';

-- 1.3 dim_role_office_allowed -------------------------------------------------
CREATE TABLE dim_role_office_allowed (
    id              BIGSERIAL PRIMARY KEY,
    role_id         BIGINT NOT NULL REFERENCES dim_role(id),
    office_id       BIGINT NOT NULL REFERENCES dim_office(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role_id, office_id)
);
CREATE TRIGGER trg_dim_role_office_allowed_updated BEFORE UPDATE ON dim_role_office_allowed
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON TABLE dim_role_office_allowed IS 'Valid (role, office) combinations. HCM/HN/DN have all 5 roles. MEL and future HK have VP only.';

-- 1.4 dim_country -------------------------------------------------------------
CREATE TABLE dim_country (
    id                  BIGSERIAL PRIMARY KEY,
    code                VARCHAR(2)  NOT NULL UNIQUE,
    name                VARCHAR(64) NOT NULL,
    is_target_country   BOOLEAN     NOT NULL DEFAULT FALSE,
    is_flat_country     BOOLEAN     NOT NULL DEFAULT FALSE,
    is_domestic_for     BIGINT      REFERENCES dim_office(id),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_dim_country_updated BEFORE UPDATE ON dim_country
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON COLUMN dim_country.is_target_country IS 'D1.R2 14 countries with enrolment targets.';
COMMENT ON COLUMN dim_country.is_flat_country IS 'D1.R2 + D6: TH/PH/MY/KR — 2-out-target = 1-target.';
COMMENT ON COLUMN dim_country.is_domestic_for IS 'For VN row, points to a VN office. Drives VN-domestic 1M rule. HK row would point to HK office when added.';

-- 1.5 dim_country_alias -------------------------------------------------------
CREATE TABLE dim_country_alias (
    id              BIGSERIAL PRIMARY KEY,
    country_id      BIGINT NOT NULL REFERENCES dim_country(id),
    alias           VARCHAR(128) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE dim_country_alias IS 'CRM exports country in Vietnamese (Úc, Hàn Quốc) and English. Alias resolves to canonical row.';


-- =============================================================================
-- SECTION 2 — STAFF
-- =============================================================================

-- 2.1 ref_staff ---------------------------------------------------------------
CREATE TABLE ref_staff (
    id                  BIGSERIAL PRIMARY KEY,
    canonical_name      VARCHAR(128) NOT NULL UNIQUE,
    email               VARCHAR(128),
    home_office_id      BIGINT NOT NULL REFERENCES dim_office(id),
    primary_role_id     BIGINT NOT NULL REFERENCES dim_role(id),
    employment_status   VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
                        CHECK (employment_status IN ('ACTIVE','LEFT','PROBATION')),
    departure_date      DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_staff_updated BEFORE UPDATE ON ref_staff
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON COLUMN ref_staff.home_office_id IS 'Default office assignment; not used in calc directly. Calc uses case office × slot role.';
COMMENT ON COLUMN ref_staff.departure_date IS 'When set, triggers D1.R23 6-month settlement.';

-- 2.2 ref_staff_alias ---------------------------------------------------------
CREATE TABLE ref_staff_alias (
    id              BIGSERIAL PRIMARY KEY,
    staff_id        BIGINT NOT NULL REFERENCES ref_staff(id),
    alias           VARCHAR(128) NOT NULL UNIQUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.3 ref_staff_target --------------------------------------------------------
CREATE TABLE ref_staff_target (
    id                  BIGSERIAL PRIMARY KEY,
    staff_id            BIGINT  NOT NULL REFERENCES ref_staff(id),
    role_id             BIGINT  NOT NULL REFERENCES dim_role(id),
    office_id           BIGINT  NOT NULL REFERENCES dim_office(id),
    year                INTEGER NOT NULL CHECK (year BETWEEN 2020 AND 2099),
    month               INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    target              INTEGER NOT NULL CHECK (target >= 0),
    co_sub_subscheme    VARCHAR(32)
                        CHECK (co_sub_subscheme IN ('ENROL_ONLY_VISA_ONLY','ENROL_PLUS_VISA') OR co_sub_subscheme IS NULL),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (staff_id, role_id, office_id, year, month)
);
CREATE TRIGGER trg_ref_staff_target_updated BEFORE UPDATE ON ref_staff_target
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE INDEX idx_ref_staff_target_lookup ON ref_staff_target(staff_id, year, month);


-- =============================================================================
-- SECTION 3 — INSTITUTIONS AND PARTNERS
-- =============================================================================

-- 3.1 ref_priority_partner ----------------------------------------------------
CREATE TABLE ref_priority_partner (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    country_id      BIGINT NOT NULL REFERENCES dim_country(id),
    is_aggregate    BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_priority_partner_updated BEFORE UPDATE ON ref_priority_partner
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON COLUMN ref_priority_partner.is_aggregate IS 'TRUE for bucket rows like "Other Navitas Colleges (AU)" that group multiple institutions.';

-- 3.2 ref_priority_target -----------------------------------------------------
CREATE TABLE ref_priority_target (
    id                      BIGSERIAL PRIMARY KEY,
    priority_partner_id     BIGINT  NOT NULL REFERENCES ref_priority_partner(id),
    year                    INTEGER NOT NULL CHECK (year BETWEEN 2020 AND 2099),
    total_target            INTEGER NOT NULL CHECK (total_target >= 0),
    direct_target           INTEGER NOT NULL CHECK (direct_target >= 0),
    sub_target              INTEGER NOT NULL CHECK (sub_target >= 0),
    bonus_pct               DECIMAL(5,4) NOT NULL CHECK (bonus_pct BETWEEN 0 AND 1),
    prior_year_owing        INTEGER DEFAULT 0,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (priority_partner_id, year)
);
CREATE TRIGGER trg_ref_priority_target_updated BEFORE UPDATE ON ref_priority_target
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 3.3 ref_partner -------------------------------------------------------------
CREATE TABLE ref_partner (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    classification  VARCHAR(16) NOT NULL CHECK (classification IN ('MASTER_AGENT','GROUP')),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_partner_updated BEFORE UPDATE ON ref_partner
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON TABLE ref_partner IS 'Master Agents and Groups — out-system referring entities. Distinct from institutions.';

-- 3.4 ref_partner_alias -------------------------------------------------------
CREATE TABLE ref_partner_alias (
    id              BIGSERIAL PRIMARY KEY,
    partner_id      BIGINT NOT NULL REFERENCES ref_partner(id),
    alias           VARCHAR(255) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.4a ref_sub_agent ----------------------------------------------------------
-- External partners who refer cases to StudyLink for CO_SUB processing.
-- Informational only — used by finance for accounts-payable reconciliation.
-- Distinct from ref_partner (which holds Master Agents and Groups).
CREATE TABLE ref_sub_agent (
    id                  BIGSERIAL PRIMARY KEY,
    canonical_name      VARCHAR(128) NOT NULL UNIQUE,
    country_id          BIGINT REFERENCES dim_country(id),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    verification_status VARCHAR(16) NOT NULL DEFAULT 'VERIFIED'
                        CHECK (verification_status IN ('VERIFIED','UNVERIFIED','MERGED')),
    merged_into_id      BIGINT REFERENCES ref_sub_agent(id),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_sub_agent_updated BEFORE UPDATE ON ref_sub_agent
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 3.4b ref_sub_agent_alias ----------------------------------------------------
CREATE TABLE ref_sub_agent_alias (
    id              BIGSERIAL PRIMARY KEY,
    sub_agent_id    BIGINT NOT NULL REFERENCES ref_sub_agent(id),
    alias           VARCHAR(128) NOT NULL UNIQUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.5 ref_institution ---------------------------------------------------------
CREATE TABLE ref_institution (
    id                              BIGSERIAL PRIMARY KEY,
    canonical_name                  VARCHAR(255) NOT NULL UNIQUE,
    country_id                      BIGINT REFERENCES dim_country(id),
    classification                  VARCHAR(32) NOT NULL CHECK (classification IN (
                                        'IN_SYSTEM_REGULAR',
                                        'IN_SYSTEM_PRIORITY',
                                        'OUT_SYSTEM_MASTER_AGENT',
                                        'OUT_SYSTEM_GROUP',
                                        'UNVERIFIED'
                                    )),
    priority_partner_id             BIGINT REFERENCES ref_priority_partner(id),
    aggregate_priority_partner_id   BIGINT REFERENCES ref_priority_partner(id),
    verification_status             VARCHAR(16) NOT NULL DEFAULT 'VERIFIED'
                                    CHECK (verification_status IN ('VERIFIED','UNVERIFIED','MERGED')),
    merged_into_id                  BIGINT REFERENCES ref_institution(id),
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 1:1 priority link only valid when classification IN_SYSTEM_PRIORITY
    CHECK (
        (classification = 'IN_SYSTEM_PRIORITY' AND priority_partner_id IS NOT NULL)
        OR (classification != 'IN_SYSTEM_PRIORITY' AND priority_partner_id IS NULL)
    )
);
CREATE TRIGGER trg_ref_institution_updated BEFORE UPDATE ON ref_institution
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE INDEX idx_ref_institution_classification ON ref_institution(classification);
CREATE INDEX idx_ref_institution_aggregate ON ref_institution(aggregate_priority_partner_id)
    WHERE aggregate_priority_partner_id IS NOT NULL;
COMMENT ON COLUMN ref_institution.priority_partner_id IS '1:1 link for individually-listed priority partners (Monash, ACU).';
COMMENT ON COLUMN ref_institution.aggregate_priority_partner_id IS 'Roll-up link: Eynesbury → Other Navitas Colleges (AU). Both Group classification and aggregate priority can apply.';
COMMENT ON COLUMN ref_institution.verification_status IS 'Data-quality flag, decoupled from classification. UNVERIFIED institutions auto-created during case entry await admin review.';

-- 3.6 ref_institution_alias ---------------------------------------------------
CREATE TABLE ref_institution_alias (
    id              BIGSERIAL PRIMARY KEY,
    institution_id  BIGINT NOT NULL REFERENCES ref_institution(id),
    alias           VARCHAR(255) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.7 ref_partner_institution -------------------------------------------------
CREATE TABLE ref_partner_institution (
    id                  BIGSERIAL PRIMARY KEY,
    partner_id          BIGINT NOT NULL REFERENCES ref_partner(id),
    institution_id      BIGINT NOT NULL REFERENCES ref_institution(id),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partner_id, institution_id)
);
COMMENT ON TABLE ref_partner_institution IS 'Many-to-many junction. Sparse for Master Agents (huge unmaintained rosters); denser for Groups.';


-- =============================================================================
-- SECTION 4 — CALCULATION CONFIGURATION
-- =============================================================================

-- 4.1 ref_status_split --------------------------------------------------------
CREATE TABLE ref_status_split (
    id                          BIGSERIAL PRIMARY KEY,
    status                      VARCHAR(64)   NOT NULL UNIQUE,
    counts_as_enrolled          BOOLEAN       NOT NULL DEFAULT FALSE,
    split_couns_pct             DECIMAL(4,3)  NOT NULL DEFAULT 0,
    split_co_dir_pct            DECIMAL(4,3)  NOT NULL DEFAULT 0,
    split_co_sub_pct            DECIMAL(4,3)  NOT NULL DEFAULT 0,
    is_carry_over               BOOLEAN       NOT NULL DEFAULT FALSE,
    is_current_enrolled         BOOLEAN       NOT NULL DEFAULT FALSE,
    is_zero_bonus               BOOLEAN       NOT NULL DEFAULT FALSE,
    fees_paid_non_enrolled      BOOLEAN       NOT NULL DEFAULT FALSE,
    is_visa_granted             BOOLEAN       NOT NULL DEFAULT FALSE,
    deduplication_rank          INTEGER       NOT NULL DEFAULT 0,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_status_split_updated BEFORE UPDATE ON ref_status_split
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 4.2 ref_client_weight -------------------------------------------------------
CREATE TABLE ref_client_weight (
    id                              BIGSERIAL PRIMARY KEY,
    client_type_code                VARCHAR(32)  NOT NULL UNIQUE,
    weight_in_system                DECIMAL(4,3) NOT NULL DEFAULT 0,
    weight_sub_agent                DECIMAL(4,3) NOT NULL DEFAULT 0,
    weight_master_agent             DECIMAL(4,3) NOT NULL DEFAULT 0,
    weight_out_system               DECIMAL(4,3) NOT NULL DEFAULT 0,
    weight_out_system_usa_28m       DECIMAL(4,3) NOT NULL DEFAULT 0,
    notes                           TEXT,
    created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_client_weight_updated BEFORE UPDATE ON ref_client_weight
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 4.3 ref_client_type_alias ---------------------------------------------------
CREATE TABLE ref_client_type_alias (
    id                  BIGSERIAL PRIMARY KEY,
    client_type_code    VARCHAR(32)  NOT NULL,
    alias               VARCHAR(128) NOT NULL UNIQUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 4.4 ref_rate ----------------------------------------------------------------
CREATE TABLE ref_rate (
    id                  BIGSERIAL PRIMARY KEY,
    office_id           BIGINT  NOT NULL REFERENCES dim_office(id),
    role_id             BIGINT  NOT NULL REFERENCES dim_role(id),
    co_sub_subscheme    VARCHAR(32)
                        CHECK (co_sub_subscheme IN ('ENROL_ONLY_VISA_ONLY','ENROL_PLUS_VISA') OR co_sub_subscheme IS NULL),
    country_bucket      VARCHAR(16) NOT NULL
                        CHECK (country_bucket IN ('TARGET','FLAT','VN_RMIT','VN_BUV','VN_OTHER','SUMMER')),
    tier                VARCHAR(16) NOT NULL
                        CHECK (tier IN ('OUT_SYSTEM','VISA_ONLY','UNDER','MEET_HIGH','MEET_LOW','MEET','OVER','FLAT')),
    amount              INTEGER     NOT NULL,
    effective_from      DATE        NOT NULL,
    effective_to        DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (office_id, role_id, co_sub_subscheme, country_bucket, tier, effective_from)
);
CREATE TRIGGER trg_ref_rate_updated BEFORE UPDATE ON ref_rate
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE INDEX idx_ref_rate_lookup ON ref_rate(office_id, role_id, country_bucket, tier);

-- 4.5 ref_calculation_param ---------------------------------------------------
CREATE TABLE ref_calculation_param (
    id              BIGSERIAL PRIMARY KEY,
    param_code      VARCHAR(64) NOT NULL,
    value_numeric   DECIMAL(18,4),
    value_text      TEXT,
    effective_from  DATE NOT NULL,
    effective_to    DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (param_code, effective_from)
);
CREATE TRIGGER trg_ref_calculation_param_updated BEFORE UPDATE ON ref_calculation_param
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON TABLE ref_calculation_param IS 'Scalar parameters: INCENTIVE_THRESHOLD, PRESALES_FLAT_FEE, LOVELY_COFFEE_REFERRAL, etc.';

-- 4.6 ref_service_fee ---------------------------------------------------------
CREATE TABLE ref_service_fee (
    id                                  BIGSERIAL PRIMARY KEY,
    service_code                        VARCHAR(64) NOT NULL,
    category                            VARCHAR(16) NOT NULL
                                        CHECK (category IN ('PACKAGE','ADDON','SERVICE_FEE','CONTRACT')),
    country_id                          BIGINT REFERENCES dim_country(id),
    fee_amount                          INTEGER NOT NULL DEFAULT 0,
    counsellor_signing_bonus            INTEGER NOT NULL DEFAULT 0,
    co_signing_bonus                    INTEGER NOT NULL DEFAULT 0,
    counsellor_deductible_on_refusal    BOOLEAN NOT NULL DEFAULT FALSE,
    refund_on_visa_refused              INTEGER NOT NULL DEFAULT 0,
    refund_on_cancel                    INTEGER NOT NULL DEFAULT 0,
    description                         TEXT,
    notes                               TEXT,
    effective_from                      DATE NOT NULL,
    effective_to                        DATE,
    is_active                           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (service_code, effective_from)
);
CREATE TRIGGER trg_ref_service_fee_updated BEFORE UPDATE ON ref_service_fee
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 4.7 ref_service_fee_alias ---------------------------------------------------
CREATE TABLE ref_service_fee_alias (
    id                  BIGSERIAL PRIMARY KEY,
    service_fee_id      BIGINT NOT NULL REFERENCES ref_service_fee(id),
    alias               VARCHAR(128) NOT NULL UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- SECTION 5 — RULES MISSING FROM BOTH ENGINES
-- =============================================================================

-- 5.1 ref_local_enrolment_bonus -----------------------------------------------
CREATE TABLE ref_local_enrolment_bonus (
    id                          BIGSERIAL PRIMARY KEY,
    country_id                  BIGINT  NOT NULL REFERENCES dim_country(id),
    flat_total_amount           INTEGER NOT NULL,
    couns_dir_alone_pct         DECIMAL(4,3) NOT NULL DEFAULT 1.000,
    couns_dir_with_co_pct       DECIMAL(4,3) NOT NULL DEFAULT 0.500,
    co_pct_when_paired          DECIMAL(4,3) NOT NULL DEFAULT 0.500,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (country_id, effective_from)
);
CREATE TRIGGER trg_ref_local_enrolment_bonus_updated BEFORE UPDATE ON ref_local_enrolment_bonus
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 5.2 ref_contract_target_tier ------------------------------------------------
CREATE TABLE ref_contract_target_tier (
    id                              BIGSERIAL PRIMARY KEY,
    office_id                       BIGINT  NOT NULL REFERENCES dim_office(id),
    target_min                      INTEGER NOT NULL,
    target_max                      INTEGER,
    excess_per_contract_amount      INTEGER NOT NULL,
    consecutive_3mo_per_contract    INTEGER NOT NULL DEFAULT 0,
    premium_min_target              INTEGER,
    premium_per_contract_amount     INTEGER,
    in_system_min_pct               DECIMAL(4,3),
    visa_pass_min_pct               DECIMAL(4,3),
    effective_from                  DATE NOT NULL,
    effective_to                    DATE,
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_contract_target_tier_updated BEFORE UPDATE ON ref_contract_target_tier
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 5.3 ref_contract_package_eligibility ----------------------------------------
CREATE TABLE ref_contract_package_eligibility (
    id                          BIGSERIAL PRIMARY KEY,
    service_fee_id              BIGINT  NOT NULL REFERENCES ref_service_fee(id),
    excess_low_target_amount    INTEGER NOT NULL,
    excess_high_target_amount   INTEGER NOT NULL,
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5.4 ref_team_excess_bonus ---------------------------------------------------
CREATE TABLE ref_team_excess_bonus (
    id                          BIGSERIAL PRIMARY KEY,
    bonus_code                  VARCHAR(32) NOT NULL UNIQUE,
    description                 TEXT,
    immediate_amount            INTEGER NOT NULL,
    confirmed_amount            INTEGER NOT NULL,
    target_threshold            INTEGER,
    team_fund_retention_pct     DECIMAL(4,3) NOT NULL DEFAULT 0,
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5.5 ref_departure_rule ------------------------------------------------------
CREATE TABLE ref_departure_rule (
    id                          BIGSERIAL PRIMARY KEY,
    rule_code                   VARCHAR(48) NOT NULL UNIQUE,
    files_count_min             INTEGER NOT NULL,
    files_count_max             INTEGER NOT NULL,
    monthly_allowance           INTEGER NOT NULL,
    duration_months             INTEGER NOT NULL DEFAULT 6,
    case_stage                  VARCHAR(32) NOT NULL,
    settlement_delay_months     INTEGER NOT NULL DEFAULT 6,
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5.6 ref_complaint_deduction -------------------------------------------------
CREATE TABLE ref_complaint_deduction (
    id                          BIGSERIAL PRIMARY KEY,
    rule_code                   VARCHAR(48) NOT NULL UNIQUE,
    description                 TEXT,
    deduction_scope             VARCHAR(32) NOT NULL
                                CHECK (deduction_scope IN ('WHOLE_MONTH','UP_TO_DATE','POST_DEPARTURE','UP_TO_REFUSAL','ALL_BONUS')),
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- SECTION 6 — TRANSACTIONAL
-- =============================================================================

-- 6.1 tx_run ------------------------------------------------------------------
CREATE TABLE tx_run (
    id                  BIGSERIAL PRIMARY KEY,
    run_year            INTEGER NOT NULL,
    run_month           INTEGER NOT NULL CHECK (run_month BETWEEN 1 AND 12),
    triggered_by        VARCHAR(64),
    trigger_type        VARCHAR(32)
                        CHECK (trigger_type IN ('INITIAL','RECALC','REVIEW_ADJUSTMENT')),
    case_count          INTEGER NOT NULL DEFAULT 0,
    bonus_payment_count INTEGER NOT NULL DEFAULT 0,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              VARCHAR(16) NOT NULL DEFAULT 'IN_PROGRESS'
                        CHECK (status IN ('IN_PROGRESS','COMPLETE','FAILED','CANCELLED')),
    notes               TEXT
);

-- 6.2 tx_case -----------------------------------------------------------------
CREATE TABLE tx_case (
    id                          BIGSERIAL PRIMARY KEY,
    contract_id                 VARCHAR(32) NOT NULL,
    student_id                  VARCHAR(32),
    student_name                VARCHAR(128) NOT NULL,
    contract_signed_date        DATE,
    course_start_date           DATE,
    visa_received_date          DATE,
    course_status               VARCHAR(32),

    case_office_id              BIGINT NOT NULL REFERENCES dim_office(id),
    country_id                  BIGINT NOT NULL REFERENCES dim_country(id),
    institution_id              BIGINT REFERENCES ref_institution(id),
    institution_text_raw        VARCHAR(255),
    referring_partner_id        BIGINT REFERENCES ref_partner(id),
    referring_sub_agent_id      BIGINT REFERENCES ref_sub_agent(id),
    referring_agent_text_raw    VARCHAR(255),
    client_type_code            VARCHAR(32),
    application_status          VARCHAR(64),
    service_fee_id              BIGINT REFERENCES ref_service_fee(id),
    incentive_amount            INTEGER NOT NULL DEFAULT 0,

    -- Four nullable slots
    counsellor_staff_id         BIGINT REFERENCES ref_staff(id),
    counsellor_role_id          BIGINT REFERENCES dim_role(id),
    case_officer_staff_id       BIGINT REFERENCES ref_staff(id),
    case_officer_role_id        BIGINT REFERENCES dim_role(id),
    presales_staff_id           BIGINT REFERENCES ref_staff(id),
    presales_role_id            BIGINT REFERENCES dim_role(id),
    vp_staff_id                 BIGINT REFERENCES ref_staff(id),
    vp_role_id                  BIGINT REFERENCES dim_role(id),

    -- Pre-sales rule B (case-level share % of Counsellor's total bonus)
    presales_share_pct          DECIMAL(4,3) CHECK (presales_share_pct BETWEEN 0 AND 1),

    -- Operator fields
    deferral_code               VARCHAR(32) NOT NULL DEFAULT 'NONE'
                                CHECK (deferral_code IN ('NONE','FEE_TRANSFERRED','DEFERRED','FEE_WAIVED','NO_SERVICE')),
    handover_flag               BOOLEAN NOT NULL DEFAULT FALSE,
    target_owner_staff_id       BIGINT REFERENCES ref_staff(id),
    case_transition             VARCHAR(32),
    prior_month_rate            INTEGER,
    notes                       TEXT,

    -- Run metadata
    run_id                      BIGINT REFERENCES tx_run(id),
    run_year                    INTEGER NOT NULL,
    run_month                   INTEGER NOT NULL CHECK (run_month BETWEEN 1 AND 12),

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A case cannot be both Master-Agent-routed AND sub-agent-referred.
    -- Both NULL is fine (direct in-system case, no external partner involved).
    CONSTRAINT chk_tx_case_partner_xor_subagent
        CHECK (referring_partner_id IS NULL OR referring_sub_agent_id IS NULL),

    UNIQUE (contract_id, run_year, run_month)
);
CREATE TRIGGER trg_tx_case_updated BEFORE UPDATE ON tx_case
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
CREATE INDEX idx_tx_case_run         ON tx_case(run_year, run_month);
CREATE INDEX idx_tx_case_couns       ON tx_case(counsellor_staff_id);
CREATE INDEX idx_tx_case_co          ON tx_case(case_officer_staff_id);
CREATE INDEX idx_tx_case_presales    ON tx_case(presales_staff_id);
CREATE INDEX idx_tx_case_vp          ON tx_case(vp_staff_id);
CREATE INDEX idx_tx_case_office      ON tx_case(case_office_id);

-- 6.3 tx_bonus_payment --------------------------------------------------------
CREATE TABLE tx_bonus_payment (
    id                          BIGSERIAL PRIMARY KEY,
    case_id                     BIGINT NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    slot                        VARCHAR(16) NOT NULL
                                CHECK (slot IN ('COUNSELLOR','CASE_OFFICER','PRESALES','VP')),
    staff_id                    BIGINT NOT NULL REFERENCES ref_staff(id),
    role_id                     BIGINT NOT NULL REFERENCES dim_role(id),
    office_id                   BIGINT NOT NULL REFERENCES dim_office(id),

    tier                        VARCHAR(16),
    target                      INTEGER,
    actual_enrolled             INTEGER,
    base_rate                   INTEGER NOT NULL DEFAULT 0,
    split_pct                   DECIMAL(4,3) NOT NULL DEFAULT 1.0,
    tier_bonus                  INTEGER NOT NULL DEFAULT 0,
    package_bonus               INTEGER NOT NULL DEFAULT 0,
    addon_bonus                 INTEGER NOT NULL DEFAULT 0,
    priority_bonus              INTEGER NOT NULL DEFAULT 0,
    presales_share_taken        INTEGER NOT NULL DEFAULT 0,
    flat_local_enrolment_bonus  INTEGER NOT NULL DEFAULT 0,
    advance_offset              INTEGER NOT NULL DEFAULT 0,
    gross_bonus                 INTEGER NOT NULL DEFAULT 0,
    net_payable                 INTEGER NOT NULL DEFAULT 0,

    calc_notes                  TEXT,
    audit_json                  JSONB,

    run_id                      BIGINT REFERENCES tx_run(id),
    run_year                    INTEGER NOT NULL,
    run_month                   INTEGER NOT NULL,
    calculated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, slot, run_year, run_month)
);
CREATE INDEX idx_tx_bonus_staff_run ON tx_bonus_payment(staff_id, run_year, run_month);
CREATE INDEX idx_tx_bonus_case      ON tx_bonus_payment(case_id);
CREATE INDEX idx_tx_bonus_office    ON tx_bonus_payment(office_id);

-- 6.4 tx_team_excess_period ---------------------------------------------------
CREATE TABLE tx_team_excess_period (
    id                  BIGSERIAL PRIMARY KEY,
    bonus_code          VARCHAR(32) NOT NULL,
    run_id              BIGINT REFERENCES tx_run(id),
    run_year            INTEGER NOT NULL,
    run_month           INTEGER NOT NULL,
    team_total_target   INTEGER NOT NULL,
    team_actual_enrolled INTEGER NOT NULL,
    immediate_amount    INTEGER NOT NULL DEFAULT 0,
    confirmed_amount    INTEGER NOT NULL DEFAULT 0,
    team_fund_retained  INTEGER NOT NULL DEFAULT 0,
    distributable       INTEGER NOT NULL DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6.5 tx_team_excess_distribution ---------------------------------------------
CREATE TABLE tx_team_excess_distribution (
    id                          BIGSERIAL PRIMARY KEY,
    team_excess_period_id       BIGINT NOT NULL REFERENCES tx_team_excess_period(id) ON DELETE CASCADE,
    staff_id                    BIGINT NOT NULL REFERENCES ref_staff(id),
    file_contribution_count     INTEGER NOT NULL,
    distribution_amount         INTEGER NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- SECTION 7 — AUDIT
-- =============================================================================

-- 7.1 tx_review_log -----------------------------------------------------------
CREATE TABLE tx_review_log (
    id                  BIGSERIAL PRIMARY KEY,
    bonus_payment_id    BIGINT NOT NULL REFERENCES tx_bonus_payment(id) ON DELETE CASCADE,
    reviewer_staff_id   BIGINT NOT NULL REFERENCES ref_staff(id),
    review_action       VARCHAR(32) NOT NULL
                        CHECK (review_action IN ('APPROVED','ADJUSTED','REJECTED','COMMENTED')),
    field_changed       VARCHAR(64),
    old_value           TEXT,
    new_value           TEXT,
    review_notes        TEXT,
    reviewed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_tx_review_log_payment ON tx_review_log(bonus_payment_id);

-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
