-- =============================================================================
-- phase14_07_asterisk_aliases.sql
-- Phase 14.07 -- Add asterisk-suffix variants as aliases of canonical institutions
-- =============================================================================
--
-- Maps 98 distinct asterisk-suffixed strings from CRM to canonical institutions
-- in ref_institution. Example: "Griffith College * - Navitas" becomes an alias
-- of canonical "Griffith College".
--
-- IMPORTANT:
-- - RUN AFTER phase14_06_missing_institutions.sql
--   (some aliases here reference canonicals added in 14.06: Stanley College, SAIT, TMU)
-- - The migration is idempotent: ON CONFLICT (alias) DO NOTHING
-- - If a canonical doesn't exist in ref_institution, that alias INSERT silently
--   skips (no harm done). Diagnostic at end shows any unmatched aliases.
--
-- =============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Build the alias mapping in a temp table for review and re-use in diagnostics
-- ----------------------------------------------------------------------------

CREATE TEMP TABLE asterisk_aliases (canonical_name TEXT, alias TEXT) ON COMMIT DROP;

INSERT INTO asterisk_aliases (canonical_name, alias) VALUES
  -- (canonical name as it should appear in ref_institution, alias as it appears in CRM)

  -- A
  ('Aorere College',                                          'Aorere College **'),
  ('Auburn University at Montgomery',                         'Auburn University at Montgomery *'),
  ('Austin Community College District',                       'Austin Community College District **'),

  -- B
  ('British Columbia Institute of Technology (BCIT)',         'British Columbia Institute of Technology (BCIT) * - ApplyBoard'),

  -- C
  ('California State University, Fullerton',                  'California State University, Fullerton * - GEEBEE'),
  ('California State University, Fullerton',                  'California State University, Fullerton * - Kings Education'),
  ('Cape Breton University',                                  'Cape Breton University *'),
  ('CELUSA',                                                  'CELUSA * - Navitas'),
  ('Centennial College',                                      'Centennial College * - Leap GeeBee'),
  ('Charles Sturt University Sydney',                         'Charles Sturt University Sydney * - Navitas'),
  ('College of Central Florida',                              'College of Central Florida * - Adventus'),

  -- D
  ('Dalhousie University',                                    'Dalhousie University *'),

  -- E (note: canonical is single-space; CRM has double-space inside name)
  ('Embry-Riddle Aeronautical University',                    'Embry-Riddle Aeronautical  University * - EduCo'),
  ('Embry-Riddle Aeronautical University',                    'Embry-Riddle Aeronautical  University *- EduCo/ USA'),
  ('Eynesbury College',                                       'Eynesbury College * - Navitas'),

  -- F
  ('Fairbanks North Star Borough School District',            'Fairbanks North Star Borough School District **'),
  ('Flinders University',                                     'Flinders University *'),
  ('Flinders University',                                     'Flinders University **'),
  ('Florida International University',                        'Florida International University *'),

  -- G
  ('Griffith College',                                        'Griffith College * - Navitas'),

  -- H
  ('Hillsboro Aero Academy',                                  'Hillsboro Aero Academy **'),
  ('Hills College',                                           'Hills College *'),

  -- I
  ('IL Texas Private High School',                            'IL Texas Private High School * - GE'),
  ('Impact English College',                                  'Impact English College **'),
  ('Indiana University Bloomington',                          'Indiana University Bloomington **'),
  ('International College of Manitoba (ICM)',                 'International College of Manitoba (ICM) * - Navitas'),
  ('INTO City University London',                             'INTO City University London * - London/ UK'),

  -- J  (location " - Singapore" is part of name, not partner)
  ('James Cook Australia Institute of Higher Learning PTE.LTD - Singapore',
                                                              'James Cook Australia Institute of Higher Learning PTE.LTD - Singapore **'),

  -- K
  ('Kwantlen Polytechnic University',                         'Kwantlen Polytechnic University * - Adventus'),

  -- L
  ('Lakehead University',                                     'Lakehead University **'),
  ('Louisiana State University',                              'Louisiana State University *'),
  ('Louisiana State University',                              'Louisiana State University * - Shorelight Education'),
  ('Lutheran High School South',                              'Lutheran High School South **'),

  -- M
  ('Millersville University',                                 'Millersville University * - Wellspring'),
  ('Minnesota State University - Mankato',                    'Minnesota State University - Mankato * - EduCo'),
  ('Murdoch College',                                         'Murdoch College *'),

  -- N
  ('North Park University',                                   'North Park University * - Wellspring'),
  -- /* VERIFY: "Northumria" is likely typo for "Northumbria"; canonical preserved as typo */
  ('Northumria University',                                   'Northumria University * - INTO UK'),
  ('Nova Scotia Community College',                           'Nova Scotia Community College **'),

  -- P
  ('Pacific International Hotel Management School (PIHMS)',   'Pacific International Hotel Management School (PIHMS) **'),
  ('Perth International College of English (P.I.C.E)',        'Perth International College of English (P.I.C.E) **'),

  -- Q  (both forms map to plain QUT canonical)
  ('Queensland University of Technology',                     'Queensland University of Technology **'),
  ('Queensland University of Technology',                     'Queensland University of Technology (QUT) **'),

  -- R
  ('Red Rocks Community College',                             'Red Rocks Community College **'),
  ('Red Rocks Community College',                             'Red Rocks Community College (RRCC) **'),
  ('Royal Holloway University of London ISC',                 'Royal Holloway University of London ISC * - Study Group'),

  -- S
  -- /* note: no space between "University" and "*" in source */
  ('Saginaw Valley State University',                         'Saginaw Valley State University* - Wellspring'),
  ('SAIBT - South Australian Institute of Business and Technology',
                                                              'SAIBT - South Australian Institute of Business and Technology * - Navitas'),
  ('Saint Leo University',                                    'Saint Leo University * - Adventus'),
  -- /* note: no space between "University" and "**" in source */
  ('Salem State University',                                  'Salem State University**'),
  ('San Jose State University',                               'San Jose State University * - GEEBEE'),
  ('Sheridan College Institute of Technology and Advanced Learning',
                                                              'Sheridan College Institute of Technology and Advanced Learning **'),
  ('Singapore Institute of Technology (SIT)',                 'Singapore Institute of Technology (SIT) **'),
  -- SAIT canonical added in Phase 14.06
  ('Southern Alberta Institute of Technology (SAIT)',         'Southern Alberta Institute of Technology (SAIT) **'),
  ('Southern Alberta Institute of Technology (SAIT)',         'Southern Alberta Institute of Technology (SAIT) * - Adventus'),
  ('Southern Institute of Technology (SIT)',                  'Southern Institute of Technology (SIT) * - GEEBEE'),
  ('Southwestern Academy',                                    'Southwestern Academy * - GE'),
  ('Springwood School',                                       'Springwood School * - Golden Education'),
  ('Stamford International University',                       'Stamford International University **'),
  -- Stanley College canonical added in Phase 14.06
  ('Stanley College',                                         'Stanley College **'),
  ('St Mary''s Preparatory High School',                      'St Mary''s Preparatory High School **'),
  ('Swinburne University of Technology Vietnam',              'Swinburne University of Technology Vietnam **'),

  -- T
  ('TAFE International Western Australia (TIWA)',             'TAFE International Western Australia (TIWA) **'),
  ('TAFE South Australia',                                    'TAFE South Australia **'),
  ('The University of Newcastle College of International Education (CIE)',
                                                              'The University of Newcastle College of International Education (CIE) *'),
  ('The University of Sydney',                                'The University of Sydney **'),
  ('Toronto Metropolitan University International College',   'Toronto Metropolitan University International College *'),
  ('Toronto Metropolitan University International College (TMUIC)',
                                                              'Toronto Metropolitan University International College (TMUIC) * - Navitas'),
  -- TMU canonical added in Phase 14.06
  ('Toronto Metropolitan University (TMU)',                   'Toronto Metropolitan University (TMU) * - Adventus'),
  ('Torrens University Australia',                            'Torrens University Australia ** - Laureate'),

  -- U
  ('ULethbridge International College Calgary (UICC)',        'ULethbridge International College Calgary (UICC) * - Navitas'),
  ('University Christian School',                             'University Christian School **'),
  ('University of Auckland',                                  'University of Auckland **'),
  ('University of Canberra College',                          'University of Canberra College * - Navitas'),
  ('University of Central Florida',                           'University of Central Florida *'),
  ('University of Cincinnati',                                'University of Cincinnati **'),
  ('University of Dayton',                                    'University of Dayton * - Shorelight'),
  ('University of Galway',                                    'University of Galway **'),
  ('University of Galway',                                    'University of Galway * - GEEBEE'),
  -- /* note: "* /" separator instead of "* -" */
  ('University of Illinois at Chicago',                       'University of Illinois at Chicago * / Shorelight'),
  ('University of Massachusetts Lowell',                      'University of Massachusetts Lowell ** - Navitas'),
  ('University of Regina',                                    'University of Regina (UR) **'),
  ('University of South Florida',                             'University of South Florida * - GEEBEE'),
  ('University of Tennessee - Knoxville',                     'University of Tennessee - Knoxville * - GEEBEE'),
  ('University of the Sunshine Coast',                        'University of the Sunshine Coast * - ECA'),
  ('University of The West of England (UWE)',                 'University of The West of England (UWE) **'),
  ('University of Toledo',                                    'University of Toledo * - Wellspring'),
  ('University of Victoria',                                  'University of Victoria * - Kaplan'),
  ('University of Waikato College',                           'University of Waikato College * - Navitas'),
  ('UWA College',                                             'UWA College * - INTO'),

  -- V
  ('Vancouver Community College',                             'Vancouver Community College **'),
  ('Victoria University - Sydney City Centre',                'Victoria University - Sydney City Centre *'),

  -- W
  ('Wakefield School',                                        'Wakefield School **'),
  -- /* VERIFY: lowercase 's' in "school" -- preserve typo from source */
  ('Wellington High school',                                  'Wellington High school *'),
  ('Western Michigan University',                             'Western Michigan University * - GEEBEE'),
  ('Western New England University',                          'Western New England University *'),
  ('Western Sydney University - Sydney City Campus',          'Western Sydney University - Sydney City Campus * - Navitas'),
  ('Wright State University',                                 'Wright State University * - GEEBEE');

-- ----------------------------------------------------------------------------
-- Confirm temp table content (should be 98 rows)
-- ----------------------------------------------------------------------------

SELECT 'Total alias mappings staged' AS metric, COUNT(*) AS value FROM asterisk_aliases;

-- ----------------------------------------------------------------------------
-- Insert aliases where canonical exists; skip silently otherwise
-- ----------------------------------------------------------------------------

INSERT INTO ref_institution_alias (institution_id, alias)
SELECT ri.id, aa.alias
FROM asterisk_aliases aa
JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name
ON CONFLICT (alias) DO NOTHING;

-- ----------------------------------------------------------------------------
-- DIAGNOSTICS
-- ----------------------------------------------------------------------------

-- Counts: how many succeeded vs failed canonical lookup
SELECT
  (SELECT COUNT(*) FROM asterisk_aliases) AS aliases_attempted,
  (SELECT COUNT(*) FROM asterisk_aliases aa
     JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name) AS canonical_match_found,
  (SELECT COUNT(*) FROM asterisk_aliases aa
     LEFT JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name
     WHERE ri.id IS NULL) AS canonical_NOT_found;

-- List any aliases where canonical was missing -- these are NOT inserted
-- and will remain UNRESOLVED_INSTITUTION on next importer run
SELECT
  aa.canonical_name AS missing_canonical,
  aa.alias AS unmapped_alias
FROM asterisk_aliases aa
LEFT JOIN ref_institution ri ON ri.canonical_name = aa.canonical_name
WHERE ri.id IS NULL
ORDER BY aa.canonical_name;

-- Confirm aliases were actually inserted (recently created)
SELECT 'Aliases just inserted' AS metric, COUNT(*) AS value
FROM ref_institution_alias
WHERE created_at > NOW() - INTERVAL '5 minutes'
  AND alias LIKE '%*%';

COMMIT;

-- =============================================================================
-- WHAT TO EXPECT
-- =============================================================================
-- aliases_attempted        = 98
-- canonical_match_found    = depends on what's in ref_institution
-- canonical_NOT_found      = should be small (0-15); review the listed rows
-- aliases_just_inserted    = canonical_match_found (minus any pre-existing)
--
-- After this runs, re-run the importer:
--   python -m backend.importer.consolidated_cli "<CRM file path>"
-- UNRESOLVED_INSTITUTION should drop from 198 to roughly the count of
-- canonical_NOT_found rows above.
-- =============================================================================
