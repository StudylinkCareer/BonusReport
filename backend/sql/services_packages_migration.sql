-- ============================================================================
-- SAVE TO: db/migrations/2026_05_11_phase5_services_packages_v6_2.sql
--
-- Full path on your machine:
--   C:\Users\rhod_\Documents\BonusReport\Application\db\migrations\
--     2026_05_11_phase5_services_packages_v6_2.sql
-- ============================================================================
--
-- Phase 5 (revised, v6.2-aware) — Services & Packages + new tx_case columns
--
-- Aligned to actual DB schema as inspected on 2026-05-11:
--   - ref_service_fee.id is BIGINT
--   - ref_service_fee.is_active is BOOLEAN (not 'Y'/'N')
--   - ref_service_fee.counsellor_signing_bonus / co_signing_bonus
--   - Categories present: SERVICE_FEE, PACKAGE, ADDON  (no CONTRACT)
--
-- This migration:
--   1. Adds bonus_payment_basis to ref_service_fee (default timing per code)
--   2. Adds 5 new columns to tx_case for the v6.2 spec
--   3. Creates the tx_case_service junction table with count + bonus_event
--   4. Adds CHECK constraints for the dropdown-validated fields
--
-- After this runs, NO rows in tx_case are changed — all new columns default
-- to NULL/FALSE. Existing cases keep loading normally.
--
-- Run via Railway dashboard query tab. Single transaction — all-or-nothing.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. ref_service_fee: bonus_payment_basis = default timing per service code
-- ----------------------------------------------------------------------------
ALTER TABLE ref_service_fee
    ADD COLUMN IF NOT EXISTS bonus_payment_basis TEXT;

COMMENT ON COLUMN ref_service_fee.bonus_payment_basis IS
    'Default timing trigger for this service code''s bonus payment. '
    'tx_case_service.bonus_event copies from this on insert and can be '
    'overridden per case. Values: contract_signed_date, visa_received_date, '
    'course_start_date, enrolment_date, manual_hold.';

-- Pre-fill heuristically. Review and adjust per-row after migration.
UPDATE ref_service_fee
   SET bonus_payment_basis = CASE
       -- All PACKAGE rows pay at contract signing
       WHEN category = 'PACKAGE' THEN 'contract_signed_date'

       -- ADDON rows: placeholder default. User to confirm per-row after
       -- reviewing the reference document they'll provide later.
       WHEN category = 'ADDON' THEN 'contract_signed_date'

       -- SERVICE_FEE: visa-flavoured codes → visa_received_date
       WHEN category = 'SERVICE_FEE'
        AND (service_code ILIKE '%visa%'
          OR service_code ILIKE '%permit%'
          OR service_code = 'CAQ')
         THEN 'visa_received_date'

       -- All other SERVICE_FEE → course_start_date
       WHEN category = 'SERVICE_FEE' THEN 'course_start_date'

       ELSE NULL
   END
 WHERE bonus_payment_basis IS NULL;

-- Enforce valid values going forward
ALTER TABLE ref_service_fee
    DROP CONSTRAINT IF EXISTS ref_service_fee_payment_basis_chk;
ALTER TABLE ref_service_fee
    ADD CONSTRAINT ref_service_fee_payment_basis_chk
    CHECK (bonus_payment_basis IS NULL OR bonus_payment_basis IN (
        'contract_signed_date',
        'visa_received_date',
        'course_start_date',
        'enrolment_date',
        'manual_hold'
    ));

-- ----------------------------------------------------------------------------
-- 2. tx_case: add 5 new columns (Phase 5 + v6.2 spec)
-- ----------------------------------------------------------------------------
ALTER TABLE tx_case
    -- Phase 5: single-select Package
    ADD COLUMN IF NOT EXISTS package_fee_id         BIGINT  REFERENCES ref_service_fee(id) ON DELETE SET NULL,
    -- Phase 5: importer auto-detect flag
    ADD COLUMN IF NOT EXISTS service_review_pending BOOLEAN NOT NULL DEFAULT FALSE,
    -- v6.2 col 9 (Trong/Ngoài hệ thống)
    ADD COLUMN IF NOT EXISTS system_type            TEXT,
    -- v6.2 col 28 (DIRECT/MASTER_AGENT/GROUP/OUT_OF_SYSTEM/RMIT_VN/OTHER_VN)
    ADD COLUMN IF NOT EXISTS institution_type       TEXT,
    -- v6.2 col 30 (who the case is transferred to — free text for now)
    ADD COLUMN IF NOT EXISTS targets_name           TEXT;

COMMENT ON COLUMN tx_case.package_fee_id IS
    'FK to ref_service_fee where category = PACKAGE. NULL if no package.';
COMMENT ON COLUMN tx_case.service_review_pending IS
    'TRUE when importer auto-detected services that user hasn''t confirmed.';
COMMENT ON COLUMN tx_case.system_type IS
    'v6.2 col 9. Whether the case is inside or outside the StudyLink system.';
COMMENT ON COLUMN tx_case.institution_type IS
    'v6.2 col 28. Channel through which the institution is serviced.';
COMMENT ON COLUMN tx_case.targets_name IS
    'v6.2 col 30. When a case is transferred, the target it''s transferred to.';

ALTER TABLE tx_case
    DROP CONSTRAINT IF EXISTS tx_case_system_type_chk;
ALTER TABLE tx_case
    ADD CONSTRAINT tx_case_system_type_chk
    CHECK (system_type IS NULL OR system_type IN (
        'Trong hệ thống',
        'Ngoài hệ thống'
    ));

ALTER TABLE tx_case
    DROP CONSTRAINT IF EXISTS tx_case_institution_type_chk;
ALTER TABLE tx_case
    ADD CONSTRAINT tx_case_institution_type_chk
    CHECK (institution_type IS NULL OR institution_type IN (
        'DIRECT',
        'MASTER_AGENT',
        'GROUP',
        'OUT_OF_SYSTEM',
        'RMIT_VN',
        'OTHER_VN'
    ));

CREATE INDEX IF NOT EXISTS idx_tx_case_package_fee_id ON tx_case(package_fee_id);

-- ----------------------------------------------------------------------------
-- 3. tx_case_service junction (multi-select Services)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tx_case_service (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT  NOT NULL REFERENCES tx_case(id)         ON DELETE CASCADE,
    service_fee_id  BIGINT  NOT NULL REFERENCES ref_service_fee(id) ON DELETE CASCADE,
    count           INTEGER NOT NULL DEFAULT 1 CHECK (count >= 1),
    bonus_event     TEXT    NOT NULL,
    confirmed       BOOLEAN NOT NULL DEFAULT FALSE,
    detection_source TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, service_fee_id),
    CHECK (bonus_event IN (
        'contract_signed_date',
        'visa_received_date',
        'course_start_date',
        'enrolment_date',
        'manual_hold'
    ))
);

COMMENT ON TABLE tx_case_service IS
    'Many-to-many between tx_case and ref_service_fee. One row per service '
    'applied to a case. PACKAGE rows belong on tx_case.package_fee_id, not '
    'here; only SERVICE_FEE and ADDON category rows should appear in this '
    'table. The (case_id, service_fee_id) UNIQUE constraint means the same '
    'service code can appear only once per case — multiple instances are '
    'represented by the count column (e.g. EXTRA_SCHOOL with count=2).';

COMMENT ON COLUMN tx_case_service.count IS
    'Quantity of this service for this case. Defaults to 1. Drives engine '
    'bonus = ref_service_fee.counsellor_signing_bonus * count (etc).';

COMMENT ON COLUMN tx_case_service.bonus_event IS
    'Per-case timing override. Defaults from ref_service_fee.bonus_payment_basis '
    'when inserted; user can edit per case. ''manual_hold'' = engine should not '
    'pay this until user manually triggers it.';

COMMENT ON COLUMN tx_case_service.confirmed IS
    'TRUE once the user has explicitly confirmed this service for this case. '
    'When the importer auto-detects a service, this stays FALSE until the '
    'user reviews and confirms (see tx_case.service_review_pending for the '
    'case-level banner).';

COMMENT ON COLUMN tx_case_service.detection_source IS
    'How the row was created: importer_keyword (auto-detected from notes), '
    'user_manual (user picked from dropdown), or NULL (legacy/unknown).';

CREATE INDEX IF NOT EXISTS idx_tx_case_service_case_id ON tx_case_service(case_id);
CREATE INDEX IF NOT EXISTS idx_tx_case_service_fee_id  ON tx_case_service(service_fee_id);

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION tx_case_service_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tx_case_service_updated_at ON tx_case_service;
CREATE TRIGGER trg_tx_case_service_updated_at
    BEFORE UPDATE ON tx_case_service
    FOR EACH ROW
    EXECUTE FUNCTION tx_case_service_set_updated_at();

COMMIT;

-- ============================================================================
-- Post-migration verification — paste each block separately into Railway
-- ============================================================================
--
-- A. Confirm bonus_payment_basis populated by category:
--      SELECT category, bonus_payment_basis, COUNT(*) AS n
--        FROM ref_service_fee
--       WHERE is_active = TRUE
--       GROUP BY category, bonus_payment_basis
--       ORDER BY category, bonus_payment_basis;
--
-- B. Spot-check the assignment per row — paste any wrong ones back to me:
--      SELECT service_code, category, bonus_payment_basis
--        FROM ref_service_fee
--       WHERE is_active = TRUE
--       ORDER BY category, service_code;
--    To fix individual rows:
--      UPDATE ref_service_fee
--         SET bonus_payment_basis = 'visa_received_date'
--       WHERE service_code = 'STUDY_PERMIT_RENEWAL';
--
-- C. Confirm new columns on tx_case:
--      SELECT column_name, data_type, is_nullable, column_default
--        FROM information_schema.columns
--       WHERE table_name = 'tx_case'
--         AND column_name IN (
--             'package_fee_id', 'service_review_pending',
--             'system_type', 'institution_type', 'targets_name'
--         )
--       ORDER BY column_name;
--
-- D. Confirm tx_case_service exists and is empty:
--      SELECT COUNT(*) FROM tx_case_service;        -- should be 0
--      \d tx_case_service                            -- shows full table spec
--
-- ============================================================================
