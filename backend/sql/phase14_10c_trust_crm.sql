-- =============================================================================
-- Phase 14.10C: Resolve remaining SYSTEM_TYPE_MISMATCH (Policy B — trust CRM)
-- =============================================================================
-- Per user decision (2026-05-10), Policy B: where CRM and DB disagree on
-- system_status, ADD a new agreement matching CRM's claim. Existing DB
-- agreements remain (overlapping coverage). Importer behavior with
-- overlapping agreements not yet validated — flag for review.
--
-- Scope: ~20 institutions where CRM claim doesn't match ANY existing DB 
-- system_status row for that institution. Includes:
--   - Pattern 3 (CRM=Trong, DB only has OOS): 7 institutions
--   - Pattern 4 (CRM=Ngoài, DB only has IN_SYSTEM): 8 institutions  
--   - Hidden in pattern 2 (date issue masked status mismatch): 5 institutions
--
-- Defaults for new agreements:
--   agreement_type=DIRECT, partner_id=NULL (neutral — matches direct enrolments;
--     for via-partner cases, importer may need to fall back to DIRECT)
--   effective_from = MIN(contract_signed_date) of mismatched cases (avoids
--     conflict with existing effective_from values, typically 2023/2024-01-01)
--   effective_to = NULL (open-ended)
--   kpi_weight = 1.0 if IN_SYSTEM, 0.0 if OUT_OF_SYSTEM (per locked policy)
--
-- Idempotent: ON CONFLICT on the natural-key expression index DO NOTHING.
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
  -- Institutions whose CRM claim is NOT represented in ANY existing agreement
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
    NULL,                                              -- DIRECT default
    'DIRECT',
    m.needed_status,
    CASE WHEN m.needed_status = 'IN_SYSTEM' THEN 1.0 ELSE 0.0 END,
    m.earliest_signed,                                 -- Avoids effective_from conflict
    NULL,
    'Phase 14.10C: Policy B trust-CRM agreement added. CRM claim "' 
      || m.crm_claim 
      || '" not represented in DB. Coexists with existing agreement(s) — '
      || 'importer selection behavior with overlapping agreements not yet validated.'
FROM needs_crm_match m
ON CONFLICT (institution_id, COALESCE(partner_id, (0)::bigint), effective_from)
   DO NOTHING;


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    new_rows           INT;
    new_in_system      INT;
    new_oos            INT;
    remaining_mismatch INT;
BEGIN
    SELECT COUNT(*) INTO new_rows
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10C%';

    SELECT COUNT(*) INTO new_in_system
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10C%' AND system_status = 'IN_SYSTEM';

    SELECT COUNT(*) INTO new_oos
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10C%' AND system_status = 'OUT_OF_SYSTEM';

    -- Remaining institutions where CRM still doesn't match ANY DB status
    -- (should be 0 after this migration if everything worked)
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
    RAISE NOTICE 'Phase 14.10C results (Policy B):';
    RAISE NOTICE '  New agreements added:       %', new_rows;
    RAISE NOTICE '    IN_SYSTEM:                %', new_in_system;
    RAISE NOTICE '    OUT_OF_SYSTEM:            %', new_oos;
    RAISE NOTICE '  Institutions still without CRM-matching status: %', remaining_mismatch;
    RAISE NOTICE '====================================================';
    RAISE NOTICE 'After import re-run, ALL ~287 SYSTEM_TYPE_MISMATCH';
    RAISE NOTICE 'warnings should clear (assuming importer accepts the';
    RAISE NOTICE 'CRM-matching agreement when one exists).';
    RAISE NOTICE '====================================================';
END $$;

COMMIT;

-- =============================================================================
-- Post-run inspection — see what was added:
--   SELECT i.canonical_name, ag.system_status, ag.kpi_weight,
--          ag.effective_from, ag.notes
--     FROM ref_institution_agreement ag
--     JOIN ref_institution i ON i.id = ag.institution_id
--    WHERE ag.notes LIKE 'Phase 14.10C%'
--    ORDER BY i.canonical_name;
--
-- See institutions that now have BOTH IN and OUT system_status agreements
-- (the overlapping-coverage situation):
--   SELECT i.canonical_name, 
--          STRING_AGG(ag.system_status || ' (' || ag.effective_from || ')', '; ' 
--                     ORDER BY ag.effective_from) AS all_agreements
--     FROM ref_institution_agreement ag
--     JOIN ref_institution i ON i.id = ag.institution_id
--    GROUP BY i.id, i.canonical_name
--   HAVING COUNT(DISTINCT ag.system_status) > 1
--    ORDER BY i.canonical_name;
-- =============================================================================
