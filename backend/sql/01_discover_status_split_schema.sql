-- Inspect ref_status_split — first show the schema, then the data.

-- 1. Column names + types
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'ref_status_split'
ORDER BY ordinal_position;

-- 2. All rows, all columns
SELECT * FROM ref_status_split ORDER BY id;

-- 3. Aliases (status code -> canonical mapping)
SELECT * FROM ref_status_split_alias ORDER BY id;
