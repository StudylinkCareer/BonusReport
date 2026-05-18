-- ============================================================================
-- Migration 14d (v3) — Load all 34 service fee rates from 09_SERVICE_FEE_RATES v5.3
-- ============================================================================
-- Purpose:
--   Synchronises ref_service_fee with the canonical rate table.
--
-- This version (v3):
--   1. Uses a CTE-based UPDATE-then-INSERT pattern (no ON CONFLICT needed).
--   2. INSERT supplies effective_from (which is NOT NULL on the table).
--      UPDATE deliberately does NOT touch effective_from — existing rows
--      keep their historical effective_from value.
--   3. Adds a UNIQUE constraint on service_code at the end.
--
-- Idempotency:
--   Safe to re-run. UPDATE handles existing rows; INSERT fires only for
--   missing rows. The UNIQUE constraint add is guarded.
--
-- Dependencies:
--   Run AFTER 14c.
-- ============================================================================

BEGIN;

WITH new_rates(service_code, description, category, applies_to,
               counsellor_signing_bonus, co_signing_bonus) AS (
    VALUES
    -- SERVICE_FEE rows (18)
    ('STUDY_PERMIT_RENEWAL',   'Study permit renewal',                    'SERVICE_FEE', 'ALL',           0,       250000),
    ('VISA_RENEWAL',           'Student visa renewal AUS/NZ',             'SERVICE_FEE', 'ALL',           0,       400000),
    ('VISA_ONLY',              'Visa only (first visa)',                  'SERVICE_FEE', 'ALL',           0,       600000),
    ('VISA_485',               'Visa 485 post-study work visa',           'SERVICE_FEE', 'ALL',           0,       600000),
    ('CAQ',                    'CAQ (Quebec Acceptance Certificate)',     'SERVICE_FEE', 'ALL',           0,       250000),
    ('GUARDIAN_CHANGE',        'Changing guardian',                       'SERVICE_FEE', 'ALL',           0,       250000),
    ('GUARDIAN_GRANTED',       'Guardian visa granted',                   'SERVICE_FEE', 'ALL',           0,       600000),
    ('GUARDIAN_REFUSED',       'Guardian visa refused',                   'SERVICE_FEE', 'ALL',           0,       300000),
    ('GUARDIAN_VISA',          'Guardian from AUS (Aug 2022+)',           'SERVICE_FEE', 'ALL',           0,       250000),
    ('DEPENDANT_GRANTED',      'Dependant visa granted',                  'SERVICE_FEE', 'ALL',           0,       400000),
    ('DEPENDANT_REFUSED',      'Dependant visa refused',                  'SERVICE_FEE', 'ALL',           0,       150000),
    ('HOMESTAY_CHANGE',        'Changing homestay',                       'SERVICE_FEE', 'ALL',           0,       250000),
    ('EXTRA_SCHOOL',           'Enrolling additional school',             'SERVICE_FEE', 'ALL',           0,       250000),
    ('VISITOR_EXCHANGE',       'Visitor/Exchange/other admin',            'SERVICE_FEE', 'ALL',           0,       250000),
    ('CANCELLED_FULL_SERVICE', 'Cancelled full-service (fees paid)',      'SERVICE_FEE', 'ALL',           0,       400000),
    ('TRANSFER_NO_COMMISSION', 'School transfer - no commission',         'SERVICE_FEE', 'ALL',           0,       250000),
    ('STUDENT_VISA_RENEWAL',   'Alias for VISA_RENEWAL',                  'SERVICE_FEE', 'ALL',           0,       400000),
    ('DIFFICULT_CASE',         'Difficult case / Out-system full 20M+',   'SERVICE_FEE', 'OUT_OF_SYSTEM', 0,       500000),

    -- PACKAGE rows (13)
    ('Standard Plus (3tr)',                  'AP Standard Plus 3M — CO: no extra bonus',  'PACKAGE', 'DIRECT',  500000,   0),
    ('Superior Package (6tr)',               'AP Superior 6M',                            'PACKAGE', 'DIRECT',  1000000,  500000),
    ('superior Package 6tr',                 'AP Superior 6M — alternate capitalisation', 'PACKAGE', 'DIRECT',  1000000,  500000),
    ('Premium Package (9tr)',                'AP Premium 9M',                             'PACKAGE', 'DIRECT',  1500000,  500000),
    ('SDS (7tr5)',                           'Canada SDS 7.5M — no CO extra',             'PACKAGE', 'DIRECT',  0,        0),
    ('Standard Package (9tr5)',              'Canada Standard 9.5M — no CO extra',        'PACKAGE', 'DIRECT',  1000000,  0),
    ('Premium Canada (14tr)',                'Canada Premium 14M',                        'PACKAGE', 'DIRECT',  2000000,  500000),
    ('Standard Package (16tr)',              'USA Standard In-Full 16M — no CO extra',    'PACKAGE', 'DIRECT',  1000000,  0),
    ('Superior Package USA In-Full (45tr)',  'USA Superior In-Full 45M',                  'PACKAGE', 'DIRECT',  2000000,  500000),
    ('Standard Package USA Out-Full (28tr)', 'USA Standard Out-Full 28M — no CO extra',   'PACKAGE', 'DIRECT',  500000,   0),
    ('Superior Package USA Out-Full (68tr)', 'USA Superior Out-Full 68M',                 'PACKAGE', 'DIRECT',  1500000,  500000),
    ('Premium Package',                      'AP Premium 9M alias (no suffix)',           'PACKAGE', 'PACKAGE', 0,        500000),
    ('Regular (9tr5)',                       'Canada Regular 9.5M — Counsellor only',     'PACKAGE', 'PACKAGE', 0,        0),

    -- CONTRACT rows (3)
    ('OUT_SYSTEM_FULL_AUS',     'Out-system full service AUS 20M (signing bonus regardless of visa)', 'CONTRACT', 'OUT_OF_SYSTEM', 1100000, 500000),
    ('GUARDIAN_AU_ADDON',       'Guardian AUS add-on (250k total split 50/50 across two COs)',         'CONTRACT', 'ALL',           0,       125000),
    ('REFERRAL_LOVELY_COFFEE',  'Add-on service referral (Lovely Cup of Coffee) — Counsellor only',    'CONTRACT', 'ALL',           100000,  0)
),
-- UPDATE existing rows (does NOT touch effective_from)
updated AS (
    UPDATE ref_service_fee r
    SET description              = n.description,
        category                 = n.category,
        applies_to               = n.applies_to,
        counsellor_signing_bonus = n.counsellor_signing_bonus,
        co_signing_bonus         = n.co_signing_bonus,
        is_active                = TRUE,
        updated_at               = NOW()
    FROM new_rates n
    WHERE r.service_code = n.service_code
    RETURNING r.service_code
)
-- INSERT missing rows (provides effective_from)
INSERT INTO ref_service_fee
    (service_code, description, category, applies_to,
     counsellor_signing_bonus, co_signing_bonus, is_active, effective_from)
SELECT n.service_code, n.description, n.category, n.applies_to,
       n.counsellor_signing_bonus, n.co_signing_bonus, TRUE, DATE '2020-01-01'
FROM new_rates n
WHERE n.service_code NOT IN (SELECT service_code FROM updated);

-- ----------------------------------------------------------------------------
-- Add UNIQUE constraint on service_code (idempotent)
-- ----------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint con
        JOIN pg_class cls ON cls.oid = con.conrelid
        WHERE cls.relname = 'ref_service_fee'
          AND con.contype = 'u'
          AND array_length(con.conkey, 1) = 1
          AND EXISTS (
              SELECT 1 FROM pg_attribute a
              WHERE a.attrelid = con.conrelid
                AND a.attnum = con.conkey[1]
                AND a.attname = 'service_code'
          )
    ) THEN
        ALTER TABLE ref_service_fee
            ADD CONSTRAINT ref_service_fee_service_code_unique
            UNIQUE (service_code);
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

SELECT category, applies_to, COUNT(*) AS row_count
FROM ref_service_fee
WHERE is_active = TRUE
GROUP BY category, applies_to
ORDER BY category, applies_to;

SELECT service_code, category, applies_to,
       counsellor_signing_bonus, co_signing_bonus, effective_from
FROM ref_service_fee
WHERE service_code IN (
    'VISA_ONLY',                    -- expect 0 / 600,000
    'DIFFICULT_CASE',               -- expect 0 / 500,000 OUT_OF_SYSTEM
    'Premium Package (9tr)',        -- expect 1,500,000 / 500,000 DIRECT
    'OUT_SYSTEM_FULL_AUS',          -- expect 1,100,000 / 500,000 CONTRACT
    'REFERRAL_LOVELY_COFFEE'        -- expect 100,000 / 0 CONTRACT ALL
)
ORDER BY service_code;

SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class cls ON cls.oid = con.conrelid
WHERE cls.relname = 'ref_service_fee'
  AND con.contype = 'u';
