-- =============================================================================
-- Phase 14.10b DIAGNOSTIC — solve the pattern 9 mystery
-- =============================================================================
-- READ-ONLY. Goal: find out why the importer says has_agreement=False for
-- institutions that clearly have agreements in the DB.
--
-- Run all 4 queries. Paste each result back labelled Q1 / Q2 / Q3 / Q4.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Q1: Full agreement rows for RMIT University (id=109)
--     RMIT is pattern-9 biggest: 17 cases, CRM=Trong, DB shows 2 IN_SYSTEM
--     DIRECT agreements from 2023-01-01 — yet importer says has_agreement=False.
-- ---------------------------------------------------------------------------
SELECT id, partner_id, institution_id, agreement_type, system_status, 
       kpi_weight, effective_from, effective_to, notes
  FROM ref_institution_agreement
 WHERE institution_id = 109
 ORDER BY effective_from, id;


-- ---------------------------------------------------------------------------
-- Q2: Sample of the 17 mismatched RMIT cases — what data is the importer
--     actually matching against?
-- ---------------------------------------------------------------------------
SELECT c.id, c.contract_id, c.course_start_date, c.contract_signed_date,
       c.institution_id, c.referring_partner_id, c.client_type_code,
       c.application_status, c.run_year, c.run_month
  FROM tx_case c
 WHERE c.institution_id = 109
   AND c.id IN (
       SELECT case_id FROM tx_case_notes_staging 
        WHERE warning_type = 'SYSTEM_TYPE_MISMATCH'
   )
 ORDER BY c.course_start_date
 LIMIT 5;


-- ---------------------------------------------------------------------------
-- Q3: Same agreement check for UNSW (id=112) — cross-confirmation that
--     the pattern is consistent across pattern-9 institutions.
-- ---------------------------------------------------------------------------
SELECT id, partner_id, institution_id, agreement_type, system_status,
       kpi_weight, effective_from, effective_to, notes
  FROM ref_institution_agreement
 WHERE institution_id = 112
 ORDER BY effective_from, id;


-- ---------------------------------------------------------------------------
-- Q4: All CHECK constraints on ref_institution_agreement.
--     The chk_agreement_consistency constraint will reveal what 
--     (agreement_type, partner_id, system_status) combinations are valid —
--     which tells us what the importer expects to see.
-- ---------------------------------------------------------------------------
SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
  FROM pg_constraint con
  JOIN pg_class cls ON cls.oid = con.conrelid
 WHERE cls.relname = 'ref_institution_agreement'
   AND con.contype = 'c';
