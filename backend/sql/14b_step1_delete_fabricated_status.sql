-- =============================================================================
-- Migration: 14b_step1_delete_fabricated_status.sql
-- =============================================================================
-- Purpose:
--   Delete the fabricated 'Closed - Visa Only Paid' row from ref_status_split.
--   This row was invented in a prior session to model visa-only contracts via
--   a status flag (is_visa_only_paid). That approach was wrong — visa-only is
--   a client_type concept ('Du học (visa)' → VISA_ONLY_SERVICE), not a status.
--
--   The fabricated status has no policy-document basis. Sheet 05 v6.0 (v7
--   workbook, reference only) lists 16 application statuses, none of which
--   is 'Closed - Visa Only Paid'. The procedural docs likewise do not
--   describe this status.
--
--   Earlier in this session, the case SLC-13618 (which had been mis-flagged
--   with this fabricated status) was already relabeled to 'Closed - Visa
--   granted' via UPDATE on tx_case. SQL verification this session shows
--   zero tx_case rows currently reference 'Closed - Visa Only Paid'.
--
-- Source documents cited:
--   - User SQL verification (this session, query 1) — zero tx_case rows
--     reference 'Closed - Visa Only Paid'.
--   - Absence of this status in all 13 procedural documents and in v7
--     Sheet 05_STATUS_RULES.
--
-- Scope:
--   This migration deletes ONLY the fabricated ref_status_split row.
--   It does NOT yet:
--     - Drop the is_visa_only_paid column from ref_status_split
--       (waits until engine code stops reading it — Phase 14b step 5)
--     - Touch any engine code (separate steps)
--     - Affect any other status rows
--
-- Idempotency:
--   Uses DELETE WHERE — re-running has no effect after the row is gone.
--   Self-verification at end confirms post-state.
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1 — Pre-flight safety check
-- =============================================================================
-- Confirm no tx_case rows reference this status. If any exist, abort —
-- we'd be orphaning data otherwise.

DO $$
DECLARE
    orphan_count INT;
BEGIN
    SELECT COUNT(*) INTO orphan_count
      FROM tx_case
     WHERE application_status = 'Closed - Visa Only Paid';

    IF orphan_count > 0 THEN
        RAISE EXCEPTION
            'Cannot delete fabricated status: % tx_case rows still reference '
            '''Closed - Visa Only Paid''. Relabel them first.',
            orphan_count;
    END IF;
END $$;


-- =============================================================================
-- STEP 2 — Delete the fabricated row
-- =============================================================================

DELETE FROM ref_status_split
 WHERE status = 'Closed - Visa Only Paid';


-- =============================================================================
-- STEP 3 — Self-verification
-- =============================================================================

DO $$
DECLARE
    remaining_count       INT;
    visa_only_paid_total  INT;
BEGIN
    -- 3a) Confirm the fabricated row is gone
    SELECT COUNT(*) INTO remaining_count
      FROM ref_status_split
     WHERE status = 'Closed - Visa Only Paid';

    IF remaining_count <> 0 THEN
        RAISE EXCEPTION
            'Expected 0 ''Closed - Visa Only Paid'' rows after delete, found %',
            remaining_count;
    END IF;

    -- 3b) Confirm no other rows have is_visa_only_paid = TRUE
    --     (The fabricated row was the only one; sanity check no others exist.)
    SELECT COUNT(*) INTO visa_only_paid_total
      FROM ref_status_split
     WHERE is_visa_only_paid = TRUE;

    IF visa_only_paid_total <> 0 THEN
        RAISE EXCEPTION
            'Unexpected: % ref_status_split rows still have is_visa_only_paid=TRUE. '
            'Expected 0 after deleting the fabricated row.',
            visa_only_paid_total;
    END IF;

    RAISE NOTICE 'Fabricated status row deleted. ref_status_split now has % rows.',
        (SELECT COUNT(*) FROM ref_status_split);
END $$;

COMMIT;


-- =============================================================================
-- POST-COMMIT VERIFICATION QUERY
-- =============================================================================

-- Show remaining ref_status_split rows — should be 21 (was 22, deleted 1)
SELECT COUNT(*) AS remaining_rows FROM ref_status_split;

-- Confirm no row has is_visa_only_paid = TRUE
SELECT status, is_visa_only_paid
  FROM ref_status_split
 WHERE is_visa_only_paid = TRUE;
-- ↑ This should return 0 rows.
