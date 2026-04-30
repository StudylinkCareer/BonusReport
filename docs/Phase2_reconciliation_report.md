# Phase 2: Engine Reconciliation Report

**Scope**: Compare procedural-doc rules (Phase 1, all 13 docs) against:
1. Existing VBA engine (9 modules, 5,757 lines) in `StudyLink_Bonus_Report_Engine_2025_v7_Template.xlsm`
2. Existing Python engine (9 modules, 2,489 lines) in `/home/claude/work/engine/`

**Goal**: Identify what's already correctly implemented, what's missing, and what's contradicted between sources.

---

## VBA Engine Inventory (Authoritative Reference Architecture)

The VBA engine is the more advanced of the two implementations — most reference data already lives in worksheets, not code. This is the architecture pattern the user wants for the rebuild.

### VBA Module summary

| Module | Lines | Purpose |
|---|---|---|
| modConstants | 240 | Schemes, tiers, offices, client type codes, institution types, deferral codes, column positions, status priority ranks, sheet name constants |
| modConfig | 1,459 | All reference data loaders. Reads from 14+ sheets and populates module-level arrays |
| modInput | 848 | Parse input rows; validation; resolve cross-office cases |
| modCalc | 853 | Core bonus calculation — 11 steps per case |
| modOutput | 479 | Write per-staff output tabs and Summary |
| modMain | 766 | Orchestration |
| modYTD | 409 | Year-to-date tracker |
| modAdvance | 236 | Advance payment offsets |
| modAudit | 467 | Audit trail |

### VBA Reference sheets (the architecture template for new dBase)

All 14 sheets that the VBA engine reads from at runtime:

| Sheet | Purpose | Mapped from |
|---|---|---|
| 02_BASE_BONUS_RATES | All tier and special rates (3 regional sections in one sheet) | Doc 6 (rate tables) |
| 03_PRIORITY_INSTNS | Priority partner list with bonus % and annual targets | Doc 2 + Doc 4 sheet 2 |
| 04_STAFF_TARGETS | Per-staff per-month enrolment targets, by year, with role + office + partner | Doc 5 + dBase additions (e.g., Loi) |
| 05_STATUS_RULES | Application status splits + flags (CarryOver / Zero / FeesPaid / VisaGranted / DeduplicationRank) | Doc 4 sheet 3 + extension flags |
| 06_CLIENT_WEIGHTS | Client type × channel target weight matrix | Doc 4 sheet 1 |
| 09_SERVICE_FEE_RATES | Service fee codes (PACKAGE, ADDON, SERVICE_FEE, CONTRACT categories) with bonus amounts | Docs 7, 8, 10, 11, 12, 13 |
| 11_MASTER_AGENTS | Master agent and Group classification list | Doc 3 |
| 12_STAFF_NAMES | CRM-name → canonical-targets-name mapping (variant aliases) | Built up by usage |
| 13_INSTITUTION_AGENTS | Institution-Agent valid pair junction | Built up by usage |
| 13_SKIP_LABELS | Row-skip labels in raw CRM input | Configuration |
| 14_COUNTRY_CODES | CRM-text → canonical country code, with IsFlatCountry / IsVietnam flags | Doc 1 + extension |
| 15_CLIENT_TYPE_MAP | CRM-text → canonical client type code (DU_HOC_FULL etc.) | Doc 4 sheet 1 + extension |
| 07_CONTRACT_BONUS | Out-of-scope contract bonus formulas | Doc 9 |
| PRE_SALES_PENDING | Staging sheet: pre-sales bonus records output by engine | New (v6.0) |

### VBA Key constants (modConstants)

**Schemes** (3): `HCM_DIRECT`, `HN_DIRECT`, `CO_SUB`
- Logic: if role=CO_SUB → CO_SUB scheme; else if office=HN/DN → HN_DIRECT; else → HCM_DIRECT
- AMBIG vs user's new structure (4 offices × 6 roles): The new structure has 19 (office, role) combinations. The VBA collapses HN+DN into one scheme. This will need redesign.

**Tiers** (5): `UNDER`, `MEET_HIGH` (incentive ≥5M), `MEET_LOW` (incentive <5M), `MEET` (compatibility), `OVER`
- Resolution at runtime: if tier=MEET → check Incentive col (col 18); if ≥5M → MEET_HIGH else MEET_LOW

**Client type codes** (9): `DU_HOC_FULL`, `DU_HOC_ENROL_ONLY`, `SUMMER_STUDY`, `VIETNAM_DOMESTIC`, `GUARDIAN_VISA`, `TOURIST_VISA`, `MIGRATION_VISA`, `DEPENDANT_VISA`, `VISA_ONLY_SERVICE`

**Institution types** (7): `DIRECT`, `MASTER_AGENT`, `GROUP`, `OUT_OF_SYSTEM`, `RMIT_VN`, `BUV_VN`, `OTHER_VN`

**Deferral codes** (5): `NONE`, `FEE_TRANSFERRED`, `DEFERRED`, `FEE_WAIVED`, `NO_SERVICE` — last 4 zero-out bonus

**Status deduplication ranks** (0-5): for resolving same ContractID with multiple statuses
- 5 = Closed full (Visa granted then enrolled / plus enrolled)
- 4 = Closed enrolment only
- 3 = Closed carry-over (Enrolled then Visa granted)
- 2 = Current Enrolled (advance)
- 1 = Zero-bonus (Cancelled / Refused)
- 0 = Unknown

**Pre-sales handling**: col 17 = Pre-sales Agent; default `NONE`. When set, Counsellor bonus halved, pre-sales record written to PRE_SALES_PENDING staging sheet. CO bonus NOT affected.

### VBA modCalc 11-step calculation flow (per case)

| Step | Action | Sourced from |
|---|---|---|
| 1 | Determine tier from weighted enrolled count vs target | D1.R10 + D4.R1 + D4.R2 |
| 2.5 | Deferral check: zero-out if FEE_TRANSFERRED/DEFERRED/FEE_WAIVED/NO_SERVICE | New v5.2 — not in master policy |
| 2.8 | Service fee type lookup (col 20). Special: MGMT_EXCEPTION uses col 27 amount directly | Docs 7-13 service fee codes |
| 3 | Zero-bonus status check (sr.IsZeroBonus) | D4.R5 (statuses with split=0) |
| 3.5 | Fees-paid non-enrolled (GROUP/OOS only): apply fees-paid rate | D1.R8 |
| 4 | Carry-over: pay 50% of prior month's rate | D1.R11 (Couns 100%/CO 50%, then CO 50%) |
| 5 | Special fixed rates: Vietnam domestic / summer study | D4.R2 (VN 0.5 weight) + Doc 6 special rates |
| 6 | Partner case (institution has * marker) → flat partner rate | D2.R3 (* marker) |
| 6B | OUT_OF_SYSTEM enrolled → 400K + 500K extra for difficult case | Doc 6 + Doc 11/13 difficult-case packages |
| 7-pre | Resolve TIER_MEET → MEET_HIGH/MEET_LOW based on Incentive ≥5M | Doc 6 incentive column |
| 7A | MASTER_AGENT enrolled → tier-based sub-referral CO rate | D6.R6 sub rate table |
| 7B | Flat-rate country / regular tier base rate | D6.R3, D6.R5, D6.R7 |
| 8 | Apply split percentage by role (Counsellor/CO Direct/CO Sub) | D4.R5 |
| 8A | Pre-sales 50/50 split | New v6.0 — not in master policy |
| 9 | Package add-on bonus (col 22 PackageType) — read from 09_SERVICE_FEE_RATES | Docs 11, 12, 13 |
| 9A | ADDON rows: unit rate × count, added to BASE row | New v6.2 |
| 10 | Priority bonus: BonusEnr × pri.BonusPct × (1.0 if KPI met else 0.5) | D2.R2 + D4.R9 |

---

## Python Engine Inventory (Current Build — Hardcoded Reference Data)

Located in `/home/claude/work/engine/`. 9 modules, 2,489 lines.

| Module | Lines | Purpose |
|---|---|---|
| policy.py | 341 | **All reference data hardcoded as Python dicts/sets** — must be migrated to dBase tables |
| engine.py | 463 | Calculation logic |
| staff.py | 170 | Staff registry, name variants, monthly targets — also hardcoded |
| parse_input.py | 43 | CRM input parser |
| parse_baocao.py | 78 | Báo cáo parser |
| pair.py | 154 | Discover (staff, year, month) pairings |
| headers.py | 72 | Column constants |
| run.py | 700 | Orchestrator |
| build_deliverable.py | 468 | Output builder |

### Python policy.py contents (everything that should be in dBase)

| Variable | Type | Doc source | Status |
|---|---|---|---|
| FLAT_RATE_COUNTRIES | set, 6 | Doc 1 §I.2 + Doc 6 | hardcoded — should be `ref_country_codes.is_flat_country` |
| WITH_TARGET_COUNTRIES | set, 14 | Doc 1 §I header | hardcoded — should be `ref_country_codes.is_target_country` |
| MASTER_AGENTS | set, 10 | Doc 3 | hardcoded — should be `ref_master_agent` |
| RATES_HCM | dict, 18 | Doc 6 sheet 2 | hardcoded — should be `ref_rate` |
| RATES_HN_DN | dict, 18 | Doc 6 sheet 3 | hardcoded — should be `ref_rate` |
| RATES_SUB | dict, 19 | Doc 6 sheet 4 | hardcoded — should be `ref_rate` |
| STATUS_SPLITS | dict, 19 | Doc 4 sheet 3 | hardcoded — should be `ref_status_split` |
| VISA_GRANTED_STATUSES | set, 8 | Doc 4 sheet 3 | hardcoded — should be `ref_status_split.is_visa_granted` flag |
| TARGET_WEIGHTS | dict, 14 | Doc 4 sheet 1 | hardcoded — should be `ref_client_weight` |
| PRIORITY_PCT | dict, 56 | Doc 2 / Doc 4 sheet 2 | hardcoded — should be `ref_priority_partner.bonus_pct` |
| PARTNER_TARGETS | dict, 37 | Doc 2 / Doc 4 sheet 2 | hardcoded — should be `ref_priority_partner.annual_target` |

### Python staff.py contents (also should be in dBase)

| Variable | Type | Doc source | Status |
|---|---|---|---|
| STAFF | dict, 14 | Mostly the canonical workbook | hardcoded — should be `ref_staff` |
| NAME_LOOKUP | dict, 58 | Mostly the canonical workbook | hardcoded — should be `ref_staff_name_alias` |
| TARGETS_2024 | dict, 8 | Doc 5 + user-confirmed Loi=10 | hardcoded — should be `ref_staff_target` (with year column) |
| TARGETS_2025 | dict, 8 | Doc 5 + user-confirmed Loi=10 | hardcoded — should be `ref_staff_target` |

### Python engine.py functions (logic — stays in code)

| Function | Doc source | Reconciliation note |
|---|---|---|
| `is_enrolled_event` | D1.R1 | OK — counts statuses that mark enrolment |
| `compute_tier` | D1.R10 + D4.R1 | OK — weighted count vs target → UNDER/MEET/OVER. Missing MEET_HIGH/MEET_LOW resolution from incentive (Doc 6) |
| `get_case_client_category` | Doc 4 sheet 1 row labels | OK — maps to FULL_SERVICE / GHI_DANH / SUMMER / VIETNAM / VISA_ONLY |
| `get_case_channel` | Doc 4 sheet 1 column labels | OK — maps to IN_SYSTEM / IN_SYSTEM_SUB / MASTER_AGENT / OUT_SYSTEM / OUT_SYSTEM_US_28M |
| `get_target_weight` | Doc 4 sheet 1 matrix | OK |
| `get_rate_table` | Doc 6 | Synthesis — "SUB_CO uses RATES_SUB" rule is mine, not in any doc |
| `lookup_rate` | Composite | OK |
| `lookup_priority` | Doc 2 substring match | OK — but bidirectional InStr matching needs replacement with proper alias table |
| `disambiguate_visa_granted` | NONE | **Heuristic I wrote** — not in any policy doc. Must be replaced with Doc 4 explicit rules + AMBIG D4.R7 (bare "Closed - Visa granted" disambiguation rule needed) |
| `normalize_status` | Helper | OK |

---

## Reconciliation: Procedural Docs vs Engines

### Items implemented in BOTH VBA and Python (with same source)

These rules are well-grounded:

| Rule | Source | VBA implementation | Python implementation |
|---|---|---|---|
| 1 enrolment = 1 student starting first course in month | D1.R1 | `is_enrolled_event` (modCalc) | `is_enrolled_event` |
| Status splits per role (Couns/CO Direct/CO Sub) | D1.R11-R12 + D4.R5 | `gStatus()` + `SplitCounPct/SplitCODirectPct/SplitCOSubPct` | `STATUS_SPLITS` dict |
| Target weight matrix (9 client types × 5 channels) | D4.R1 | `gClientWeight()` + `GetKPIWeight()` | `TARGET_WEIGHTS` dict + `get_target_weight()` |
| Priority partners + bonus % + annual target | D2.R1 + D4.R4 | `gPriority()` + `GetPriorityMatch()` | `PRIORITY_PCT` + `PARTNER_TARGETS` |
| Master agent classification | D3.R1 | `gMasterAgents()` | `MASTER_AGENTS` set |
| Country tiers (with-target / flat-rate / VN) | D1.R2 + D1.R9 | `gCountryCode()` + `IsFlatCountryCode()` / `IsVietnamCountry()` | `WITH_TARGET_COUNTRIES` + `FLAT_RATE_COUNTRIES` |
| Carry-over: 50% of prior month rate | D1.R11 | Step 4 | OK |
| Out-of-system → flat 400K rate | D1.R8 + D6.R2 | Step 6B | OK |
| Priority bonus 50% / 100% based on KPI | D2.R2 + D4.R9 | Step 10 | OK |

### Items implemented ONLY in VBA (missing from Python)

These are gaps in the Python engine:

| Rule | Doc source | VBA implementation | Python gap |
|---|---|---|---|
| **MEET_HIGH vs MEET_LOW resolution by Incentive ≥5M** | Doc 6 (rate sheet "with incentive" column) | Step 7-pre (`if Incentive ≥ 5M then MEET_HIGH`) | Python only has UNDER/MEET/OVER — does not split MEET into HIGH/LOW. Result: Python always picks one MEET rate (the wrong one for non-incentive cases). |
| **Pre-sales agent split** | New v6.0 — not in procedural docs | Step 8A: Counsellor bonus halved, pre-sales record written | Not in Python. AMBIG: This is a new rule from canonical workbook, not procedural docs. Need user confirmation it should be in rebuild. |
| **MGMT_EXCEPTION service fee** | New v6.1 — not in procedural docs | Step 2.8: bonus = col 27 (manual override) | Not in Python. AMBIG: Need user confirmation. |
| **Deferral / bonus waiver codes** | Not in procedural docs | Step 2.5: zero-out for FEE_TRANSFERRED/DEFERRED/FEE_WAIVED/NO_SERVICE | Not in Python. AMBIG: Need user confirmation. |
| **Difficult-case extra 500K for OUT_OF_SYSTEM** | D11.R4-R5, D13.R3 (signing bonuses for difficult cases) | Step 6B | Not in Python. |
| **Status deduplication ranking (same ContractID multiple statuses)** | Not in procedural docs (operational rule) | Status rule col L | Not in Python — Python doesn't dedupe by ContractID. AMBIG: Need user confirmation on dedup logic. |
| **GUARDIAN_AU_ADDON service fee stacking** | Doc 6 (Guardian rates) | Step 9 | Not in Python. |
| **Service fee rate codes (e.g. SDS, Premium)** | Docs 7-13 service packages | Step 2.8 + 09_SERVICE_FEE_RATES sheet | Not in Python. |
| **Package add-on bonuses (Gói 2/3/4 Counsellor signing bonus)** | D11.R6, D12.R5, D13.R6 | Step 9 + 09_SERVICE_FEE_RATES PACKAGE category | Not in Python. **Major gap** — Counsellor signing bonuses (500K-2M) per package not paid. |
| **ADDON rows (multiple add-ons per case)** | New v6.2 | Step 9A | Not in Python. |
| **Tier inheritance for cross-office staff (target=0 in secondary office)** | D5.R5 (Hoàng Yến HCM+HN) | `inheritedTier` parameter | Python aggregates targets but does not properly inherit tier across offices. |
| **Status `Closed - Not Exempted` / `Closed - Exempted` / `Closed - Follow up enrolment` (Covid era)** | D4.R5 N/A entries | `gStatus()` reads from sheet (operator decides) | Python: not in STATUS_SPLITS, would error on encounter. AMBIG D4.R6: how to handle these. |
| **Cross-office case exclusion** | D5.R5 implication | `cs.ExcludeFromCalc` flag | Python does not have cross-office exclusion logic. |

### Items in procedural docs but NOT implemented in either engine

These are gaps in BOTH VBA and Python:

| Rule | Doc source | Impact | Required for rebuild? |
|---|---|---|---|
| **Out-of-scope contract bonus** (highest standard package + 20% excess) | D9.R5 | Counsellor signing bonus on out-of-frame contracts | **YES** — affects out-of-frame fee customers |
| **2-out-target = 1 target equivalent** (US: 2 = 1.4) | D1.R6 | Target accumulation for non-target-country cases | **YES** — affects target tier qualification |
| **New employee training rule (CO duty for first file per market)** | D1.R13 | New Counsellor in probation does CO work | **YES** for new-staff scenarios |
| **Probation completion bonus** | D1.R14 | Probation cases bonused only after probation passes | **YES** |
| **New Counsellor handover rule** (no target on handed-over clients unless replan) | D1.R15 | Target counting | **YES** |
| **Customer/partner serious complaint deduction** | D1.R16 | Bonus deducted for month or up to complaint date | **YES** — impacts payouts |
| **Post-departure complaint deduction** | D1.R17 | Forfeit all post-departure bonus | **YES** |
| **Commission claw-back from future bonuses** | D1.R18 | Recovery from future bonuses or post-departure | **YES** |
| **CO refusing handover when ≤40 Current files** | D1.R19 | Full bonus deduction up to refusal date | **YES** |
| **Departure bonus rules pre-lodge / post-lodge / post-enrolment** | D1.R20-R22 | Departing-staff and new-CO splits + allowances | **YES** — affects departing employees |
| **6-month settlement period after departure** | D1.R23 | Bonus payout delayed 6 months | **YES** |
| **Post-departure data theft penalty** | D1.R24 | Forfeit all bonus | **YES** |
| **Team excess bonuses** (national 10M+10M, pair 2M+1M, sub 3M+3M) | D1.R25-R27 | Team-level monthly bonuses | **YES** — separate calculation track |
| **Contract target bonus per Counsellor** | D1.R28-R34 | Whole secondary KPI scheme for Counsellors | **YES** — major gap |
| **Premium contract tier (>10 contracts/month or doubled target)** | D1.R32 | 2.2M per excess contract | **YES** |
| **Pre-sales bonus scheme** | User-confirmed (yet to be defined) | Pre-sales separate from Couns/CO | **TBD** — user said scheme not yet defined |
| **VP (Office) bonus scheme** | User-confirmed (different scheme) | Office-level bonuses | **TBD** — user said scheme not yet defined |
| **Lovely Cup of Coffee referral (100K flat)** | D1.R10 | Add-on referral bonus | YES |

### Items where doc rules conflict between sources

These need user resolution:

| Conflict | Source A | Source B | Resolution needed |
|---|---|---|---|
| **Master agent target weight** | D1.R10 says Out-system master agent = 0.7 | D7.R13 says Out-system master agent counted as 1 in-system | Which weight applies? Likely D1.R10 supersedes D7.R13 since Doc 1 is later (June 2024) |
| **Cancelled-with-fee status pay rate** | D1.R8 says "Out-system / Fees paid yet visa refused / Extra high risk" rate | D4.R5 says split=0 for Closed - Cancelled / Closed - Visa refused | Which applies when fee is paid but no visa? Likely D1.R8 wins for fees-paid cases (sr.FeesPaidNonEnrolled flag) |
| **SDS service fee** | D7.R10 + D9.R1 say SDS increased to 7M | D12.R2 page 2 body says SDS = 5.5M (4M service + 1.5M admin) | Latest SDS fee? VBA likely has 7M. |
| **AP Out-system Counsellor signing bonus** | D7.R12 says 500K | D10.R2 says 1.1M (AU) | Regional difference? D7 covers AE (US/CA/UK); D10 covers AP (AU/NZ/SGP) |
| **Country list 11 vs 13** | D6.R8 lists 11: AUS, NZ, SG, US, CAN, UK, FL, NL, GER, FRA, IRL | D1 lists 13 (adds Switzerland, Malaysia) | Canonical country list? VBA uses 14_COUNTRY_CODES sheet |

### Items implemented in Python but NOT in any procedural doc

These are heuristics/synthesis I added that should be removed or properly sourced:

| Item | Where | Issue |
|---|---|---|
| `disambiguate_visa_granted` function | engine.py | Heuristic for bare "Closed - Visa granted" — not in any policy doc. Should be removed; require Doc 4 row for bare "Closed - Visa granted" with explicit splits, or have operator disambiguate at input. |
| "SUB_CO role always uses RATES_SUB regardless of office" rule | engine.py | My synthesis from Loi-investigation. Need to verify against canonical scheme logic (VBA does this differently — scheme is HCM_DIRECT/HN_DIRECT/CO_SUB based on role+office combo) |
| Sub-CO default to UNDER tier when target is None | engine.py (later reverted) | My synthesis. Not policy. |
| Specific Trường An office assignment | staff.py | Was inferred from rate behavior, then changed based on canonical workbook reference (which user said is OUT OF SCOPE). Requires user confirmation. |
| `disambiguate_visa_granted` fallback heuristics | engine.py | All heuristics, not policy. |

---

## Reconciliation Summary

### What's well-grounded (rule, source, both engines agree)
- Status splits per role (D4.R5 → both engines)
- Priority partners + bonus % + annual targets (D2 + D4 sheet 2 → both)
- Master agent classification (D3 → both)
- Master rate tables structure (Doc 6 → both, Python missing MEET_HIGH/MEET_LOW split)
- Country tiers (Doc 1 + Doc 6 → both)
- Carry-over 50% rule (D1.R11-R12 → both)
- Tier weighting rules (D4.R1 → both)

### Where Python is materially incomplete vs VBA
1. **No MEET_HIGH/MEET_LOW resolution** — Python uses single MEET rate, VBA splits by incentive
2. **No service fee handling** — Python lacks col 20 service fee codes; VBA has full lookup
3. **No package signing bonuses** — Counsellor 500K-2M signing bonuses on Gói 2/3/4 packages not paid in Python
4. **No deferral codes** — Python doesn't recognize FEE_TRANSFERRED/DEFERRED/FEE_WAIVED/NO_SERVICE → would mis-pay deferred cases
5. **No pre-sales split** — col 17 ignored in Python
6. **No status deduplication** — duplicate ContractIDs may double-pay in Python
7. **No tier inheritance** — cross-office cases for same staff use wrong tier in Python
8. **No ADDON row support** — multi-line add-ons ignored in Python

### Where BOTH engines lack procedural-doc rules
1. **All of Section II (Contract Target Bonus)** — Doc 1 §II contract-target system completely absent. This is a significant secondary KPI scheme for Counsellors that pays per-contract bonuses + premium tiers.
2. **Out-of-scope contract bonus** (D9.R5) — fee above schedule → highest standard + 20% excess
3. **2-out-target = 1 target arithmetic** (D1.R6) — Thai/Korea/Malay 2:1, US 2:1.4
4. **Departure rules** (D1.R20-R23) — pre-lodge / post-lodge / post-enrolment with allowances and 6-month delay
5. **Team excess bonuses** (D1.R25-R27) — 10M+10M / 2M+1M / 3M+3M tiers
6. **Complaint deductions** (D1.R16-R19) — full bonus withholding
7. **New employee rules** (D1.R13-R15) — probation CO duty, handover target rules
8. **Pre-sales bonus scheme** — undefined per user
9. **VP (office) bonus scheme** — undefined per user

### Where Python should be retired in favor of VBA
The VBA engine is more advanced. The Python rebuild should:
1. Adopt VBA's reference-data-in-tables architecture (move all data to `ref_*` tables)
2. Implement VBA's 11-step calculation flow
3. Add the procedural-doc rules missing from BOTH (Section II, departures, team bonuses, etc.)
4. Replace the canonical workbook (.xlsm) sheets with PostgreSQL tables, structurally identical

---

## Recommendations for Phase 4-5 Schema Design

The VBA's 14-sheet structure maps cleanly to PostgreSQL tables. Recommended naming:

| VBA sheet | PostgreSQL table |
|---|---|
| 02_BASE_BONUS_RATES | `ref_rate` (with scheme + region + tier columns) |
| 03_PRIORITY_INSTNS | `ref_priority_partner` (with year column for 2025/2026) |
| 04_STAFF_TARGETS | `ref_staff_target` |
| 05_STATUS_RULES | `ref_status_split` |
| 06_CLIENT_WEIGHTS | `ref_client_weight` |
| 09_SERVICE_FEE_RATES | `ref_service_fee` |
| 11_MASTER_AGENTS | `ref_institution_classification` |
| 12_STAFF_NAMES | `ref_staff_name_alias` |
| 14_COUNTRY_CODES | `ref_country_code` |
| 15_CLIENT_TYPE_MAP | `ref_client_type_alias` |

Plus new tables for the 4-office × 6-role structure:
- `ref_office`
- `ref_role`
- `ref_office_role`
- `ref_staff` (replaces hardcoded STAFF dict)

And tables for currently-missing rules (Section II, departures, etc.):
- `ref_contract_bonus_tier`
- `ref_team_excess_bonus`
- `ref_departure_rule`
- `ref_complaint_deduction`
- `ref_calculation_param` (scalar parameters with effective dates)
