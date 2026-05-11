-- =============================================================================
-- Phase 14.10E: Final cleanup — handle (institution, CRM claim) pairs
-- =============================================================================
-- Bug in Phase 14.10C/D: I aggregated by institution and picked one crm_claim
-- per institution. For institutions with BOTH "Trong" and "Ngoài" cases, the
-- "missing" claim was never addressed.
--
-- Fix: handle every distinct (institution_id, crm_claim) pair where the DB
-- doesn't have a matching system_status. This may add multiple agreements
-- per institution (one IN_SYSTEM and one OUT_OF_SYSTEM if both claims are
-- present and missing).
-- =============================================================================

BEGIN;

WITH 
-- Distinct (institution, claim) pairs from mismatch warnings
problem_pairs AS (
  SELECT DISTINCT
    c.institution_id,
    SPLIT_PART(n.raw_value, ' vs ', 1) AS crm_claim
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
),
-- Earliest signed date per (institution, claim) pair specifically
pair_earliest AS (
  SELECT 
    c.institution_id,
    SPLIT_PART(n.raw_value, ' vs ', 1) AS crm_claim,
    MIN(c.contract_signed_date) AS earliest_signed
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
  GROUP BY c.institution_id, SPLIT_PART(n.raw_value, ' vs ', 1)
),
needs_crm_match AS (
  SELECT 
    pp.institution_id,
    pp.crm_claim,
    pe.earliest_signed,
    CASE WHEN pp.crm_claim LIKE 'Trong%' 
         THEN 'IN_SYSTEM' ELSE 'OUT_OF_SYSTEM' END AS needed_status
  FROM problem_pairs pp
  JOIN pair_earliest pe 
    ON pe.institution_id = pp.institution_id AND pe.crm_claim = pp.crm_claim
  WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution_agreement ag
     WHERE ag.institution_id = pp.institution_id
       AND ag.system_status = CASE WHEN pp.crm_claim LIKE 'Trong%' 
                                   THEN 'IN_SYSTEM' ELSE 'OUT_OF_SYSTEM' END
  )
)
INSERT INTO ref_institution_agreement (
    institution_id, partner_id, agreement_type, system_status, kpi_weight,
    effective_from, effective_to, notes
)
SELECT 
    m.institution_id,
    NULL,
    'DIRECT',
    m.needed_status,
    CASE WHEN m.needed_status = 'IN_SYSTEM' THEN 1.0 ELSE 0.0 END,
    m.earliest_signed,
    NULL,
    'Phase 14.10E: Policy B trust-CRM (per-claim granularity). CRM claim "' 
      || m.crm_claim || '" not represented in DB.'
FROM needs_crm_match m
ON CONFLICT (institution_id, COALESCE(partner_id, (0)::bigint), effective_from)
   DO NOTHING;


-- ---------------------------------------------------------------------------
-- Self-verification (per-pair granularity matching the verification logic)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    new_rows           INT;
    remaining_pairs    INT;
BEGIN
    SELECT COUNT(*) INTO new_rows
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10E%';

    -- Count distinct (institution, claim) pairs still without matching status
    WITH problem_pairs AS (
      SELECT DISTINCT
        c.institution_id,
        SPLIT_PART(n.raw_value, ' vs ', 1) AS crm_claim
      FROM tx_case_notes_staging n
      JOIN tx_case c ON c.id = n.case_id
      WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
    )
    SELECT COUNT(*) INTO remaining_pairs
      FROM problem_pairs pp
     WHERE NOT EXISTS (
       SELECT 1 FROM ref_institution_agreement ag
        WHERE ag.institution_id = pp.institution_id
          AND ag.system_status = CASE WHEN pp.crm_claim LIKE 'Trong%' 
                                      THEN 'IN_SYSTEM' ELSE 'OUT_OF_SYSTEM' END
     );

    RAISE NOTICE '====================================================';
    RAISE NOTICE 'Phase 14.10E results:';
    RAISE NOTICE '  New agreements added:                  %', new_rows;
    RAISE NOTICE '  Remaining (institution, claim) pairs:  %', remaining_pairs;
    RAISE NOTICE '====================================================';
    
    IF remaining_pairs > 0 THEN
        RAISE WARNING 'Some (institution, claim) pairs still unmatched — likely effective_from collision. Run diagnostic to see specifics.';
    END IF;
END $$;

COMMIT;
