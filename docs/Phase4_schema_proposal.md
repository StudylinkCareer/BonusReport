# Phase 4: Schema Proposal — StudyLink Bonus Engine

**Status:** PROPOSAL FOR REVIEW. No tables created. No data inserted.

**Stack:** PostgreSQL 15+ on Railway. SQL given as `CREATE TABLE` DDL with PostgreSQL syntax. Designed for migration via Alembic.

**Naming convention:**
- `ref_*` tables hold reference/configuration data (rates, classifications, priority partners, etc.)
- `tx_*` tables hold transactional data (cases, bonus calculations, audit)
- `dim_*` tables hold dimensional data (offices, roles, etc.)
- All primary keys are `id BIGSERIAL`. All tables have `created_at` and `updated_at` audit columns.
- Effective-dated tables use `effective_from DATE NOT NULL` and `effective_to DATE` (NULL = currently in effect). New rates/rules are INSERTs with new effective dates.

**Review approach:** Read top-to-bottom. Each table has its purpose, then DDL, then rationale notes. Push back where you disagree; nothing here is built yet.

---

## Section 1 — Core Dimensional Tables

These define the *vocabulary* of the system. Small, slow-changing, drive everything else.

### 1.1 `dim_office`

**Purpose:** The four current offices (HCM, HN, DN, MEL) plus future expansion (HK).

```sql
CREATE TABLE dim_office (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(8)  NOT NULL UNIQUE,    -- 'HCM','HN','DN','MEL','HK'
    name            VARCHAR(64) NOT NULL,           -- 'Ho Chi Minh City'
    country_code    VARCHAR(2)  NOT NULL,           -- 'VN','AU','HK'
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:** Code is the natural key referenced everywhere. Country_code anchors office to a country (matters for HK expansion — VN-domestic 1M rule applies for VN offices, future HK rule may differ).

### 1.2 `dim_role`

**Purpose:** The six roles. Drives bonus scheme selection.

```sql
CREATE TABLE dim_role (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(16) NOT NULL UNIQUE,    -- 'COUNS_DIR','CO_DIR','CO_SUB','PRESALES','VP'
    name            VARCHAR(64) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:** Six values today: COUNS_DIR, CO_DIR, CO_SUB, PRESALES, VP_DN, VP_MEL — wait. You said VP_DN and VP_MEL are different *because they have different bonus schemes*. Two ways to model this:

- **(A)** One `VP` role, scheme selection driven by office (case has office=DN → VP scheme = VP_DN scheme). Cleaner. Adding HK VP is just an office row.
- **(B)** Separate VP_DN and VP_MEL role codes. More explicit but requires a new role code per future office.

I lean **(A)** — VP is a single role conceptually, scheme variation is by office. The code list becomes: `COUNS_DIR`, `CO_DIR`, `CO_SUB`, `PRESALES`, `VP`. Five roles. Confirm?

### 1.3 `dim_role_office_allowed`

**Purpose:** Define which (role, office) combinations are valid. Per your earlier confirmation: HCM/HN/DN have all five roles; MEL has only VP; future HK same as MEL or all five.

```sql
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
```

**Rationale:** Validation table — when assigning a person to a slot, the (role, case_office) combo must exist here. Prevents nonsense like "CO_SUB at MEL" if MEL doesn't have a sub-agent operation. If you decide later MEL grows a sub-agent operation, you INSERT one row.

### 1.4 `dim_country`

**Purpose:** Canonical country codes for cases (where the student studies). Replaces the FLAT_RATE_COUNTRIES / WITH_TARGET_COUNTRIES sets in Python.

```sql
CREATE TABLE dim_country (
    id                  BIGSERIAL PRIMARY KEY,
    code                VARCHAR(2)  NOT NULL UNIQUE,   -- ISO-2: 'AU','CA','US','VN','TH'
    name                VARCHAR(64) NOT NULL,
    is_target_country   BOOLEAN     NOT NULL DEFAULT FALSE,  -- 14 with-target countries from D1.R2
    is_flat_country     BOOLEAN     NOT NULL DEFAULT FALSE,  -- TH/PH/MY: 2-out-target = 1-target
    is_domestic_for     BIGINT      REFERENCES dim_office(id), -- VN row points to VN offices; HK row would point to HK office
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:**
- `is_target_country` covers Doc 1 §I header: AU, CA, US, NZ, UK, SGP, IRL, CHE, FIN, NLD, DEU, FRA, MYS — actually wait, MYS is also flat-country. Need to reconcile this against Doc 6's 11-country list (AMBIG D6.R8). I'll INSERT both flag values per country in Phase 5; you confirm against current operations.
- `is_flat_country` covers Doc 1 §I.2 + Doc 6: TH, KR, MY, PH (the "no target / 2-out=1" countries).
- `is_domestic_for` enables the future HK rule: "Vietnam domestic" today is `dim_country.code='VN'` with `is_domestic_for = (VN office)`. HK domestic would be a new country row with `is_domestic_for = (HK office)`. The VN-1M flat rule in Section 4 reads this column.

### 1.5 `dim_country_alias`

```sql
CREATE TABLE dim_country_alias (
    id              BIGSERIAL PRIMARY KEY,
    country_id      BIGINT NOT NULL REFERENCES dim_country(id),
    alias           VARCHAR(128) NOT NULL,           -- 'Australia','Úc','AUS','AU'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
```

**Rationale:** CRM exports country in Vietnamese ("Úc", "Hàn Quốc") and English ("Australia", "Korea"). Alias resolves to canonical row.

---

## Section 2 — Staff and Targets

### 2.1 `ref_staff`

**Purpose:** Every person who can appear in a case slot. Home office + primary role are defaults at assignment time only.

```sql
CREATE TABLE ref_staff (
    id                  BIGSERIAL PRIMARY KEY,
    canonical_name      VARCHAR(128) NOT NULL UNIQUE,    -- 'Phạm Thị Lợi'
    email               VARCHAR(128),
    home_office_id      BIGINT NOT NULL REFERENCES dim_office(id),
    primary_role_id     BIGINT NOT NULL REFERENCES dim_role(id),
    employment_status   VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',  -- 'ACTIVE','LEFT','PROBATION'
    departure_date      DATE,                           -- triggers 6-month settlement (D1.R23)
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:**
- `home_office_id` + `primary_role_id`: defaults when assigning to a case slot, NOT used directly in calculation. Per your clarification: case office × slot role drives calc.
- `employment_status` + `departure_date`: needed for D1.R20-R23 departure rules (handover allowances, 6-month settlement period).
- Loi appears once here with primary_role=CO_SUB, home_office=DN. Her VP_DN role on certain cases is recorded at the case slot, not on her staff row.

### 2.2 `ref_staff_alias`

```sql
CREATE TABLE ref_staff_alias (
    id              BIGSERIAL PRIMARY KEY,
    staff_id        BIGINT NOT NULL REFERENCES ref_staff(id),
    alias           VARCHAR(128) NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
```

**Rationale:** "Loi", "Phạm Thị Lợi", "Pham Thi Loi", "Phạm Thị Lợi (DN)" all resolve to one staff_id.

### 2.3 `ref_staff_target`

**Purpose:** Per-staff per-month enrolment targets, year-bound. Replaces the hardcoded TARGETS_2024/2025 in Python.

```sql
CREATE TABLE ref_staff_target (
    id              BIGSERIAL PRIMARY KEY,
    staff_id        BIGINT  NOT NULL REFERENCES ref_staff(id),
    role_id         BIGINT  NOT NULL REFERENCES dim_role(id),
    office_id       BIGINT  NOT NULL REFERENCES dim_office(id),
    year            INTEGER NOT NULL CHECK (year BETWEEN 2020 AND 2099),
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    target          INTEGER NOT NULL CHECK (target >= 0),
    co_sub_subscheme VARCHAR(32),                   -- 'ENROL_ONLY_VISA_ONLY' or 'ENROL_PLUS_VISA' (NULL for non-CO_SUB roles)
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (staff_id, role_id, office_id, year, month)
);
```

**Rationale:**
- Granularity (staff, role, office, year, month) supports multi-office staff like Hoàng Yến (HCM target=6 + HN target=2 in Jan 2024 — two rows).
- `co_sub_subscheme`: per Phase 3 finding — CO_SUB has two rate sub-schemes from Doc 6 sheet 4. Nullable for non-CO_SUB roles. Trường An and Loi both = `ENROL_ONLY_VISA_ONLY`.
- A new year is INSERTs, not schema change.

---

## Section 3 — Institutions and Partners

This is the part you most recently revised. Locking in the 4-classification model.

### 3.1 `ref_priority_partner`

**Purpose:** Priority list entries. One row per priority *concept* (Monash, Other Navitas AU, etc.), not per physical institution. 38 rows from Doc 2 + 4-sheet aggregates.

```sql
CREATE TABLE ref_priority_partner (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,    -- 'Monash University', 'Other Navitas Colleges (AU)'
    country_id      BIGINT NOT NULL REFERENCES dim_country(id),
    is_aggregate    BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE for 'Other Navitas Colleges (AU)' bucket rows
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.2 `ref_priority_target`

**Purpose:** Year-bound annual commitments. Per your confirmation.

```sql
CREATE TABLE ref_priority_target (
    id                      BIGSERIAL PRIMARY KEY,
    priority_partner_id     BIGINT  NOT NULL REFERENCES ref_priority_partner(id),
    year                    INTEGER NOT NULL CHECK (year BETWEEN 2020 AND 2099),
    total_target            INTEGER NOT NULL CHECK (total_target >= 0),
    direct_target           INTEGER NOT NULL CHECK (direct_target >= 0),
    sub_target              INTEGER NOT NULL CHECK (sub_target >= 0),
    bonus_pct               DECIMAL(5,4) NOT NULL CHECK (bonus_pct BETWEEN 0 AND 1),  -- 0.30 = 30%
    prior_year_owing        INTEGER DEFAULT 0,       -- the "+ 2023 owing" portion in Doc 2 col 'YYYY total target'
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (priority_partner_id, year)
);
```

**Rationale:** Doc 2's "2024 commitment + 2023 owing" is split into `total_target` and `prior_year_owing` for transparency. The engine reads `total_target` for KPI checks. New year = INSERTs.

### 3.3 `ref_partner` (Master Agents and Groups)

**Purpose:** Out-system referring entities. Per your final clarification — Master Agent (weight 0.7) and Group (weight 1.0).

```sql
CREATE TABLE ref_partner (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,    -- 'Adventus', 'Navitas', 'INTO'
    classification  VARCHAR(16) NOT NULL CHECK (classification IN ('MASTER_AGENT','GROUP')),
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:** 27 rows from Doc 3 + future additions. Classification drives weight + rate sheet via code (not via columns on this table — calculation logic stays in code).

### 3.4 `ref_partner_alias`

```sql
CREATE TABLE ref_partner_alias (
    id              BIGSERIAL PRIMARY KEY,
    partner_id      BIGINT NOT NULL REFERENCES ref_partner(id),
    alias           VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
```

### 3.5 `ref_institution`

**Purpose:** Every school that appears in a case. Classification drives calc.

```sql
CREATE TABLE ref_institution (
    id                          BIGSERIAL PRIMARY KEY,
    canonical_name              VARCHAR(255) NOT NULL UNIQUE,
    country_id                  BIGINT REFERENCES dim_country(id),    -- nullable for UNVERIFIED
    classification              VARCHAR(32) NOT NULL CHECK (classification IN (
                                    'IN_SYSTEM_REGULAR',
                                    'IN_SYSTEM_PRIORITY',
                                    'OUT_SYSTEM_MASTER_AGENT',
                                    'OUT_SYSTEM_GROUP',
                                    'UNVERIFIED'
                                )),
    priority_partner_id         BIGINT REFERENCES ref_priority_partner(id),  -- set when classification = IN_SYSTEM_PRIORITY
    aggregate_priority_partner_id BIGINT REFERENCES ref_priority_partner(id), -- set when this institution rolls up to an aggregate (Eynesbury → 'Other Navitas AU')
    verification_status         VARCHAR(16) NOT NULL DEFAULT 'VERIFIED' CHECK (verification_status IN ('VERIFIED','UNVERIFIED','MERGED')),
    merged_into_id              BIGINT REFERENCES ref_institution(id),  -- if verification_status='MERGED', points to the surviving row
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (classification = 'IN_SYSTEM_PRIORITY' AND priority_partner_id IS NOT NULL) OR
        (classification != 'IN_SYSTEM_PRIORITY' AND priority_partner_id IS NULL)
    )
);
```

**Rationale:**
- `priority_partner_id`: 1:1 link for priority cases (Monash institution row → Monash priority row).
- `aggregate_priority_partner_id`: separate FK for the "Eynesbury rolls up to Other Navitas AU" case. Both the physical institution (Eynesbury, classification=IN_SYSTEM_PRIORITY, with `aggregate_priority_partner_id` set) AND the aggregate priority row exist. The engine reads `priority_partner_id` first, falls back to `aggregate_priority_partner_id` for priority bonus calc.
  - **Hmm, design question:** is Eynesbury IN_SYSTEM_PRIORITY (because it's part of an aggregate priority bucket) or IN_SYSTEM_REGULAR? I'd lean PRIORITY since the priority bonus does flow on those enrolments. Confirm tomorrow.
- `verification_status` + `merged_into_id`: the UNVERIFIED workflow you approved. New auto-created institutions start UNVERIFIED; admin merges duplicates by setting `merged_into_id` and status=MERGED, or promotes to VERIFIED.
- `classification = UNVERIFIED` AND `verification_status = UNVERIFIED` are decoupled — classification is calc-relevant, verification is data-quality-relevant. An institution can be `IN_SYSTEM_REGULAR` + `UNVERIFIED` (classified for calc but pending review).

### 3.6 `ref_institution_alias`

```sql
CREATE TABLE ref_institution_alias (
    id              BIGSERIAL PRIMARY KEY,
    institution_id  BIGINT NOT NULL REFERENCES ref_institution(id),
    alias           VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
```

### 3.7 `ref_partner_institution` (junction)

**Purpose:** Many-to-many partner ↔ institution. Sparse for Master Agents (per your point about huge unmaintained rosters), denser for Groups.

```sql
CREATE TABLE ref_partner_institution (
    id                  BIGSERIAL PRIMARY KEY,
    partner_id          BIGINT NOT NULL REFERENCES ref_partner(id),
    institution_id      BIGINT NOT NULL REFERENCES ref_institution(id),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partner_id, institution_id)
);
```

**Rationale:** When a case has institution = Eynesbury and arrives via Navitas, both relationships are recorded. Eynesbury exists in `ref_institution` once, Navitas exists in `ref_partner` once, junction row links them. Admin can populate this opportunistically — no obligation to maintain a full Adventus roster.

---

## Section 4 — Calculation Configuration

### 4.1 `ref_status_split`

**Purpose:** Application status rules from Doc 4 sheet 3 + flag extensions.

```sql
CREATE TABLE ref_status_split (
    id                          BIGSERIAL PRIMARY KEY,
    status                      VARCHAR(64) NOT NULL UNIQUE,    -- 'Closed - Visa granted (plus enrolled)'
    counts_as_enrolled          BOOLEAN NOT NULL DEFAULT FALSE,
    split_couns_pct             DECIMAL(4,3) NOT NULL DEFAULT 0,  -- 1.000 = 100%
    split_co_dir_pct            DECIMAL(4,3) NOT NULL DEFAULT 0,
    split_co_sub_pct            DECIMAL(4,3) NOT NULL DEFAULT 0,
    is_carry_over               BOOLEAN NOT NULL DEFAULT FALSE,  -- pays remaining 50% from prior month
    is_current_enrolled         BOOLEAN NOT NULL DEFAULT FALSE,  -- 50% advance, balance pays later
    is_zero_bonus               BOOLEAN NOT NULL DEFAULT FALSE,  -- explicit zero
    fees_paid_non_enrolled      BOOLEAN NOT NULL DEFAULT FALSE,  -- triggers 400K rate IF fee retained per package refund policy
    is_visa_granted             BOOLEAN NOT NULL DEFAULT FALSE,
    deduplication_rank          INTEGER NOT NULL DEFAULT 0,      -- higher wins when same ContractID has multiple statuses
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:** Mirrors VBA's `05_STATUS_RULES` sheet structure exactly — proven model. 18 status rows from Doc 4 sheet 3 + Covid-era statuses (D4.R6 — currently unresolved AMBIG, will INSERT with `notes='AMBIG: confirm handling'`).

### 4.2 `ref_client_weight`

**Purpose:** 9 client types × 5 channel columns from Doc 4 sheet 1.

```sql
CREATE TABLE ref_client_weight (
    id                              BIGSERIAL PRIMARY KEY,
    client_type_code                VARCHAR(32) NOT NULL UNIQUE, -- 'DU_HOC_FULL','VIETNAM_DOMESTIC',etc.
    weight_in_system                DECIMAL(4,3) NOT NULL DEFAULT 0,  -- DIRECT/GROUP, scheme<>CO_SUB
    weight_sub_agent                DECIMAL(4,3) NOT NULL DEFAULT 0,  -- DIRECT, scheme=CO_SUB
    weight_master_agent             DECIMAL(4,3) NOT NULL DEFAULT 0,  -- MASTER_AGENT classification
    weight_out_system               DECIMAL(4,3) NOT NULL DEFAULT 0,  -- OUT_SYSTEM standard
    weight_out_system_usa_28m       DECIMAL(4,3) NOT NULL DEFAULT 0,  -- OUT_SYSTEM + country=US + service_fee>=28M
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.3 `ref_client_type_alias`

**Purpose:** CRM Vietnamese text → canonical client type code.

```sql
CREATE TABLE ref_client_type_alias (
    id                  BIGSERIAL PRIMARY KEY,
    client_type_code    VARCHAR(32) NOT NULL,         -- references ref_client_weight.client_type_code (logical FK)
    alias               VARCHAR(128) NOT NULL,        -- 'Du học (Ghi danh + visa)','Du hoc tai cho (Vietnam)'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
```

### 4.4 `ref_rate`

**Purpose:** Tier-based bonus rates by (office, role, scheme, country bucket, tier). The big one.

```sql
CREATE TABLE ref_rate (
    id                  BIGSERIAL PRIMARY KEY,
    office_id           BIGINT NOT NULL REFERENCES dim_office(id),
    role_id             BIGINT NOT NULL REFERENCES dim_role(id),
    co_sub_subscheme    VARCHAR(32),               -- 'ENROL_ONLY_VISA_ONLY','ENROL_PLUS_VISA' or NULL
    country_bucket      VARCHAR(32) NOT NULL,      -- 'TARGET','FLAT' (Thai/Korea/Malaysia/Phil),'VN_DOMESTIC','SUMMER'
    tier                VARCHAR(16) NOT NULL,      -- 'OUT_SYSTEM','VISA_ONLY','UNDER','MEET_HIGH','MEET_LOW','OVER'
    amount              INTEGER NOT NULL,          -- VND, integer
    effective_from      DATE NOT NULL,
    effective_to        DATE,                      -- NULL = current
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (office_id, role_id, co_sub_subscheme, country_bucket, tier, effective_from)
);
```

**Rationale:**
- Single rate table covers all of Doc 6's 3 sheets (HCM, HN/DN, Sub) and special fixed-rate cases. Adding rates is INSERTs.
- `effective_from`/`effective_to`: rate changes mid-year don't lose history.
- `country_bucket`: not the country itself — a classification (TARGET / FLAT / VN_DOMESTIC / SUMMER). A `country_bucket` lookup table could be added later if values proliferate.
- `co_sub_subscheme`: nullable for non-CO_SUB roles.
- Pulling current MEET_HIGH/MEET_LOW resolution into the table (instead of code) means the 5M incentive threshold logic stays in code, but the rates each tier maps to are configuration. Right separation.

### 4.5 `ref_calculation_param`

**Purpose:** Single-value scalar parameters with effective dates. Things like "incentive threshold = 5,000,000".

```sql
CREATE TABLE ref_calculation_param (
    id              BIGSERIAL PRIMARY KEY,
    param_code      VARCHAR(64) NOT NULL,    -- 'INCENTIVE_THRESHOLD','LOVELY_COFFEE_REFERRAL','PRESALES_FLAT_FEE'
    value_numeric   DECIMAL(18,4),
    value_text      TEXT,
    effective_from  DATE NOT NULL,
    effective_to    DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (param_code, effective_from)
);
```

**Rationale:** Holds the 5,000,000 threshold, the 200,000 pre-sales flat fee, the 1,000,000 VN-domestic flat, the 100,000 Lovely Coffee referral. Single home for "magic numbers" that would otherwise hide in code.

### 4.6 `ref_service_fee`

**Purpose:** Service packages and add-ons from Docs 7, 8, 10, 11, 12, 13. Mirrors VBA's `09_SERVICE_FEE_RATES`.

```sql
CREATE TABLE ref_service_fee (
    id                          BIGSERIAL PRIMARY KEY,
    service_code                VARCHAR(64) NOT NULL,           -- 'GOI_3_SUPERIOR_AP','SDS','GUARDIAN_AU_ADDON'
    category                    VARCHAR(16) NOT NULL CHECK (category IN ('PACKAGE','ADDON','SERVICE_FEE','CONTRACT')),
    country_id                  BIGINT REFERENCES dim_country(id),  -- nullable for cross-country addons
    counsellor_signing_bonus    INTEGER NOT NULL DEFAULT 0,
    co_signing_bonus            INTEGER NOT NULL DEFAULT 0,
    counsellor_deductible_on_refusal BOOLEAN NOT NULL DEFAULT FALSE, -- AP Gói 3/4 = TRUE; Gói 2 = FALSE
    refund_on_visa_refused      INTEGER NOT NULL DEFAULT 0,     -- amount refunded → fee NOT retained
    refund_on_cancel            INTEGER NOT NULL DEFAULT 0,
    description                 TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (service_code, effective_from)
);
```

**Rationale:**
- The Phase 3 finding "400K fees-paid rate fires only when fee is RETAINED" reads `refund_on_visa_refused` here. If refund = total package fee, fee not retained → 0 bonus. If refund < total, fee partially retained → 400K may fire.
- `counsellor_deductible_on_refusal`: Gói 2 signing bonus is non-deductible per D11.R3, Gói 3/4 signing bonuses deduct on visa-refused per D11.R4/R5.
- Effective-dated so SDS price changes (5.5M → 7M, D7.R10) don't lose history.

### 4.7 `ref_service_fee_alias`

```sql
CREATE TABLE ref_service_fee_alias (
    id                  BIGSERIAL PRIMARY KEY,
    service_fee_id      BIGINT NOT NULL REFERENCES ref_service_fee(id),
    alias               VARCHAR(128) NOT NULL,         -- 'Superior 6tr','Gói 3','Superior Package'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias)
);
```

---

## Section 5 — Bonus Rules That Currently Don't Exist in Either Engine

These cover Phase 2's "missing from both engines" gap.

### 5.1 `ref_local_enrolment_bonus`

**Purpose:** The flat-1M Vietnam-domestic rule (and future HK rule). Per your latest clarification.

```sql
CREATE TABLE ref_local_enrolment_bonus (
    id                          BIGSERIAL PRIMARY KEY,
    country_id                  BIGINT NOT NULL REFERENCES dim_country(id),
    flat_total_amount           INTEGER NOT NULL,                -- 1,000,000 for VN
    couns_dir_alone_pct         DECIMAL(4,3) NOT NULL DEFAULT 1.000,  -- if Couns_Dir alone, gets 100%
    couns_dir_with_co_pct       DECIMAL(4,3) NOT NULL DEFAULT 0.500,  -- 50/50 split when CO present
    co_pct_when_paired          DECIMAL(4,3) NOT NULL DEFAULT 0.500,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (country_id, effective_from)
);
```

**Rationale:** Configurable for HK expansion. VN row: country=VN, flat=1M, alone=1.0, paired=0.5/0.5. HK can have its own row with different mechanics later.

### 5.2 `ref_contract_target_tier`

**Purpose:** Doc 1 §II contract target bonus — entire secondary KPI scheme for Counsellors that's missing from both engines.

```sql
CREATE TABLE ref_contract_target_tier (
    id                              BIGSERIAL PRIMARY KEY,
    office_id                       BIGINT NOT NULL REFERENCES dim_office(id),
    target_min                      INTEGER NOT NULL,         -- e.g. 2 (rule applies when 2 ≤ target < 4)
    target_max                      INTEGER,                  -- NULL means open-ended
    excess_per_contract_amount      INTEGER NOT NULL,         -- 100,000 or 200,000 per excess contract
    consecutive_3mo_per_contract    INTEGER NOT NULL DEFAULT 0,  -- 200,000 for 3 consecutive months
    premium_min_target              INTEGER,                  -- premium tier kicks in at target ≥ 4
    premium_per_contract_amount     INTEGER,                  -- 2,200,000 for >10/mo or doubled-target contracts
    in_system_min_pct               DECIMAL(4,3),             -- 0.80 (D1.R33)
    visa_pass_min_pct               DECIMAL(4,3),             -- 0.75 (D1.R33)
    effective_from                  DATE NOT NULL,
    effective_to                    DATE,
    notes                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.3 `ref_contract_package_eligibility`

**Purpose:** Doc 1 §II.4(*) — eligible packages for the contract excess bonus. E.g., 6M/9M/20M for AU/NZ/UK/SGP; 7.5M Canada has special rate (80K/140K).

```sql
CREATE TABLE ref_contract_package_eligibility (
    id                          BIGSERIAL PRIMARY KEY,
    service_fee_id              BIGINT NOT NULL REFERENCES ref_service_fee(id),
    excess_low_target_amount    INTEGER NOT NULL,    -- 100,000 (or 80,000 for CA 7.5M)
    excess_high_target_amount   INTEGER NOT NULL,    -- 200,000 (or 140,000 for CA 7.5M)
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.4 `ref_team_excess_bonus`

**Purpose:** Doc 1 §I.7 + §II.3 team excess bonuses (10M+10M, 2M+1M, 3M+3M, 5M).

```sql
CREATE TABLE ref_team_excess_bonus (
    id                          BIGSERIAL PRIMARY KEY,
    bonus_code                  VARCHAR(32) NOT NULL UNIQUE,    -- 'NATIONAL_TEAM_ENROL','PAIR_ENROL_3PLUS','SUB_TEAM','COUNS_TEAM_CONTRACT'
    description                 TEXT,
    immediate_amount            INTEGER NOT NULL,
    confirmed_amount            INTEGER NOT NULL,                -- paid after Finance confirms 100% enrol
    target_threshold            INTEGER,                         -- e.g. 3 (pair must have ≥3 target)
    team_fund_retention_pct     DECIMAL(4,3) NOT NULL DEFAULT 0,  -- 0.20 = 20% retained for team fund
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.5 `ref_departure_rule`

**Purpose:** D1.R20-R23 departure handover allowances + 6-month settlement.

```sql
CREATE TABLE ref_departure_rule (
    id                          BIGSERIAL PRIMARY KEY,
    rule_code                   VARCHAR(32) NOT NULL UNIQUE,    -- 'PRELODGE_HANDOVER_5_OR_LESS', etc.
    files_count_min             INTEGER NOT NULL,
    files_count_max             INTEGER NOT NULL,
    monthly_allowance           INTEGER NOT NULL,                -- 500,000 / 1,000,000 / 1,500,000
    duration_months             INTEGER NOT NULL DEFAULT 6,
    case_stage                  VARCHAR(32) NOT NULL,            -- 'PRELODGE','POSTLODGE','POSTENROL'
    settlement_delay_months     INTEGER NOT NULL DEFAULT 6,      -- D1.R23
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.6 `ref_complaint_deduction`

**Purpose:** D1.R16-R19 complaint deduction rules.

```sql
CREATE TABLE ref_complaint_deduction (
    id                          BIGSERIAL PRIMARY KEY,
    rule_code                   VARCHAR(32) NOT NULL UNIQUE,
    description                 TEXT,
    deduction_scope             VARCHAR(32) NOT NULL,    -- 'WHOLE_MONTH','UP_TO_DATE','POST_DEPARTURE','UP_TO_REFUSAL'
    notes                       TEXT,
    effective_from              DATE NOT NULL,
    effective_to                DATE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Section 6 — Transactional (Cases and Bonus Output)

### 6.1 `tx_case`

**Purpose:** The case itself — the four-slot structure you confirmed. One row per case.

```sql
CREATE TABLE tx_case (
    id                          BIGSERIAL PRIMARY KEY,
    contract_id                 VARCHAR(32) NOT NULL,           -- 'SLC-13687'
    student_id                  VARCHAR(32),                    -- 'C-11752'
    student_name                VARCHAR(128) NOT NULL,
    contract_signed_date        DATE,
    course_start_date           DATE,
    visa_received_date          DATE,
    course_status               VARCHAR(32),

    -- Case attributes that drive calc routing
    case_office_id              BIGINT NOT NULL REFERENCES dim_office(id),  -- the office the case BELONGS TO
    country_id                  BIGINT NOT NULL REFERENCES dim_country(id), -- where the student studies
    institution_id              BIGINT REFERENCES ref_institution(id),
    institution_text_raw        VARCHAR(255),                   -- raw CRM text before alias resolution (audit)
    referring_partner_id        BIGINT REFERENCES ref_partner(id),  -- if out-system, who referred
    referring_agent_text_raw    VARCHAR(255),                   -- raw CRM 'Refer Source Agent' text
    client_type_code            VARCHAR(32),                    -- references ref_client_weight (logical FK)
    application_status          VARCHAR(64),                    -- references ref_status_split (logical FK)
    service_fee_id              BIGINT REFERENCES ref_service_fee(id),  -- the package on the case (Gói 3, etc.)
    incentive_amount            INTEGER NOT NULL DEFAULT 0,     -- col 18 — drives MEET_HIGH/MEET_LOW resolution

    -- Four slots (the heart of the model)
    counsellor_staff_id         BIGINT REFERENCES ref_staff(id),
    counsellor_role_id          BIGINT REFERENCES dim_role(id),
    case_officer_staff_id       BIGINT REFERENCES ref_staff(id),
    case_officer_role_id        BIGINT REFERENCES dim_role(id),
    presales_staff_id           BIGINT REFERENCES ref_staff(id),
    presales_role_id            BIGINT REFERENCES dim_role(id),
    vp_staff_id                 BIGINT REFERENCES ref_staff(id),
    vp_role_id                  BIGINT REFERENCES dim_role(id),

    -- Pre-sales rule B: case-level share of Counsellor bonus
    presales_share_pct          DECIMAL(4,3) CHECK (presales_share_pct BETWEEN 0 AND 1),

    -- Operator fields (mirrors VBA col 21-28)
    deferral_code               VARCHAR(32) NOT NULL DEFAULT 'NONE',
    handover_flag               BOOLEAN NOT NULL DEFAULT FALSE,
    target_owner_staff_id       BIGINT REFERENCES ref_staff(id), -- if handover, who owns the target
    case_transition             VARCHAR(32),                     -- carry-over flags etc.
    prior_month_rate            INTEGER,                         -- for carry-over cases
    notes                       TEXT,

    -- Run metadata
    run_year                    INTEGER NOT NULL,
    run_month                   INTEGER NOT NULL CHECK (run_month BETWEEN 1 AND 12),

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (contract_id, run_year, run_month)
);

CREATE INDEX idx_tx_case_run ON tx_case(run_year, run_month);
CREATE INDEX idx_tx_case_couns ON tx_case(counsellor_staff_id);
CREATE INDEX idx_tx_case_co ON tx_case(case_officer_staff_id);
CREATE INDEX idx_tx_case_presales ON tx_case(presales_staff_id);
CREATE INDEX idx_tx_case_vp ON tx_case(vp_staff_id);
```

**Rationale:**
- Four nullable slot pairs (staff_id + role_id). Role on the slot is essential because the same person can hold different roles on different cases (Loi as VP_DN on one, CO_SUB on another).
- `case_office_id` is the *case's* office, not any staff member's. Drives bonus rate sheet selection per slot.
- `institution_text_raw` and `referring_agent_text_raw`: audit columns preserving what CRM exported, separate from the resolved FKs. Useful for the UNVERIFIED workflow and for forensics when alias resolution fails.
- `presales_share_pct`: per your case-level decision.
- Indexes on each slot enable the review board's "show me my cases" query for any role.

### 6.2 `tx_bonus_payment`

**Purpose:** One row per (case, slot) — the calculation output. A case with all four slots filled produces four payment rows.

```sql
CREATE TABLE tx_bonus_payment (
    id                          BIGSERIAL PRIMARY KEY,
    case_id                     BIGINT NOT NULL REFERENCES tx_case(id),
    slot                        VARCHAR(16) NOT NULL CHECK (slot IN ('COUNSELLOR','CASE_OFFICER','PRESALES','VP')),
    staff_id                    BIGINT NOT NULL REFERENCES ref_staff(id),
    role_id                     BIGINT NOT NULL REFERENCES dim_role(id),
    office_id                   BIGINT NOT NULL REFERENCES dim_office(id),  -- the case's office (denormalized for query speed)

    -- Calculation breakdown (audit trail)
    tier                        VARCHAR(16),
    target                      INTEGER,
    actual_enrolled             INTEGER,
    base_rate                   INTEGER NOT NULL DEFAULT 0,
    split_pct                   DECIMAL(4,3) NOT NULL DEFAULT 1.0,
    tier_bonus                  INTEGER NOT NULL DEFAULT 0,    -- = base_rate × split_pct
    package_bonus               INTEGER NOT NULL DEFAULT 0,    -- Superior/Premium signing
    addon_bonus                 INTEGER NOT NULL DEFAULT 0,    -- Guardian AU
    priority_bonus              INTEGER NOT NULL DEFAULT 0,
    presales_share_taken        INTEGER NOT NULL DEFAULT 0,    -- positive on PRESALES row, negative on COUNSELLOR row
    flat_local_enrolment_bonus  INTEGER NOT NULL DEFAULT 0,    -- VN-domestic 1M flat
    advance_offset              INTEGER NOT NULL DEFAULT 0,    -- prior month advances
    gross_bonus                 INTEGER NOT NULL DEFAULT 0,    -- sum before offsets
    net_payable                 INTEGER NOT NULL DEFAULT 0,    -- after offsets

    calc_notes                  TEXT,
    audit_json                  JSONB,                          -- full calc trace for forensic review

    run_year                    INTEGER NOT NULL,
    run_month                   INTEGER NOT NULL,
    calculated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, slot, run_year, run_month)
);

CREATE INDEX idx_tx_bonus_staff_run ON tx_bonus_payment(staff_id, run_year, run_month);
CREATE INDEX idx_tx_bonus_case ON tx_bonus_payment(case_id);
```

**Rationale:**
- One row per slot, not per case → review board for any staff member just queries `WHERE staff_id = ? AND run_year = ? AND run_month = ?`. They see the same case from their own perspective. Right model for the review workflow you described.
- Decomposed bonus columns (tier_bonus / package_bonus / addon_bonus / priority_bonus / presales_share_taken / flat_local) → review board can show line-by-line breakdown. No mystery numbers.
- `audit_json`: full calculation trace as JSONB. Enables "why did I get this?" without forcing every intermediate to be its own column.
- `presales_share_taken` is signed: +N on the PRESALES row, -N on the COUNSELLOR row. Sum across slots for one case = net case bonus.

### 6.3 `tx_team_excess_period`

**Purpose:** Team excess bonuses are calculated at team-level, not case-level. Separate output table.

```sql
CREATE TABLE tx_team_excess_period (
    id                  BIGSERIAL PRIMARY KEY,
    bonus_code          VARCHAR(32) NOT NULL,        -- references ref_team_excess_bonus (logical FK)
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
```

### 6.4 `tx_team_excess_distribution`

**Purpose:** Distribution of team excess to individuals based on file contribution.

```sql
CREATE TABLE tx_team_excess_distribution (
    id                          BIGSERIAL PRIMARY KEY,
    team_excess_period_id       BIGINT NOT NULL REFERENCES tx_team_excess_period(id),
    staff_id                    BIGINT NOT NULL REFERENCES ref_staff(id),
    file_contribution_count     INTEGER NOT NULL,
    distribution_amount         INTEGER NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Section 7 — Audit and Operations

### 7.1 `tx_run`

**Purpose:** Each engine run is a row. Reproducibility, debugging, "what reference data was active at calc time?"

```sql
CREATE TABLE tx_run (
    id                  BIGSERIAL PRIMARY KEY,
    run_year            INTEGER NOT NULL,
    run_month           INTEGER NOT NULL,
    triggered_by        VARCHAR(64),
    trigger_type        VARCHAR(32),                 -- 'INITIAL','RECALC','REVIEW_ADJUSTMENT'
    case_count          INTEGER NOT NULL DEFAULT 0,
    bonus_payment_count INTEGER NOT NULL DEFAULT 0,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              VARCHAR(16) NOT NULL DEFAULT 'IN_PROGRESS',
    notes               TEXT
);
```

### 7.2 `tx_review_log`

**Purpose:** Five-eyes review — track who reviewed what and any adjustments.

```sql
CREATE TABLE tx_review_log (
    id                  BIGSERIAL PRIMARY KEY,
    bonus_payment_id    BIGINT NOT NULL REFERENCES tx_bonus_payment(id),
    reviewer_staff_id   BIGINT NOT NULL REFERENCES ref_staff(id),
    review_action       VARCHAR(32) NOT NULL,        -- 'APPROVED','ADJUSTED','REJECTED','COMMENTED'
    field_changed       VARCHAR(64),                 -- if adjusted, which field
    old_value           TEXT,
    new_value           TEXT,
    review_notes        TEXT,
    reviewed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Decisions you need to confirm before Phase 5 INSERTs

These are points where I made an interpretation. Push back where wrong:

1. **`dim_role.code` values:** 5 codes (`COUNS_DIR`, `CO_DIR`, `CO_SUB`, `PRESALES`, `VP`) with VP scheme variation driven by office, OR 6 codes with explicit `VP_DN` / `VP_MEL` separation? I lean 5.

2. **Eynesbury and other aggregate-bucket institutions:** Classification = `IN_SYSTEM_PRIORITY` (since priority bonus flows on enrolments) or `IN_SYSTEM_REGULAR` (since they're not individually targeted)? I lean PRIORITY.

3. **`co_sub_subscheme` values:** I've assumed two sub-schemes from Doc 6: `ENROL_ONLY_VISA_ONLY` and `ENROL_PLUS_VISA`. Confirm naming and that there are only these two.

4. **`country_bucket` values in ref_rate:** I've assumed 4 buckets — TARGET, FLAT, VN_DOMESTIC, SUMMER. Doc 6 also has special rates for RMIT_VN, BUV_VN, Other_VN as separate rows. Should these be sub-buckets of VN_DOMESTIC, or their own buckets? I'd model them as separate buckets (`VN_RMIT`, `VN_BUV`, `VN_OTHER`) for clean rate lookup. Confirm?

5. **Pre-sales scheme is undefined per your earlier statement.** Does the PRESALES role have a `ref_rate` row at all, or does pre-sales bonus come exclusively from (a) the 200K flat in `ref_calculation_param`, plus (b) the share% of Counsellor bonus from `tx_case.presales_share_pct`? If purely (a)+(b), PRESALES has NO `ref_rate` rows, which is clean.

6. **VP scheme is undefined per your earlier statement.** Same question for VP — once defined, will it follow the `ref_rate` pattern (tier-based by office) or some other structure?

7. **Status `Closed - Not Exempted` / `Exempted` / `Follow up enrolment`** (Covid-era, AMBIG D4.R6) — keep as rows in `ref_status_split` with all flags FALSE, or omit entirely? I lean keep with `is_zero_bonus=TRUE` and a clear note, so encountering them doesn't crash the engine.

8. **The bare "Closed - Visa granted" status** (AMBIG D4.R7) — will the import process disambiguate to one of the qualified variants by date comparison, OR will the operator be required to disambiguate at data entry? Schema is the same either way, but the import logic differs.

---

## Summary

26 tables across 7 sections:
- 5 dimensional (offices, roles, countries, allowed combinations, country aliases)
- 3 staff (staff, alias, target)
- 7 institution/partner (priority partner, priority target, partner, partner alias, institution, institution alias, partner-institution junction)
- 7 calculation config (status split, client weight, client type alias, rate, calculation param, service fee, service fee alias)
- 6 missing-rules tables (local enrolment, contract target tier, contract package eligibility, team excess bonus, departure rule, complaint deduction)
- 4 transactional (case, bonus payment, team excess period, team excess distribution)
- 2 audit (run, review log)

Total = ~30 tables. More than I'd want for a tiny MVP, but each is doing one thing — that's the goal you set ("not the sprawling mess I have today"). Sprawl comes from tables doing multiple things; this design has tables that each handle a single concept.

Read it, push back where I've misunderstood, and once you confirm I'll move to Phase 5 (the actual SQL DDL CREATE statements as a runnable file, plus INSERT statements per table from the Phase 1 rules — also as runnable SQL).
