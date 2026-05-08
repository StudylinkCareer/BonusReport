-- Schema discovery for tx_bonus_payment.
-- Need exact column names to write the INSERT in persist_payments().

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'tx_bonus_payment'
ORDER BY ordinal_position;

-- Also any indexes on it
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'tx_bonus_payment';
