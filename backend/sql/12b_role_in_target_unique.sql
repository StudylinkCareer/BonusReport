-- ============================================================================
-- Migration: Add role_id to ref_staff_target unique key
-- ============================================================================
-- Why: Phạm Thị Lợi has two role streams (CO_SUB sub-agent + CO_DIR direct).
-- Both produce CANCELLED-rate targets for the same months. Under the previous
-- (staff_id, year, month, target_type) constraint they collided.  Adding
-- role_id to the key lets both coexist.
--
-- Effect on existing data: none. Old rows already have role_id populated,
-- and no current rows would conflict under the wider key.
-- ============================================================================

BEGIN;

-- 1. Drop the existing 4-column unique constraint (whatever Postgres named it)
DO $$
DECLARE
  cname  TEXT;
  cols   name[];
  target_cols name[] := ARRAY['month','staff_id','target_type','year']::name[];
BEGIN
  FOR cname IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'ref_staff_target'::regclass
      AND c.contype  = 'u'
  LOOP
    SELECT array_agg(a.attname ORDER BY a.attname) INTO cols
    FROM pg_constraint c2
    JOIN pg_attribute a ON a.attrelid = c2.conrelid AND a.attnum = ANY(c2.conkey)
    WHERE c2.conname = cname;

    IF cols = target_cols THEN
      EXECUTE format('ALTER TABLE ref_staff_target DROP CONSTRAINT %I', cname);
      RAISE NOTICE 'Dropped old unique constraint: %', cname;
      EXIT;
    END IF;
  END LOOP;
END $$;

-- 2. Add the new 5-column unique constraint
ALTER TABLE ref_staff_target
  ADD CONSTRAINT ref_staff_target_unique_key
  UNIQUE (staff_id, role_id, year, month, target_type);

-- 3. Verify
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'ref_staff_target'::regclass
  AND contype  = 'u';

COMMIT;
