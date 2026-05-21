-- =====================================================================
-- Migration 14_01: Clean slate — truncate all tx_* tables
-- =====================================================================
--
-- Purpose: Wipe all transactional data and reset identity sequences.
-- Reference data (ref_*, dim_*) is untouched.
--
-- Wraps everything in BEGIN/COMMIT so you can review the row counts
-- BEFORE committing. If anything looks wrong, run ROLLBACK instead of
-- COMMIT and the database is restored.
--
-- CASCADE handles FK ordering automatically.
-- RESTART IDENTITY resets all SERIAL sequences back to 1.
--
-- Tables wiped (17 total):
--   tx_bonus_payment              -- engine output
--   tx_bonus_reversal             -- bonus reversals
--   tx_carry_over_balance         -- carry-over state
--   tx_case                       -- main case rows
--   tx_case_approval              -- approval workflow
--   tx_case_edit_log              -- edit audit
--   tx_case_notes_staging         -- importer notes
--   tx_case_override              -- manual overrides
--   tx_case_service               -- (purpose unknown to me — included for completeness)
--   tx_clawback_balance           -- clawback state
--   tx_comment                    -- comments
--   tx_import_run                 -- import run audit
--   tx_priority_quota_tracker     -- Phase 12a tracker (already empty)
--   tx_review_log                 -- review audit
--   tx_run                        -- engine run audit
--   tx_team_excess_distribution   -- team bonus distribution
--   tx_team_excess_period         -- team bonus period state
-- =====================================================================

BEGIN;

-- Show what's there before
SELECT 'BEFORE WIPE' AS phase;
SELECT 'tx_bonus_payment' AS table_name, COUNT(*) AS rows FROM tx_bonus_payment
UNION ALL SELECT 'tx_bonus_reversal',            COUNT(*) FROM tx_bonus_reversal
UNION ALL SELECT 'tx_carry_over_balance',        COUNT(*) FROM tx_carry_over_balance
UNION ALL SELECT 'tx_case',                      COUNT(*) FROM tx_case
UNION ALL SELECT 'tx_case_approval',             COUNT(*) FROM tx_case_approval
UNION ALL SELECT 'tx_case_edit_log',             COUNT(*) FROM tx_case_edit_log
UNION ALL SELECT 'tx_case_notes_staging',        COUNT(*) FROM tx_case_notes_staging
UNION ALL SELECT 'tx_case_override',             COUNT(*) FROM tx_case_override
UNION ALL SELECT 'tx_case_service',              COUNT(*) FROM tx_case_service
UNION ALL SELECT 'tx_clawback_balance',          COUNT(*) FROM tx_clawback_balance
UNION ALL SELECT 'tx_comment',                   COUNT(*) FROM tx_comment
UNION ALL SELECT 'tx_import_run',                COUNT(*) FROM tx_import_run
UNION ALL SELECT 'tx_priority_quota_tracker',    COUNT(*) FROM tx_priority_quota_tracker
UNION ALL SELECT 'tx_review_log',                COUNT(*) FROM tx_review_log
UNION ALL SELECT 'tx_run',                       COUNT(*) FROM tx_run
UNION ALL SELECT 'tx_team_excess_distribution',  COUNT(*) FROM tx_team_excess_distribution
UNION ALL SELECT 'tx_team_excess_period',        COUNT(*) FROM tx_team_excess_period
ORDER BY table_name;

-- The wipe. CASCADE walks all FK relationships so order doesn't matter.
TRUNCATE TABLE
    tx_bonus_payment,
    tx_bonus_reversal,
    tx_carry_over_balance,
    tx_case,
    tx_case_approval,
    tx_case_edit_log,
    tx_case_notes_staging,
    tx_case_override,
    tx_case_service,
    tx_clawback_balance,
    tx_comment,
    tx_import_run,
    tx_priority_quota_tracker,
    tx_review_log,
    tx_run,
    tx_team_excess_distribution,
    tx_team_excess_period
RESTART IDENTITY CASCADE;

-- Show what's there after (everything should read 0)
SELECT 'AFTER WIPE' AS phase;
SELECT 'tx_bonus_payment' AS table_name, COUNT(*) AS rows FROM tx_bonus_payment
UNION ALL SELECT 'tx_bonus_reversal',            COUNT(*) FROM tx_bonus_reversal
UNION ALL SELECT 'tx_carry_over_balance',        COUNT(*) FROM tx_carry_over_balance
UNION ALL SELECT 'tx_case',                      COUNT(*) FROM tx_case
UNION ALL SELECT 'tx_case_approval',             COUNT(*) FROM tx_case_approval
UNION ALL SELECT 'tx_case_edit_log',             COUNT(*) FROM tx_case_edit_log
UNION ALL SELECT 'tx_case_notes_staging',        COUNT(*) FROM tx_case_notes_staging
UNION ALL SELECT 'tx_case_override',             COUNT(*) FROM tx_case_override
UNION ALL SELECT 'tx_case_service',              COUNT(*) FROM tx_case_service
UNION ALL SELECT 'tx_clawback_balance',          COUNT(*) FROM tx_clawback_balance
UNION ALL SELECT 'tx_comment',                   COUNT(*) FROM tx_comment
UNION ALL SELECT 'tx_import_run',                COUNT(*) FROM tx_import_run
UNION ALL SELECT 'tx_priority_quota_tracker',    COUNT(*) FROM tx_priority_quota_tracker
UNION ALL SELECT 'tx_review_log',                COUNT(*) FROM tx_review_log
UNION ALL SELECT 'tx_run',                       COUNT(*) FROM tx_run
UNION ALL SELECT 'tx_team_excess_distribution',  COUNT(*) FROM tx_team_excess_distribution
UNION ALL SELECT 'tx_team_excess_period',        COUNT(*) FROM tx_team_excess_period
ORDER BY table_name;

-- If "AFTER WIPE" shows all zeros, commit. Otherwise rollback.
-- COMMIT;
-- ROLLBACK;
