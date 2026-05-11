-- ============================================================
-- Phase 14 Migration 2 (REVISED): Insert 17 new GROUP partners
-- 
-- CORRECTIONS from prior version:
--   * Uses ref_partner.classification (not partner_type)
--   * Also inserts a row in ref_partner_classification for each new
--     partner (category='GROUP', bonus_model='TIER', kpi_weight=1.00),
--     matching the convention of existing 18 GROUP partners.
--   * Uses WHERE NOT EXISTS for idempotency (no UNIQUE constraint
--     on ref_partner.name).
--
-- All 17 partners are GROUPs per user confirmation.
-- Includes typo fix: 'Beidge Edu' (CSV) → 'Bridge Edu' (canonical).
-- ============================================================

BEGIN;

-- =====================
-- Part 1: Insert 17 new partners into ref_partner
-- =====================
WITH new_partners (name, classification, notes) AS (
  VALUES
    ('LBPSB',       'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('UPP',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('AIEP',        'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('ISES',        'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('KIC',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('EduLink',     'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('IP Edu',      'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('WHG',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('ASG',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('CIEE',        'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('CEG',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('LCI',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('ESLI',        'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('EAP',         'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('ACAP',        'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('ICEAP',       'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner'),
    ('Bridge Edu',  'GROUP', 'Tier 2 master list 2026-05-10: added as GROUP partner (typo fix from "Beidge Edu" in source)')
)
INSERT INTO ref_partner (name, classification, is_active, effective_from, effective_to, notes)
SELECT np.name, np.classification, TRUE, '2023-01-01'::date, '2026-12-31'::date, np.notes
FROM new_partners np
WHERE NOT EXISTS (
  SELECT 1 FROM ref_partner p WHERE p.name = np.name
);

-- =====================
-- Part 2: Insert classification rows in ref_partner_classification
-- All 17 new partners are GROUP / TIER / kpi_weight 1.00
-- (matches convention of existing 18 GROUP partners)
-- =====================
INSERT INTO ref_partner_classification 
  (partner_id, category, kpi_weight, bonus_model, effective_from, effective_to, notes)
SELECT 
  p.id,
  'GROUP'::varchar,
  1.00::numeric,
  'TIER'::varchar,
  '2024-01-01'::date,
  NULL::date,
  'Tier 2 master list 2026-05-10: GROUP/TIER/1.00 (default GROUP convention)'
FROM ref_partner p
WHERE p.name IN (
  'LBPSB','UPP','AIEP','ISES','KIC','EduLink','IP Edu','WHG','ASG','CIEE',
  'CEG','LCI','ESLI','EAP','ACAP','ICEAP','Bridge Edu'
)
AND NOT EXISTS (
  SELECT 1 FROM ref_partner_classification pc
  WHERE pc.partner_id = p.id
);

COMMIT;

-- ============================================================
-- Verification queries
-- ============================================================

-- ref_partner total should go from 27 to 44
SELECT classification, COUNT(*) AS partner_count
FROM ref_partner
GROUP BY classification
ORDER BY classification;
-- Expected: GROUP=35, MASTER_AGENT=9 (was GROUP=18, MASTER_AGENT=9)

-- ref_partner_classification total should go from 27 to 44
SELECT category, bonus_model, kpi_weight, COUNT(*) AS partner_count
FROM ref_partner_classification
GROUP BY category, bonus_model, kpi_weight
ORDER BY category, bonus_model;
-- Expected: GROUP/TIER/1.00 should be 35 (was 18)

-- The 17 new partners + their classifications, side-by-side
SELECT p.id, p.name, p.classification, 
       pc.category, pc.bonus_model, pc.kpi_weight
FROM ref_partner p
LEFT JOIN ref_partner_classification pc ON pc.partner_id = p.id
WHERE p.name IN (
  'LBPSB','UPP','AIEP','ISES','KIC','EduLink','IP Edu','WHG','ASG','CIEE',
  'CEG','LCI','ESLI','EAP','ACAP','ICEAP','Bridge Edu'
)
ORDER BY p.name;
-- All 17 should appear with classification=GROUP and pc rows populated
