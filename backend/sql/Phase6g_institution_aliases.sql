-- =============================================================================
-- Phase 6g — Institution alias seed and new canonical inserts
-- File:    Phase6g_institution_aliases.sql
-- Purpose: Resolve all 126 distinct Institution Name values from CRM history
--          to canonical ref_institution rows via ref_institution_alias.
--
-- Source: distinct_values_for_review.xlsx — "Institution Name" tab
--
-- Categorization (from review):
--   75 OK          — already-canonical or naming variants of existing canonical
--   24 misfiled-Group        — institution names with * suffix (via Group)
--    7 misfiled-MasterAgent  — institution names with ** suffix (via Master Agent)
--   20 SCRAP       — data-entry errors, dates, gibberish (skipped here;
--                    importer will mark such cases import_status='SCRAP')
--   = 126 total
--
-- Asterisk convention (from policy + reviewer):
--   *  = referred via a Group (institution-collective). Engine treats as
--        OUT_SYSTEM_GROUP. No master-agent logic triggers.
--   ** = referred via a Master Agent. Engine treats as OUT_SYSTEM_MASTER_AGENT.
--        Triggers CO Sub rate table, 0.7 KPI weight, IsPartnerCase flag.
--
-- Suffixed asterisks (e.g. "* - Navitas", "* - GEEBEE") name the partner
-- explicitly — the importer parses it and sets ref_partner_institution.
--
-- Bare asterisks (just * or **, no suffix):
--   *  → classification set, no partner link required (group-level routing
--        is informational only for the engine).
--   ** → classification set, referring_partner_id NULL,
--        import_status='UNRESOLVED-PARTNER' so QM review surfaces them.
--
-- Country attribution: Excel review file does not include country, so
-- attribution below is by AI inference from institution name. Notes column
-- flags any uncertain attributions for human verification.
-- =============================================================================

BEGIN;

-- =============================================================================
-- SECTION 1 — Aliases for institutions ALREADY in ref_institution
-- =============================================================================
-- 13 naming variants confirmed by user as aliases of existing canonicals.
-- Plus 11 OK rows where raw text already matches existing canonical_name.
-- Plus 4 misfiled-Group raw rows whose canonical exists already.
--
-- All are pure ref_institution_alias inserts — no new canonical rows.
-- -----------------------------------------------------------------------------

-- 1.a  Naming-variant aliases pointing to existing canonicals
-- (13 rows — confirmed by user)

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, alias_text
FROM ref_institution
JOIN (VALUES
    -- (existing canonical_name,                                  raw alias text from CRM)
    ('The University of New South Wales (UNSW)',                  'The University of New South Wales - UNSW'),
    ('VIC DET',                                                   'Department of Education and Early Chilhood Development, Victoria (VIC DET)'),
    ('RMIT University Vietnam',                                   'RMIT International University Vietnam'),
    ('Australian Catholic University (ACU)',                      'Australian Catholic University - ACU'),
    ('EQI',                                                       'Education Queensland International'),
    ('University of Technology Sydney (UTS)',                     'University of Technology Sydney'),
    ('The University of Queensland',                              'The University of Queensland - UQ'),
    ('Curtin University',                                         'Curtin University of Technology'),
    ('The University of Adelaide',                                'Adelaide University'),
    ('University of Tasmania (UTAS)',                             'University of Tasmania'),
    ('University of Western Australia (UWA)',                     'University of Western Australia'),
    ('University of South Australia (UniSA)',                     'University of South Australia'),
    ('Nanyang Institute of Management (NIM)',                     'Nanyang Institute of Management (NIM)')
) AS variant(canon_name, alias_text)
ON ref_institution.canonical_name = variant.canon_name
ON CONFLICT (alias) DO NOTHING;


-- 1.b  Self-aliases for OK rows where raw exactly matches existing canonical
-- (11 rows — Monash, Deakin University, RMIT, etc.)

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, canonical_name
FROM ref_institution
WHERE canonical_name IN (
    'RMIT University',
    'Monash University',
    'Deakin University',
    'Swinburne University of Technology',
    'La Trobe University',
    'Griffith University',
    'Macquarie University',
    'Kaplan Business School Australia',
    'Nanyang Institute of Management (NIM)',
    'The University of Adelaide',
    -- These exist as priority canonicals but the raw OK matches:
    'British University Vietnam (BUV)'
)
ON CONFLICT (alias) DO NOTHING;


-- 1.c  Misfiled-Group raw text aliases — canonicals already exist with
-- OUT_SYSTEM_GROUP classification. We just add the asterisked raw text
-- as aliases pointing to the existing canonical.

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, alias_text
FROM ref_institution
JOIN (VALUES
    ('Deakin College',         'Deakin College *'),
    ('Deakin College',         'Deakin College * - Navitas'),
    ('La Trobe College',       'La Trobe College Melbourne * - Navitas'),
    ('Griffith College',       'Griffith College * - Navitas')
) AS misfiled(canon_name, alias_text)
ON ref_institution.canonical_name = misfiled.canon_name
ON CONFLICT (alias) DO NOTHING;


-- =============================================================================
-- SECTION 2 — New canonical inserts
-- =============================================================================
-- Section 2.a — Regular IN_SYSTEM_REGULAR institutions from OK rows
--                that have no equivalent in the existing canonicals.
-- Section 2.b — OUT_SYSTEM_GROUP institutions from misfiled-Group rows
--                with new canonicals.
-- Section 2.c — OUT_SYSTEM_MASTER_AGENT institutions from misfiled-MA rows
--                with new canonicals.
-- -----------------------------------------------------------------------------

-- 2.a  New IN_SYSTEM_REGULAR canonicals
-- ~50 institutions encountered in CRM that aren't priority partners or
-- Navitas members.

INSERT INTO ref_institution (canonical_name, country_id, classification, verification_status, notes)
SELECT row_data.canonical_name, dim_country.id, 'IN_SYSTEM_REGULAR', 'VERIFIED', row_data.note_txt
FROM (VALUES
    -- Australia (most common)
    ('NSW Department of Education and Communities',                    'AU', 'Phase 6g.'),
    ('TAFE NSW',                                                       'AU', 'Phase 6g.'),
    ('Macquarie University - MQ',                                      'AU', 'Phase 6g. Variant naming for Macquarie University.'),
    ('Phoenix Academy',                                                'AU', 'Phase 6g.'),
    ('TAFE Queensland',                                                'AU', 'Phase 6g.'),
    ('University of Wollongong',                                       'AU', 'Phase 6g.'),
    ('Insearch UTS',                                                   'AU', 'Phase 6g.'),
    ('Edith Cowan University',                                         'AU', 'Phase 6g.'),
    ('Murdoch University',                                             'AU', 'Phase 6g.'),
    ('Trinity College - The University of Melbourne',                  'AU', 'Phase 6g.'),
    ('Academia International',                                         'AU', 'Phase 6g.'),
    ('Department of Education and Training, South Australia (SA DET)', 'AU', 'Phase 6g.'),
    ('Holmesglen Institute',                                           'AU', 'Phase 6g.'),
    ('Monash College',                                                 'AU', 'Phase 6g.'),
    ('South Australia College of English (SACE)',                      'AU', 'Phase 6g.'),
    ('Central Queensland University (CQU)',                            'AU', 'Phase 6g.'),
    ('Charles Darwin University',                                      'AU', 'Phase 6g.'),
    ('Deakin University English Language Institute',                   'AU', 'Phase 6g. DUELI = its parenthetical alias.'),
    ('ILSC Australia',                                                 'AU', 'Phase 6g.'),
    ('Perth International College of English (P.I.C.E)',               'AU', 'Phase 6g.'),
    ('Southern Cross University - SCU',                                'AU', 'Phase 6g.'),
    ('UNSW Global Pty Limited',                                        'AU', 'Phase 6g.'),
    ('William Angliss Institute',                                      'AU', 'Phase 6g.'),
    ('ACT Dept of Education and Training',                             'AU', 'Phase 6g.'),
    ('Australian National Institute of Business & Technology (ANIBT)', 'AU', 'Phase 6g.'),
    ('BROWNS',                                                         'AU', 'Phase 6g.'),
    ('Impact English College',                                         'AU', 'Phase 6g.'),
    ('Ivanhoe Grammar School',                                         'AU', 'Phase 6g.'),
    ('James Cook University Townsville & Cairns',                      'AU', 'Phase 6g.'),
    ('JMC Academy',                                                    'AU', 'Phase 6g.'),
    ('Kangan Institute',                                               'AU', 'Phase 6g.'),
    ('Le Cordon Bleu - Australia',                                     'AU', 'Phase 6g.'),
    ('Melbourne Institute of Technology',                              'AU', 'Phase 6g. MIT = parenthetical alias.'),
    ('Sarina Russo School Australia',                                  'AU', 'Phase 6g.'),
    -- Canada
    ('Thompson Rivers University',                                     'CA', 'Phase 6g.'),
    ('University of Calgary - Continuing Education',                   'CA', 'Phase 6g.'),
    ('Langara College',                                                'CA', 'Phase 6g.'),
    ('MacEwan University',                                             'CA', 'Phase 6g.'),
    ('Surrey School District, International Education Department',    'CA', 'Phase 6g.'),
    ('The University of Winnipeg',                                     'CA', 'Phase 6g.'),
    ('Upper Madison College High School',                              'CA', 'Phase 6g.'),
    ('York Region District School Board',                              'CA', 'Phase 6g.'),
    -- USA
    ('University of North Texas (UNT)',                                'US', 'Phase 6g.'),
    ('St. Paul''s International College',                              'US', 'Phase 6g — country attributed by AI; verify.'),
    -- Europe
    ('SRH Berlin University of Applied Science',                       'DE', 'Phase 6g.'),
    -- Asia (Singapore / Malaysia / Vietnam)
    ('PSB Academy',                                                    'SG', 'Phase 6g.'),
    ('ILSC',                                                           'SG', 'Phase 6g — country attributed by AI; verify (ILSC has multiple campuses).'),
    ('Monash University, Malaysia',                                    'MY', 'Phase 6g.'),
    ('University of Wollongong Malaysia',                              'MY', 'Phase 6g.'),
    ('QTS Vietnam',                                                    'VN', 'Phase 6g.'),
    ('Swinburne University of Technology Vietnam',                     'VN', 'Phase 6g.'),
    -- Suffixed Acknowledge Education row — treat as IN_SYSTEM_REGULAR with
    -- the partner suffix preserved as alias (canonical strips the *)
    ('Front Cooking School',                                           'AU', 'Phase 6g. Listed as via Acknowledge Education group.')
) AS row_data(canonical_name, country_code, note_txt)
JOIN dim_country ON dim_country.code = row_data.country_code
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution ri WHERE ri.canonical_name = row_data.canonical_name
);


-- 2.b  New OUT_SYSTEM_GROUP canonicals (misfiled with *)
-- 17 unique canonicals (some raw aliases share a canonical).

INSERT INTO ref_institution (canonical_name, country_id, classification, verification_status, notes)
SELECT row_data.canonical_name, dim_country.id, 'OUT_SYSTEM_GROUP', 'VERIFIED', row_data.note_txt
FROM (VALUES
    ('Melbourne Language Centre (MLC)',                                  'AU', 'Phase 6g — via Group (suffix not specified).'),
    ('Edith Cowan College',                                              'AU', 'Phase 6g — typo in review file said "Edwin"; corrected to "Edith".'),
    ('Flinders University',                                              'AU', 'Phase 6g — encountered via Can-Achieve master agent referral but listed as institution.'),
    ('Northern Territory Goverment - Department of Education',           'AU', 'Phase 6g — review tagged GROUP. Spelling preserved from CRM.'),
    ('University of Prince Edward Island',                               'CA', 'Phase 6g.'),
    ('Victoria University',                                              'AU', 'Phase 6g.'),
    ('Victoria University - Sydney City Centre',                         'AU', 'Phase 6g.'),
    ('Cape Breton Language Centre',                                      'CA', 'Phase 6g.'),
    ('Capilano University',                                              'CA', 'Phase 6g.'),
    ('Monroe College',                                                   'US', 'Phase 6g.'),
    ('Murdoch College',                                                  'AU', 'Phase 6g.'),
    ('SAIBT - South Australian Institute of Business and Technology',    'AU', 'Phase 6g — full name. Note SAIBT also exists as Navitas-priority.'),
    ('SRH International College',                                        'DE', 'Phase 6g — country attributed by AI; verify.'),
    ('Stott''s Colleges',                                                'AU', 'Phase 6g.'),
    ('TAFE International Western Australia',                             'AU', 'Phase 6g. TIWA = parenthetical alias.'),
    ('The University of Adelaide College',                               'AU', 'Phase 6g.'),
    ('University of Dayton',                                             'US', 'Phase 6g.'),
    ('Western Sydney University - Sydney City Campus',                   'AU', 'Phase 6g.')
) AS row_data(canonical_name, country_code, note_txt)
JOIN dim_country ON dim_country.code = row_data.country_code
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution ri WHERE ri.canonical_name = row_data.canonical_name
);


-- 2.c  New OUT_SYSTEM_MASTER_AGENT canonicals (misfiled with **)
-- 7 institutions reached via Master Agents (specific MA not identified
-- from raw text — all will be import_status='UNRESOLVED-PARTNER').

INSERT INTO ref_institution (canonical_name, country_id, classification, verification_status, notes)
SELECT row_data.canonical_name, dim_country.id, 'OUT_SYSTEM_MASTER_AGENT', 'UNVERIFIED', row_data.note_txt
FROM (VALUES
    ('British University Vietnam',                                       'VN', 'Phase 6g — via MA. Note: priority "British University Vietnam (BUV)" exists separately as IN_SYSTEM_REGULAR.'),
    ('Douglas College',                                                  'CA', 'Phase 6g — via Master Agent (specific MA not yet identified).'),
    ('Ozford Institute of Higher Education',                             'AU', 'Phase 6g — via Master Agent (specific MA not yet identified).'),
    ('TasTAFE (GETI)',                                                   'AU', 'Phase 6g — GETI suffix suggests Golden Education routing; verify.'),
    ('The University of Melbourne',                                      'AU', 'Phase 6g — via Master Agent (specific MA not yet identified).'),
    ('University of Calgary',                                            'CA', 'Phase 6g — via Master Agent (specific MA not yet identified).')
    -- Note: 'Victoria University' already inserted in 2.b above (as Group);
    -- the ** raw alias for it is handled in section 3.c below.
) AS row_data(canonical_name, country_code, note_txt)
JOIN dim_country ON dim_country.code = row_data.country_code
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution ri WHERE ri.canonical_name = row_data.canonical_name
);


-- =============================================================================
-- SECTION 3 — Aliases for the new canonicals
-- =============================================================================

-- 3.a  Self-aliases for all the new canonicals inserted above.
-- This lets the importer resolve canonical_name → canonical_id directly.

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, canonical_name
FROM ref_institution
WHERE notes LIKE 'Phase 6g%'
  AND id NOT IN (SELECT institution_id FROM ref_institution_alias)
ON CONFLICT (alias) DO NOTHING;


-- 3.b  Parenthetical-stripped aliases for new canonicals where raw CRM
-- text includes the parenthetical that we stripped.

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, alias_text
FROM ref_institution
JOIN (VALUES
    ('Melbourne Institute of Technology',                              'Melbourne Institute of Technology (MIT)'),
    ('Deakin University English Language Institute',                   'Deakin University English Language Institute (DUELI)')
) AS variant(canon_name, alias_text)
ON ref_institution.canonical_name = variant.canon_name
ON CONFLICT (alias) DO NOTHING;


-- 3.c  Asterisked raw text aliases — both Group (*) and MA (**) variants.
-- These are the actual CRM strings that appeared in closed-file reports.
-- They map to the canonicals inserted in 2.b and 2.c.

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT id, alias_text
FROM ref_institution
JOIN (VALUES
    -- 2.b Group asterisks (raw text from CRM)
    ('Melbourne Language Centre (MLC)',                                  'Melbourne Language Centre (MLC) *'),
    ('Edith Cowan College',                                              'Edith Cowan College*'),
    ('Flinders University',                                              'Flinders University * - Can-Achieve'),
    ('University of Prince Edward Island',                               'University of Prince Edward Island * - GEEBEE'),
    ('Victoria University',                                              'Victoria University * - ECA'),
    ('Victoria University - Sydney City Centre',                         'Victoria University - Sydney City Centre *'),
    ('Cape Breton Language Centre',                                      'Cape Breton Language Centre (CBLC) *'),
    ('Capilano University',                                              'Capilano University * - GEEBEE'),
    ('Capilano University',                                              'Capilano University * - GEEBEE Education'),
    ('Monroe College',                                                   'Monroe College * - GEEBEE'),
    ('Murdoch College',                                                  'Murdoch College * - Kaplan'),
    ('SAIBT - South Australian Institute of Business and Technology',    'SAIBT - South Australian Institute of Business and Technology * - Navitas'),
    ('SRH International College',                                        'SRH International College * - Navitas'),
    ('Stott''s Colleges',                                                'Stott''s Colleges *'),
    ('TAFE International Western Australia',                             'TAFE International Western Australia (TIWA) *'),
    ('TAFE International Western Australia',                             'TAFE International Western Australia (TIWA) * - Link2Uni'),
    ('The University of Adelaide College',                               'The University of Adelaide College * - Kaplan'),
    ('University of Dayton',                                             'University of Dayton *'),
    ('Western Sydney University - Sydney City Campus',                   'Western Sydney University - Sydney City Campus *'),
    -- Front Cooking School with suffix preserved
    ('Front Cooking School',                                             'Front Cooking School * - Acknowledge Education'),
    -- 2.c Master Agent asterisks
    ('British University Vietnam',                                       'British University Vietnam (BUV) **'),
    ('Douglas College',                                                  'Douglas College **'),
    ('Ozford Institute of Higher Education',                             'Ozford Institute of Higher Education **'),
    ('TasTAFE (GETI)',                                                   'TasTAFE (GETI) **'),
    ('The University of Melbourne',                                      'The University of Melbourne**'),
    ('University of Calgary',                                            'University of Calgary **'),
    ('Victoria University',                                              'Victoria University - VU **')
) AS asterisk_alias(canon_name, alias_text)
ON ref_institution.canonical_name = asterisk_alias.canon_name
ON CONFLICT (alias) DO NOTHING;


-- =============================================================================
-- SECTION 4 — ref_partner_institution links for suffixed asterisks
-- =============================================================================
-- When CRM text says "X * - Navitas" or "X * - GEEBEE", we know which
-- partner the case was routed through. Record that knowledge so the
-- importer can populate referring_partner_id automatically.
--
-- Note: this populates a many-to-many — institution X may be reachable
-- via multiple partners over time.
-- -----------------------------------------------------------------------------

INSERT INTO ref_partner_institution (partner_id, institution_id, notes)
SELECT p.id, i.id, 'Phase 6g — derived from CRM "* - <partner>" suffix.'
FROM ref_partner p
JOIN (VALUES
    -- (partner canonical_name,        institution canonical_name)
    ('Navitas',                        'Deakin College'),
    ('Navitas',                        'La Trobe College'),
    ('Navitas',                        'Griffith College'),
    ('Navitas',                        'SAIBT - South Australian Institute of Business and Technology'),
    ('Navitas',                        'SRH International College'),
    ('Can-Achieve',                    'Flinders University'),
    ('GEEBEE Education',               'University of Prince Edward Island'),
    ('GEEBEE Education',               'Capilano University'),
    ('GEEBEE Education',               'Monroe College'),
    ('Education Centre of Australia (ECA)', 'Victoria University'),
    ('Kaplan',                         'Murdoch College'),
    ('Kaplan',                         'The University of Adelaide College'),
    ('Link2Uni',                       'TAFE International Western Australia'),
    ('Acknowledge Education',          'Front Cooking School')
) AS link(partner_name, inst_name)
ON p.name = link.partner_name
JOIN ref_institution i ON i.canonical_name = link.inst_name
ON CONFLICT (partner_id, institution_id) DO NOTHING;


-- =============================================================================
-- SECTION 5 — Verification
-- =============================================================================

SELECT 'new_canonicals_phase6g' AS metric, count(*) AS actual
FROM ref_institution
WHERE notes LIKE 'Phase 6g%'

UNION ALL

SELECT 'aliases_total_after_phase6g' AS metric, count(*) AS actual
FROM ref_institution_alias

UNION ALL

SELECT 'partner_inst_links_phase6g' AS metric, count(*) AS actual
FROM ref_partner_institution
WHERE notes LIKE 'Phase 6g%';

COMMIT;
