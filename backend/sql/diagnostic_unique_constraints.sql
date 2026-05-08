-- Quick diagnostic: which of the columns we're using in ON CONFLICT
-- actually have unique constraints or unique indexes?
--
-- Run this in pgAdmin and paste the result back.

SELECT
    t.relname AS table_name,
    i.relname AS index_name,
    a.attname AS column_name,
    ix.indisunique AS is_unique,
    ix.indpred IS NOT NULL AS is_partial
FROM pg_class t
JOIN pg_index ix     ON t.oid = ix.indrelid
JOIN pg_class i      ON i.oid = ix.indexrelid
JOIN pg_attribute a  ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE t.relname IN (
    'ref_institution',
    'ref_institution_alias',
    'ref_sub_agent',
    'ref_sub_agent_alias',
    'ref_priority_group',
    'ref_priority_partner'
)
  AND ix.indisunique = TRUE
ORDER BY t.relname, i.relname, a.attnum;
