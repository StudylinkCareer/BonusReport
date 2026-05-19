-- ============================================================================
-- Phase 14.3 — Widen tx_case.bonus_year_month from CHAR(7) to TEXT
-- ============================================================================
-- Rationale: this column is a grouping label only ("which bonus run does
-- this case belong to"), not a typed date. CHAR(7) is too strict — a
-- date object flowing through psycopg gets ISO-formatted to "2024-01-01"
-- (10 chars) and overflows, and there's no benefit to enforcing exactly
-- 7 chars at the column level. TEXT matches how the field is actually
-- used: a consistent string applied uniformly to every case in a batch.
--
-- Safe to run multiple times — the guard checks current type before
-- altering. No data conversion is needed (any existing CHAR(7) values
-- store cleanly as TEXT, including blank-padding which TEXT preserves).
-- ============================================================================

BEGIN;

SELECT 'Phase 14.3: widen bonus_year_month to TEXT' AS section;

-- Show current state
SELECT 'BEFORE' AS state, column_name, data_type, character_maximum_length, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'tx_case' AND column_name = 'bonus_year_month';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'tx_case'
       AND column_name = 'bonus_year_month'
       AND data_type IN ('character', 'character varying')
  ) THEN
    ALTER TABLE tx_case ALTER COLUMN bonus_year_month TYPE TEXT;
    RAISE NOTICE 'bonus_year_month altered to TEXT.';
  ELSE
    RAISE NOTICE 'bonus_year_month is already TEXT (or missing); no change.';
  END IF;
END
$$;

-- Verification — should now show data_type = 'text', character_maximum_length = NULL
SELECT 'AFTER' AS state, column_name, data_type, character_maximum_length, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'tx_case' AND column_name = 'bonus_year_month';

COMMIT;
