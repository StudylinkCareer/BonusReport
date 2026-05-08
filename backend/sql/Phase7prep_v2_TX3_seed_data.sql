-- =============================================================================
-- Phase7prep_v2_TX3_seed_data.sql
-- Run AFTER Phase7prep_v2_TX2_rebuild_schema.sql succeeded.
-- =============================================================================

-- ╔════════════════════════════════════════════════════════════════════════════╗
-- ║  TRANSACTION 3 — DATA SEEDING + Phase 6l fixes                             ║
-- ╚════════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3.1 Reclassify institutions
--     IN_SYSTEM_REGULAR        → IN_SYSTEM
--     OUT_SYSTEM_GROUP         → IN_SYSTEM
--     OUT_SYSTEM_MASTER_AGENT  → IN_SYSTEM
--     IN_SYSTEM_PRIORITY       → IN_SYSTEM
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE ref_institution SET classification = 'IN_SYSTEM'
 WHERE classification IN (
     'IN_SYSTEM_REGULAR',
     'IN_SYSTEM_PRIORITY',
     'OUT_SYSTEM_GROUP',
     'OUT_SYSTEM_MASTER_AGENT'
 );

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
-- 3.2 Seed ref_partner_classification (27 rows)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_partner_classification
    (partner_id, category, kpi_weight, bonus_model, effective_from, notes)
SELECT
    p.id,
    CASE p.name
        WHEN 'ApplyBoard'                       THEN 'MASTER_AGENT_GENUINE'
        WHEN 'Can-Achieve'                      THEN 'MASTER_AGENT_GENUINE'
        WHEN 'Adventus'                         THEN 'MASTER_AGENT_OOS'
        WHEN 'Amerigo Education LLC'            THEN 'MASTER_AGENT_OOS'
        WHEN 'Educatius US'                     THEN 'MASTER_AGENT_OOS'
        WHEN 'EduCo International'              THEN 'MASTER_AGENT_OOS'
        WHEN 'GEEBEE Education'                 THEN 'MASTER_AGENT_OOS'
        WHEN 'Golden Education (GE)'            THEN 'MASTER_AGENT_OOS'
        WHEN 'Wellspring International Education' THEN 'MASTER_AGENT_OOS'
        ELSE 'GROUP'
    END,
    CASE WHEN p.name IN ('ApplyBoard','Can-Achieve','Adventus','Amerigo Education LLC',
                          'Educatius US','EduCo International','GEEBEE Education',
                          'Golden Education (GE)','Wellspring International Education')
         THEN 0.7 ELSE 1.0 END,
    CASE WHEN p.name IN ('ApplyBoard','Can-Achieve') THEN 'FLAT' ELSE 'TIER' END,
    DATE '2024-01-01',
    'Seeded by Phase7prep_v2 from Doc 7 (Classification of Master-agent and Group)'
  FROM ref_partner p;


-- ─────────────────────────────────────────────────────────────────────────────
-- 3.3 Seed ref_partner_flat_rate (12 rows)
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
    'Seeded by Phase7prep_v2 — flat rate for Master Agent (genuine) cases'
  FROM ref_partner p
  CROSS JOIN dim_office o
  CROSS JOIN dim_role   r
 WHERE p.name IN ('ApplyBoard', 'Can-Achieve')
   AND o.code IN ('HCM', 'HN', 'DN')
   AND r.code IN ('COUNS_DIR', 'CO_DIR');


-- ─────────────────────────────────────────────────────────────────────────────
-- 3.4 Set Lợi's secondary_role_id = CO_DIR
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE ref_staff
   SET secondary_role_id = (SELECT id FROM dim_role WHERE code = 'CO_DIR')
 WHERE canonical_name = 'Phạm Thị Lợi';


-- ─────────────────────────────────────────────────────────────────────────────
-- 3.5 Seed ref_priority_group (29 Groups)
--
--    2 multi-List Groups: Navitas, ENZ
--    27 single-institution Groups (one per standalone priority institution)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_priority_group (canonical_name, country_id, effective_from, notes)
SELECT g.canonical_name,
       (SELECT id FROM dim_country WHERE code = g.country_code),
       DATE '2024-01-01',
       g.notes
  FROM (VALUES
    -- Multi-List Groups
    ('Navitas', NULL, 'Top-level commercial relationship; multiple Lists across AU/CA/NZ.'),
    ('ENZ',     'NZ', 'Education New Zealand; member NZ public schools form ENZL List.'),

    -- Single-institution Groups (27)
    ('Australian Catholic University (ACU)',                  'AU', 'Direct contract; single-institution Group.'),
    ('Curtin University',                                     'AU', 'Direct contract; single-institution Group.'),
    ('Deakin University',                                     'AU', 'Direct contract; single-institution Group.'),
    ('Education Queensland International (EQI)',              'AU', 'Direct contract; single-institution Group.'),
    ('Griffith University',                                   'AU', 'Direct contract; single-institution Group.'),
    ('James Cook University Brisbane (JCUB)',                 'AU', 'Direct contract; single-institution Group.'),
    ('Kaplan Business School Australia',                      'AU', 'Direct contract; single-institution Group.'),
    ('La Trobe University',                                   'AU', 'Direct contract; single-institution Group.'),
    ('Macquarie University',                                  'AU', 'Direct contract; single-institution Group.'),
    ('Monash University',                                     'AU', 'Direct contract; single-institution Group.'),
    ('RMIT University',                                       'AU', 'Direct contract; single-institution Group.'),
    ('Swinburne University of Technology',                    'AU', 'Direct contract; single-institution Group.'),
    ('The University of Adelaide',                            'AU', 'Direct contract; single-institution Group.'),
    ('The University of New South Wales (UNSW)',              'AU', 'Direct contract; single-institution Group.'),
    ('The University of Queensland',                          'AU', 'Direct contract; single-institution Group.'),
    ('University of Newcastle',                               'AU', 'Direct contract; single-institution Group.'),
    ('University of South Australia (UniSA)',                 'AU', 'Direct contract; single-institution Group.'),
    ('University of Tasmania (UTAS)',                         'AU', 'Direct contract; single-institution Group.'),
    ('University of Technology Sydney (UTS)',                 'AU', 'Direct contract; single-institution Group.'),
    ('University of Western Australia (UWA)',                 'AU', 'Direct contract; single-institution Group.'),
    ('VIC DET (Dept of Education & Training, VIC)',           'AU', 'Direct contract; single-institution Group.'),
    ('Algonquin College',                                     'CA', 'Direct contract; single-institution Group.'),
    ('Cape Breton University (CBU)',                          'CA', 'Direct contract; single-institution Group.'),
    ('Braemar College',                                       'CA', 'Direct contract; single-institution Group.'),
    ('Toronto Metropolitan University',                       'CA', 'Direct contract; single-institution Group.'),
    ('University of Guelph',                                  'CA', 'Direct contract; single-institution Group.'),
    ('University of Regina',                                  'CA', 'Direct contract; single-institution Group.'),
    ('LightPath',                                             'NZ', 'Direct contract; single-institution Group.'),
    ('Raffles Education Network',                             'SG', 'Direct contract; single-institution Group.'),
    ('Nanyang Institute of Management (NIM)',                 'SG', 'Direct contract; single-institution Group.')
  ) AS g(canonical_name, country_code, notes);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3.6 Update / seed ref_priority_list — 38 Lists
--
--    Strategy: pre-existing ref_priority_partner rows from Phase 5 had names
--    in the OLD form (e.g. "EQI", "JCUB"). These rows were carried into TX2's
--    rename. Now we:
--      (a) UPDATE pre-existing rows to the new canonical name + assign Group
--      (b) INSERT the old name as an alias
--      (c) INSERT any genuinely new Lists (none expected — pre-flight Bucket D
--          showed all 9 differences are renames, not new entries)
--
--    Each List is bound to its Group via group_id.
-- ─────────────────────────────────────────────────────────────────────────────

-- Pre-flight Bucket D's 9 renames: link old → new
WITH renames(old_name, new_canonical) AS (VALUES
    ('EQI',                                            'Education Queensland International (EQI)'),
    ('JCUB',                                           'James Cook University Brisbane (JCUB)'),
    ('VIC DET',                                        'VIC DET (Dept of Education & Training, VIC)'),
    ('ENZ (any NZ providers count)',                   'ENZL'),
    ('WSU College/WSU-Sydney City campus (Navitas)',   'WSU College / WSU Sydney City (Navitas)'),
    ('Toronto Metropolitan Uni Intl College (Navitas)','Toronto Met Uni Intl College (Navitas)'),
    ('Other Navitas Colleges (AU)',                    'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'),
    ('Other Navitas Colleges (CA)',                    'Other Navitas CA: FIC, ULIC, WLIC'),
    ('Other Navitas Colleges (NZ)',                    'Other Navitas NZ: UCIC')
)
UPDATE ref_priority_list rpl
   SET canonical_name = r.new_canonical
  FROM renames r
 WHERE rpl.canonical_name = r.old_name;

-- Capture old names as aliases
INSERT INTO ref_priority_list_alias (priority_list_id, alias, notes)
SELECT rpl.id, alias.old, 'Phase 5 form; renamed in Phase7prep_v2'
  FROM (VALUES
    ('Education Queensland International (EQI)',                 'EQI'),
    ('James Cook University Brisbane (JCUB)',                    'JCUB'),
    ('VIC DET (Dept of Education & Training, VIC)',              'VIC DET'),
    ('ENZL',                                                     'ENZ (any NZ providers count)'),
    ('WSU College / WSU Sydney City (Navitas)',                  'WSU College/WSU-Sydney City campus (Navitas)'),
    ('Toronto Met Uni Intl College (Navitas)',                   'Toronto Metropolitan Uni Intl College (Navitas)'),
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC', 'Other Navitas Colleges (AU)'),
    ('Other Navitas CA: FIC, ULIC, WLIC',                        'Other Navitas Colleges (CA)'),
    ('Other Navitas NZ: UCIC',                                   'Other Navitas Colleges (NZ)')
  ) AS alias(canonical, old)
  JOIN ref_priority_list rpl ON rpl.canonical_name = alias.canonical;

-- Verify all 38 expected canonical names exist; report any missing.
DO $$
DECLARE
    expected_names CONSTANT TEXT[] := ARRAY[
        'Australian Catholic University (ACU)',
        'Curtin University','Deakin University',
        'Education Queensland International (EQI)','Griffith University',
        'James Cook University Brisbane (JCUB)','Kaplan Business School Australia',
        'La Trobe University','Macquarie University','Monash University','RMIT University',
        'Swinburne University of Technology','The University of Adelaide',
        'The University of New South Wales (UNSW)','The University of Queensland',
        'University of Newcastle','University of South Australia (UniSA)',
        'University of Tasmania (UTAS)','University of Technology Sydney (UTS)',
        'University of Western Australia (UWA)',
        'VIC DET (Dept of Education & Training, VIC)',
        'Algonquin College','Cape Breton University (CBU)','Braemar College',
        'Toronto Metropolitan University','University of Guelph','University of Regina',
        'ENZL','LightPath','Raffles Education Network','Nanyang Institute of Management (NIM)',
        'Griffith College (Navitas)','WSU College / WSU Sydney City (Navitas)',
        'ICM (Navitas)','Toronto Met Uni Intl College (Navitas)',
        'Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC',
        'Other Navitas CA: FIC, ULIC, WLIC',
        'Other Navitas NZ: UCIC'
    ];
    missing TEXT;
BEGIN
    FOR missing IN SELECT unnest(expected_names) EXCEPT SELECT canonical_name FROM ref_priority_list
    LOOP
        RAISE WARNING 'Expected priority list missing: %', missing;
    END LOOP;
END$$;


-- Now link every List to its Group via group_id
UPDATE ref_priority_list rpl
   SET group_id = (
        SELECT id FROM ref_priority_group g
         WHERE g.canonical_name = mapping.group_name
           AND g.effective_to IS NULL
   ),
       effective_from = DATE '2024-01-01'
  FROM (VALUES
    -- Single-institution standalone Lists: List name = Group name
    ('Australian Catholic University (ACU)',                  'Australian Catholic University (ACU)'),
    ('Curtin University',                                     'Curtin University'),
    ('Deakin University',                                     'Deakin University'),
    ('Education Queensland International (EQI)',              'Education Queensland International (EQI)'),
    ('Griffith University',                                   'Griffith University'),
    ('James Cook University Brisbane (JCUB)',                 'James Cook University Brisbane (JCUB)'),
    ('Kaplan Business School Australia',                      'Kaplan Business School Australia'),
    ('La Trobe University',                                   'La Trobe University'),
    ('Macquarie University',                                  'Macquarie University'),
    ('Monash University',                                     'Monash University'),
    ('RMIT University',                                       'RMIT University'),
    ('Swinburne University of Technology',                    'Swinburne University of Technology'),
    ('The University of Adelaide',                            'The University of Adelaide'),
    ('The University of New South Wales (UNSW)',              'The University of New South Wales (UNSW)'),
    ('The University of Queensland',                          'The University of Queensland'),
    ('University of Newcastle',                               'University of Newcastle'),
    ('University of South Australia (UniSA)',                 'University of South Australia (UniSA)'),
    ('University of Tasmania (UTAS)',                         'University of Tasmania (UTAS)'),
    ('University of Technology Sydney (UTS)',                 'University of Technology Sydney (UTS)'),
    ('University of Western Australia (UWA)',                 'University of Western Australia (UWA)'),
    ('VIC DET (Dept of Education & Training, VIC)',           'VIC DET (Dept of Education & Training, VIC)'),
    ('Algonquin College',                                     'Algonquin College'),
    ('Cape Breton University (CBU)',                          'Cape Breton University (CBU)'),
    ('Braemar College',                                       'Braemar College'),
    ('Toronto Metropolitan University',                       'Toronto Metropolitan University'),
    ('University of Guelph',                                  'University of Guelph'),
    ('University of Regina',                                  'University of Regina'),
    ('LightPath',                                             'LightPath'),
    ('Raffles Education Network',                             'Raffles Education Network'),
    ('Nanyang Institute of Management (NIM)',                 'Nanyang Institute of Management (NIM)'),

    -- ENZ Group has 1 List
    ('ENZL',                                                  'ENZ'),

    -- Navitas Group has 7 Lists
    ('Griffith College (Navitas)',                            'Navitas'),
    ('WSU College / WSU Sydney City (Navitas)',               'Navitas'),
    ('ICM (Navitas)',                                         'Navitas'),
    ('Toronto Met Uni Intl College (Navitas)',                'Navitas'),
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC', 'Navitas'),
    ('Other Navitas CA: FIC, ULIC, WLIC',                     'Navitas'),
    ('Other Navitas NZ: UCIC',                                'Navitas')
  ) AS mapping(list_name, group_name)
 WHERE rpl.canonical_name = mapping.list_name;

-- Now enforce NOT NULL on group_id and effective_from
ALTER TABLE ref_priority_list
    ALTER COLUMN group_id SET NOT NULL,
    ALTER COLUMN effective_from SET NOT NULL,
    ADD CONSTRAINT chk_priority_list_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from);

-- Replace the unique-on-name constraint with a partial unique index
ALTER TABLE ref_priority_list
    DROP CONSTRAINT IF EXISTS ref_priority_list_canonical_name_key;
CREATE UNIQUE INDEX uniq_priority_list_canonical_active
    ON ref_priority_list (canonical_name)
    WHERE effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 3.7 Replace existing ref_priority_target rows with effective-dated 2024+2025
--
--    The pre-existing 38 rows were brought through TX2 with effective_from
--    = 2024-01-01, effective_to = 2024-12-31. Many have correct numbers but
--    we overwrite cleanly to ensure exact match with management's data.
-- ─────────────────────────────────────────────────────────────────────────────

-- Wipe pre-existing target rows (we have their data; we'll re-seed).
TRUNCATE ref_priority_target;

-- 2024 from Doc 6
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
    ('ENZL',                                                  10,  5, 5, 0.40),
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
    (priority_list_id, total_target, direct_target, sub_target, bonus_pct,
     prior_year_owing, effective_from, effective_to, notes)
SELECT rpl.id, t.total_target, t.direct_target, t.sub_target, t.bonus_pct,
       0, DATE '2024-01-01', DATE '2024-12-31',
       'Seeded by Phase7prep_v2 from Doc 6 (Priority 2024 final v2)'
  FROM targets_2024 t
  JOIN ref_priority_list rpl ON rpl.canonical_name = t.name;

-- 2025 — same targets, bonus_pct = 0 (program paused)
INSERT INTO ref_priority_target
    (priority_list_id, total_target, direct_target, sub_target, bonus_pct,
     prior_year_owing, effective_from, effective_to, notes)
SELECT rpl.id,
       (SELECT total_target FROM ref_priority_target rpt
         WHERE rpt.priority_list_id = rpl.id
           AND rpt.effective_from = DATE '2024-01-01'),
       (SELECT direct_target FROM ref_priority_target rpt
         WHERE rpt.priority_list_id = rpl.id
           AND rpt.effective_from = DATE '2024-01-01'),
       (SELECT sub_target FROM ref_priority_target rpt
         WHERE rpt.priority_list_id = rpl.id
           AND rpt.effective_from = DATE '2024-01-01'),
       0, 0, DATE '2025-01-01', NULL,
       'Seeded by Phase7prep_v2 from PRIORITY 2025 image — bonus_pct=0 (paused)'
  FROM ref_priority_list rpl
 WHERE rpl.effective_to IS NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 3.8 PHASE 6L — Sub-agents
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO ref_sub_agent (canonical_name, verification_status, notes)
VALUES
    ('IMEC (Tư Vấn Du Học Quốc Tế IMEC)', 'VERIFIED', 'Phase7prep_v2; team-confirmed canonical.'),
    ('Công ty TNHH Tư vấn Du học - Visa - Luật Úc ALVE', 'VERIFIED', 'Phase7prep_v2; team-confirmed canonical.'),
    ('TRUST EDU', 'VERIFIED', 'Phase7prep_v2; team-confirmed canonical.'),
    ('Công ty Cổ Phần Phát Triển Giáo Dục Dạ Minh Châu', 'VERIFIED', 'Phase7prep_v2; team-confirmed canonical.'),
    ('Á Âu (Asia-Europe Co., Ltd.)', 'VERIFIED', 'Phase7prep_v2; team-confirmed canonical.'),
    ('Du học Toàn Cầu', 'VERIFIED', 'Phase7prep_v2; team-confirmed canonical.')
ON CONFLICT (canonical_name) DO NOTHING;

INSERT INTO ref_sub_agent_alias (sub_agent_id, alias)
SELECT id, canonical_name FROM ref_sub_agent
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
-- 3.9 PHASE 6L — Institutions
-- ─────────────────────────────────────────────────────────────────────────────

-- 3.9a International Language Academy (ILAC pathway)
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'International Language Academy', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep_v2 / Phase 6l. Reached via ILAC group.'
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

-- Link to ILAC partner (existing Group)
INSERT INTO ref_partner_institution
    (partner_id, institution_id, partner_type, effective_from, notes)
SELECT
    (SELECT id FROM ref_partner WHERE name = 'ILAC'),
    (SELECT id FROM ref_institution WHERE canonical_name = 'International Language Academy' AND merged_into_id IS NULL),
    (SELECT classification FROM ref_partner WHERE name = 'ILAC'),
    DATE '2024-01-01',
    'Phase7prep_v2 / Phase 6l'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_partner_institution rpi
     WHERE rpi.partner_id = (SELECT id FROM ref_partner WHERE name = 'ILAC')
       AND rpi.institution_id = (SELECT id FROM ref_institution WHERE canonical_name = 'International Language Academy' AND merged_into_id IS NULL)
       AND rpi.effective_to IS NULL
);


-- 3.9b Education Queensland International (EQI)
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Education Queensland International (EQI)', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep_v2 / Phase 6l. Direct StudyLink contract. Priority via List membership.'
  FROM dim_country c
 WHERE c.code = 'AU'
   AND NOT EXISTS (
       SELECT 1 FROM ref_institution
        WHERE canonical_name = 'Education Queensland International (EQI)'
          AND merged_into_id IS NULL
   );

-- Link EQI institution to its priority List (the EQI List)
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT
    (SELECT id FROM ref_priority_list WHERE canonical_name = 'Education Queensland International (EQI)' AND effective_to IS NULL),
    (SELECT id FROM ref_institution WHERE canonical_name = 'Education Queensland International (EQI)' AND merged_into_id IS NULL),
    DATE '2024-01-01',
    'Phase7prep_v2 / Phase 6l — single-institution List'
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_list_institution rpli
     WHERE rpli.priority_list_id = (SELECT id FROM ref_priority_list WHERE canonical_name = 'Education Queensland International (EQI)' AND effective_to IS NULL)
       AND rpli.institution_id = (SELECT id FROM ref_institution WHERE canonical_name = 'Education Queensland International (EQI)' AND merged_into_id IS NULL)
       AND rpli.effective_to IS NULL
);

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, 'Education Queensland International (EQI)'
  FROM ref_institution
 WHERE canonical_name = 'Education Queensland International (EQI)'
   AND merged_into_id IS NULL
ON CONFLICT (alias) DO NOTHING;


-- 3.9c Wesley College
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Wesley College', c.id, 'IN_SYSTEM', 'VERIFIED',
       'Phase7prep_v2 / Phase 6l. Direct contract, not on priority list.'
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


-- 3.9d Northern Territory Government - Department of Education
INSERT INTO ref_institution
    (canonical_name, country_id, classification, verification_status, notes)
SELECT 'Northern Territory Government - Department of Education', c.id,
       'IN_SYSTEM', 'VERIFIED',
       'Phase7prep_v2 / Phase 6l. State DET, not on priority list.'
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


-- 3.9e Victoria University aliases (canonical id 288 from Phase 6j)
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
-- 3.10 Link Priority List members — institution junction
--
--      For each single-institution priority List, link to the matching
--      institution row (creating the institution if not yet present is a
--      Phase 6l concern handled in 3.9).
--
--      For aggregate Lists (the 3 Navitas aggregates + ENZL), members come
--      from existing data. ENZL starts empty (no NZ public schools yet seeded);
--      the Navitas aggregates have member institutions in ref_institution from
--      Phase 6g/6j that we'll link via best-effort name matching.
-- ─────────────────────────────────────────────────────────────────────────────

-- Single-institution Lists: link List → institution by canonical name match
INSERT INTO ref_priority_list_institution
    (priority_list_id, institution_id, effective_from, notes)
SELECT rpl.id, i.id, DATE '2024-01-01',
       'Phase7prep_v2 — single-institution List'
  FROM ref_priority_list rpl
  JOIN ref_institution i ON i.canonical_name = rpl.canonical_name
                         AND i.merged_into_id IS NULL
 WHERE rpl.effective_to IS NULL
   AND rpl.is_aggregate = FALSE
   AND NOT EXISTS (
       SELECT 1 FROM ref_priority_list_institution rpli
        WHERE rpli.priority_list_id = rpl.id
          AND rpli.institution_id = i.id
          AND rpli.effective_to IS NULL
   );


-- ─────────────────────────────────────────────────────────────────────────────
-- TX3 verification
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_classif       INTEGER;
    n_flat          INTEGER;
    n_groups        INTEGER;
    n_lists         INTEGER;
    n_lists_with_g  INTEGER;
    n_2024_targets  INTEGER;
    n_2025_targets  INTEGER;
    loi_2nd         BIGINT;
    n_legacy        INTEGER;
    n_subag_new     INTEGER;
    n_inst_new      INTEGER;
    n_renames_alias INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_classif       FROM ref_partner_classification WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_flat          FROM ref_partner_flat_rate     WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_groups        FROM ref_priority_group         WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_lists         FROM ref_priority_list          WHERE effective_to IS NULL;
    SELECT COUNT(*) INTO n_lists_with_g  FROM ref_priority_list
                                         WHERE effective_to IS NULL AND group_id IS NOT NULL;
    SELECT COUNT(*) INTO n_2024_targets  FROM ref_priority_target WHERE effective_from = DATE '2024-01-01';
    SELECT COUNT(*) INTO n_2025_targets  FROM ref_priority_target WHERE effective_from = DATE '2025-01-01';
    SELECT secondary_role_id INTO loi_2nd FROM ref_staff WHERE canonical_name = 'Phạm Thị Lợi';
    SELECT COUNT(*) INTO n_legacy        FROM ref_institution
                                         WHERE classification IN ('IN_SYSTEM_REGULAR','IN_SYSTEM_PRIORITY','OUT_SYSTEM_GROUP','OUT_SYSTEM_MASTER_AGENT');
    SELECT COUNT(*) INTO n_subag_new     FROM ref_sub_agent
                                         WHERE canonical_name IN (
                                             'IMEC (Tư Vấn Du Học Quốc Tế IMEC)',
                                             'Công ty TNHH Tư vấn Du học - Visa - Luật Úc ALVE',
                                             'TRUST EDU',
                                             'Công ty Cổ Phần Phát Triển Giáo Dục Dạ Minh Châu',
                                             'Á Âu (Asia-Europe Co., Ltd.)',
                                             'Du học Toàn Cầu');
    SELECT COUNT(*) INTO n_inst_new      FROM ref_institution
                                         WHERE canonical_name IN (
                                             'International Language Academy',
                                             'Education Queensland International (EQI)',
                                             'Wesley College',
                                             'Northern Territory Government - Department of Education');
    SELECT COUNT(*) INTO n_renames_alias FROM ref_priority_list_alias;

    RAISE NOTICE 'TX3 results:';
    RAISE NOTICE '  ref_partner_classification (active):              %',  n_classif;
    RAISE NOTICE '  ref_partner_flat_rate (active):                   %',  n_flat;
    RAISE NOTICE '  ref_priority_group (active):                      %',  n_groups;
    RAISE NOTICE '  ref_priority_list (active):                       %',  n_lists;
    RAISE NOTICE '  ref_priority_list with group_id assigned:         %',  n_lists_with_g;
    RAISE NOTICE '  ref_priority_target rows for 2024:                %',  n_2024_targets;
    RAISE NOTICE '  ref_priority_target rows for 2025:                %',  n_2025_targets;
    RAISE NOTICE '  Lợi.secondary_role_id:                            %',  loi_2nd;
    RAISE NOTICE '  Legacy classification rows (must be 0):           %',  n_legacy;
    RAISE NOTICE '  Phase 6l sub-agent canonicals:                    %',  n_subag_new;
    RAISE NOTICE '  Phase 6l institution canonicals:                  %',  n_inst_new;
    RAISE NOTICE '  ref_priority_list_alias rows (renames captured):  %',  n_renames_alias;

    IF n_classif      <> 27 THEN RAISE EXCEPTION 'Expected 27 partner classifications, got %', n_classif; END IF;
    IF n_flat         <> 12 THEN RAISE EXCEPTION 'Expected 12 flat rates, got %', n_flat; END IF;
    IF n_groups       <> 32 THEN RAISE EXCEPTION 'Expected 32 priority groups (30 singles + Navitas + ENZ), got %', n_groups; END IF;
    IF n_lists        <> 38 THEN RAISE EXCEPTION 'Expected 38 priority lists, got %', n_lists; END IF;
    IF n_lists_with_g <> n_lists THEN RAISE EXCEPTION 'Lists without group_id: %', (n_lists - n_lists_with_g); END IF;
    IF n_2024_targets <> 38 THEN RAISE EXCEPTION 'Expected 38 priority targets for 2024, got %', n_2024_targets; END IF;
    IF n_2025_targets <> 38 THEN RAISE EXCEPTION 'Expected 38 priority targets for 2025, got %', n_2025_targets; END IF;
    IF loi_2nd IS NULL      THEN RAISE EXCEPTION 'Lợi.secondary_role_id not set'; END IF;
    IF n_legacy   <>  0     THEN RAISE EXCEPTION 'Legacy classification rows remain: %', n_legacy; END IF;
    IF n_subag_new   <>  6  THEN RAISE EXCEPTION 'Expected 6 Phase 6l sub-agent canonicals, got %', n_subag_new; END IF;
    IF n_inst_new    <>  4  THEN RAISE EXCEPTION 'Expected 4 Phase 6l institution canonicals, got %', n_inst_new; END IF;
    IF n_renames_alias <> 9 THEN RAISE EXCEPTION 'Expected 9 list-alias rows from renames, got %', n_renames_alias; END IF;

    RAISE NOTICE 'TX3 data verification PASSED.';
END$$;

COMMIT;

-- =============================================================================
-- END OF Phase7prep_v2.sql
-- =============================================================================
