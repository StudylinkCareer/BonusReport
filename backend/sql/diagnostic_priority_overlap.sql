-- ─────────────────────────────────────────────────────────────────────────────
-- Diagnostic: priority partner names — pre-existing vs TX2's 2024 seed list
-- ─────────────────────────────────────────────────────────────────────────────

-- A) Pre-existing priority partners (from before any of this migration)
--    The 38 rows pre-flight Check 8 told us about
SELECT
    'A — Pre-existing priority_partner names' AS bucket,
    pp.id, pp.name, c.code AS country
FROM ref_priority_partner pp
LEFT JOIN dim_country c ON c.id = pp.country_id
WHERE pp.effective_to IS NULL
ORDER BY c.code, pp.name;


-- B) Pre-existing priority targets for 2024
--    (whatever effective_from values the TX1 rename left them with)
SELECT
    'B — Pre-existing priority_target rows' AS bucket,
    pp.name, rpt.effective_from, rpt.effective_to,
    rpt.total_target, rpt.direct_target, rpt.sub_target, rpt.bonus_pct
FROM ref_priority_target rpt
JOIN ref_priority_partner pp ON pp.id = rpt.priority_partner_id
ORDER BY rpt.effective_from, pp.name;


-- C) The 38 names TX2 was trying to seed for 2024
--    (this is just text — what's in the migration)
WITH targets_2024(name) AS (VALUES
    ('Australian Catholic University (ACU)'),
    ('Curtin University'),
    ('Deakin University'),
    ('Education Queensland International (EQI)'),
    ('Griffith University'),
    ('James Cook University Brisbane (JCUB)'),
    ('Kaplan Business School Australia'),
    ('La Trobe University'),
    ('Macquarie University'),
    ('Monash University'),
    ('RMIT University'),
    ('Swinburne University of Technology'),
    ('The University of Adelaide'),
    ('The University of New South Wales (UNSW)'),
    ('The University of Queensland'),
    ('University of Newcastle'),
    ('University of South Australia (UniSA)'),
    ('University of Tasmania (UTAS)'),
    ('University of Technology Sydney (UTS)'),
    ('University of Western Australia (UWA)'),
    ('VIC DET (Dept of Education & Training, VIC)'),
    ('Algonquin College'),
    ('Cape Breton University (CBU)'),
    ('Braemar College'),
    ('Toronto Metropolitan University'),
    ('University of Guelph'),
    ('University of Regina'),
    ('ENZ (any NZ providers)'),
    ('LightPath'),
    ('Raffles Education Network'),
    ('Nanyang Institute of Management (NIM)'),
    ('Griffith College (Navitas)'),
    ('WSU College / WSU Sydney City (Navitas)'),
    ('ICM (Navitas)'),
    ('Toronto Met Uni Intl College (Navitas)'),
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'),
    ('Other Navitas CA: FIC, ULIC, WLIC'),
    ('Other Navitas NZ: UCIC')
)
-- Cross-check: which TX2-list names are NOT in pre-existing priority_partner?
SELECT 'C — Names in TX2 list but NOT in ref_priority_partner' AS bucket, t.name
FROM targets_2024 t
WHERE NOT EXISTS (
    SELECT 1 FROM ref_priority_partner pp
     WHERE pp.name = t.name AND pp.effective_to IS NULL
);


-- D) Names in pre-existing priority_partner that DON'T match TX2's list
--    (these would be older names — possibly aliased/superseded forms)
WITH targets_2024(name) AS (VALUES
    ('Australian Catholic University (ACU)'),
    ('Curtin University'),
    ('Deakin University'),
    ('Education Queensland International (EQI)'),
    ('Griffith University'),
    ('James Cook University Brisbane (JCUB)'),
    ('Kaplan Business School Australia'),
    ('La Trobe University'),
    ('Macquarie University'),
    ('Monash University'),
    ('RMIT University'),
    ('Swinburne University of Technology'),
    ('The University of Adelaide'),
    ('The University of New South Wales (UNSW)'),
    ('The University of Queensland'),
    ('University of Newcastle'),
    ('University of South Australia (UniSA)'),
    ('University of Tasmania (UTAS)'),
    ('University of Technology Sydney (UTS)'),
    ('University of Western Australia (UWA)'),
    ('VIC DET (Dept of Education & Training, VIC)'),
    ('Algonquin College'),
    ('Cape Breton University (CBU)'),
    ('Braemar College'),
    ('Toronto Metropolitan University'),
    ('University of Guelph'),
    ('University of Regina'),
    ('ENZ (any NZ providers)'),
    ('LightPath'),
    ('Raffles Education Network'),
    ('Nanyang Institute of Management (NIM)'),
    ('Griffith College (Navitas)'),
    ('WSU College / WSU Sydney City (Navitas)'),
    ('ICM (Navitas)'),
    ('Toronto Met Uni Intl College (Navitas)'),
    ('Other Navitas AU: Eynesbury, CC, ECUC, SAIBT, DC, LC, WSUIC, GC'),
    ('Other Navitas CA: FIC, ULIC, WLIC'),
    ('Other Navitas NZ: UCIC')
)
SELECT 'D — Pre-existing names NOT in TX2 list' AS bucket, pp.name
FROM ref_priority_partner pp
WHERE pp.effective_to IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM targets_2024 t WHERE t.name = pp.name
);
