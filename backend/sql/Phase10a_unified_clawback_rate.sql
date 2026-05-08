-- =========================================================================
-- Phase 10a: Unified clawback rate table
-- =========================================================================
-- Replaces ref_priority_clawback_rate with a unified ref_clawback_rate.
-- Single table, per-year, per-bonus-type clawback percentages.
--
-- BASE     = clawback applied to tier/package/addon/flat_local bonuses
--            when §I.5.3 fires (student doesn't enrol or commission missing).
--            Default 1.000 preserves existing engine behaviour.
--
-- PRIORITY = clawback applied to the at-enrolment 50% priority half if
--            year-end KPI misses. Default 0.000 — no clawback for now,
--            ramp later by inserting new (year, 'PRIORITY') rows.
--
-- Both rates can be changed independently per year. The year-end
-- finalizer code will read this table when it computes any clawback.
-- =========================================================================

BEGIN;

-- 1. Drop the priority-only table (1 row, easy to recreate via INSERT below)
DROP TABLE IF EXISTS ref_priority_clawback_rate;

-- 2. Create unified table
CREATE TABLE ref_clawback_rate (
    id              BIGSERIAL PRIMARY KEY,
    effective_year  INTEGER NOT NULL,
    bonus_type      VARCHAR(16) NOT NULL CHECK (bonus_type IN ('BASE', 'PRIORITY')),
    clawback_pct    DECIMAL(4,3) NOT NULL CHECK (clawback_pct BETWEEN 0 AND 1),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (effective_year, bonus_type)
);

CREATE TRIGGER trg_ref_clawback_rate_set_updated_at
BEFORE UPDATE ON ref_clawback_rate
FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- 3. Seed 2024 rows
INSERT INTO ref_clawback_rate (effective_year, bonus_type, clawback_pct, notes)
VALUES
    (2024, 'BASE',     1.000, 'Base bonus full clawback per existing §I.5.3 behaviour'),
    (2024, 'PRIORITY', 0.000, 'No priority clawback for 2024 — capability deployed but inactive');

-- 4. Verification (should return 2 rows)
SELECT effective_year, bonus_type, clawback_pct, notes
FROM ref_clawback_rate
ORDER BY effective_year, bonus_type;

COMMIT;

-- After commit, to verify:
-- SELECT effective_year, bonus_type, clawback_pct FROM ref_clawback_rate;
--
-- To change a rate later:
-- INSERT INTO ref_clawback_rate (effective_year, bonus_type, clawback_pct, notes)
-- VALUES (2025, 'PRIORITY', 0.250, 'Ramp to 25% clawback for priority in 2025');
