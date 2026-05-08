-- Phase7_priority_targets_2026.sql
--
-- Maintains ref_priority_target by:
--   1. Closing the open-ended 2025 rows (effective_to was NULL) on 2025-12-31
--   2. Inserting 2026 rows with bonus_pct = 0 across the board
--
-- 2026 baseline matches 2025 baseline: no priority-partner bonuses are paid,
-- per management directive. This is consistent with the 03_PRIORITY_INSTNS
-- tab in the engine workbook for both 2025 and 2026.
--
-- Idempotent:
--   * The UPDATE only touches rows where effective_to IS NULL — re-running
--     after the first execution finds nothing to update.
--   * The INSERT uses NOT EXISTS to skip rows that already have a 2026 entry.
--
-- Verification queries at the end confirm the resulting state before COMMIT.

BEGIN;

-- 1. Close the 2025 open-ended rows.
UPDATE ref_priority_target
   SET effective_to = DATE '2025-12-31',
       updated_at   = NOW()
 WHERE effective_from = DATE '2025-01-01'
   AND effective_to IS NULL;

-- 2. Insert 2026 rows for every priority_list_id that has a 2025 row.
--    bonus_pct = 0; total_target carried forward from the 2025 row;
--    effective_to left NULL (open-ended) until 2026 is itself maintained.
INSERT INTO ref_priority_target (
    priority_list_id,
    bonus_pct,
    total_target,
    effective_from,
    effective_to,
    created_at,
    updated_at
)
SELECT
    src.priority_list_id,
    0.0000                  AS bonus_pct,
    src.total_target,
    DATE '2026-01-01'       AS effective_from,
    NULL                    AS effective_to,
    NOW()                   AS created_at,
    NOW()                   AS updated_at
  FROM ref_priority_target src
 WHERE src.effective_from = DATE '2025-01-01'
   AND NOT EXISTS (
       SELECT 1
         FROM ref_priority_target tgt
        WHERE tgt.priority_list_id = src.priority_list_id
          AND tgt.effective_from   = DATE '2026-01-01'
   );

-- ---------------------------------------------------------------------------
-- VERIFICATION QUERIES
-- ---------------------------------------------------------------------------

-- 2025 rows should now all have effective_to = 2025-12-31
SELECT
    'check_1_2025_rows_closed'                             AS check_label,
    COUNT(*)                                                AS total_2025_rows,
    SUM(CASE WHEN effective_to = DATE '2025-12-31'
             THEN 1 ELSE 0 END)                             AS closed_count,
    SUM(CASE WHEN effective_to IS NULL THEN 1 ELSE 0 END)   AS still_open_count
  FROM ref_priority_target
 WHERE effective_from = DATE '2025-01-01';

-- 2026 rows should exist for every priority_list_id, with bonus_pct = 0
SELECT
    'check_2_2026_rows_inserted'                            AS check_label,
    COUNT(*)                                                AS total_2026_rows,
    SUM(CASE WHEN bonus_pct = 0 THEN 1 ELSE 0 END)          AS zero_pct_rows,
    SUM(CASE WHEN bonus_pct <> 0 THEN 1 ELSE 0 END)         AS non_zero_pct_rows
  FROM ref_priority_target
 WHERE effective_from = DATE '2026-01-01';

-- Coverage sanity: every list with a 2025 row should also have a 2026 row
SELECT
    'check_3_coverage'                                      AS check_label,
    COUNT(DISTINCT pl_2025.priority_list_id)                AS lists_with_2025,
    COUNT(DISTINCT pl_2026.priority_list_id)                AS lists_with_2026,
    COUNT(DISTINCT pl_2025.priority_list_id)
      - COUNT(DISTINCT pl_2026.priority_list_id)            AS missing_in_2026
  FROM (
        SELECT priority_list_id FROM ref_priority_target
         WHERE effective_from = DATE '2025-01-01'
       ) pl_2025
  LEFT JOIN (
        SELECT priority_list_id FROM ref_priority_target
         WHERE effective_from = DATE '2026-01-01'
       ) pl_2026
    ON pl_2026.priority_list_id = pl_2025.priority_list_id;

-- Show three representative rows so you can eyeball the data
SELECT
    priority_list_id,
    bonus_pct,
    total_target,
    effective_from,
    effective_to
  FROM ref_priority_target
 WHERE priority_list_id IN (115, 117, 127)
 ORDER BY priority_list_id, effective_from;

COMMIT;
