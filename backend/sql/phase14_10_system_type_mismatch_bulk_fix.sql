-- =============================================================================
-- Phase 14.10: SYSTEM_TYPE_MISMATCH bulk fix (patterns 1 + 2 + 9)
-- =============================================================================
-- Resolves ~199 of 287 SYSTEM_TYPE_MISMATCH warnings by adding agreement rows
-- whose effective_from covers the earliest contract_signed_date per institution.
--
-- DISCOVERY: importer matches against tx_case.contract_signed_date, not
-- course_start_date. (Verified diagnostic 2026-05-10.)
--
-- IMPORTANT: ON CONFLICT must mirror the natural-key expression index:
--   uq_ref_institution_agreement_natural ON
--     (institution_id, COALESCE(partner_id, (0)::bigint), effective_from)
-- This is why Postgres needs the COALESCE in the conflict target.
--
-- Sections:
--   A. EXTEND BACKWARD: copy earliest existing agreement, new effective_from
--      = year-start of earliest signed date, effective_to = day before existing.
--   B. INSERT NEW: defaults DIRECT, partner_id=NULL, system_status from CRM,
--      kpi_weight=1.0 if IN_SYSTEM else 0.0, effective_to=NULL.
--
-- NOT covered (defer to Phase 14.10C):
--   - Patterns 3+4 (~28 cases / 15 institutions): genuine system_status
--     disagreement, needs your judgment per institution
--   - 4 institutions in pattern 1 with alias-vs-CRM conflict — loaded per CRM
--     but FLAGGED in notes for verification:
--       3452 Hillsboro Aero, 3456 Lutheran HS South,
--       3447 PIHMS, 3435 SAIT
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Section A: EXTEND BACKWARD (institutions with existing agreements)
-- ---------------------------------------------------------------------------
WITH problem_cases AS (
  SELECT 
    c.institution_id,
    MIN(c.contract_signed_date) AS earliest_signed,
    DATE_TRUNC('year', MIN(c.contract_signed_date))::date AS new_eff_from
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
  GROUP BY c.institution_id
),
existing_earliest AS (
  SELECT DISTINCT ON (institution_id)
    institution_id,
    partner_id,
    agreement_type,
    system_status,
    kpi_weight,
    effective_from AS existing_from
  FROM ref_institution_agreement
  ORDER BY institution_id, effective_from
)
INSERT INTO ref_institution_agreement (
    institution_id, partner_id, agreement_type, system_status, kpi_weight,
    effective_from, effective_to, notes
)
SELECT 
    pc.institution_id,
    ee.partner_id,
    ee.agreement_type,
    ee.system_status,
    ee.kpi_weight,
    pc.new_eff_from,
    ee.existing_from - INTERVAL '1 day',
    'Phase 14.10A: Extended backward to cover earliest contract_signed_date='
      || pc.earliest_signed::text
FROM problem_cases pc
JOIN existing_earliest ee ON ee.institution_id = pc.institution_id
WHERE pc.new_eff_from < ee.existing_from
ON CONFLICT (institution_id, COALESCE(partner_id, (0)::bigint), effective_from)
   DO NOTHING;


-- ---------------------------------------------------------------------------
-- Section B: INSERT NEW (institutions with no existing agreements)
-- ---------------------------------------------------------------------------
WITH problem_cases AS (
  SELECT 
    c.institution_id,
    MIN(c.contract_signed_date) AS earliest_signed,
    DATE_TRUNC('year', MIN(c.contract_signed_date))::date AS new_eff_from,
    (ARRAY_AGG(SPLIT_PART(n.raw_value, ' vs ', 1)))[1] AS crm_claim
  FROM tx_case_notes_staging n
  JOIN tx_case c ON c.id = n.case_id
  WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
  GROUP BY c.institution_id
)
INSERT INTO ref_institution_agreement (
    institution_id, partner_id, agreement_type, system_status, kpi_weight,
    effective_from, effective_to, notes
)
SELECT 
    pc.institution_id,
    NULL,
    'DIRECT',
    CASE WHEN pc.crm_claim LIKE 'Trong%' THEN 'IN_SYSTEM' ELSE 'OUT_OF_SYSTEM' END,
    CASE WHEN pc.crm_claim LIKE 'Trong%' THEN 1.0 ELSE 0.0 END,
    pc.new_eff_from,
    NULL,
    'Phase 14.10B: New agreement from CRM claim "' || pc.crm_claim 
      || '", earliest signed=' || pc.earliest_signed::text
      || CASE WHEN pc.institution_id IN (3452, 3456, 3447, 3435)
              THEN '. FLAGGED: alias signal contradicts CRM — verify before relying on KPI weight.'
              ELSE '' END
FROM problem_cases pc
WHERE NOT EXISTS (
    SELECT 1 FROM ref_institution_agreement ag 
     WHERE ag.institution_id = pc.institution_id
)
ON CONFLICT (institution_id, COALESCE(partner_id, (0)::bigint), effective_from)
   DO NOTHING;


-- ---------------------------------------------------------------------------
-- Self-verification
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    section_a_count        INT;
    section_b_count        INT;
    remaining_uncovered    INT;
    flagged_count          INT;
BEGIN
    SELECT COUNT(*) INTO section_a_count
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10A%';

    SELECT COUNT(*) INTO section_b_count
      FROM ref_institution_agreement
     WHERE notes LIKE 'Phase 14.10B%';

    SELECT COUNT(*) INTO flagged_count
      FROM ref_institution_agreement
     WHERE notes LIKE '%FLAGGED%';

    SELECT COUNT(DISTINCT c.institution_id) INTO remaining_uncovered
      FROM tx_case_notes_staging n
      JOIN tx_case c ON c.id = n.case_id
     WHERE n.warning_type = 'SYSTEM_TYPE_MISMATCH'
       AND NOT EXISTS (
         SELECT 1 FROM ref_institution_agreement ag
          WHERE ag.institution_id = c.institution_id
            AND c.contract_signed_date >= ag.effective_from
            AND (ag.effective_to IS NULL OR c.contract_signed_date <= ag.effective_to)
       );

    RAISE NOTICE '====================================================';
    RAISE NOTICE 'Phase 14.10 results:';
    RAISE NOTICE '  Section A (extend backward): % new rows', section_a_count;
    RAISE NOTICE '  Section B (insert new):      % new rows', section_b_count;
    RAISE NOTICE '  Institutions still uncovered by signed_date: %', remaining_uncovered;
    RAISE NOTICE '  Flagged for manual verification:             %', flagged_count;
    RAISE NOTICE '====================================================';
    RAISE NOTICE 'Expected after import re-run:';
    RAISE NOTICE '  ~199 SYSTEM_TYPE_MISMATCH warnings cleared';
    RAISE NOTICE '  ~28 remaining (patterns 3 + 4) → Phase 14.10C';
    RAISE NOTICE '====================================================';
END $$;

COMMIT;

-- =============================================================================
-- Post-run inspection:
--   SELECT i.canonical_name, ag.system_status, ag.agreement_type, ag.kpi_weight,
--          ag.effective_from, ag.effective_to, ag.notes
--     FROM ref_institution_agreement ag
--     JOIN ref_institution i ON i.id = ag.institution_id
--    WHERE ag.notes LIKE 'Phase 14.10%'
--    ORDER BY i.canonical_name, ag.effective_from;
-- =============================================================================
