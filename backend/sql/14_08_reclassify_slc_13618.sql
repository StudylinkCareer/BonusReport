-- =============================================================================
-- Migration 14_08: Reclassify SLC-13618 status to "Closed - Visa Only Paid"
-- =============================================================================
--
-- SLC-13618 (Lê Gia Huy, Deakin University, Phạm Thị Lợi case officer)
-- was tagged with status_id=57 ('Closed - Visa granted'), which has
-- is_zero_bonus=true and means "visa granted PLUS enrolled". That's
-- incorrect for this case — the bao cao shows "Thu phí dv: 170 USD",
-- meaning a visa-renewal service fee was paid but no study enrolment
-- occurred. The correct status is id=59 ('Closed - Visa Only Paid')
-- which has is_visa_only_paid=true.
--
-- Migration 14_08a (this file) fixes SLC-13618 specifically.
--
-- Going forward, operators should pick:
--   * id=59 'Closed - Visa Only Paid'  → visa-only service fees paid,
--                                         no underlying study enrolment
--   * id=57 'Closed - Visa granted'    → ONLY when used as a generic
--                                         catch-all where 39 (plus
--                                         enrolled) or 40 (visa only)
--                                         can't be disambiguated.
--                                         Engine treats id=57 as zero-
--                                         bonus per the [14c] correction
--                                         in its notes.
--
-- A separate cleanup task (out of scope here) is to audit other cases
-- with status_id=57 + a confirmed tx_case_service row — these are
-- candidates for the same reclassification.
-- =============================================================================

BEGIN;

-- Confirm starting state (verification before mutation)
SELECT
  contract_id,
  application_status,
  application_status_id
FROM tx_case
WHERE contract_id = 'SLC-13618';

-- Reclassify
UPDATE tx_case
   SET application_status    = (SELECT status FROM ref_status_split WHERE id = 59),
       application_status_id = 59,
       updated_at            = NOW()
 WHERE contract_id = 'SLC-13618';

-- Confirm new state
SELECT
  contract_id,
  application_status,
  application_status_id
FROM tx_case
WHERE contract_id = 'SLC-13618';

-- And cross-check the status row that we're now pointing at
SELECT
  id,
  status,
  is_zero_bonus,
  is_visa_only_paid,
  notes
FROM ref_status_split
WHERE id = 59;

COMMIT;
