-- Find the CHECK constraint on tx_bonus_payment.slot to see allowed values
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'tx_bonus_payment'::regclass
  AND contype = 'c'
ORDER BY conname;
