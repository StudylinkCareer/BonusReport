-- =====================================================================
-- Phase 7 prep v2 extension — patch 5 (revised)
-- Date: 2026-05-05
--
-- Fix ref_status_split row id=57 — bare "Closed - Visa granted".
--
-- The 80-file inventory shows bare "Closed - Visa granted" is the
-- paperwork-complete-but-awaiting-enrolment state. 162 of 767 contracts
-- appear in two reports — first with bare "Closed - Visa granted" (no
-- payment expected, future course start), then with "Closed - Visa
-- granted, then enrolled" (id=41) when enrolment confirms and bonus
-- pays.
--
-- This patch updates only the columns we know exist (splits + is_zero_bonus).
-- The descriptive note stays in this comment block rather than the table.
-- =====================================================================

BEGIN;

-- Show before
SELECT 'BEFORE: row 57' AS check_name;
SELECT *
FROM ref_status_split
WHERE id = 57;

-- The fix — only the columns whose names we've confirmed
UPDATE ref_status_split
SET split_couns_pct = 0.000,
    split_co_dir_pct = 0.000,
    split_co_sub_pct = 0.000,
    is_zero_bonus = TRUE,
    updated_at = NOW()
WHERE id = 57;

-- Show after
SELECT 'AFTER: row 57' AS check_name;
SELECT *
FROM ref_status_split
WHERE id = 57;

COMMIT;
