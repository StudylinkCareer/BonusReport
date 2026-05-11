-- =============================================================================
-- Phase 15.1: Drop the legacy unique constraint on tx_case
-- =============================================================================
-- Removes the unique constraint/index on (contract_id, run_year, run_month)
-- because the new dedup rule is (contract_id, application_status), enforced
-- at the application layer (writer.py).
--
-- Idempotent. Defensive — finds the constraint/index by its column set
-- rather than hardcoding a name.
--
-- Note: pg_attribute.attname has type `name`, which is distinct from `text`
-- in PostgreSQL. We cast to text[] for array comparison.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    constraint_name TEXT;
    index_name      TEXT;
BEGIN
    -- Find a UNIQUE constraint whose key is exactly (contract_id, run_year, run_month)
    SELECT con.conname INTO constraint_name
      FROM pg_constraint con
      JOIN pg_class rel       ON rel.oid = con.conrelid
      JOIN pg_namespace nsp   ON nsp.oid = rel.relnamespace
     WHERE rel.relname = 'tx_case'
       AND nsp.nspname = 'public'
       AND con.contype = 'u'
       AND (
           SELECT array_agg(att.attname::text ORDER BY arr.ord)
             FROM unnest(con.conkey) WITH ORDINALITY AS arr(num, ord)
             JOIN pg_attribute att ON att.attnum = arr.num AND att.attrelid = rel.oid
       ) = ARRAY['contract_id', 'run_year', 'run_month']::text[];

    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE tx_case DROP CONSTRAINT %I', constraint_name);
        RAISE NOTICE 'Phase 15.1: dropped UNIQUE constraint "%"', constraint_name;
    END IF;

    -- Find a non-constraint UNIQUE index covering exactly those three columns
    SELECT (idx.indexrelid::regclass)::text INTO index_name
      FROM pg_index idx
      JOIN pg_class rel ON rel.oid = idx.indrelid
      JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
     WHERE rel.relname = 'tx_case'
       AND nsp.nspname = 'public'
       AND idx.indisunique = TRUE
       AND idx.indisprimary = FALSE
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint c
            WHERE c.conindid = idx.indexrelid
       )
       AND (
           SELECT array_agg(att.attname::text ORDER BY arr.ord)
             FROM unnest(idx.indkey) WITH ORDINALITY AS arr(num, ord)
             JOIN pg_attribute att ON att.attnum = arr.num AND att.attrelid = rel.oid
       ) = ARRAY['contract_id', 'run_year', 'run_month']::text[];

    IF index_name IS NOT NULL THEN
        EXECUTE format('DROP INDEX %s', index_name);
        RAISE NOTICE 'Phase 15.1: dropped UNIQUE INDEX "%"', index_name;
    END IF;

    IF constraint_name IS NULL AND index_name IS NULL THEN
        RAISE NOTICE 'Phase 15.1: no constraint or index found on (contract_id, run_year, run_month) — already clean';
    END IF;
END $$;


-- ---------------------------------------------------------------------------
-- Verification: confirm no UNIQUE constraint remains on those columns
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    remaining INT;
BEGIN
    SELECT COUNT(*) INTO remaining
      FROM pg_constraint con
      JOIN pg_class rel ON rel.oid = con.conrelid
     WHERE rel.relname = 'tx_case'
       AND con.contype = 'u'
       AND (
           SELECT array_agg(att.attname::text ORDER BY arr.ord)
             FROM unnest(con.conkey) WITH ORDINALITY AS arr(num, ord)
             JOIN pg_attribute att ON att.attnum = arr.num AND att.attrelid = rel.oid
       ) = ARRAY['contract_id', 'run_year', 'run_month']::text[];

    IF remaining <> 0 THEN
        RAISE EXCEPTION 'Phase 15.1 FAILED: % UNIQUE constraint(s) remain on (contract_id, run_year, run_month)', remaining;
    END IF;

    RAISE NOTICE '=========================================================';
    RAISE NOTICE 'Phase 15.1 OK';
    RAISE NOTICE 'Writer can now use app-level dedup by';
    RAISE NOTICE '(contract_id, application_status).';
    RAISE NOTICE '=========================================================';
END $$;

COMMIT;
