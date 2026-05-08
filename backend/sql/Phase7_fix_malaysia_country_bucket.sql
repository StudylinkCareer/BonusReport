-- =============================================================================
-- Phase 7 fix: Malaysia incorrectly flagged as both target AND flat country
-- =============================================================================
-- Issue: dim_country has Malaysia (id=67) with is_target_country=TRUE AND
-- is_flat_country=TRUE. classifiers.classify_country_bucket() checks the
-- target flag first, so Malaysia returned BUCKET_TARGET and got the
-- performance-tier rate (1,100k OVER for Lợi in July) instead of the
-- BUCKET_FLAT rate (600k flat for sub-agent CO).
--
-- Per policy doc Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.2 and
-- ref_rate row 238 note "D6.R3 HCM Couns flat (TH/PH/MY/KR)" — MY belongs
-- in the FLAT bucket alongside TH/PH/KR.
--
-- Sister flat countries (verified in same query):
--   TH (id=68): is_target=FALSE, is_flat=TRUE  ✓ correct
--   PH (id=69): is_target=FALSE, is_flat=TRUE  ✓ correct
--   KR (id=70): is_target=FALSE, is_flat=TRUE  ✓ correct
--   MY (id=67): is_target=TRUE,  is_flat=TRUE  ✗ this fix
--
-- Verified impact (Lợi 2025): closes Bug 1, SLC-14362 will pay 600k from
-- ref_rate row 295 (office=18, role=18, ENROL_ONLY, FLAT/FLAT) instead of
-- 1,100k from row 292 (TARGET/OVER), matching the bao cao.
-- =============================================================================

BEGIN;

-- The actual fix: clear is_target_country on Malaysia.
UPDATE dim_country
SET is_target_country = FALSE,
    updated_at = NOW()
WHERE code = 'MY'
  AND is_target_country = TRUE;

-- Self-verification: this SELECT must return exactly 4 rows, all with
-- is_target=FALSE and is_flat=TRUE.
SELECT
    id,
    code,
    name,
    is_target_country,
    is_flat_country,
    CASE
        WHEN is_target_country = FALSE AND is_flat_country = TRUE THEN 'OK'
        ELSE 'FAIL — flags still wrong'
    END AS verify_status
FROM dim_country
WHERE code IN ('MY', 'TH', 'PH', 'KR')
ORDER BY code;

COMMIT;

-- =============================================================================
-- Post-deploy: re-run engine for Lợi July 2025 (--persist) and confirm
-- SLC-14362 audit_json now shows:
--   "country_bucket": "FLAT"
--   "tier": "FLAT"
--   "rate_amount": 600000
--   "rate_row_id": 295
-- =============================================================================
