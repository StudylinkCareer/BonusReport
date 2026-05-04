-- =============================================================================
-- Phase 6j patch — restore aggregate_priority_partner_id on Griffith
-- File:    Phase6j_patch_griffith_aggregate.sql
--
-- Background:
--   Phase 6j Merge 1 reclassified Griffith College (id 130) from
--   IN_SYSTEM_PRIORITY to OUT_SYSTEM_GROUP and nulled both priority FKs.
--   Per chat 2026-05-03, both FKs should not have been nulled — Griffith
--   is a Navitas-managed pathway college that aggregates up to the same
--   Navitas priority row (id 150) as SAIBT and WSUIC.
--
-- Effect:
--   Sets aggregate_priority_partner_id = 150 on Griffith College (130),
--   matching SAIBT (137) and WSUIC (140). Leaves priority_partner_id NULL
--   because the institution itself is not a priority partner — it just
--   rolls up to one for reporting.
-- =============================================================================

BEGIN;

UPDATE ref_institution
SET aggregate_priority_partner_id = 150,
    notes = COALESCE(notes,'') || ' [Phase 6j patch: agg restored to Navitas (150) per chat 2026-05-03.]',
    updated_at = NOW()
WHERE id = 130
  AND canonical_name = 'Griffith College'
  AND aggregate_priority_partner_id IS NULL;

COMMIT;


-- Verification — should now show all three rolling up to 150
SELECT id, canonical_name, classification,
       priority_partner_id, aggregate_priority_partner_id
FROM ref_institution
WHERE canonical_name IN (
    'Griffith College',
    'South Australian Institute of Business and Technology',
    'Western Sydney University International College'
)
ORDER BY canonical_name;
