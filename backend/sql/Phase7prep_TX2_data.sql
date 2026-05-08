-- =============================================================================
-- Phase7prep_TX2_data.sql
-- Run AFTER Phase7prep_TX1_schema.sql has succeeded.
-- Run AFTER you have confirmed TX1's NOTICE output reads
-- "TX1 schema changes verified."
-- =============================================================================

-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║                          TRANSACTION 2 — DATA                              ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2a. Translate ref_institution.aggregate_priority_partner_id → junction rows
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_priority_partner_institution
    (priority_partner_id, institution_id, effective_from, notes)
SELECT
    aggregate_priority_partner_id,
    id,
    DATE '2024-01-01',
    'Migrated from ref_institution.aggregate_priority_partner_id during Phase7prep'
  FROM ref_institution
 WHERE aggregate_priority_partner_id IS NOT NULL;

-- Also translate the 1:1 priority_partner_id FK (single-institution Lists).
-- This column points to the priority_partner row that represents the institution
-- itself (Macquarie institution → Macquarie priority partner row). Same logical
-- relationship, just a different historical column.
INSERT INTO ref_priority_partner_institution
    (priority_partner_id, institution_id, effective_from, notes)
SELECT
    priority_partner_id,
    id,
    DATE '2024-01-01',
    'Migrated from ref_institution.priority_partner_id during Phase7prep'
  FROM ref_institution
 WHERE priority_partner_id IS NOT NULL
   AND NOT EXISTS (
       SELECT 1
         FROM ref_priority_partner_institution ppi
        WHERE ppi.priority_partner_id = ref_institution.priority_partner_id
          AND ppi.institution_id      = ref_institution.id
   );

-- ─────────────────────────────────────────────────────────────────────────────
-- 2b. Drop the now-redundant FKs on ref_institution
--
--     The CHECK constraint on ref_institution requires priority_partner_id to
--     be NOT NULL when classification = 'IN_SYSTEM_PRIORITY'. We must drop
--     that constraint BEFORE dropping the column.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    cn TEXT;
BEGIN
    -- Drop any constraint that references priority_partner_id
    FOR cn IN
        SELECT conname
        FROM   pg_constraint
        WHERE  conrelid = 'ref_institution'::regclass
          AND  contype  = 'c'
          AND  pg_get_constraintdef(oid) ILIKE '%priority_partner_id%'
    LOOP
        EXECUTE format('ALTER TABLE ref_institution DROP CONSTRAINT %I', cn);
    END LOOP;
END$$;

ALTER TABLE ref_institution DROP COLUMN IF EXISTS aggregate_priority_partner_id;
ALTER TABLE ref_institution DROP COLUMN IF EXISTS priority_partner_id;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2c. Reclassify institutions
--     IN_SYSTEM_REGULAR        → IN_SYSTEM   (rename)
--     OUT_SYSTEM_GROUP         → IN_SYSTEM   (Groups are in-system)
--     OUT_SYSTEM_MASTER_AGENT  → IN_SYSTEM   (rare, but if any exist)
--     IN_SYSTEM_PRIORITY       → IN_SYSTEM   (priority is now a flag, set in 2e)
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE ref_institution SET classification = 'IN_SYSTEM'
 WHERE classification IN (
     'IN_SYSTEM_REGULAR',
     'IN_SYSTEM_PRIORITY',
     'OUT_SYSTEM_GROUP',
     'OUT_SYSTEM_MASTER_AGENT'
 );


-- ─────────────────────────────────────────────────────────────────────────────
-- 2d. Tighten ref_institution.classification CHECK to final form
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE ref_institution
    DROP CONSTRAINT chk_ref_institution_classification_interim;

ALTER TABLE ref_institution
    ADD CONSTRAINT chk_ref_institution_classification CHECK (
        classification IN (
            'IN_SYSTEM',
            'UNVERIFIED'
        )
    );


-- ─────────────────────────────────────────────────────────────────────────────
-- 2e. Backfill ref_institution.is_priority_member from junction table
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE ref_institution i
   SET is_priority_member = TRUE
 WHERE EXISTS (
     SELECT 1 FROM ref_priority_partner_institution ppi
      WHERE ppi.institution_id = i.id
        AND ppi.effective_to IS NULL
 );


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Seed ref_partner_classification (27 rows)
-- ─────────────────────────────────────────────────────────────────────────────

-- Helper view for clarity (cleaned up at TX end).
CREATE TEMP VIEW _v_partner_lookup AS
    SELECT id, name FROM ref_partner;

INSERT INTO ref_partner_classification
    (partner_id, category, kpi_weight, bonus_model, effective_from, notes)
SELECT
    p.id,
    CASE p.name
        -- Master Agents (genuine) — flat rate, no tier
        WHEN 'ApplyBoard'                       THEN 'MASTER_AGENT_GENUINE'
        WHEN 'Can-Achieve'                      THEN 'MASTER_AGENT_GENUINE'
        -- Master Agents (out-of-system) — tier-based bonus
        WHEN 'Adventus'                         THEN 'MASTER_AGENT_OOS'
        WHEN 'Amerigo Education LLC'            THEN 'MASTER_AGENT_OOS'
        WHEN 'Educatius US'                     THEN 'MASTER_AGENT_OOS'
        WHEN 'EduCo International'              THEN 'MASTER_AGENT_OOS'
        WHEN 'GEEBEE Education'                 THEN 'MASTER_AGENT_OOS'
        WHEN 'Golden Education (GE)'            THEN 'MASTER_AGENT_OOS'
        WHEN 'Wellspring International Education' THEN 'MASTER_AGENT_OOS'
        -- Groups — in-system, weight 1.0
        ELSE 'GROUP'
    END,
    CASE p.name
        WHEN 'ApplyBoard'                       THEN 0.7
        WHEN 'Can-Achieve'                      THEN 0.7
        WHEN 'Adventus'                         THEN 0.7
        WHEN 'Amerigo Education LLC'            THEN 0.7
        WHEN 'Educatius US'                     THEN 0.7
        WHEN 'EduCo International'              THEN 0.7
        WHEN 'GEEBEE Education'                 THEN 0.7
        WHEN 'Golden Education (GE)'            THEN 0.7
        WHEN 'Wellspring International Education' THEN 0.7
        ELSE 1.0
    END,
    CASE p.name
        WHEN 'ApplyBoard'  THEN 'FLAT'
        WHEN 'Can-Achieve' THEN 'FLAT'
        ELSE 'TIER'
    END,
    DATE '2024-01-01',
    'Seeded by Phase7prep from Doc 7 (Classification of Master-agent and Group)'
  FROM _v_partner_lookup p
 WHERE NOT EXISTS (
       SELECT 1 FROM ref_partner_classification rpc
        WHERE rpc.partner_id     = p.id
          AND rpc.effective_to   IS NULL
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Seed ref_partner_flat_rate
--    ApplyBoard + Can-Achieve × HCM/HN/DN × Counsellor/CO_DIR
--    Rates per management:
--      HCM: Counsellor 1,000,000 | CO 800,000
--      HN:  Counsellor   900,000 | CO 700,000
--      DN:  Counsellor   900,000 | CO 700,000  (= HN)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_partner_flat_rate
    (partner_id, office_id, role_id, amount, effective_from, notes)
SELECT
    p.id,
    o.id,
    r.id,
    CASE
        WHEN o.code = 'HCM' AND r.code = 'COUNS_DIR' THEN 1000000
        WHEN o.code = 'HCM' AND r.code = 'CO_DIR'    THEN  800000
        WHEN o.code IN ('HN','DN') AND r.code = 'COUNS_DIR' THEN 900000
        WHEN o.code IN ('HN','DN') AND r.code = 'CO_DIR'    THEN 700000
    END,
    DATE '2024-01-01',
    'Seeded by Phase7prep — flat rate for Master Agent (genuine) cases'
  FROM ref_partner p
  CROSS JOIN dim_office o
  CROSS JOIN dim_role   r
 WHERE p.name IN ('ApplyBoard', 'Can-Achieve')
   AND o.code IN ('HCM', 'HN', 'DN')
   AND r.code IN ('COUNS_DIR', 'CO_DIR')
   AND NOT EXISTS (
       SELECT 1 FROM ref_partner_flat_rate rpfr
        WHERE rpfr.partner_id = p.id
          AND rpfr.office_id  = o.id
          AND rpfr.role_id    = r.id
          AND rpfr.effective_to IS NULL
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. Set Lợi's secondary_role_id = CO_DIR
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE ref_staff
   SET secondary_role_id = (SELECT id FROM dim_role WHERE code = 'CO_DIR')
 WHERE canonical_name = 'Phạm Thị Lợi';


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Seed ref_priority_group
--
--    From Doc 7 + management clarifications, the only Groups currently relevant
--    as priority partners (i.e. with priority Lists rolling up) is Navitas.
--    Others (INTO, Study Group, Kaplan, etc.) exist in ref_partner as Groups
--    but have no priority Lists rolling up at this time.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_priority_group (name, effective_from, notes)
SELECT 'Navitas', DATE '2024-01-01',
       'Top-level commercial relationship. Hosts 7 priority Lists across AU/CA/NZ.'
 WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_group
     WHERE name = 'Navitas' AND effective_to IS NULL
 );


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. Update / seed ref_priority_partner from PRIORITY 2025 image
--
--    Existing rows from Phase 5 may already be present. We use INSERT…ON
--    CONFLICT DO NOTHING for the few that aren't, and rely on existing names
--    matching for the ones that are.
--
--    Notes on canonical names (matching the image exactly):
--    - "James Cook University Brisbane (JCUB)" — full form, with abbreviation
--    - "VIC DET (Dept of Education & Training, VIC)" — full form
--    - "Toronto Met Uni Intl College (Navitas)"     — image's spelling
--    - "WSU College / WSU Sydney City (Navitas)"   — image's spelling
-- ─────────────────────────────────────────────────────────────────────────────

-- Helper: country IDs (stable from Phase 5)
CREATE TEMP VIEW _v_country AS
    SELECT id, code FROM dim_country;

-- Insert any priority partners not already present.
WITH wanted(name, country_code, is_aggregate) AS (VALUES
    -- AU singles
    ('Australian Catholic University (ACU)',                  'AU', FALSE),
    ('Curtin University',                                     'AU', FALSE),
    ('Deakin University',                                     'AU', FALSE),
    ('Education Queensland International (EQI)',              'AU', FALSE),
    ('Griffith University',                                   'AU', FALSE),
    ('James Cook University Brisbane (JCUB)',                 'AU', FALSE),
    ('Kaplan Business School Australia',                      'AU', FALSE),
    ('La Trobe University',                                   'AU', FALSE),
    ('Macquarie University',                                  'AU', FALSE),
    ('Monash University',                                     'AU', FALSE),
    ('RMIT University',                                       'AU', FALSE),
    ('Swinburne University of Technology',                    'AU', FALSE),
    ('The University of Adelaide',                            'AU', FALSE),
    ('The University of New South Wales (UNSW)',              'AU', FALSE),
    ('The University of Queensland',                          'AU', FALSE),
    ('University of Newcastle',                               'AU', FALSE),
    ('University of South Australia (UniSA)',                 'AU', FALSE),
    ('University of Tasmania (UTAS)',                         'AU', FALSE),
    ('University of Technology Sydney (UTS)',                 'AU', FALSE),
    ('University of Western Australia (UWA)',                 'AU', FALSE),
    ('VIC DET (Dept of Education & Training, VIC)',           'AU', FALSE),
    -- CA singles
    ('Algonquin College',                                     'CA', FALSE),
    ('Cape Breton University (CBU)',                          'CA', FALSE),
    ('Braemar College',                                       'CA', FALSE),
    ('Toronto Metropolitan University',                       'CA', FALSE),
    ('University of Guelph',                                  'CA', FALSE),
    ('University of Regina',                                  'CA', FALSE),
    -- NZ
    ('ENZ (any NZ providers)',                                'NZ', TRUE),
    ('LightPath',                                             'NZ', FALSE),
    -- SING
    ('Raffles Education Network',                             'SG', FALSE),
    ('Nanyang Institute of Management (NIM)',                 'SG', FALSE),
    -- Navitas Lists (single institutions)
    ('Griffith College (Navitas)',                            'AU', FALSE),
    ('WSU College / WSU Sydney City (Navitas)',               'AU', FALSE),
    ('ICM (Navitas)',                                         'CA', FALSE),
    ('Toronto Met Uni Intl College (Navitas)',                'CA', FALSE),
    -- Navitas Lists (aggregates)
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC', 'AU', TRUE),
    ('Other Navitas CA: FIC, ULIC, WLIC',                     'CA', TRUE),
    ('Other Navitas NZ: UCIC',                                'NZ', TRUE)
)
INSERT INTO ref_priority_partner (name, country_id, is_aggregate, effective_from, notes)
SELECT w.name, c.id, w.is_aggregate, DATE '2024-01-01',
       'Seeded by Phase7prep from PRIORITY 2025 image'
  FROM wanted w
  JOIN _v_country c ON c.code = w.country_code
 WHERE NOT EXISTS (
       SELECT 1 FROM ref_priority_partner rpp
        WHERE rpp.name = w.name
          AND rpp.effective_to IS NULL
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Seed ref_priority_target — 2024 (real %) and 2025 (0% paused)
--
--    2024 numbers from Doc 6 (Priority 2024 final v2)
--    2025 numbers from PRIORITY 2025 image — bonus_pct = 0 across the board
--
--    NOTE: 2024 and 2025 values are identical for total/direct/sub targets per
--    the management image (which is labelled "PRIORITY PARTNER INSTITUTIONS
--    2025 — Targets & Bonus %" but the targets columns match 2024 Doc 6).
--    Bonus % is the ONLY column that differs between the two years.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TEMP VIEW _v_pp_lookup AS
    SELECT id, name FROM ref_priority_partner WHERE effective_to IS NULL;

-- 2024 values from Doc 6 (Priority 2024 final v2)
WITH targets_2024(name, total_target, direct_target, sub_target, bonus_pct) AS (VALUES
    ('Australian Catholic University (ACU)',                   6,  4, 2, 0.25),
    ('Curtin University',                                      6,  3, 3, 0.30),
    ('Deakin University',                                      6,  4, 2, 0.25),
    ('Education Queensland International (EQI)',              10,  3, 7, 0.30),
    ('Griffith University',                                    3,  2, 1, 0.30),
    ('James Cook University Brisbane (JCUB)',                  5,  3, 2, 0.20),
    ('Kaplan Business School Australia',                       4,  2, 2, 0.20),
    ('La Trobe University',                                    8,  5, 3, 0.60),
    ('Macquarie University',                                  10,  5, 5, 0.30),
    ('Monash University',                                     10,  3, 7, 0.50),
    ('RMIT University',                                        8,  3, 5, 0.20),
    ('Swinburne University of Technology',                    14,  7, 7, 0.20),
    ('The University of Adelaide',                            14,  7, 7, 0.70),
    ('The University of New South Wales (UNSW)',               5,  2, 3, 0.25),
    ('The University of Queensland',                           6,  4, 2, 0.40),
    ('University of Newcastle',                                3,  3, 0, 0.20),
    ('University of South Australia (UniSA)',                 14,  7, 7, 0.70),
    ('University of Tasmania (UTAS)',                          5,  3, 2, 0.25),
    ('University of Technology Sydney (UTS)',                  6,  3, 3, 0.30),
    ('University of Western Australia (UWA)',                  8,  4, 4, 0.70),
    ('VIC DET (Dept of Education & Training, VIC)',           15,  7, 8, 0.20),
    ('Algonquin College',                                      4,  2, 2, 0.30),
    ('Cape Breton University (CBU)',                           5,  5, 0, 0.50),
    ('Braemar College',                                        4,  4, 0, 0.30),
    ('Toronto Metropolitan University',                        3,  3, 0, 0.20),
    ('University of Guelph',                                   1,  1, 0, 0.40),
    ('University of Regina',                                   2,  2, 0, 0.30),
    ('ENZ (any NZ providers)',                                10,  5, 5, 0.40),
    ('LightPath',                                              3,  3, 0, 0.40),
    ('Raffles Education Network',                              1,  1, 0, 0.20),
    ('Nanyang Institute of Management (NIM)',                  1,  1, 0, 0.20),
    ('Griffith College (Navitas)',                             2,  1, 1, 0.40),
    ('WSU College / WSU Sydney City (Navitas)',                1,  1, 0, 0.40),
    ('ICM (Navitas)',                                          1,  1, 0, 0.40),
    ('Toronto Met Uni Intl College (Navitas)',                 1,  1, 0, 0.40),
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC', 7, 3, 4, 0.30),
    ('Other Navitas CA: FIC, ULIC, WLIC',                      2,  2, 0, 0.30),
    ('Other Navitas NZ: UCIC',                                 1,  1, 0, 0.30)
)
INSERT INTO ref_priority_target
    (priority_partner_id, total_target, direct_target, sub_target,
     bonus_pct, prior_year_owing, effective_from, effective_to, notes)
SELECT pp.id, t.total_target, t.direct_target, t.sub_target,
       t.bonus_pct, 0, DATE '2024-01-01', DATE '2024-12-31',
       'Seeded by Phase7prep from Doc 6 (Priority 2024 final v2)'
  FROM targets_2024 t
  JOIN _v_pp_lookup pp ON pp.name = t.name
 WHERE NOT EXISTS (
       SELECT 1 FROM ref_priority_target rpt
        WHERE rpt.priority_partner_id = pp.id
          AND rpt.effective_from = DATE '2024-01-01'
   );

-- 2025 values — same targets, bonus_pct = 0 (program paused)
WITH targets_2025(name, total_target, direct_target, sub_target) AS (VALUES
    ('Australian Catholic University (ACU)',                   6,  4, 2),
    ('Curtin University',                                      6,  3, 3),
    ('Deakin University',                                      6,  4, 2),
    ('Education Queensland International (EQI)',              10,  3, 7),
    ('Griffith University',                                    3,  2, 1),
    ('James Cook University Brisbane (JCUB)',                  5,  3, 2),
    ('Kaplan Business School Australia',                       4,  2, 2),
    ('La Trobe University',                                    8,  5, 3),
    ('Macquarie University',                                  10,  5, 5),
    ('Monash University',                                     10,  3, 7),
    ('RMIT University',                                        8,  3, 5),
    ('Swinburne University of Technology',                    14,  7, 7),
    ('The University of Adelaide',                            14,  7, 7),
    ('The University of New South Wales (UNSW)',               5,  2, 3),
    ('The University of Queensland',                           6,  4, 2),
    ('University of Newcastle',                                3,  3, 0),
    ('University of South Australia (UniSA)',                 14,  7, 7),
    ('University of Tasmania (UTAS)',                          5,  3, 2),
    ('University of Technology Sydney (UTS)',                  6,  3, 3),
    ('University of Western Australia (UWA)',                  8,  4, 4),
    ('VIC DET (Dept of Education & Training, VIC)',           15,  7, 8),
    ('Algonquin College',                                      4,  2, 2),
    ('Cape Breton University (CBU)',                           5,  5, 0),
    ('Braemar College',                                        4,  4, 0),
    ('Toronto Metropolitan University',                        3,  3, 0),
    ('University of Guelph',                                   1,  1, 0),
    ('University of Regina',                                   2,  2, 0),
    ('ENZ (any NZ providers)',                                10,  5, 5),
    ('LightPath',                                              3,  3, 0),
    ('Raffles Education Network',                              1,  1, 0),
    ('Nanyang Institute of Management (NIM)',                  1,  1, 0),
    ('Griffith College (Navitas)',                             2,  1, 1),
    ('WSU College / WSU Sydney City (Navitas)',                1,  1, 0),
    ('ICM (Navitas)',                                          1,  1, 0),
    ('Toronto Met Uni Intl College (Navitas)',                 1,  1, 0),
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC', 7, 3, 4),
    ('Other Navitas CA: FIC, ULIC, WLIC',                      2,  2, 0),
    ('Other Navitas NZ: UCIC',                                 1,  1, 0)
)
INSERT INTO ref_priority_target
    (priority_partner_id, total_target, direct_target, sub_target,
     bonus_pct, prior_year_owing, effective_from, effective_to, notes)
SELECT pp.id, t.total_target, t.direct_target, t.sub_target,
       0, 0, DATE '2025-01-01', NULL,
       'Seeded by Phase7prep from PRIORITY 2025 image — program paused, bonus_pct=0'
  FROM targets_2025 t
  JOIN _v_pp_lookup pp ON pp.name = t.name
 WHERE NOT EXISTS (
       SELECT 1 FROM ref_priority_target rpt
        WHERE rpt.priority_partner_id = pp.id
          AND rpt.effective_from = DATE '2025-01-01'
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- 9. Seed ref_priority_group_partner — Navitas's 7 Lists
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_priority_group_partner
    (priority_group_id, priority_partner_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_group WHERE name = 'Navitas' AND effective_to IS NULL),
    pp.id,
    DATE '2024-01-01',
    'Seeded by Phase7prep'
  FROM ref_priority_partner pp
 WHERE pp.effective_to IS NULL
   AND pp.name IN (
       'Griffith College (Navitas)',
       'WSU College / WSU Sydney City (Navitas)',
       'ICM (Navitas)',
       'Toronto Met Uni Intl College (Navitas)',
       'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC',
       'Other Navitas CA: FIC, ULIC, WLIC',
       'Other Navitas NZ: UCIC'
   )
   AND NOT EXISTS (
       SELECT 1 FROM ref_priority_group_partner rpgp
        WHERE rpgp.priority_partner_id = pp.id
          AND rpgp.effective_to IS NULL
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- 10. PHASE 6L DATA FIXES — Sub-agents
-- ─────────────────────────────────────────────────────────────────────────────

-- Insert canonicals
INSERT INTO ref_sub_agent (canonical_name, verification_status, notes)
VALUES
    ('IMEC (Tư Vấn Du Học Quốc Tế IMEC)', 'VERIFIED',
     'Phase7prep / Phase 6l backfill. Confirmed canonical by team.'),
    ('Công ty TNHH Tư vấn Du học - Visa - Luật Úc ALVE', 'VERIFIED',
     'Phase7prep / Phase 6l backfill. Confirmed canonical by team.'),
    ('TRUST EDU', 'VERIFIED',
     'Phase7prep / Phase 6l backfill. Confirmed canonical by team.'),
    ('Công ty Cổ Phần Phát Triển Giáo Dục Dạ Minh Châu', 'VERIFIED',
     'Phase7prep / Phase 6l backfill. Confirmed canonical by team.'),
    ('Á Âu (Asia-Europe Co., Ltd.)', 'VERIFIED',
     'Phase7prep / Phase 6l backfill. Confirmed canonical by team.'),
    ('Du học Toàn Cầu', 'VERIFIED',
     'Phase7prep / Phase 6l backfill. Confirmed canonical by team.')
ON CONFLICT (canonical_name) DO NOTHING;

-- Self-aliases for each
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias)
SELECT id, canonical_name
  FROM ref_sub_agent
 WHERE canonical_name IN (
     'IMEC (Tư Vấn Du Học Quốc Tế IMEC)',
     'Công ty TNHH Tư vấn Du học - Visa - Luật Úc ALVE',
     'TRUST EDU',
     'Công ty Cổ Phần Phát Triển Giáo Dục Dạ Minh Châu',
     'Á Âu (Asia-Europe Co., Ltd.)',
     'Du học Toàn Cầu'
 )
ON CONFLICT (alias) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- 11. PHASE 6L DATA FIXES — Institutions
-- ─────────────────────────────────────────────────────────────────────────────

-- 11a. International Language Academy (ILAC pathway)
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'International Language Academy', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep / Phase 6l. Reached via ILAC group; classification IN_SYSTEM
        (Group routing captured via ref_partner_institution).'
  FROM dim_country c
 WHERE c.code = 'CA'
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution
        WHERE canonical_name = 'International Language Academy'
          AND merged_into_id IS NULL
   );

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT i.id, a.alias
  FROM ref_institution i
 CROSS JOIN (VALUES
    ('International Language Academy'),
    ('International Language Academy * - ILAC')
 ) AS a(alias)
 WHERE i.canonical_name = 'International Language Academy'
   AND i.merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;

-- Link to ILAC partner (an existing Group)
INSERT INTO ref_partner_institution
    (partner_id, institution_id, partner_type, effective_from, notes)
SELECT
    (SELECT id FROM ref_partner WHERE name = 'ILAC'),
    (SELECT id FROM ref_institution WHERE canonical_name = 'International Language Academy' AND merged_into_id IS NULL),
    (SELECT classification FROM ref_partner WHERE name = 'ILAC'),
    DATE '2024-01-01',
    'Phase7prep / Phase 6l'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_partner_institution rpi
     WHERE rpi.partner_id = (SELECT id FROM ref_partner WHERE name = 'ILAC')
       AND rpi.institution_id = (SELECT id FROM ref_institution WHERE canonical_name = 'International Language Academy' AND merged_into_id IS NULL)
       AND rpi.effective_to IS NULL
);


-- 11b. Education Queensland International (EQI)
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Education Queensland International (EQI)', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep / Phase 6l. Direct StudyLink contract; on Doc 6 priority list.
        Priority status set via is_priority_member flag (step 2e via junction).'
  FROM dim_country c
 WHERE c.code = 'AU'
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution
        WHERE canonical_name = 'Education Queensland International (EQI)'
          AND merged_into_id IS NULL
   );

-- EQI as a priority List was inserted in section 7. Now link the institution
-- to its priority partner.
INSERT INTO ref_priority_partner_institution
    (priority_partner_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_partner WHERE name = 'Education Queensland International (EQI)' AND effective_to IS NULL),
    (SELECT id FROM ref_institution WHERE canonical_name = 'Education Queensland International (EQI)' AND merged_into_id IS NULL),
    DATE '2024-01-01',
    'Phase7prep / Phase 6l'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_partner_institution ppi
     WHERE ppi.priority_partner_id = (SELECT id FROM ref_priority_partner WHERE name = 'Education Queensland International (EQI)' AND effective_to IS NULL)
       AND ppi.institution_id = (SELECT id FROM ref_institution WHERE canonical_name = 'Education Queensland International (EQI)' AND merged_into_id IS NULL)
       AND ppi.effective_to IS NULL
);

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, 'Education Queensland International (EQI)'
  FROM ref_institution
 WHERE canonical_name = 'Education Queensland International (EQI)'
   AND merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;


-- 11c. Wesley College
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Wesley College', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep / Phase 6l. Direct contract. Per management: not priority.'
  FROM dim_country c
 WHERE c.code = 'AU'
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution
        WHERE canonical_name = 'Wesley College'
          AND merged_into_id IS NULL
   );

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, 'Wesley College'
  FROM ref_institution
 WHERE canonical_name = 'Wesley College'
   AND merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;


-- 11d. Northern Territory Government - Department of Education
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Northern Territory Government - Department of Education', c.id,
       'IN_SYSTEM', 'VERIFIED',
       'Phase7prep / Phase 6l. State DET. Direct contract. Not on priority list.'
  FROM dim_country c
 WHERE c.code = 'AU'
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution
        WHERE canonical_name = 'Northern Territory Government - Department of Education'
          AND merged_into_id IS NULL
   );

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, 'Northern Territory Government - Department of Education'
  FROM ref_institution
 WHERE canonical_name = 'Northern Territory Government - Department of Education'
   AND merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;


-- 11e. Victoria University aliases (canonical id 288 from Phase 6j)
INSERT INTO ref_institution_alias (institution_id, alias)
SELECT i.id, a.alias
  FROM ref_institution i
 CROSS JOIN (VALUES
    ('Victoria University - Melbourne'),
    ('Victoria University - Melbourne **'),
    ('Victoria University - VU'),
    ('Victoria University - VU **')
 ) AS a(alias)
 WHERE i.canonical_name = 'Victoria University'
   AND i.merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- 11f. Re-backfill ref_institution.is_priority_member
--      Section 2e ran before sections 7-11 added new junction rows. Re-run
--      to catch institutions linked to priority Lists during this migration.
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE ref_institution i
   SET is_priority_member = TRUE
 WHERE is_priority_member = FALSE
   AND EXISTS (
       SELECT 1 FROM ref_priority_partner_institution ppi
        WHERE ppi.institution_id = i.id
          AND ppi.effective_to IS NULL
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- TX2 verification
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_classif       INTEGER;
    n_flat          INTEGER;
    n_pgroup        INTEGER;
    n_2024_targets  INTEGER;
    n_2025_targets  INTEGER;
    n_navitas_links INTEGER;
    loi_2nd         BIGINT;
    n_legacy        INTEGER;
    n_subag_new     INTEGER;
    n_inst_new      INTEGER;
    n_priority_inst INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_classif FROM ref_partner_classification WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_flat    FROM ref_partner_flat_rate     WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_pgroup  FROM ref_priority_group         WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_2024_targets
                       FROM ref_priority_target
                      WHERE effective_from = DATE '2024-01-01';
    SELECT COUNT(*) INTO n_2025_targets
                       FROM ref_priority_target
                      WHERE effective_from = DATE '2025-01-01';
    SELECT COUNT(*) INTO n_navitas_links
                       FROM ref_priority_group_partner
                      WHERE effective_to IS NULL;
    SELECT secondary_role_id INTO loi_2nd
      FROM ref_staff WHERE canonical_name = 'Phạm Thị Lợi';
    SELECT COUNT(*) INTO n_legacy
      FROM ref_institution
     WHERE classification IN ('IN_SYSTEM_REGULAR','OUT_SYSTEM_GROUP','OUT_SYSTEM_MASTER_AGENT');
    SELECT COUNT(*) INTO n_subag_new
      FROM ref_sub_agent
     WHERE canonical_name IN (
        'IMEC (Tư Vấn Du Học Quốc Tế IMEC)',
        'Công ty TNHH Tư vấn Du học - Visa - Luật Úc ALVE',
        'TRUST EDU',
        'Công ty Cổ Phần Phát Triển Giáo Dục Dạ Minh Châu',
        'Á Âu (Asia-Europe Co., Ltd.)',
        'Du học Toàn Cầu'
     );
    SELECT COUNT(*) INTO n_inst_new
      FROM ref_institution
     WHERE canonical_name IN (
        'International Language Academy',
        'Education Queensland International (EQI)',
        'Wesley College',
        'Northern Territory Government - Department of Education'
     );
    SELECT COUNT(*) INTO n_priority_inst
      FROM ref_institution
     WHERE is_priority_member = TRUE;

    RAISE NOTICE 'TX2 results:';
    RAISE NOTICE '  ref_partner_classification (active):              %',  n_classif;
    RAISE NOTICE '  ref_partner_flat_rate (active):                   %',  n_flat;
    RAISE NOTICE '  ref_priority_group (active):                      %',  n_pgroup;
    RAISE NOTICE '  ref_priority_target rows for 2024:                %',  n_2024_targets;
    RAISE NOTICE '  ref_priority_target rows for 2025:                %',  n_2025_targets;
    RAISE NOTICE '  ref_priority_group_partner (Navitas links):       %',  n_navitas_links;
    RAISE NOTICE '  Lợi.secondary_role_id:                            %',  loi_2nd;
    RAISE NOTICE '  Legacy classification rows remaining (must be 0): %',  n_legacy;
    RAISE NOTICE '  Phase 6l sub-agent canonicals present:            %',  n_subag_new;
    RAISE NOTICE '  Phase 6l institution canonicals present:          %',  n_inst_new;
    RAISE NOTICE '  Institutions flagged as priority members:         %',  n_priority_inst;

    -- Hard checks
    IF n_classif      <> 27 THEN RAISE EXCEPTION 'Expected 27 active classifications, got %', n_classif; END IF;
    IF n_flat         <> 12 THEN RAISE EXCEPTION 'Expected 12 active flat rates, got %', n_flat; END IF;
    IF n_pgroup       <>  1 THEN RAISE EXCEPTION 'Expected 1 active priority group (Navitas), got %', n_pgroup; END IF;
    IF n_2024_targets <> 38 THEN RAISE EXCEPTION 'Expected 38 priority targets for 2024, got %', n_2024_targets; END IF;
    IF n_2025_targets <> 38 THEN RAISE EXCEPTION 'Expected 38 priority targets for 2025, got %', n_2025_targets; END IF;
    IF n_navitas_links <> 7 THEN RAISE EXCEPTION 'Expected 7 active Navitas group-partner links, got %', n_navitas_links; END IF;
    IF loi_2nd IS NULL      THEN RAISE EXCEPTION 'Lợi.secondary_role_id not set'; END IF;
    IF n_legacy   <>  0     THEN RAISE EXCEPTION 'Legacy classification rows remain: %', n_legacy; END IF;
    IF n_subag_new   <>  6  THEN RAISE EXCEPTION 'Expected 6 Phase 6l sub-agent canonicals, got %', n_subag_new; END IF;
    IF n_inst_new    <>  4  THEN RAISE EXCEPTION 'Expected 4 Phase 6l institution canonicals, got %', n_inst_new; END IF;

    RAISE NOTICE 'TX2 data verification PASSED.';
END$$;

COMMIT;

-- =============================================================================
-- END OF Phase7prep_partner_priority_redesign.sql
-- =============================================================================
