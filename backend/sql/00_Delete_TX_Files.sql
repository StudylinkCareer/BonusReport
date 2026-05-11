BEGIN;

TRUNCATE TABLE 
    tx_bonus_payment,
    tx_carry_over_balance,
    tx_case,
    tx_case_approval,
    tx_case_edit_log,
    tx_case_notes_staging,
    tx_clawback_balance,
    tx_import_run,
    tx_priority_quota_tracker,
    tx_review_log,
    tx_run,
    tx_team_excess_distribution,
    tx_team_excess_period
RESTART IDENTITY CASCADE;

COMMIT;