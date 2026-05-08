-- =========================================================================
-- Phase 11a v2: Office referrals (corrected) + HOL + DEVIS sub-agents
-- =========================================================================
-- Phase 11a v1 failed because dim_office.country_code is NOT NULL and the
-- Melbourne insert didn't supply it. This re-runs the full Phase 11a with
-- country_code='AU' for Melbourne, plus adds HOL Global Solutions and DEVIS
-- as new sub-agent canonicals.
--
-- Three separate transactions so partial success is preserved if a later
-- block fails:
--   Block A: Phase 11a (office referrals) — re-run from scratch
--   Block B: HOL Global Solutions sub-agent
--   Block C: DEVIS sub-agent + GTC Toàn Cầu alias
-- =========================================================================


-- =========================================================================
-- BLOCK A: Phase 11a — Office referrals (re-run)
-- =========================================================================

BEGIN;

-- 1. Add Melbourne to dim_office (country_code='AU')
INSERT INTO dim_office (code, name, country_code)
VALUES ('MEL', 'Melbourne', 'AU')
ON CONFLICT (code) DO UPDATE SET country_code = EXCLUDED.country_code;

-- 2. Create ref_office_alias
CREATE TABLE IF NOT EXISTS ref_office_alias (
    id            BIGSERIAL PRIMARY KEY,
    office_id     BIGINT      NOT NULL REFERENCES dim_office(id),
    alias         VARCHAR(255) NOT NULL UNIQUE,
    is_canonical  BOOLEAN     NOT NULL DEFAULT FALSE,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ref_office_alias_office ON ref_office_alias (office_id);

-- 3. Seed canonical names + known variants
-- Đà Nẵng
INSERT INTO ref_office_alias (office_id, alias, is_canonical, notes)
SELECT id, 'StudyLink (Văn phòng chi nhánh Đà Nẵng)', TRUE, 'Canonical'
FROM dim_office WHERE code = 'DN'
ON CONFLICT (alias) DO NOTHING;

-- Hà Nội — canonical + lowercase 'văn' variant seen in CRM
INSERT INTO ref_office_alias (office_id, alias, is_canonical, notes)
SELECT id, 'StudyLink (Văn phòng chi nhánh Hà Nội)', TRUE, 'Canonical'
FROM dim_office WHERE code = 'HN'
ON CONFLICT (alias) DO NOTHING;

INSERT INTO ref_office_alias (office_id, alias, is_canonical, notes)
SELECT id, 'StudyLink (văn phòng chi nhánh Hà Nội)', FALSE, 'Lowercase ''văn'' variant'
FROM dim_office WHERE code = 'HN'
ON CONFLICT (alias) DO NOTHING;

-- Hồ Chí Minh
INSERT INTO ref_office_alias (office_id, alias, is_canonical, notes)
SELECT id, 'StudyLink (Văn phòng chi nhánh Hồ Chí Minh)', TRUE, 'Canonical'
FROM dim_office WHERE code = 'HCM'
ON CONFLICT (alias) DO NOTHING;

-- Melbourne — canonical + 'Hoang Le – VP Mel' variant (16 cases across 2024)
INSERT INTO ref_office_alias (office_id, alias, is_canonical, notes)
SELECT id, 'StudyLink (Văn phòng chi nhánh Melbourne)', TRUE, 'Canonical'
FROM dim_office WHERE code = 'MEL'
ON CONFLICT (alias) DO NOTHING;

INSERT INTO ref_office_alias (office_id, alias, is_canonical, notes)
SELECT id, 'Hoang Le – VP Mel', FALSE, 'Personal-name variant — Hoang Le is VP based in Melbourne office'
FROM dim_office WHERE code = 'MEL'
ON CONFLICT (alias) DO NOTHING;

-- 4. Add referring_office_id column to tx_case (nullable for now)
ALTER TABLE tx_case
    ADD COLUMN IF NOT EXISTS referring_office_id BIGINT REFERENCES dim_office(id);

CREATE INDEX IF NOT EXISTS idx_tx_case_referring_office
ON tx_case (referring_office_id)
WHERE referring_office_id IS NOT NULL;

-- 5. Verification
SELECT o.code, o.name, o.country_code, a.alias, a.is_canonical
FROM ref_office_alias a
JOIN dim_office o ON o.id = a.office_id
ORDER BY o.code, a.is_canonical DESC, a.alias;

COMMIT;


-- =========================================================================
-- BLOCK B: HOL Global Solutions
-- =========================================================================
-- Per RP: previously identified as a visa office sub-agent. Adding canonical;
-- the raw value 'HOL Global Solutions' will match exactly. If a different
-- canonical already exists in ref_sub_agent, this INSERT will be skipped
-- by ON CONFLICT and you can manually add 'HOL Global Solutions' as an
-- alias to the existing canonical instead.
-- =========================================================================

BEGIN;

INSERT INTO ref_sub_agent (canonical_name, verification_status, notes)
VALUES ('HOL Global Solutions', 'VERIFIED', 'Visa office sub-agent — confirmed by RP from prior research')
ON CONFLICT (canonical_name) DO NOTHING;

-- Self-alias so the resolver matches the raw value
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias)
SELECT id, 'HOL Global Solutions'
FROM ref_sub_agent
WHERE canonical_name = 'HOL Global Solutions'
ON CONFLICT (alias) DO NOTHING;

-- Verify
SELECT s.canonical_name, a.alias
FROM ref_sub_agent s
LEFT JOIN ref_sub_agent_alias a ON a.sub_agent_id = s.id
WHERE s.canonical_name = 'HOL Global Solutions';

COMMIT;


-- =========================================================================
-- BLOCK C: DEVIS sub-agent + GTC Toàn Cầu alias
-- =========================================================================
-- Per RP: canonical = 'Công Ty Cổ Phần DEVIS' (formal name pattern matches
-- other Vietnamese sub-agent canonicals). The CRM raw value uses the
-- branch's full registered name with DEVIS in parentheses; that becomes the
-- alias.
-- =========================================================================

BEGIN;

INSERT INTO ref_sub_agent (canonical_name, verification_status, notes)
VALUES ('Công Ty Cổ Phần DEVIS', 'VERIFIED', 'DEVIS Joint Stock Co. — Vietnamese sub-agent')
ON CONFLICT (canonical_name) DO NOTHING;

-- Self-alias (canonical match)
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias)
SELECT id, 'Công Ty Cổ Phần DEVIS'
FROM ref_sub_agent
WHERE canonical_name = 'Công Ty Cổ Phần DEVIS'
ON CONFLICT (alias) DO NOTHING;

-- Short-name alias
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias)
SELECT id, 'DEVIS'
FROM ref_sub_agent
WHERE canonical_name = 'Công Ty Cổ Phần DEVIS'
ON CONFLICT (alias) DO NOTHING;

-- The full CRM raw value alias (Bà Rịa - Vũng Tàu branch registered name)
INSERT INTO ref_sub_agent_alias (sub_agent_id, alias)
SELECT id, 'Chi Nhánh Công Ty Cổ Phần Quốc Tế GTC Toàn Cầu - Tại Tỉnh Bà Rịa - Vũng Tàu (Công Ty Cổ Phần DEVIS)'
FROM ref_sub_agent
WHERE canonical_name = 'Công Ty Cổ Phần DEVIS'
ON CONFLICT (alias) DO NOTHING;

-- Verify
SELECT s.canonical_name, a.alias
FROM ref_sub_agent s
LEFT JOIN ref_sub_agent_alias a ON a.sub_agent_id = s.id
WHERE s.canonical_name = 'Công Ty Cổ Phần DEVIS'
ORDER BY a.alias;

COMMIT;
