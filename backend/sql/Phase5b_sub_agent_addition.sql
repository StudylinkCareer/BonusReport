-- =============================================================================
-- Phase 5b — Sub-Agent Addition
-- File:    Phase5b_sub_agent_addition.sql
-- Purpose: Add ref_sub_agent + ref_sub_agent_alias tables, and link
--          tx_case to a sub-agent for CO_SUB referral cases.
-- Target:  PostgreSQL 15+
-- Run:     Once, against the Railway 'railway' database.
-- =============================================================================
-- Background:
--   - ref_partner holds Master Agents and Groups (institution-side classification).
--   - Sub-agents are external partners that REFER cases TO StudyLink for
--     CO_SUB processing. Conceptually distinct from Master Agents.
--   - Sub-agents are informational only (no calc impact); finance uses the
--     identifier for accounts-payable reconciliation.
--   - Mutual exclusivity: a case cannot simultaneously have a Master Agent
--     route AND a sub-agent referrer.
-- =============================================================================

-- 2.x  ref_sub_agent (mirrors ref_institution's UNVERIFIED workflow) ----------
CREATE TABLE ref_sub_agent (
    id                  BIGSERIAL PRIMARY KEY,
    canonical_name      VARCHAR(128) NOT NULL UNIQUE,
    country_id          BIGINT REFERENCES dim_country(id),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    verification_status VARCHAR(16) NOT NULL DEFAULT 'VERIFIED'
                        CHECK (verification_status IN ('VERIFIED','UNVERIFIED','MERGED')),
    merged_into_id      BIGINT REFERENCES ref_sub_agent(id),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_ref_sub_agent_updated BEFORE UPDATE ON ref_sub_agent
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
COMMENT ON TABLE ref_sub_agent IS
    'External partners who refer cases to StudyLink for CO_SUB processing. '
    'Informational only — used for finance accounts-payable reconciliation. '
    'Distinct from ref_partner (which holds Master Agents and Groups).';

-- 2.y  ref_sub_agent_alias -----------------------------------------------------
CREATE TABLE ref_sub_agent_alias (
    id              BIGSERIAL PRIMARY KEY,
    sub_agent_id    BIGINT NOT NULL REFERENCES ref_sub_agent(id),
    alias           VARCHAR(128) NOT NULL UNIQUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2.z  tx_case: add referring_sub_agent_id + mutual-exclusivity --------------
ALTER TABLE tx_case
    ADD COLUMN referring_sub_agent_id BIGINT REFERENCES ref_sub_agent(id);

COMMENT ON COLUMN tx_case.referring_sub_agent_id IS
    'External sub-agent that referred this case to StudyLink. '
    'Populated for CO_SUB cases only. Mutually exclusive with referring_partner_id.';

COMMENT ON COLUMN tx_case.referring_partner_id IS
    'Master Agent route used for this case (when applicable). '
    'Mutually exclusive with referring_sub_agent_id.';

-- A case cannot simultaneously be Master-Agent-routed AND sub-agent-referred.
-- Both NULL is fine (direct in-system case, no external partner involved).
ALTER TABLE tx_case
    ADD CONSTRAINT chk_tx_case_partner_xor_subagent
    CHECK (referring_partner_id IS NULL OR referring_sub_agent_id IS NULL);

-- =============================================================================
-- End of Phase 5b
-- =============================================================================
