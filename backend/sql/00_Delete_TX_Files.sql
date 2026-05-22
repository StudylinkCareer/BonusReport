BEGIN;

TRUNCATE TABLE
    tx_bonus_payment,
    tx_bonus_reversal,
    tx_carry_over_balance,
    tx_case,
    tx_case_approval,
    tx_case_edit_log,
    tx_case_override,
    tx_case_service,
    tx_clawback_balance,
    tx_comment,
    tx_engine_row_write,
    tx_engine_run,
    tx_import_run,
    tx_priority_quota_tracker,
    tx_review_log,
    tx_run,
    tx_team_excess_distribution,
    tx_team_excess_period
RESTART IDENTITY CASCADE;

COMMIT;