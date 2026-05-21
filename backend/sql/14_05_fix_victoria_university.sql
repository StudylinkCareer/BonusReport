-- =====================================================================
-- Migration 14_05: Fix Victoria University agreement classification
-- =====================================================================
--
-- Purpose: Victoria University (id=288) currently has an IN_SYSTEM /
-- VIA_PARTNER (partner_id=66) agreement, but cases in source files use
-- the `**` suffix to mark this institution as out-of-system. The
-- business confirms the institution should be OUT_OF_SYSTEM.
--
-- Approach: UPDATE the existing row in place rather than DELETE-INSERT,
-- preserving the id and effective_from for any downstream FK references.
--
-- Future bad classifications will be surfaced during regression testing,
-- not pre-emptively audited.
-- =====================================================================

BEGIN;

-- Show current state
SELECT 'BEFORE' AS phase, i.id, i.canonical_name,
       ia.system_status, ia.agreement_type, ia.partner_id,
       ia.effective_from, ia.effective_to
FROM ref_institution i
JOIN ref_institution_agreement ia ON ia.institution_id = i.id
WHERE i.id = 288;

-- Update classification: OUT_OF_SYSTEM, no partner (genuine 3rd-party institution)
UPDATE ref_institution_agreement
   SET system_status = 'OUT_OF_SYSTEM',
       agreement_type = 'DIRECT',
       partner_id = NULL,
       notes = COALESCE(notes || ' | ', '')
               || 'Reclassified from IN_SYSTEM/VIA_PARTNER (partner=66) '
               || 'to OUT_OF_SYSTEM per business correction 2026-05-21. '
               || 'Surfaced by SLC-13349 audit.',
       updated_at = NOW()
 WHERE institution_id = 288;

-- Show after state
SELECT 'AFTER' AS phase, i.id, i.canonical_name,
       ia.system_status, ia.agreement_type, ia.partner_id,
       ia.effective_from, ia.effective_to, ia.notes
FROM ref_institution i
JOIN ref_institution_agreement ia ON ia.institution_id = i.id
WHERE i.id = 288;

-- =====================================================================
-- If verification looks right, run:    COMMIT;
-- If anything looks wrong, run:        ROLLBACK;
-- =====================================================================
