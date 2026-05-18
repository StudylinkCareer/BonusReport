-- ============================================================================
-- Migration 14j — Create tx_comment table
-- ============================================================================
-- Purpose:
--   Comments attached to cases (or specific bonus payment slots). Used for:
--     - General notes between staff during In Review
--     - Queries raised by staff in Submitted phase ("why is my bonus X?")
--     - Resolutions/replies from Director/FO/Admin
--
--   payment_id is nullable: NULL = case-level comment; non-NULL = comment
--   on a specific bonus_payment row (slot-level).
--
--   is_query + resolved together implement the "open query" pattern. A
--   period cannot be closed while open queries exist.
--
-- Idempotency:
--   CREATE TABLE IF NOT EXISTS.
--
-- Dependencies:
--   tx_case (exists), tx_bonus_payment (exists), 14f (app_user).
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS tx_comment (
    id                      BIGSERIAL PRIMARY KEY,
    case_id                 BIGINT  NOT NULL REFERENCES tx_case(id) ON DELETE CASCADE,
    payment_id              BIGINT  REFERENCES tx_bonus_payment(id) ON DELETE CASCADE,
    comment_text            TEXT    NOT NULL CHECK (LENGTH(TRIM(comment_text)) > 0),
    is_query                BOOLEAN NOT NULL DEFAULT FALSE,
    resolved                BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by_user_id     BIGINT  REFERENCES app_user(id),
    resolved_at             TIMESTAMPTZ,
    created_by_user_id      BIGINT  NOT NULL REFERENCES app_user(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- A non-query can't be "resolved"; resolved requires resolver fields
    CHECK ((resolved = FALSE AND resolved_at IS NULL AND resolved_by_user_id IS NULL)
        OR (resolved = TRUE  AND resolved_at IS NOT NULL AND resolved_by_user_id IS NOT NULL
            AND is_query = TRUE))
);

-- Most common: "all comments on this case" (chronological)
CREATE INDEX IF NOT EXISTS idx_tx_comment_case
    ON tx_comment (case_id, created_at DESC);

-- For period-close gate: "are there any open queries?"
CREATE INDEX IF NOT EXISTS idx_tx_comment_open_queries
    ON tx_comment (case_id)
    WHERE is_query = TRUE AND resolved = FALSE;

-- For slot-level retrieval
CREATE INDEX IF NOT EXISTS idx_tx_comment_payment
    ON tx_comment (payment_id)
    WHERE payment_id IS NOT NULL;

-- "Comments I've raised" view for staff
CREATE INDEX IF NOT EXISTS idx_tx_comment_created_by
    ON tx_comment (created_by_user_id, created_at DESC);

-- updated_at trigger
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'set_updated_at_tx_comment'
    ) THEN
        CREATE TRIGGER set_updated_at_tx_comment
            BEFORE UPDATE ON tx_comment
            FOR EACH ROW
            EXECUTE FUNCTION trg_set_updated_at();
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'tx_comment'
ORDER BY ordinal_position;

SELECT COUNT(*) AS initial_row_count FROM tx_comment;
