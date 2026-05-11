-- =============================================================================
-- Phase 14.10D: Catch remaining 3 institutions from Phase 14.10C
-- =============================================================================
-- Phase 14.10C left 3 institutions without CRM-matching agreements because
-- their MIN(contract_signed_date) collided with an existing effective_from
-- (probably one created by Phase 14.10A's backward extension).
--
-- Fix: use (earliest_signed - 1 day) as the new effective_from. This dodges
-- the collision while still covering the case (since contracts signed on day X
-- are still within an agreement effective from X-1).
--
-- Idempotent: ON CONFLICT DO NOTHING.
-- =============================================================================

BEGIN;

WITH problem_cases AS (
  SELECT 
    c.institution_id,
    MIN(c.contract_signed_date) AS earliest_signed,
    (ARRAY_AGG(SPLIT_PART(n.raw_value, ' vs ', 1)))[1] AS crm_claim
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
  GROUP BY c.institution_id
),
needs_crm_match AS (
  SELECT 
    pc.institution_id,
    pc.earliest_signed,
    pc.crm_claim,
    CASE WHEN pc.crm_claim LIKE 'Trong%' 
         THEN 'IN_SYSTEM' ELSE 'OUT_OF_SYSTEM' END AS needed_status
  FROM problem_cases pc
  WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution_agreement ag
     WHERE ag.institution_id = pc.institution_id
       AND ag.system_status = CASE WHEN pc.crm_claim LIKE 'Trong%' 
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
    m.earliest_signed - INTERVAL '1 day',     -- Offset to dodge effective_from collision
    NULL,
    'Phase 14.10D: Policy B trust-CRM, retry with -1 day offset to dodge ' ||
    'effective_from collision from 14.10A/14.10C. CRM claim "' || m.crm_claim || '".'
FROM needs_crm_match m
ON CONFLICT (institution_id, COALESCE(partner_id, (0)::bigint), effective_from)
   DO NOTHING;


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    new_rows           INT;
    remaining_mismatch INT;
BEGIN
    SELECT COUNT(*) INTO new_rows
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10D%';

    WITH problem_cases AS (
      SELECT DISTINCT
        c.institution_id,
        SPLIT_PART(n.raw_value, ' vs ', 1) AS crm_claim
      FROM tx_case_notes_staging n
      JOIN tx_case c ON c.id = n.case_id
      WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
    )
    SELECT COUNT(DISTINCT pc.institution_id) INTO remaining_mismatch
      FROM problem_cases pc
     WHERE NOT EXISTS (
       SELECT 1 FROM ref_institution_agreement ag
        WHERE ag.institution_id = pc.institution_id
          AND ag.system_status = CASE WHEN pc.crm_claim LIKE 'Trong%' 
                                      THEN 'IN_SYSTEM' ELSE 'OUT_OF_SYSTEM' END
     );

    RAISE NOTICE '====================================================';
    RAISE NOTICE 'Phase 14.10D results:';
    RAISE NOTICE '  New agreements added: % (expected 3)', new_rows;
    RAISE NOTICE '  Institutions still mismatched: % (expected 0)', remaining_mismatch;
    RAISE NOTICE '====================================================';
    
    IF remaining_mismatch > 0 THEN
        RAISE WARNING 'Some institutions still have CRM/DB status mismatch — needs manual review.';
    END IF;
END $$;

COMMIT;
