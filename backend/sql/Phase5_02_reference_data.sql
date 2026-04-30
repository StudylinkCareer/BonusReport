-- =============================================================================
-- StudyLink Vietnam Bonus Engine — Reference Data
-- File:    02_reference_data.sql
-- Purpose: Populate all dim_* and ref_* tables (except staff and targets, which
--          live in 03_staff_data.sql).
-- Target:  PostgreSQL 15+
-- Order:   Run AFTER 01_schema.sql, BEFORE 03_staff_data.sql.
-- =============================================================================
-- Data sourced from Phase 1 rule inventory. Citations follow each block as
-- "-- Source: D{doc#}.R{rule#}" referencing rule_inventory.md.
--
-- Effective dates: where unknown, use 2024-01-01 as a conservative starting
-- point (most procedural docs predate 2024). Operator can update later.
--
-- Convention for INSERTs: explicit column lists, no relying on column order.
-- =============================================================================


-- =============================================================================
-- SECTION 1.1 — dim_office
-- Source: User-confirmed (Phase 4 design)
-- =============================================================================
INSERT INTO dim_office (code, name, country_code, is_active, notes) VALUES
    ('HCM', 'Ho Chi Minh City', 'VN', TRUE,  'Primary VN office; full role set.'),
    ('HN',  'Hanoi',            'VN', TRUE,  'VN office; full role set.'),
    ('DN',  'Da Nang',          'VN', TRUE,  'VN office; full role set.'),
    ('MEL', 'Melbourne',        'AU', TRUE,  'AU office; VP role only.'),
    ('HK',  'Hong Kong',        'HK', FALSE, 'Future office; VP role only when activated. is_active=FALSE until operations begin.');


-- =============================================================================
-- SECTION 1.2 — dim_role
-- Source: User-confirmed (Option A: 5 roles, VP scheme variation by office)
-- =============================================================================
INSERT INTO dim_role (code, name, description) VALUES
    ('COUNS_DIR', 'Counsellor (Direct)', 'Direct Counsellor. Heads case advisory + KPI.'),
    ('CO_DIR',    'Case Officer (Direct)', 'Direct Case Officer. Handles enrolment + visa workflow for direct cases.'),
    ('CO_SUB',    'Case Officer (Sub-agent)', 'Case Officer for sub-agent referrals. Has its own rate sheet (D6.R6).'),
    ('PRESALES',  'Pre-sales', 'Lead generation/qualification. 200K flat per case + optional case-level share % of Counsellor bonus.'),
    ('VP',        'Vice President', 'Office-level senior. Scheme variation by office (DN, MEL initially).');


-- =============================================================================
-- SECTION 1.3 — dim_role_office_allowed
-- Source: User-confirmed. HCM/HN/DN have all 5 roles. MEL and HK have VP only.
-- =============================================================================
-- HCM, HN, DN: all 5 roles
INSERT INTO dim_role_office_allowed (role_id, office_id, notes)
SELECT r.id, o.id, 'Full role set for primary VN offices.'
FROM dim_role r
CROSS JOIN dim_office o
WHERE o.code IN ('HCM','HN','DN');

-- MEL: VP only
INSERT INTO dim_role_office_allowed (role_id, office_id, notes)
SELECT r.id, o.id, 'AU office: VP only.'
FROM dim_role r, dim_office o
WHERE r.code = 'VP' AND o.code = 'MEL';

-- HK: VP only (when activated)
INSERT INTO dim_role_office_allowed (role_id, office_id, is_active, notes)
SELECT r.id, o.id, FALSE, 'HK office reserved; VP only when activated.'
FROM dim_role r, dim_office o
WHERE r.code = 'VP' AND o.code = 'HK';


-- =============================================================================
-- SECTION 1.4 — dim_country
-- Source: D1.R2 (14 target countries), D1.R6 + D6.R9 (flat-rate countries),
--         D1.R9 (Vietnam domestic)
-- =============================================================================
INSERT INTO dim_country (code, name, is_target_country, is_flat_country, notes) VALUES
    ('AU', 'Australia',     TRUE,  FALSE, 'D1.R2 target country.'),
    ('CA', 'Canada',        TRUE,  FALSE, 'D1.R2 target country.'),
    ('US', 'United States', TRUE,  FALSE, 'D1.R2 target country. US ≥28M Out-system gets 0.7 weight (D1.R10).'),
    ('NZ', 'New Zealand',   TRUE,  FALSE, 'D1.R2 target country.'),
    ('GB', 'United Kingdom',TRUE,  FALSE, 'D1.R2 target country.'),
    ('SG', 'Singapore',     TRUE,  FALSE, 'D1.R2 target country.'),
    ('IE', 'Ireland',       TRUE,  FALSE, 'D1.R2 target country.'),
    ('CH', 'Switzerland',   TRUE,  FALSE, 'D1.R2 target country.'),
    ('FI', 'Finland',       TRUE,  FALSE, 'D1.R2 target country.'),
    ('NL', 'Netherlands',   TRUE,  FALSE, 'D1.R2 target country.'),
    ('DE', 'Germany',       TRUE,  FALSE, 'D1.R2 target country.'),
    ('FR', 'France',        TRUE,  FALSE, 'D1.R2 target country.'),
    ('MY', 'Malaysia',      TRUE,  TRUE,  'D1.R2 target + D1.R6 flat (2-out-target = 1-target).'),
    ('TH', 'Thailand',      FALSE, TRUE,  'D1.R6 flat-rate country (2-out-target = 1-target). No-target.'),
    ('PH', 'Philippines',   FALSE, TRUE,  'D6.R9 flat-rate country.'),
    ('KR', 'South Korea',   FALSE, TRUE,  'D6.R9 flat-rate country.'),
    ('VN', 'Vietnam',       FALSE, FALSE, 'Domestic (du học tại chỗ). VN-domestic 1M flat rule applies.'),
    ('TW', 'Taiwan',        FALSE, FALSE, 'Visitor/non-target visa types per Doc 8.');

-- VN domestic anchor: VN country is_domestic_for the primary VN office (HCM)
-- as the anchor. The VN-domestic flat-1M rule applies for any case where
-- country=VN, regardless of which VN office handles it.
UPDATE dim_country SET is_domestic_for = (SELECT id FROM dim_office WHERE code = 'HCM')
WHERE code = 'VN';


-- =============================================================================
-- SECTION 1.5 — dim_country_alias
-- Source: CRM and BC observations + procedural docs
-- =============================================================================
INSERT INTO dim_country_alias (country_id, alias) VALUES
    ((SELECT id FROM dim_country WHERE code='AU'), 'Australia'),
    ((SELECT id FROM dim_country WHERE code='AU'), 'Úc'),
    ((SELECT id FROM dim_country WHERE code='AU'), 'AUS'),
    ((SELECT id FROM dim_country WHERE code='CA'), 'Canada'),
    ((SELECT id FROM dim_country WHERE code='CA'), 'CAN'),
    ((SELECT id FROM dim_country WHERE code='US'), 'United States'),
    ((SELECT id FROM dim_country WHERE code='US'), 'USA'),
    ((SELECT id FROM dim_country WHERE code='US'), 'Mỹ'),
    ((SELECT id FROM dim_country WHERE code='NZ'), 'New Zealand'),
    ((SELECT id FROM dim_country WHERE code='GB'), 'United Kingdom'),
    ((SELECT id FROM dim_country WHERE code='GB'), 'UK'),
    ((SELECT id FROM dim_country WHERE code='GB'), 'Anh'),
    ((SELECT id FROM dim_country WHERE code='SG'), 'Singapore'),
    ((SELECT id FROM dim_country WHERE code='SG'), 'SING'),
    ((SELECT id FROM dim_country WHERE code='SG'), 'SG'),
    ((SELECT id FROM dim_country WHERE code='IE'), 'Ireland'),
    ((SELECT id FROM dim_country WHERE code='CH'), 'Switzerland'),
    ((SELECT id FROM dim_country WHERE code='CH'), 'Thụy Sĩ'),
    ((SELECT id FROM dim_country WHERE code='FI'), 'Finland'),
    ((SELECT id FROM dim_country WHERE code='NL'), 'Netherlands'),
    ((SELECT id FROM dim_country WHERE code='NL'), 'Hà Lan'),
    ((SELECT id FROM dim_country WHERE code='DE'), 'Germany'),
    ((SELECT id FROM dim_country WHERE code='DE'), 'Đức'),
    ((SELECT id FROM dim_country WHERE code='FR'), 'France'),
    ((SELECT id FROM dim_country WHERE code='FR'), 'Pháp'),
    ((SELECT id FROM dim_country WHERE code='MY'), 'Malaysia'),
    ((SELECT id FROM dim_country WHERE code='MY'), 'ML'),
    ((SELECT id FROM dim_country WHERE code='TH'), 'Thailand'),
    ((SELECT id FROM dim_country WHERE code='TH'), 'Thái Lan'),
    ((SELECT id FROM dim_country WHERE code='TH'), 'THAI'),
    ((SELECT id FROM dim_country WHERE code='PH'), 'Philippines'),
    ((SELECT id FROM dim_country WHERE code='PH'), 'PHIL'),
    ((SELECT id FROM dim_country WHERE code='KR'), 'Hàn Quốc'),
    ((SELECT id FROM dim_country WHERE code='KR'), 'Korea'),
    ((SELECT id FROM dim_country WHERE code='KR'), 'South Korea'),
    ((SELECT id FROM dim_country WHERE code='VN'), 'Vietnam'),
    ((SELECT id FROM dim_country WHERE code='VN'), 'Việt Nam'),
    ((SELECT id FROM dim_country WHERE code='TW'), 'Taiwan'),
    ((SELECT id FROM dim_country WHERE code='TW'), 'Đài Loan');


-- =============================================================================
-- SECTION 3.1 — ref_priority_partner
-- Source: D2.R1 (Doc 2 priority list, 38 entries)
-- =============================================================================
INSERT INTO ref_priority_partner (name, country_id, is_aggregate, notes) VALUES
    -- AU partners (21)
    ('Australian Catholic University (ACU)', (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('Curtin University',                     (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('Deakin University',                     (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('EQI',                                   (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1; Education Queensland International.'),
    ('Griffith University',                   (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('JCUB',                                  (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1; James Cook University Brisbane.'),
    ('Kaplan Business School Australia',      (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('La Trobe University',                   (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('Macquarie University',                  (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('Monash University',                     (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('RMIT University',                       (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('Swinburne University of Technology',    (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('The University of Adelaide',            (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('The University of New South Wales (UNSW)', (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('The University of Queensland',          (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('University of Newcastle',               (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1; D2.R3 admission via other agents.'),
    ('University of South Australia (UniSA)', (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('University of Tasmania (UTAS)',         (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('University of Technology Sydney (UTS)', (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('University of Western Australia (UWA)', (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('VIC DET',                               (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1; Victoria Department of Education.'),
    -- CA partners (6)
    ('Algonquin College',                     (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1'),
    ('Cape Breton University (CBU)',          (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1'),
    ('Braemar College',                       (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1'),
    ('Toronto Metropolitan University',       (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1; D2.R3 admission via other agents.'),
    ('University of Guelph',                  (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1'),
    ('University of Regina',                  (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1'),
    -- NZ partners (2)
    ('ENZ (any NZ providers count)',          (SELECT id FROM dim_country WHERE code='NZ'), FALSE, 'D2.R1; aggregate-like behaviour but treated as single priority partner.'),
    ('LightPath',                             (SELECT id FROM dim_country WHERE code='NZ'), FALSE, 'D2.R1'),
    -- SG partners (2)
    ('Raffles Education Network',             (SELECT id FROM dim_country WHERE code='SG'), FALSE, 'D2.R1'),
    ('Nanyang Institute of Management (NIM)', (SELECT id FROM dim_country WHERE code='SG'), FALSE, 'D2.R1'),
    -- Navitas individual priority entries (4)
    ('Griffith College (Navitas)',            (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1; Navitas member with own priority row.'),
    ('WSU College/WSU-Sydney City campus (Navitas)', (SELECT id FROM dim_country WHERE code='AU'), FALSE, 'D2.R1'),
    ('ICM (Navitas)',                         (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1; International College of Manitoba.'),
    ('Toronto Metropolitan Uni Intl College (Navitas)', (SELECT id FROM dim_country WHERE code='CA'), FALSE, 'D2.R1'),
    -- Aggregate priority entries (3)
    ('Other Navitas Colleges (AU)',           (SELECT id FROM dim_country WHERE code='AU'), TRUE,  'D2.R1; D2.R4 aggregate. Members: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC.'),
    ('Other Navitas Colleges (CA)',           (SELECT id FROM dim_country WHERE code='CA'), TRUE,  'D2.R1; D2.R4 aggregate. Members: FIC, ULIC, WLIC.'),
    ('Other Navitas Colleges (NZ)',           (SELECT id FROM dim_country WHERE code='NZ'), TRUE,  'D2.R1; D2.R4 aggregate. Members: UCIC.');


-- =============================================================================
-- SECTION 3.2 — ref_priority_target (year-bound)
-- Source: D2.R1 (2024 commitments)
-- =============================================================================
INSERT INTO ref_priority_target (priority_partner_id, year, total_target, direct_target, sub_target, bonus_pct, prior_year_owing, notes)
SELECT pp.id, 2024, targets.total_target, targets.direct_target, targets.sub_target, targets.bonus_pct, 0, targets.notes
FROM (VALUES
    ('Australian Catholic University (ACU)',          6,  4, 2, 0.2500, 'D2.R1 2024'),
    ('Curtin University',                              6,  3, 3, 0.3000, 'D2.R1 2024'),
    ('Deakin University',                              6,  4, 2, 0.2500, 'D2.R1 2024'),
    ('EQI',                                           10,  3, 7, 0.3000, 'D2.R1 2024'),
    ('Griffith University',                            3,  2, 1, 0.3000, 'D2.R1 2024'),
    ('JCUB',                                           5,  3, 2, 0.2000, 'D2.R1 2024'),
    ('Kaplan Business School Australia',               4,  2, 2, 0.2000, 'D2.R1 2024'),
    ('La Trobe University',                            8,  5, 3, 0.6000, 'D2.R1 2024'),
    ('Macquarie University',                          10,  5, 5, 0.3000, 'D2.R1 2024'),
    ('Monash University',                             10,  3, 7, 0.5000, 'D2.R1 2024'),
    ('RMIT University',                                8,  3, 5, 0.2000, 'D2.R1 2024'),
    ('Swinburne University of Technology',            14,  7, 7, 0.2000, 'D2.R1 2024'),
    ('The University of Adelaide',                    14,  7, 7, 0.7000, 'D2.R1 2024'),
    ('The University of New South Wales (UNSW)',       5,  2, 3, 0.2500, 'D2.R1 2024'),
    ('The University of Queensland',                   6,  4, 2, 0.4000, 'D2.R1 2024'),
    ('University of Newcastle',                        3,  3, 0, 0.2000, 'D2.R1 2024 — admission via other agents'),
    ('University of South Australia (UniSA)',         14,  7, 7, 0.7000, 'D2.R1 2024'),
    ('University of Tasmania (UTAS)',                  5,  3, 2, 0.2500, 'D2.R1 2024'),
    ('University of Technology Sydney (UTS)',          6,  3, 3, 0.3000, 'D2.R1 2024'),
    ('University of Western Australia (UWA)',          8,  4, 4, 0.7000, 'D2.R1 2024'),
    ('VIC DET',                                       15,  7, 8, 0.2000, 'D2.R1 2024'),
    ('Algonquin College',                              4,  2, 2, 0.3000, 'D2.R1 2024'),
    ('Cape Breton University (CBU)',                   5,  5, 0, 0.5000, 'D2.R1 2024'),
    ('Braemar College',                                4,  4, 0, 0.3000, 'D2.R1 2024'),
    ('Toronto Metropolitan University',                3,  3, 0, 0.2000, 'D2.R1 2024 — admission via other agents'),
    ('University of Guelph',                           1,  1, 0, 0.4000, 'D2.R1 2024'),
    ('University of Regina',                           2,  2, 0, 0.3000, 'D2.R1 2024'),
    ('ENZ (any NZ providers count)',                  10,  5, 5, 0.4000, 'D2.R1 2024'),
    ('LightPath',                                      3,  3, 0, 0.4000, 'D2.R1 2024'),
    ('Raffles Education Network',                      1,  1, 0, 0.2000, 'D2.R1 2024'),
    ('Nanyang Institute of Management (NIM)',          1,  1, 0, 0.2000, 'D2.R1 2024'),
    ('Griffith College (Navitas)',                     2,  1, 1, 0.4000, 'D2.R1 2024'),
    ('WSU College/WSU-Sydney City campus (Navitas)',   1,  1, 0, 0.4000, 'D2.R1 2024'),
    ('ICM (Navitas)',                                  1,  1, 0, 0.4000, 'D2.R1 2024'),
    ('Toronto Metropolitan Uni Intl College (Navitas)', 1, 1, 0, 0.4000, 'D2.R1 2024'),
    ('Other Navitas Colleges (AU)',                    7,  3, 4, 0.3000, 'D2.R1 2024 aggregate'),
    ('Other Navitas Colleges (CA)',                    2,  2, 0, 0.3000, 'D2.R1 2024 aggregate'),
    ('Other Navitas Colleges (NZ)',                    1,  1, 0, 0.3000, 'D2.R1 2024 aggregate')
) AS targets(name, total_target, direct_target, sub_target, bonus_pct, notes)
JOIN ref_priority_partner pp ON pp.name = targets.name;


-- =============================================================================
-- SECTION 3.3 — ref_partner (Master Agents and Groups)
-- Source: D3.R1 (Doc 3, 27 entries: 9 Master Agents + 18 Groups)
-- =============================================================================
INSERT INTO ref_partner (name, classification, notes) VALUES
    -- Master Agents (9)
    ('Adventus',                            'MASTER_AGENT', 'D3.R1'),
    ('Amerigo Education LLC',               'MASTER_AGENT', 'D3.R1'),
    ('ApplyBoard',                          'MASTER_AGENT', 'D3.R1'),
    ('Can-Achieve',                         'MASTER_AGENT', 'D3.R1'),
    ('Educatius US',                        'MASTER_AGENT', 'D3.R1'),
    ('EduCo International',                 'MASTER_AGENT', 'D3.R1'),
    ('GEEBEE Education',                    'MASTER_AGENT', 'D3.R1'),
    ('Golden Education (GE)',               'MASTER_AGENT', 'D3.R1'),
    ('Wellspring International Education',  'MASTER_AGENT', 'D3.R1'),
    -- Groups (18)
    ('Acknowledge Education',               'GROUP', 'D3.R1'),
    ('EC English',                          'GROUP', 'D3.R1'),
    ('Education Centre of Australia (ECA)', 'GROUP', 'D3.R1'),
    ('ELS',                                 'GROUP', 'D3.R1'),
    ('FLS International',                   'GROUP', 'D3.R1'),
    ('ILAC',                                'GROUP', 'D3.R1'),
    ('INTO',                                'GROUP', 'D3.R1'),
    ('InUni',                               'GROUP', 'D3.R1'),
    ('Kaplan',                              'GROUP', 'D3.R1'),
    ('Kings Education',                     'GROUP', 'D3.R1'),
    ('Lightpath Group',                     'GROUP', 'D3.R1'),
    ('Link2Uni',                            'GROUP', 'D3.R1'),
    ('Navitas',                             'GROUP', 'D3.R1; Eynesbury and other Navitas colleges link via ref_partner_institution AND aggregate priority via ref_institution.aggregate_priority_partner_id.'),
    ('Raffles Education Network',           'GROUP', 'D3.R1; also a priority partner.'),
    ('Shorelight Education',                'GROUP', 'D3.R1'),
    ('Study Group',                         'GROUP', 'D3.R1'),
    ('Universal Learning',                  'GROUP', 'D3.R1'),
    ('UP Education',                        'GROUP', 'D3.R1');


-- =============================================================================
-- SECTION 3.5 — ref_institution
-- Source: D2.R1 priority partners (also institutions); aggregate Navitas members
--         from D2.R4. Other institutions to be added on first encounter via
--         UNVERIFIED workflow.
-- =============================================================================

-- Direct-1:1 priority institutions (each priority partner is also an institution row,
-- with classification IN_SYSTEM_PRIORITY and priority_partner_id pointing back to itself)
INSERT INTO ref_institution (canonical_name, country_id, classification, priority_partner_id, notes)
SELECT pp.name, pp.country_id, 'IN_SYSTEM_PRIORITY', pp.id, 'Direct priority institution. D2.R1.'
FROM ref_priority_partner pp
WHERE pp.is_aggregate = FALSE;

-- Aggregate Navitas member institutions (Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC)
-- These are GROUP institutions that ALSO get priority bonus via aggregate_priority_partner_id
-- Per user clarification: "Eynesbury part of Navitas Group AND aggregate priority bonus apply simultaneously"
INSERT INTO ref_institution (canonical_name, country_id, classification, aggregate_priority_partner_id, notes) VALUES
    -- AU Other Navitas members
    ('Eynesbury',          (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. Group classification + aggregate priority bonus apply simultaneously.'),
    ('Curtin College',     (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. Navitas CC.'),
    ('Edith Cowan College',(SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. ECUC.'),
    ('SAIBT',              (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. South Australian Institute of Business and Technology.'),
    ('Deakin College',     (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. DC.'),
    ('La Trobe College',   (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. LC.'),
    ('Western Sydney University International College', (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. WSUIC.'),
    ('Griffith College',   (SELECT id FROM dim_country WHERE code='AU'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (AU)'), 'D2.R1 + D2.R4 aggregate. GC. NOTE: priority entry "Griffith College (Navitas)" is a separate row — confirm with operator if these are the same school.'),
    -- CA Other Navitas members
    ('Fraser International College (FIC)',     (SELECT id FROM dim_country WHERE code='CA'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (CA)'), 'D2.R1 + D2.R4 aggregate.'),
    ('University of Lethbridge International College (ULIC)', (SELECT id FROM dim_country WHERE code='CA'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (CA)'), 'D2.R1 + D2.R4 aggregate.'),
    ('Wilfrid Laurier International College (WLIC)', (SELECT id FROM dim_country WHERE code='CA'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (CA)'), 'D2.R1 + D2.R4 aggregate.'),
    -- NZ Other Navitas members
    ('University of Canterbury International College (UCIC)', (SELECT id FROM dim_country WHERE code='NZ'), 'OUT_SYSTEM_GROUP', (SELECT id FROM ref_priority_partner WHERE name='Other Navitas Colleges (NZ)'), 'D2.R1 + D2.R4 aggregate.'),
    -- Vietnam-domestic special institutions (frequently encountered, pre-seeded)
    ('RMIT University Vietnam', (SELECT id FROM dim_country WHERE code='VN'), 'IN_SYSTEM_REGULAR', NULL, 'D6.R3/R5 RMIT VN special rate bucket. Different from RMIT University Australia.'),
    ('British University Vietnam (BUV)', (SELECT id FROM dim_country WHERE code='VN'), 'IN_SYSTEM_REGULAR', NULL, 'D6.R3/R5 BUV VN special rate bucket.');


-- =============================================================================
-- SECTION 3.7 — ref_partner_institution (junction)
-- Source: D2.R4 + D3.R1. Sparse for Master Agents per user; Group↔institution
--         links populated for Navitas members.
-- =============================================================================
INSERT INTO ref_partner_institution (partner_id, institution_id, notes)
SELECT
    (SELECT id FROM ref_partner WHERE name='Navitas'),
    i.id,
    'D2.R1 + D3.R1: ' || i.canonical_name || ' is a Navitas Group institution.'
FROM ref_institution i
WHERE i.canonical_name IN (
    'Eynesbury','Curtin College','Edith Cowan College','SAIBT','Deakin College','La Trobe College',
    'Western Sydney University International College','Griffith College',
    'Fraser International College (FIC)','University of Lethbridge International College (ULIC)',
    'Wilfrid Laurier International College (WLIC)','University of Canterbury International College (UCIC)',
    'Griffith College (Navitas)','WSU College/WSU-Sydney City campus (Navitas)',
    'ICM (Navitas)','Toronto Metropolitan Uni Intl College (Navitas)'
);


-- =============================================================================
-- SECTION 3.6 — ref_institution_alias
-- Source: BC observations and Doc 6 aliases (e.g. "RMIT VN" for "RMIT University Vietnam")
-- =============================================================================
INSERT INTO ref_institution_alias (institution_id, alias) VALUES
    ((SELECT id FROM ref_institution WHERE canonical_name='RMIT University Vietnam'), 'RMIT VN'),
    ((SELECT id FROM ref_institution WHERE canonical_name='RMIT University Vietnam'), 'RMIT Vietnam'),
    ((SELECT id FROM ref_institution WHERE canonical_name='British University Vietnam (BUV)'), 'BUV VN'),
    ((SELECT id FROM ref_institution WHERE canonical_name='British University Vietnam (BUV)'), 'BUV'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Edith Cowan College'), 'ECUC'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Edith Cowan College'), 'Edith Cowan College*'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Eynesbury'), 'Eynesbury College'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Eynesbury'), 'Eynesbury Senior College'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Deakin College'), 'Deakin College *'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Deakin University'), 'Deakin University English Centre'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Macquarie University'), 'Macquarie University - MQ'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Macquarie University'), 'Macquarie Uni'),
    ((SELECT id FROM ref_institution WHERE canonical_name='RMIT University'), 'RMIT'),
    ((SELECT id FROM ref_institution WHERE canonical_name='Monash University'), 'Monash');


-- =============================================================================
-- SECTION 4.1 — ref_status_split
-- Source: D4.R5 (Doc 4 sheet 3, 18 statuses) + D4.R6 Covid-era (kept zero-bonus
--         per user-confirmed approach) + bare "Closed - Visa granted" added.
-- Status names preserved verbatim per user instruction (drives other functions).
-- =============================================================================
INSERT INTO ref_status_split (
    status, counts_as_enrolled,
    split_couns_pct, split_co_dir_pct, split_co_sub_pct,
    is_carry_over, is_current_enrolled, is_zero_bonus,
    fees_paid_non_enrolled, is_visa_granted, deduplication_rank, notes
) VALUES
    ('Closed - Visa granted (plus enrolled)', TRUE,  1.000, 1.000, 1.000, FALSE, FALSE, FALSE, FALSE, TRUE,  5, 'D4.R5 full enrolment + visa.'),
    ('Closed - Visa granted (visa only)',     FALSE, 1.000, 1.000, 0.000, FALSE, FALSE, FALSE, FALSE, TRUE,  4, 'D4.R5 visa only — Sub split = 0.'),
    ('Closed - Visa granted then enrolled',   TRUE,  1.000, 1.000, 1.000, FALSE, FALSE, FALSE, FALSE, TRUE,  5, 'D4.R5 full.'),
    ('Closed - Visa granted then cancelled',  FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  FALSE, FALSE, 1, 'D4.R5 cancelled after visa.'),
    ('Closed - Visa refused',                 FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  TRUE,  FALSE, 1, 'D4.R5 + D1.R8: fees-paid retained → 400K rate fires per package refund policy.'),
    ('Closed - Visa refused then granted',    TRUE,  1.000, 1.000, 1.000, FALSE, FALSE, FALSE, FALSE, TRUE,  5, 'D4.R5 visa eventually granted.'),
    ('Closed - Not Exempted',                 FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  FALSE, FALSE, 1, 'D4.R6 Covid-era status. Pays zero bonus by default. Confirm handling if encountered in current data.'),
    ('Closed - Exempted',                     FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  FALSE, FALSE, 1, 'D4.R6 Covid-era status. Pays zero bonus by default. Confirm handling if encountered in current data.'),
    ('Closed - Follow up enrolment',          FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  FALSE, FALSE, 1, 'D4.R6 Covid-era status. Pays zero bonus by default. Confirm handling if encountered in current data.'),
    ('Closed - Institution refused',          FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  FALSE, FALSE, 1, 'D4.R5 institution refused — zero bonus.'),
    ('Closed - Enrolment',                    TRUE,  1.000, 1.000, 1.000, FALSE, FALSE, FALSE, FALSE, FALSE, 4, 'D4.R5 enrolment-only file (no visa needed) — full bonus.'),
    ('Closed - Enrolled then cancelled',      FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  FALSE, FALSE, 1, 'D4.R5 zero bonus.'),
    ('Closed - Enrolled then visa refused',   FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  TRUE,  FALSE, 1, 'D4.R5 + D1.R8 fees-paid retained.'),
    ('Closed - Enrolled, then Visa granted',  TRUE,  0.000, 0.500, 0.500, TRUE,  FALSE, FALSE, FALSE, TRUE,  3, 'D4.R5 carry-over: enrolled prior month, visa just granted. CO/Sub get remaining 50% (Counsellor was paid 100% prior month).'),
    ('Closed - Cancelled',                    FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  TRUE,  FALSE, 1, 'D4.R5 + D1.R8 fees-paid retained → 400K may fire per package refund policy.'),
    ('Current - Enrolled',                    TRUE,  1.000, 0.500, 0.500, FALSE, TRUE,  FALSE, FALSE, FALSE, 2, 'D4.R5 advance: Counsellor 100%, CO/Sub 50% — balance pays when visa+file close.'),
    ('Current - Visa refused',                FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  TRUE,  FALSE, 1, 'D4.R5 zero — fees-paid retained.'),
    ('Pending - Visa refused',                FALSE, 0.000, 0.000, 0.000, FALSE, FALSE, TRUE,  TRUE,  FALSE, 1, 'D4.R5 zero — fees-paid retained.'),
    ('Closed - Visa granted',                 TRUE,  1.000, 1.000, 1.000, FALSE, FALSE, FALSE, FALSE, TRUE,  5, 'D4.R7 bare "Closed - Visa granted" (no qualifier). Treated equivalent to "Closed - Visa granted (plus enrolled)" by default. Operator should disambiguate at data entry where possible.');


-- =============================================================================
-- SECTION 4.2 — ref_client_weight
-- Source: D4.R1 (Doc 4 sheet 1: 9 client types × 5 channels)
-- =============================================================================
INSERT INTO ref_client_weight (client_type_code, weight_in_system, weight_sub_agent, weight_master_agent, weight_out_system, weight_out_system_usa_28m, notes) VALUES
    ('DU_HOC_FULL',          1.000, 0.700, 0.700, 0.000, 0.700, 'D4.R1 Du học (Ghi danh + visa). Most common.'),
    ('DU_HOC_ENROL_ONLY',    1.000, 0.000, 0.700, 0.000, 0.700, 'D4.R1 Du học (Ghi danh). Sub agent column = 0 (no visa).'),
    ('SUMMER_STUDY',         0.000, 0.000, 0.000, 0.000, 0.000, 'D4.R1 Du học hè. Zero target weight; flat rate per Doc 6.'),
    ('VIETNAM_DOMESTIC',     0.500, 0.000, 0.000, 0.000, 0.000, 'D4.R1 + D4.R2 Du học tại chỗ. 0.5 weight, in-system Direct only. Flat 1M rule per ref_local_enrolment_bonus.'),
    ('GUARDIAN_VISA',        0.000, 0.000, 0.000, 0.000, 0.000, 'D4.R1 + D4.R3 Visa Giám hộ. Zero target; flat rate per Doc 6.'),
    ('TOURIST_VISA',         0.000, 0.000, 0.000, 0.000, 0.000, 'D4.R1 + D4.R3 Visa Du lịch. Zero target.'),
    ('MIGRATION_VISA',       0.000, 0.000, 0.000, 0.000, 0.000, 'D4.R1 + D4.R3 Visa Định cư. Zero target.'),
    ('DEPENDANT_VISA',       0.000, 0.000, 0.000, 0.000, 0.000, 'D4.R1 + D4.R3 Visa Phụ thuộc. Zero target.'),
    ('VISA_ONLY_SERVICE',    0.000, 0.000, 0.000, 0.000, 0.000, 'D4.R1 + D4.R3 Visa Du học only. Zero target.');


-- =============================================================================
-- SECTION 4.3 — ref_client_type_alias
-- Source: D4.R1 row labels (Vietnamese) + English variants
-- =============================================================================
INSERT INTO ref_client_type_alias (client_type_code, alias) VALUES
    ('DU_HOC_FULL',       'Du học (Ghi danh + visa)'),
    ('DU_HOC_FULL',       'Du học (ghi danh + visa)'),
    ('DU_HOC_FULL',       'Study + Visa'),
    ('DU_HOC_ENROL_ONLY', 'Du học (Ghi danh)'),
    ('DU_HOC_ENROL_ONLY', 'Du học (ghi danh)'),
    ('DU_HOC_ENROL_ONLY', 'Enrolment only'),
    ('SUMMER_STUDY',      'Du học hè'),
    ('SUMMER_STUDY',      'Summer'),
    ('SUMMER_STUDY',      'Summer abroad'),
    ('VIETNAM_DOMESTIC',  'Du học tại chỗ (Vietnam)'),
    ('VIETNAM_DOMESTIC',  'Du học tại chỗ'),
    ('VIETNAM_DOMESTIC',  'VN Domestic'),
    ('GUARDIAN_VISA',     'Visa Giám hộ'),
    ('GUARDIAN_VISA',     'Guardian'),
    ('TOURIST_VISA',      'Visa Du lịch'),
    ('TOURIST_VISA',      'Tourist'),
    ('TOURIST_VISA',      'Visitor'),
    ('MIGRATION_VISA',    'Visa Định cư'),
    ('MIGRATION_VISA',    'Settlement'),
    ('MIGRATION_VISA',    'Migration'),
    ('DEPENDANT_VISA',    'Visa Phụ thuộc'),
    ('DEPENDANT_VISA',    'Dependant'),
    ('DEPENDANT_VISA',    'Dependent'),
    ('VISA_ONLY_SERVICE', 'Visa Du học only'),
    ('VISA_ONLY_SERVICE', 'Visa only');


-- =============================================================================
-- SECTION 4.4 — ref_rate
-- Source: D6.R2-R7 (Doc 6 rate sheets: HCM, HN/DN, Sub-agent)
-- Effective from 2021-09-01 per Doc 6 sheet name "2021-Sep" (first effective).
-- VP rates are seeded as a copy of COUNS_DIR rates per office per user direction.
-- =============================================================================

-- Helper notes:
--   - "TARGET" country bucket = the 14 with-target countries (D1.R2)
--   - "FLAT" = TH, KR, MY, PH (D1.R6 + D6.R9)
--   - "VN_RMIT", "VN_BUV", "VN_OTHER" = Vietnam-domestic sub-buckets (D6.R3/R5/R7)
--   - "SUMMER" = du học hè (D6.R3 row "Summer")
--   - Tier "OUT_SYSTEM" = "Out-system / Fees paid yet visa refused / Extra high risk"
--   - Tier "VISA_ONLY" = "Visa only (first visa)"
--   - Tier "FLAT" = applies to flat-rate countries (TH/KR/MY/PH) at single rate

-- HCM Counsellor + CO_Dir rates: TARGET bucket
INSERT INTO ref_rate (office_id, role_id, country_bucket, tier, amount, effective_from, notes) VALUES
    -- HCM Counsellor (COUNS_DIR), TARGET countries (D6.R2)
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'TARGET', 'OUT_SYSTEM',  600000,  '2021-09-01', 'D6.R2 HCM Couns Out-system'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'TARGET', 'UNDER',      1000000, '2021-09-01', 'D6.R2 HCM Couns Under'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'TARGET', 'MEET_HIGH',  1400000, '2021-09-01', 'D6.R2 HCM Couns Meet w/ incentive ≥5M'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'TARGET', 'MEET_LOW',   1800000, '2021-09-01', 'D6.R2 HCM Couns Meet w/o incentive'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'TARGET', 'OVER',       2200000, '2021-09-01', 'D6.R2 HCM Couns Over'),
    -- HCM CO_DIR, TARGET countries
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'TARGET', 'OUT_SYSTEM',  400000, '2021-09-01', 'D6.R2 HCM CO Out-system'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'TARGET', 'VISA_ONLY',   600000, '2021-09-01', 'D6.R2 HCM CO Visa-only first visa'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'TARGET', 'UNDER',       800000, '2021-09-01', 'D6.R2 HCM CO Under'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'TARGET', 'MEET_HIGH',  1000000, '2021-09-01', 'D6.R2 HCM CO Meet w/ incentive'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'TARGET', 'MEET_LOW',   1400000, '2021-09-01', 'D6.R2 HCM CO Meet w/o incentive'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'TARGET', 'OVER',       1800000, '2021-09-01', 'D6.R2 HCM CO Over'),
    -- HCM FLAT countries (D6.R3 THAI/PHIL/ML)
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'FLAT',   'FLAT',       1000000, '2021-09-01', 'D6.R3 HCM Couns flat (TH/PH/MY/KR)'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='CO_DIR'),    'FLAT',   'FLAT',        500000, '2021-09-01', 'D6.R3 HCM CO flat'),
    -- HCM VN-domestic (D6.R3)
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'VN_RMIT','FLAT',       1000000, '2021-09-01', 'D6.R3 HCM Couns RMIT VN under/post-grad'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'VN_BUV', 'FLAT',       1000000, '2021-09-01', 'D6.R3 HCM Couns BUV VN under/post-grad'),
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'VN_OTHER','FLAT',       500000, '2021-09-01', 'D6.R3 HCM Couns Other VN programs / RMIT Eng / BUV Eng'),
    -- HCM Summer (D6.R3)
    ((SELECT id FROM dim_office WHERE code='HCM'), (SELECT id FROM dim_role WHERE code='COUNS_DIR'), 'SUMMER', 'FLAT',        600000, '2021-09-01', 'D6.R3 HCM Couns Summer study');

-- HN/DN Counsellor + CO_Dir rates (D6.R4) — applies to both HN and DN offices.
INSERT INTO ref_rate (office_id, role_id, country_bucket, tier, amount, effective_from, notes)
SELECT
    o.id, r.id, br.country_bucket, br.tier, br.amount, '2021-09-01', br.notes
FROM (VALUES
    ('COUNS_DIR', 'TARGET', 'OUT_SYSTEM',  600000,  'D6.R4 HN/DN Couns Out-system'),
    ('COUNS_DIR', 'TARGET', 'UNDER',       900000,  'D6.R4 HN/DN Couns Under'),
    ('COUNS_DIR', 'TARGET', 'MEET_HIGH',  1000000,  'D6.R4 HN/DN Couns Meet w/ incentive'),
    ('COUNS_DIR', 'TARGET', 'MEET_LOW',   1400000,  'D6.R4 HN/DN Couns Meet w/o incentive'),
    ('COUNS_DIR', 'TARGET', 'OVER',       1700000,  'D6.R4 HN/DN Couns Over'),
    ('CO_DIR',    'TARGET', 'OUT_SYSTEM',  400000,  'D6.R4 HN/DN CO Out-system'),
    ('CO_DIR',    'TARGET', 'VISA_ONLY',   600000,  'D6.R4 HN/DN CO Visa-only'),
    ('CO_DIR',    'TARGET', 'UNDER',       700000,  'D6.R4 HN/DN CO Under'),
    ('CO_DIR',    'TARGET', 'MEET_HIGH',   800000,  'D6.R4 HN/DN CO Meet w/ incentive'),
    ('CO_DIR',    'TARGET', 'MEET_LOW',   1100000,  'D6.R4 HN/DN CO Meet w/o incentive'),
    ('CO_DIR',    'TARGET', 'OVER',       1300000,  'D6.R4 HN/DN CO Over'),
    -- FLAT countries (D6.R5)
    ('COUNS_DIR', 'FLAT',   'FLAT',        800000,  'D6.R5 HN/DN Couns flat'),
    ('CO_DIR',    'FLAT',   'FLAT',        400000,  'D6.R5 HN/DN CO flat'),
    -- VN-domestic + Summer (D6.R5 same as HCM)
    ('COUNS_DIR', 'VN_RMIT','FLAT',       1000000,  'D6.R5 HN/DN Couns RMIT VN'),
    ('COUNS_DIR', 'VN_BUV', 'FLAT',       1000000,  'D6.R5 HN/DN Couns BUV VN'),
    ('COUNS_DIR', 'VN_OTHER','FLAT',       500000,  'D6.R5 HN/DN Couns Other VN'),
    ('COUNS_DIR', 'SUMMER', 'FLAT',        600000,  'D6.R5 HN/DN Couns Summer')
) AS br(role_code, country_bucket, tier, amount, notes)
JOIN dim_role r ON r.code = br.role_code
CROSS JOIN dim_office o
WHERE o.code IN ('HN','DN');

-- CO_SUB rates: ENROL_ONLY_VISA_ONLY sub-scheme (D6.R6 first sub-scheme)
-- Per Phase 3: Trường An and Loi both use this. Office = HCM as default home,
-- but rate applies regardless of office (CO_SUB is sub-agent network).
INSERT INTO ref_rate (office_id, role_id, co_sub_subscheme, country_bucket, tier, amount, effective_from, notes)
SELECT
    o.id,
    (SELECT id FROM dim_role WHERE code='CO_SUB'),
    'ENROL_ONLY_VISA_ONLY',
    br.country_bucket, br.tier, br.amount, '2021-09-01', br.notes
FROM (VALUES
    ('TARGET',  'OUT_SYSTEM',  400000, 'D6.R6 Sub: Enroll only thru a partner — flat 400K'),
    ('TARGET',  'UNDER',       700000, 'D6.R6 Sub Enrol-only-visa-only Under'),
    ('TARGET',  'MEET_HIGH',   900000, 'D6.R6 Sub Enrol-only-visa-only Meet (incentive does not split this scheme; treat MEET_HIGH=MEET_LOW=900K)'),
    ('TARGET',  'MEET_LOW',    900000, 'D6.R6 Sub Enrol-only-visa-only Meet'),
    ('TARGET',  'OVER',       1100000, 'D6.R6 Sub Enrol-only-visa-only Over'),
    ('FLAT',    'FLAT',        600000, 'D6.R7 Sub flat countries Under tier'),
    ('VN_RMIT', 'FLAT',        600000, 'D6.R7 Sub RMIT VN'),
    ('VN_BUV',  'FLAT',        600000, 'D6.R7 Sub BUV VN'),
    ('VN_OTHER','FLAT',        300000, 'D6.R7 Sub Other VN'),
    ('SUMMER',  'FLAT',        300000, 'D6.R7 Sub Summer')
) AS br(country_bucket, tier, amount, notes)
CROSS JOIN dim_office o
WHERE o.code IN ('HCM','HN','DN');

-- CO_SUB rates: ENROL_PLUS_VISA sub-scheme (D6.R6 second sub-scheme)
INSERT INTO ref_rate (office_id, role_id, co_sub_subscheme, country_bucket, tier, amount, effective_from, notes)
SELECT
    o.id,
    (SELECT id FROM dim_role WHERE code='CO_SUB'),
    'ENROL_PLUS_VISA',
    br.country_bucket, br.tier, br.amount, '2021-09-01', br.notes
FROM (VALUES
    ('TARGET', 'UNDER',     800000,  'D6.R6 Sub Enrol-plus-visa Under'),
    ('TARGET', 'MEET_HIGH', 1100000, 'D6.R6 Sub Enrol-plus-visa Meet'),
    ('TARGET', 'MEET_LOW',  1100000, 'D6.R6 Sub Enrol-plus-visa Meet'),
    ('TARGET', 'OVER',      1300000, 'D6.R6 Sub Enrol-plus-visa Over')
) AS br(country_bucket, tier, amount, notes)
CROSS JOIN dim_office o
WHERE o.code IN ('HCM','HN','DN');

-- VP rates: starting point — copy COUNS_DIR rates from same office per user direction.
-- VP_DN rates = HN/DN COUNS_DIR rates (since DN follows HN/DN scheme).
-- VP_MEL initial seed = HCM COUNS_DIR rates (placeholder until MEL scheme defined).
-- Operator can override per VP-office once schemes are confirmed.
INSERT INTO ref_rate (office_id, role_id, country_bucket, tier, amount, effective_from, notes)
SELECT
    r.office_id,
    (SELECT id FROM dim_role WHERE code='VP'),
    r.country_bucket, r.tier, r.amount, r.effective_from,
    'VP seed: copied from COUNS_DIR ' || (SELECT code FROM dim_office WHERE id=r.office_id) || ' per user direction. Adjust when VP scheme is finalised.'
FROM ref_rate r
WHERE r.role_id = (SELECT id FROM dim_role WHERE code='COUNS_DIR')
  AND r.office_id IN (SELECT id FROM dim_office WHERE code IN ('DN'));

INSERT INTO ref_rate (office_id, role_id, country_bucket, tier, amount, effective_from, notes)
SELECT
    (SELECT id FROM dim_office WHERE code='MEL'),
    (SELECT id FROM dim_role WHERE code='VP'),
    r.country_bucket, r.tier, r.amount, r.effective_from,
    'VP_MEL seed: placeholder copy of HCM COUNS_DIR rates. Adjust when MEL scheme is finalised.'
FROM ref_rate r
WHERE r.role_id = (SELECT id FROM dim_role WHERE code='COUNS_DIR')
  AND r.office_id = (SELECT id FROM dim_office WHERE code='HCM');


-- =============================================================================
-- SECTION 4.5 — ref_calculation_param
-- Source: scattered through Phase 1 — gathered as named scalars
-- =============================================================================
INSERT INTO ref_calculation_param (param_code, value_numeric, effective_from, notes) VALUES
    ('INCENTIVE_THRESHOLD',           5000000,    '2021-09-01', 'D6.R2/R4 — MEET_HIGH if monthly bonus ≥5M, else MEET_LOW.'),
    ('PRESALES_FLAT_FEE',             200000,     '2024-06-01', 'User-confirmed: Pre-sales rule A — 200K flat per case when slot filled.'),
    ('LOVELY_COFFEE_REFERRAL',        100000,     '2024-06-01', 'D1.R10 — Lovely Cup of Coffee referral to add-on partner: 100K flat.'),
    ('CARRY_OVER_PCT',                0.5000,     '2024-06-01', 'D1.R11/R12 — 50% pays this month, 50% next.'),
    ('CURRENT_ENROLLED_CO_PCT',       0.5000,     '2024-06-01', 'D4.R5 — Current Enrolled CO Direct/Sub split.'),
    ('PRIORITY_PRE_KPI_MULTIPLIER',   0.5000,     '2024-06-01', 'D2.R2/D4.R9 — 50% paid at enrolment, 50% after KPI met for partner.'),
    ('TWO_OUT_TARGET_EQUIV',          1.0,        '2024-06-01', 'D1.R6 — 2 out-target = 1 target equivalent (US: 1.4).'),
    ('TWO_OUT_TARGET_EQUIV_US',       1.4,        '2024-06-01', 'D1.R6 — US 2 out-target = 1.4 target.'),
    ('NEW_COUNS_HANDOVER_TARGET_CREDIT', 0,       '2024-06-01', 'D1.R15 — Handover clients do NOT count to new Counsellor target unless replan.'),
    ('OUT_SYSTEM_DIFFICULT_EXTRA',    500000,     '2022-01-11', 'D11.R4/R5 + D13.R3/R5 — Difficult-case extra 500K added to OUT_SYSTEM tier.');


-- =============================================================================
-- SECTION 4.6 — ref_service_fee
-- Source: Docs 7, 8, 10, 11, 12, 13 + addenda (D7.R10-R14, D9, D10.R2)
-- Effective dates from doc effective dates where stated.
-- =============================================================================
-- AP packages (Docs 10 + 11)
INSERT INTO ref_service_fee (service_code, category, country_id, fee_amount, counsellor_signing_bonus, co_signing_bonus, counsellor_deductible_on_refusal, refund_on_visa_refused, refund_on_cancel, description, effective_from, notes) VALUES
    ('AP_GOI_1_STANDARD',         'PACKAGE', NULL, 0,        0,       0,      FALSE, 0,       0, 'AP Gói 1 Standard — Free service, no deposit. D11.R2.',                    '2022-01-11', 'D11.R2'),
    ('AP_GOI_2_STANDARD_PLUS',    'PACKAGE', NULL, 3000000,  500000,  0,      FALSE, 1500000, 0, 'AP Gói 2 Standard Plus — 3M deposit; signing bonus 500K not deductible on refusal. D11.R3.', '2022-01-11', 'D11.R3'),
    ('AP_GOI_3_SUPERIOR',         'PACKAGE', NULL, 6000000,  1000000, 500000, TRUE,  6000000, 0, 'AP Gói 3 Superior — 6M fee; signing 1M deductible on refusal; CO 500K. D11.R4.', '2022-01-11', 'D11.R4'),
    ('AP_GOI_4_PREMIUM_HCM',      'PACKAGE', NULL, 9000000,  1500000, 500000, TRUE,  9000000, 0, 'AP Gói 4 Premium — 9M fee, HCM only; signing 1.5M deductible on refusal; CO 500K. D11.R5.', '2022-01-11', 'D11.R5'),
    -- Canada packages (Doc 12)
    ('CA_GOI_1_SDS',              'PACKAGE', (SELECT id FROM dim_country WHERE code='CA'), 7000000, 0,       0,      FALSE, 0,       0,       'CA Gói 1 SDS — Fee updated to 7M per D7.R10. Bonus per scheme on enrolment.', '2022-04-12', 'D12.R2 + D7.R10 update'),
    ('CA_GOI_2_STANDARD_REGULAR', 'PACKAGE', (SELECT id FROM dim_country WHERE code='CA'), 9500000, 1000000, 0,      FALSE, 3000000, 0,       'CA Gói 2 Standard Regular — 9.5M fee; signing 1M not deductible. D12.R3.', '2022-04-12', 'D12.R3'),
    ('CA_GOI_3_PREMIUM',          'PACKAGE', (SELECT id FROM dim_country WHERE code='CA'), 14000000, 2000000, 500000, FALSE, 7000000, 0,      'CA Gói 3 Premium — 14M fee; signing 2M not deductible; CO 500K. D12.R4.', '2022-04-12', 'D12.R4'),
    -- US packages (Doc 13)
    ('US_GOI_1_STANDARD_INFULL',  'PACKAGE', (SELECT id FROM dim_country WHERE code='US'), 16000000, 1000000, 0,      TRUE,  3500000, 0,      'US Gói 1 Standard In-Full — 16M; signing 1M deductible on refusal. D13.R2.',  '2021-09-22', 'D13.R2'),
    ('US_GOI_2_SUPERIOR_INFULL',  'PACKAGE', (SELECT id FROM dim_country WHERE code='US'), 45000000, 2000000, 500000, TRUE,  22000000, 0,     'US Gói 2 Superior In-Full — 45M; signing 2M deductible; CO 500K. D13.R3.',  '2021-09-22', 'D13.R3'),
    ('US_GOI_3_STANDARD_OUTFULL', 'PACKAGE', (SELECT id FROM dim_country WHERE code='US'), 28000000, 500000,  0,      TRUE,  14000000, 0,     'US Gói 3 Standard Out-Full — 28M; signing 500K deductible; counts as in-system per D7.R12. D13.R4.', '2021-09-22', 'D13.R4'),
    ('US_GOI_4_SUPERIOR_OUTFULL', 'PACKAGE', (SELECT id FROM dim_country WHERE code='US'), 68000000, 1500000, 500000, TRUE,  22000000, 0,     'US Gói 4 Superior Out-Full — 68M; signing 1.5M deductible; CO 500K. D13.R5.', '2021-09-22', 'D13.R5'),
    -- AP add-on for AU difficult cases / out-system (D10.R2)
    ('AP_DIFFICULT_CASE_AU',      'ADDON',   (SELECT id FROM dim_country WHERE code='AU'), 20000000, 1100000, 0,      TRUE,  5000000, 0,       'D10.R2 AU Difficult cases / Out-system Full — 1.1M signing bonus.', '2022-01-11', 'D10.R2'),
    ('AP_DIFFICULT_CASE_NZ',      'ADDON',   (SELECT id FROM dim_country WHERE code='NZ'), 20000000, 1100000, 0,      TRUE,  5000000, 0,       'D10.R2 NZ Difficult cases / Out-system Full — 1.1M signing bonus.', '2022-01-11', 'D10.R2'),
    -- Guardian AU add-on (D6.R8 / Doc 6 entry "Guardian ÚC (Aug 2022+)")
    ('GUARDIAN_AU_ADDON',         'ADDON',   (SELECT id FROM dim_country WHERE code='AU'), 0,        0,       250000, FALSE, 0,        0,      'D6.R8 Guardian AU add-on (post Aug 2022): 250K total split 50/50 between Couns and CO = 125K each. Stack on tier + package bonus.', '2022-08-01', 'D6.R8'),
    -- Out-of-frame service fees (signing bonuses from D7 addenda)
    ('OUT_SYSTEM_FULL_SERVICE_30M', 'SERVICE_FEE', NULL, 30000000, 500000, 0, TRUE, 5000000, 0, 'D7.R12 Out-system full service 30M (was 14M). Signing 500K deductible on refusal. Counts as 1 in-system target.', '2022-04-12', 'D7.R12'),
    ('OUT_SYSTEM_MASTER_AGENT_14M', 'SERVICE_FEE', NULL, 14000000, 1000000, 0, FALSE, 0, 0, 'D7.R13 Out-system via Master Agent 14M. Signing 1M NOT deductible. Counts as 1 in-system target. Target counted via master agent commission.', '2022-04-12', 'D7.R13'),
    -- VN-domestic local enrolment placeholder (the actual flat-1M rule lives in ref_local_enrolment_bonus)
    ('VN_LOCAL_ENROLMENT',        'SERVICE_FEE', (SELECT id FROM dim_country WHERE code='VN'), 0, 0, 0, FALSE, 0, 0, 'VN-domestic local enrolment marker. Bonus calc uses ref_local_enrolment_bonus (1M flat split rule).', '2024-06-01', 'User-confirmed VN-domestic flat 1M rule');


-- =============================================================================
-- SECTION 4.7 — ref_service_fee_alias
-- Source: BC observations (Vietnamese package nicknames)
-- =============================================================================
INSERT INTO ref_service_fee_alias (service_fee_id, alias) VALUES
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_2_STANDARD_PLUS'),    'Standard Plus 3tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_2_STANDARD_PLUS'),    'Gói 2'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_2_STANDARD_PLUS'),    'Standard Plus Package'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_3_SUPERIOR'),         'Superior 6tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_3_SUPERIOR'),         'Superior Package 6tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_3_SUPERIOR'),         'Gói 3'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_3_SUPERIOR'),         'Superior Package'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_4_PREMIUM_HCM'),      'Premium 9tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_4_PREMIUM_HCM'),      'Premium package 9tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_4_PREMIUM_HCM'),      'Gói 4'),
    ((SELECT id FROM ref_service_fee WHERE service_code='AP_GOI_4_PREMIUM_HCM'),      'Premium Package'),
    ((SELECT id FROM ref_service_fee WHERE service_code='CA_GOI_1_SDS'),              'SDS'),
    ((SELECT id FROM ref_service_fee WHERE service_code='CA_GOI_2_STANDARD_REGULAR'), 'standard regular 9tr5'),
    ((SELECT id FROM ref_service_fee WHERE service_code='CA_GOI_2_STANDARD_REGULAR'), 'Standard Regular'),
    ((SELECT id FROM ref_service_fee WHERE service_code='CA_GOI_3_PREMIUM'),          'CA Premium 14tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='US_GOI_1_STANDARD_INFULL'),  'Standard Package 16tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='US_GOI_2_SUPERIOR_INFULL'),  'Superior Package 45tr'),
    ((SELECT id FROM ref_service_fee WHERE service_code='US_GOI_3_STANDARD_OUTFULL'), '30tr (1 out = 1 in)'),
    ((SELECT id FROM ref_service_fee WHERE service_code='US_GOI_4_SUPERIOR_OUTFULL'), 'Superior Out-Full 68tr');


-- =============================================================================
-- SECTION 5.1 — ref_local_enrolment_bonus
-- Source: User-confirmed (supersedes Doc 4 sheet 1 0.5 weight rule).
-- VN-domestic flat 1M; Couns_Dir alone gets 100%, paired with CO splits 50/50.
-- Pre-sales rules apply on top per ref_calculation_param + tx_case.presales_share_pct.
-- =============================================================================
INSERT INTO ref_local_enrolment_bonus (country_id, flat_total_amount, couns_dir_alone_pct, couns_dir_with_co_pct, co_pct_when_paired, effective_from, notes) VALUES
    ((SELECT id FROM dim_country WHERE code='VN'), 1000000, 1.000, 0.500, 0.500, '2024-06-01', 'User-confirmed VN-domestic flat 1M rule. Couns_Dir alone: 100%. With CO: 50/50. Pre-sales applies on top.');


-- =============================================================================
-- SECTION 5.2 — ref_contract_target_tier
-- Source: D1.R31 + D1.R32 (Doc 1 §II.4)
-- =============================================================================
INSERT INTO ref_contract_target_tier (office_id, target_min, target_max, excess_per_contract_amount, consecutive_3mo_per_contract, premium_min_target, premium_per_contract_amount, in_system_min_pct, visa_pass_min_pct, effective_from, notes)
SELECT o.id, 2, 4, 100000, 200000, NULL, NULL, 0.800, 0.750, '2024-06-01',
       'D1.R31(i) HCM/HN/DN: target 2≤target<4 → +100K per excess contract for all month''s contracts. (ii) 3 consec months exceeding → +200K per total quarter contracts.'
FROM dim_office o WHERE o.code IN ('HCM','HN','DN');

INSERT INTO ref_contract_target_tier (office_id, target_min, target_max, excess_per_contract_amount, consecutive_3mo_per_contract, premium_min_target, premium_per_contract_amount, in_system_min_pct, visa_pass_min_pct, effective_from, notes)
SELECT o.id, 4, NULL, 200000, 200000, 4, 2200000, 0.800, 0.750, '2024-06-01',
       'D1.R31(i)/R32 HCM/HN/DN: target ≥4 → +200K per excess. R32 premium tier: when target ≥4 AND >10/mo or doubled-target → 2.2M per excess.'
FROM dim_office o WHERE o.code IN ('HCM','HN','DN');


-- =============================================================================
-- SECTION 5.3 — ref_contract_package_eligibility
-- Source: D1.R34 (eligible packages for excess bonus)
-- =============================================================================
-- Note: Most packages get the standard excess rates from ref_contract_target_tier.
-- Only the special CA 7.5M case has different excess values (80K low, 140K high).
INSERT INTO ref_contract_package_eligibility (service_fee_id, excess_low_target_amount, excess_high_target_amount, effective_from, notes)
SELECT sf.id, 100000, 200000, '2024-06-01', 'D1.R34 Eligible package: ' || sf.service_code
FROM ref_service_fee sf
WHERE sf.service_code IN (
    'AP_GOI_3_SUPERIOR',          -- AP 6M, 9M, 20M
    'AP_GOI_4_PREMIUM_HCM',
    'AP_DIFFICULT_CASE_AU',
    'AP_DIFFICULT_CASE_NZ',
    'CA_GOI_2_STANDARD_REGULAR',  -- CA 9.5M
    'CA_GOI_3_PREMIUM',           -- CA 14M
    'US_GOI_1_STANDARD_INFULL',   -- US 16M
    'US_GOI_3_STANDARD_OUTFULL'   -- US 28M, 45M
);
-- Special CA 7.5M case: SDS pre-update fee. Note: SDS fee is now 7M per D7.R10 but
-- D1.R34 specifically mentions 7.5M Canada with 80K/140K excess rates.
INSERT INTO ref_contract_package_eligibility (service_fee_id, excess_low_target_amount, excess_high_target_amount, effective_from, notes)
SELECT sf.id, 80000, 140000, '2024-06-01', 'D1.R34 special: CA 7.5M SDS pre-update — 80K low / 140K high excess.'
FROM ref_service_fee sf WHERE sf.service_code = 'CA_GOI_1_SDS';


-- =============================================================================
-- SECTION 5.4 — ref_team_excess_bonus
-- Source: D1.R25-R27 + D1.R30
-- =============================================================================
INSERT INTO ref_team_excess_bonus (bonus_code, description, immediate_amount, confirmed_amount, target_threshold, team_fund_retention_pct, effective_from, notes) VALUES
    ('NATIONAL_TEAM_ENROL',   'D1.R25 National Couns/CO team excess (excludes sub-agent). 10M immediate + 10M after Finance confirms 100% enrol.', 10000000, 10000000, NULL, 0.200, '2024-06-01', 'D1.R25; 20% retained for team fund.'),
    ('PAIR_ENROL_3PLUS',      'D1.R26 Couns/CO pair with target ≥3/month exceeds. 2M immediate + 1M after Finance.', 2000000, 1000000, 3, 0.000, '2024-06-01', 'D1.R26'),
    ('SUB_TEAM_EXCESS',       'D1.R27 Sub-agent team excess. 3M immediate + 3M after Finance.', 3000000, 3000000, NULL, 0.000, '2024-06-01', 'D1.R27'),
    ('COUNS_TEAM_CONTRACT',   'D1.R30 Whole Counsellor/Sales team excess monthly contract (excludes sub-agent). 5M immediate; 20% retained.', 5000000, 0, NULL, 0.200, '2024-06-01', 'D1.R30');


-- =============================================================================
-- SECTION 5.5 — ref_departure_rule
-- Source: D1.R20 (3 file-count tiers for pre-lodge handover allowance)
-- =============================================================================
INSERT INTO ref_departure_rule (rule_code, files_count_min, files_count_max, monthly_allowance, duration_months, case_stage, settlement_delay_months, effective_from, notes) VALUES
    ('PRELODGE_HANDOVER_1_TO_5',   1,  5,  500000,  6, 'PRELODGE', 6, '2024-06-01', 'D1.R20 Option B: 500K/mo × 6mo for 1-5 pre-lodge handover files.'),
    ('PRELODGE_HANDOVER_6_TO_10',  6,  10, 1000000, 6, 'PRELODGE', 6, '2024-06-01', 'D1.R20 Option B: 1M/mo × 6mo for 6-10 files.'),
    ('PRELODGE_HANDOVER_11_TO_15', 11, 15, 1500000, 6, 'PRELODGE', 6, '2024-06-01', 'D1.R20 Option B: 1.5M/mo × 6mo for 11-15 files.');


-- =============================================================================
-- SECTION 5.6 — ref_complaint_deduction
-- Source: D1.R16-R19 + D1.R24
-- =============================================================================
INSERT INTO ref_complaint_deduction (rule_code, description, deduction_scope, effective_from, notes) VALUES
    ('SERIOUS_COMPLAINT_MONTHLY',     'Customer or partner serious complaint due to staff negligence — full bonus deducted for the month.', 'WHOLE_MONTH', '2024-06-01', 'D1.R16'),
    ('POST_DEPARTURE_COMPLAINT',      'Complaint arises during handover or post-departure — all post-departure bonus forfeited.', 'POST_DEPARTURE', '2024-06-01', 'D1.R17'),
    ('CO_REFUSED_HANDOVER',           'Senior CO refusing handover when ordered (≤40 Current files / ≤60 Senior CO) — full bonus deducted up to refusal date.', 'UP_TO_REFUSAL', '2024-06-01', 'D1.R19'),
    ('POST_DEPARTURE_DATA_THEFT',     'Evidence of post-departure customer data theft — all bonus forfeited.', 'ALL_BONUS', '2024-06-01', 'D1.R24');


-- =============================================================================
-- END OF REFERENCE DATA
-- =============================================================================
-- Next file: 03_staff_data.sql (staff registry, aliases, monthly targets)
-- =============================================================================
