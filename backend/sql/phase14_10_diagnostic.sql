-- =============================================================================
-- Phase 14.10 DIAGNOSTIC — SYSTEM_TYPE_MISMATCH analysis
-- =============================================================================
-- READ-ONLY. No INSERT/UPDATE/DELETE. Safe to run any number of times.
--
-- Purpose: Triangulate three sources of truth for each mismatched institution:
--   1. CRM claim (from raw_value: "Trong hệ thống" or "Ngoài hệ thống")
--   2. Current DB state (ref_institution_agreement)
--   3. Alias asterisk pattern signal (corrected legend):
--        no asterisk → in system
--        *           → via partner (Group or MA)
--        **          → out of system, accessed via MA
--
-- Run all 4 queries. Paste results back so I can write Phase 14.10 migration.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Query 1: Distribution of CRM-claim vs DB-state pairs
--          (Confirms the journal's "~250 / ~37" split or reveals other patterns)
-- ---------------------------------------------------------------------------
SELECT 
  SPLIT_PART(raw_value, ' vs ', 1) AS crm_claim,
  SPLIT_PART(raw_value, ' vs ', 2) AS db_state_reported,
  COUNT(*) AS case_count
FROM tx_case_notes_staging
WHERE warning_type = 'SYSTEM_TYPE_MISMATCH'
GROUP BY 1, 2
ORDER BY case_count DESC;


-- ---------------------------------------------------------------------------
-- Query 2: Per-institution breakdown with alias signal + DB agreement state
--          (The main analytical view — drives the migration grouping)
-- ---------------------------------------------------------------------------
WITH mismatch_cases AS (
  SELECT 
    n.case_id,
    n.raw_value,
    n.run_year,
    c.institution_id,
    c.course_start_date,
    SPLIT_PART(n.raw_value, ' vs ', 1) AS crm_claim
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
)
SELECT 
  i.id,
  i.canonical_name,
  COUNT(m.case_id) AS case_count,
  
  -- Year span of affected cases
  MIN(m.run_year) AS earliest_year,
  MAX(m.run_year) AS latest_year,
  MIN(m.course_start_date) AS earliest_course_start,
  
  -- Asterisk pattern signal (the new ground truth)
  (SELECT BOOL_OR(alias NOT LIKE '%*%') 
     FROM ref_institution_alias WHERE institution_id = i.id) AS alias_in_system,
  (SELECT BOOL_OR(alias LIKE '%*%' AND alias NOT LIKE '%**%')
     FROM ref_institution_alias WHERE institution_id = i.id) AS alias_via_partner,
  (SELECT BOOL_OR(alias LIKE '%**%')
     FROM ref_institution_alias WHERE institution_id = i.id) AS alias_oos,
  
  -- Current DB agreement state
  (SELECT COUNT(*) FROM ref_institution_agreement 
     WHERE institution_id = i.id) AS db_agreement_count,
  (SELECT MIN(effective_from) FROM ref_institution_agreement 
     WHERE institution_id = i.id) AS db_earliest_from,
  (SELECT STRING_AGG(DISTINCT system_status, ',') FROM ref_institution_agreement 
     WHERE institution_id = i.id) AS db_statuses,
  (SELECT STRING_AGG(DISTINCT agreement_type, ',') FROM ref_institution_agreement 
     WHERE institution_id = i.id) AS db_agreement_types,
  
  -- Sample CRM claim
  (ARRAY_AGG(DISTINCT m.crm_claim))[1] AS crm_claim_sample,
  
  -- Inferred fix pattern (preliminary categorization)
  CASE
    WHEN (SELECT COUNT(*) FROM ref_institution_agreement WHERE institution_id = i.id) = 0
         THEN '1_NO_AGREEMENT_AT_ALL'
    WHEN (SELECT MIN(effective_from) FROM ref_institution_agreement WHERE institution_id = i.id) > MIN(m.course_start_date)
         THEN '2_AGREEMENT_TOO_RECENT'
    WHEN BOOL_OR(m.crm_claim LIKE 'Trong%') 
         AND (SELECT BOOL_OR(system_status = 'OUT_OF_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
         AND NOT (SELECT BOOL_OR(system_status = 'IN_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
         THEN '3_CRM_IN_DB_OOS'
    WHEN BOOL_OR(m.crm_claim LIKE 'Ngoài%')
         AND (SELECT BOOL_OR(system_status = 'IN_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
         AND NOT (SELECT BOOL_OR(system_status = 'OUT_OF_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
         THEN '4_CRM_OOS_DB_IN'
    ELSE '9_OTHER_OR_MIXED'
  END AS fix_pattern
  
FROM mismatch_cases m
JOIN ref_institution i ON i.id = m.institution_id
GROUP BY i.id, i.canonical_name
ORDER BY case_count DESC, i.canonical_name;


-- ---------------------------------------------------------------------------
-- Query 3: Roll-up by fix_pattern (so we know what migration sections to write)
-- ---------------------------------------------------------------------------
WITH mismatch_cases AS (
  SELECT 
    n.case_id, n.raw_value,
    c.institution_id, c.course_start_date,
    SPLIT_PART(n.raw_value, ' vs ', 1) AS crm_claim
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
),
per_inst AS (
  SELECT 
    i.id,
    i.canonical_name,
    COUNT(m.case_id) AS case_count,
    CASE
      WHEN (SELECT COUNT(*) FROM ref_institution_agreement WHERE institution_id = i.id) = 0
           THEN '1_NO_AGREEMENT_AT_ALL'
      WHEN (SELECT MIN(effective_from) FROM ref_institution_agreement WHERE institution_id = i.id) > MIN(m.course_start_date)
           THEN '2_AGREEMENT_TOO_RECENT'
      WHEN BOOL_OR(m.crm_claim LIKE 'Trong%') 
           AND (SELECT BOOL_OR(system_status = 'OUT_OF_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
           AND NOT (SELECT BOOL_OR(system_status = 'IN_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
           THEN '3_CRM_IN_DB_OOS'
      WHEN BOOL_OR(m.crm_claim LIKE 'Ngoài%')
           AND (SELECT BOOL_OR(system_status = 'IN_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
           AND NOT (SELECT BOOL_OR(system_status = 'OUT_OF_SYSTEM') FROM ref_institution_agreement WHERE institution_id = i.id)
           THEN '4_CRM_OOS_DB_IN'
      ELSE '9_OTHER_OR_MIXED'
    END AS fix_pattern
  FROM mismatch_cases m
  JOIN ref_institution i ON i.id = m.institution_id
  GROUP BY i.id, i.canonical_name
)
SELECT 
  fix_pattern,
  COUNT(DISTINCT id) AS institution_count,
  SUM(case_count) AS total_cases
FROM per_inst
GROUP BY fix_pattern
ORDER BY fix_pattern;


-- ---------------------------------------------------------------------------
-- Query 4: Sanity check — confirm total count matches journal expectation (287)
-- ---------------------------------------------------------------------------
SELECT 
  warning_type, 
  COUNT(*) AS total_cases,
  COUNT(DISTINCT case_id) AS distinct_cases
FROM tx_case_notes_staging
WHERE warning_type IN ('SYSTEM_TYPE_MISMATCH', 'DEPARTED_STAFF', 'UNRESOLVED_REFER_SOURCE',
                       'UNRESOLVED_INSTITUTION', 'period_unresolved', 'NO_RESOLVABLE_OFFICE',
                       'UNRESOLVED_COUNSELLOR', 'UNRESOLVED_COUNTRY', 'UNRESOLVED_CASE_OFFICER')
GROUP BY warning_type
ORDER BY total_cases DESC;
