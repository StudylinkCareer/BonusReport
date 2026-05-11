-- =============================================================================
-- Phase 14_15: Reclassify the 4 Phase 14.10B flagged institutions
-- =============================================================================
-- Per user (2026-05-10), final per-institution decisions after alias review:
--
--   3452 Hillsboro Aero Academy      → OUT_OF_SYSTEM, weight 0 (rule 2: ** no MA)
--   3456 Lutheran High School South  → OUT_OF_SYSTEM, weight 0 (rule 2: ** no MA)
--   3447 Pacific Intl Hotel Mgmt Sch → OUT_OF_SYSTEM, weight 0 (rule 2: ** no MA)
--   3435 Southern Alberta Inst (SAIT)→ OUT_OF_SYSTEM via Adventus, weight 0.7
--                                       (rule 3: ** with MA assigned via 
--                                       `* - Adventus` alias; SAIT is under
--                                       contract with Adventus per user.)
--
-- Note: Phase 14.10B inserted DIRECT IN_SYSTEM weight 1.0 for all 4. We're
-- updating those rows. For SAIT, this changes:
--    agreement_type   DIRECT → VIA_PARTNER
--    partner_id       NULL   → Adventus's id
--    system_status    IN_SYSTEM → OUT_OF_SYSTEM
--    kpi_weight       1.0    → 0.7
-- This changes the natural-key index value (COALESCE(partner_id,0)) but the
-- new combination won't conflict (SAIT had no other agreements).
--
-- Side effect: all 4 will reappear as SYSTEM_TYPE_MISMATCH warnings on next
-- importer reload (CRM=Trong vs DB=OOS). Intentional — flags CRM errors.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1-3. Hillsboro, Lutheran, PIHMS: pure OOS, weight 0
-- ---------------------------------------------------------------------------
UPDATE ref_institution_agreement
   SET system_status = 'OUT_OF_SYSTEM',
       kpi_weight    = 0,
       notes = 'Phase 14_15: flipped IN_SYSTEM→OUT_OF_SYSTEM, weight 1.0→0 per '
            || 'alias signal (** only, no MA). CRM-vs-DB warning will persist '
            || 'on next reload — flagging CRM data entry error. '
            || 'Original: ' || COALESCE(notes, '')
 WHERE institution_id IN (3452, 3456, 3447)
   AND notes LIKE 'Phase 14.10B%';

-- ---------------------------------------------------------------------------
-- 4. SAIT: OUT_OF_SYSTEM via Adventus (Master Agent), weight 0.7
-- ---------------------------------------------------------------------------
UPDATE ref_institution_agreement
   SET system_status   = 'OUT_OF_SYSTEM',
       agreement_type  = 'VIA_PARTNER',
       partner_id      = (SELECT id FROM ref_partner 
                           WHERE name = 'Adventus' 
                             AND classification = 'MASTER_AGENT'),
       kpi_weight      = 0.7,
       notes = 'Phase 14_15: SAIT reclassified per user — under contract with '
            || 'Adventus (Master Agent) per `* - Adventus` alias. '
            || 'IN_SYSTEM/DIRECT/1.0 → OUT_OF_SYSTEM/VIA_PARTNER(Adventus)/0.7. '
            || 'CRM-vs-DB warning will persist as expected. '
            || 'Original: ' || COALESCE(notes, '')
 WHERE institution_id = 3435
   AND notes LIKE 'Phase 14.10B%';


-- ---------------------------------------------------------------------------
-- Self-verification (numeric comparison)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    pure_oos_count INT;
    sait_status    TEXT;
    sait_type      TEXT;
    sait_partner   BIGINT;
    sait_weight    NUMERIC;
    adventus_id    BIGINT;
BEGIN
    SELECT id INTO adventus_id 
      FROM ref_partner 
     WHERE name = 'Adventus' AND classification = 'MASTER_AGENT';

    IF adventus_id IS NULL THEN
        RAISE EXCEPTION 'Phase 14_15 FAILED: Adventus MASTER_AGENT not found in ref_partner';
    END IF;

    SELECT COUNT(*) INTO pure_oos_count
      FROM ref_institution_agreement
     WHERE institution_id IN (3452, 3456, 3447)
       AND notes LIKE 'Phase 14_15%'
       AND system_status = 'OUT_OF_SYSTEM' AND kpi_weight = 0
       AND agreement_type = 'DIRECT' AND partner_id IS NULL;

    IF pure_oos_count <> 3 THEN
        RAISE EXCEPTION 'Phase 14_15 FAILED: expected 3 pure-OOS rows, found %', pure_oos_count;
    END IF;

    SELECT system_status, agreement_type, partner_id, kpi_weight
      INTO sait_status, sait_type, sait_partner, sait_weight
      FROM ref_institution_agreement
     WHERE institution_id = 3435 AND notes LIKE 'Phase 14_15%';

    IF sait_status <> 'OUT_OF_SYSTEM' 
       OR sait_type <> 'VIA_PARTNER'
       OR sait_partner <> adventus_id
       OR sait_weight <> 0.7 THEN
        RAISE EXCEPTION 'Phase 14_15 FAILED: SAIT expected OOS/VIA_PARTNER/Adventus(id=%)/0.7, got %/%/%/%',
            adventus_id, sait_status, sait_type, sait_partner, sait_weight;
    END IF;

    RAISE NOTICE '====================================================';
    RAISE NOTICE 'Phase 14_15 OK:';
    RAISE NOTICE '  3452 Hillsboro:    OUT_OF_SYSTEM / DIRECT / 0';
    RAISE NOTICE '  3456 Lutheran HS:  OUT_OF_SYSTEM / DIRECT / 0';
    RAISE NOTICE '  3447 PIHMS:        OUT_OF_SYSTEM / DIRECT / 0';
    RAISE NOTICE '  3435 SAIT:         OUT_OF_SYSTEM / VIA_PARTNER(Adventus id=%) / 0.7', adventus_id;
    RAISE NOTICE '====================================================';
END $$;

COMMIT;
