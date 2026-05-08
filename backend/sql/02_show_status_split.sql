-- Step 1: see all column names of ref_status_split
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'ref_status_split'
ORDER BY ordinal_position;

-- Step 2: see all rows of ref_status_split (just SELECT * — schema unknown)
SELECT * FROM ref_status_split ORDER BY id;
