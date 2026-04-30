# Phase 3: Báo Cáo Validation Report

**Approach:** Sample diverse báo cáos and verify that documented rules (Phase 1 inventory) reproduce the actual bonus amounts paid. Where amounts match, the rule is validated. Where they don't, the discrepancy is flagged.

**Sample size:** 4 báo cáos covering 3 staff × 4 distinct scenarios:
1. Lê Thị Trường An — Jan 2024 (CO_SUB scheme, OVER tier, full month)
2. Phạm Thị Lợi — Jan 2025 sub_Agent (CO_SUB scheme, UNDER tier, low volume)
3. Phạm Thị Lợi — Jan 2024 VP_ĐN (CO Direct DN scheme, package cases)
4. Quan Hoàng Yến — Jan 2024 VP_HCM + VP_HN (CO Direct, multi-office, package + Guardian AU stacking)

This is a sample, not exhaustive. Validates the most-used rules but does NOT validate edge cases like out-of-scope contracts (D9.R5), team excess bonuses (D1.R25-R27), or contract target premium tier (D1.R32).

---

## Sample 1: Lê Thị Trường An — Jan 2024 (target=13, CO_SUB)

**File:** `Báo_cáo_Lê_Thị_Trường_An_tháng_01_2024.xlsx`, sheet "Tháng 01"

### Case breakdown

| # | Status | Course start | Bonus paid | Rule applied |
|---|---|---|---|---|
| 1-13 | Closed - Cancelled | various | 0 each | D4.R5: Cancelled split = 0 |
| 14-20 (cases 14-20) | Closed - Visa granted | Feb-Apr 2024 | 0 each | Enrolment in future month → 0 in current; will pay when enrol date arrives |
| 21-22 | Closed - Enrolled, then Visa granted | Aug 2023 | 350,000 each | D1.R12 carry-over: 50% of prior month rate. 700K (Under tier "Enrolment only" rate) × 50% = 350K ✓ |
| 23-26 | Closed - Visa granted, then enrolled / Closed - Enrolment | Jan 2024 | 1,100,000 each | D6.R6 OVER tier "Enrolment only - sub does visa only" ✓ |
| 27-41 | Closed - Visa granted, then enrolled | Jan 2024 | 1,100,000 each (×15) | Same as above |
| 42-45 | Current - Enrolled | Jan 2024 | 550,000 each (×4) | D1.R12 advance: enrolled, no visa yet → 50% of base. 1,100,000 × 50% = 550,000 ✓ |

### Tier calculation

- Target Jan 2024 = 13 (per D5.R1)
- Actual enrolments (course start in Jan 2024): 19 closed-with-enrol + 4 current-enrol = **23 enrolments**
- 23 > 13 → **OVER tier** ✓

### Total reconciliation

| Bucket | Cases | Rate | Subtotal |
|---|---|---|---|
| Enrolled at OVER tier | 19 | 1,100,000 | 20,900,000 |
| Current-Enrolled (advance 50%) | 4 | 550,000 | 2,200,000 |
| Carry-over (50% of prior 700K) | 2 | 350,000 | 700,000 |
| **Total bonus enrolled** | | | **23,800,000** ✓ |

**BC TỔNG bonus enrolled** = 23,800,000 ✓ matches.

### Priority bonus reconciliation

- Formula: bonus_enrolled × bonus_pct × multiplier (1.0 if KPI met YTD, 0.5 otherwise)
- All cases below use 0.5 multiplier (KPI not yet met early in year)

| Institution | Bonus % (D2) | Cases | Per case | Subtotal |
|---|---|---|---|---|
| EQI (Education Queensland Intl) | 30% | 5 | 1,100,000 × 0.30 × 0.5 = 165,000 | 825,000 |
| Griffith University | 30% | 1 | 165,000 | 165,000 |
| RMIT University | 20% | 2 | 1,100,000 × 0.20 × 0.5 = 110,000 | 220,000 |
| VIC DET (Dept of Education and Training) | 20% | 4 | 110,000 | 440,000 |
| Macquarie University (Current-Enrolled at 550K) | 30% | 1 | 550,000 × 0.30 × 0.5 = 82,500 | 82,500 |
| **Total priority** | | | | **1,732,500** ✓ |

**BC TỔNG bonus priority** = 1,732,500 ✓ matches.

### Grand total

23,800,000 + 1,732,500 = **25,532,500** ✓ matches BC TỔNG combined.

### Rules validated

| Rule | Validated |
|---|---|
| D4.R5 Cancelled status → split 0 | ✓ |
| D1.R12 carry-over: 50% of prior month rate | ✓ |
| D1.R12 Current-Enrolled advance: 50% | ✓ |
| D1.R12 Visa-then-enrolled: 100% bonus | ✓ |
| D6.R6 CO_SUB OVER tier rate | ✓ (matches "Enrolment only - sub does visa only" Over = 1,100,000) |
| D6.R6 CO_SUB UNDER tier (carry-over reverse-calc) | ✓ (matches "Enrolment only" Under = 700,000) |
| D2.R1 Priority partner bonus % | ✓ (EQI/Griffith 30%, RMIT/VIC DET 20%, Macquarie 30%) |
| D2.R2 Priority 50% pre-KPI | ✓ |
| D4.R9 Priority bonus formula bonus_enrolled × % × multiplier | ✓ |
| Closed-Visa-granted with future enrol date → 0 | ✓ (will pay in enrol month) |

### **NEW finding: CO_SUB has TWO sub-schemes**

The Doc 6 sub-rate sheet has TWO scheme variants for sub-agent CO:
1. "Enrolment only - in system - sub does visa only" (Under 700K / Meet 900K / Over 1.1M)
2. "Enrolment + visa - in system" (Under 800K / Meet 1.1M / Over 1.3M)

Trường An is paid per scheme #1 (rates 700K/900K/1.1M). This means the engine needs a **CO_SUB sub-scheme indicator** per staff record (or per case) — currently the rule inventory and Python engine treat CO_SUB as a single scheme.

Suggested per-staff field: `co_sub_subscheme` with values `ENROL_ONLY_VISA_ONLY` / `ENROL_PLUS_VISA`.

---

## Sample 2: Phạm Thị Lợi — Jan 2025 sub_Agents (target=10, CO_SUB)

**File:** `Báo_cáo_Phạm_Thị_Lợi_tháng_01_2025_sub_Agents.xlsx`

### Case breakdown

| # | Status | Course start | Bonus | Rule applied |
|---|---|---|---|---|
| 1-2 | Closed - Cancelled | Mar 2025 | 0 each | D4.R5 |
| 3-6 | Closed - Visa granted | Mar 2025 | 0 each | Enrolment in future month → 0 |
| 7 | Closed - Visa granted, then enrolled | Jan 31, 2025 | 700,000 | D6.R6 UNDER tier "Enrolment only" rate |

### Tier calculation

- Target Jan 2025 = 10 (per user statement, not in Doc 5)
- Actual enrolments (course start Jan 2025): 1
- 1 < 10 → **UNDER tier** ✓

### Total

700,000 ✓ matches BC TỔNG.

### Rules validated

| Rule | Validated |
|---|---|
| D6.R6 CO_SUB UNDER "Enrolment only" rate = 700K | ✓ |
| Visa-then-enrolled: 100% bonus = full base rate | ✓ |
| User-confirmed Loi target=10 | ✓ confirmed by tier behaviour |

### Sub-scheme inheritance

Loi's sub-agent role uses scheme #1 (Enrolment only - sub does visa only) — same as Trường An. This appears to be the standard scheme for the sub-agent network CO role.

---

## Sample 3: Phạm Thị Lợi — Jan 2024 VP_ĐN (CO Direct, DN scheme)

**File:** `Báo_cáo_Phạm_Thị_Lợi_tháng_01_2024_VP_ĐN.xlsx`

### Case breakdown

| # | Counsellor | Status | Package | Bonus | Rule applied |
|---|---|---|---|---|---|
| 1 | Vũ Thị Hòa | Closed - Cancelled | Superior 6tr | 400,000 | D1.R8 fees-paid Out-system rate |
| 2 | Nguyễn Ngọc Hà B | Closed - Cancelled | Premium 9tr | 400,000 | D1.R8 fees-paid Out-system rate |
| 3 | Nguyễn Ngọc Hà B | Closed - Visa refused | Superior 6tr | 0 | Superior package refunds 6M on visa-refused → no fee retained → 0 |

### NEW FINDING: Fees-paid 400K rate fires only when fee is RETAINED

This is a critical rule not explicit in Doc 1:
- **Cancelled cases**: customer pays fee, no refund → fee retained → 400K Out-system rate fires
- **Visa-refused cases on Superior/Premium packages**: per D11.R4/R5, package guarantees full refund on visa-refused → fee NOT retained → 0 bonus
- **Visa-refused cases on Standard Plus**: per D11.R3, only 50% deposit refunded (1.5M kept) → fee partially retained → 400K rate may fire (need confirmation)
- **Visa-refused cases on Standard SDS Canada**: per D12.R2, refund 4M of 5.5M-7M → fee partially retained → similar

**This rule is NOT in either VBA or Python engines** — both apply 400K uniformly to all "fees-paid yet visa refused" cases without checking package refund terms.

### Cross-office collaboration confirmed

- Cases 1, 2 had HCM-based Counsellors (Vũ Thị Hòa, Nguyễn Ngọc Hà B) but Loi as DN-based CO
- Premium package (D11.R5) is documented as HCM-only — but here it's used with a DN CO
- Suggests: package availability is by Counsellor's office, not by CO's office

---

## Sample 4: Quan Hoàng Yến — Jan 2024 VP_HCM + VP_HN (CO Direct, multi-office)

**Files:** `Báo_cáo_Quan_Hoàng_Yến_tháng_01_2024_VP_HCM.xlsx` and `_VP_HN.xlsx`

### HCM file — case breakdown

| # | Status | Country | Package | Bonus | Rule |
|---|---|---|---|---|---|
| 1-4 | Closed - Cancelled | AU/CA | Superior/Standard | 400,000 each | D1.R8 fees-paid retained |
| 5-7 | Closed - Visa granted | AU | Standard Plus | 0 each | Future enrolment month |
| 8 | Closed - V granted, then enrolled | Canada | "30tr (1 out = 1 in)" | 800,000 | UNDER HCM CO base rate |
| 9 | Closed - V granted, then enrolled | AU | Superior 6tr | **1,425,000** | **Stacked: 800K base + 500K Superior CO + 125K Guardian AU** |
| 10 | Closed - V granted, then enrolled | AU | Premium 9tr | **1,425,000** | **Stacked: 800K base + 500K Premium CO + 125K Guardian AU** |
| 11 | Closed - V granted, then enrolled | USA | Standard 16tr | 800,000 | UNDER HCM CO base rate (US Standard has no CO addon) |

### HN file — case breakdown

| # | Status | Country | Package | Bonus | Rule |
|---|---|---|---|---|---|
| 1 | Closed - V granted, then enrolled | AU | Superior 6tr | **1,325,000** | **Stacked: 700K HN base + 500K Superior CO + 125K Guardian AU** |

### Tier calculation

- HCM target Jan 2024 = 6 (per D5.R1)
- HCM enrolments = 4 (cases 8-11)
- 4 < 6 → HCM tier = **UNDER**

- HN target Jan 2024 = 2 (per D5.R1)
- HN enrolments = 1 (case 1)
- 1 < 2 → HN tier = **UNDER**

### Stacking validation (cases 9, 10, HN-1)

| Component | Source | Amount | Validated |
|---|---|---|---|
| HCM CO Under base rate | D6.R2 (with-target country, Under, CO) | 800,000 | ✓ |
| HN CO Under base rate | D6.R4 (HN/DN, with-target country, Under, CO) | 700,000 | ✓ |
| Superior package CO bonus | D11.R4 (Gói 3 CO 500K + bonus scheme) | 500,000 | ✓ |
| Premium package CO bonus | D11.R5 (Gói 4 CO 500K + bonus scheme) | 500,000 | ✓ |
| Guardian AU addon (post-Aug 2022) | D6.R8 (250K split 50/50) | 125,000 | ✓ |

Cases 9, 10 stack: base + package + Guardian = 1,425,000 ✓
Case HN-1 stacks: base + Superior + Guardian = 1,325,000 ✓

### NEW finding: Multi-office tier independence

- Hoàng Yến's HCM and HN cases have separate BC files
- Each office computes its own tier using its own target × own enrolments
- HCM BC uses HCM rates (800K Under base)
- HN BC uses HN/DN rates (700K Under base)
- The two are NOT aggregated for tier determination

**This contradicts the VBA `inheritedTier` logic** which inherits tier from primary office to secondary when secondary target=0. In Hoàng Yến's case, BOTH offices have real targets (HCM 6, HN 2), so independent tier calculation applies.

The VBA logic should still work for cases where secondary office target IS 0 (e.g., the secondary office is incidental coverage). But the BCs show that when both offices have targets, they're computed independently. The rebuild engine needs to handle BOTH cases.

### Rules validated

| Rule | Validated |
|---|---|
| D1.R8 fees-paid 400K retained-fee rate | ✓ (cancelled cases) |
| D6.R2 HCM CO Under tier rate = 800K | ✓ |
| D6.R4 HN/DN CO Under tier rate = 700K | ✓ |
| D11.R4 Superior package CO +500K stacking | ✓ |
| D11.R5 Premium package CO +500K stacking | ✓ |
| D6.R8 Guardian AU addon +125K (post-Aug 2022, half of 250K) | ✓ |
| D7.R12 Out-system 30M = 1 in-system equivalent (target counted) | ✓ (case 8 contributed to tier count) |
| Multi-office independent tier | ✓ |

---

## Cross-Sample Findings

### A. Validated rules (apply across all samples)

These rules are confirmed by multiple BCs:

1. **D4.R5 status splits**: Cancelled / Visa refused → 0; Visa granted (closed) → 1.0; Current-Enrolled → 0.5 (CO Direct/CO Sub)
2. **D1.R11/R12 carry-over and advance pattern**: 50% advance on enrolment-before-visa, 50% on visa-grant-and-file-close
3. **D6.R2/R4 base rate tables**: HCM (800K Under CO), HN/DN (700K Under CO)
4. **D6.R6 CO_SUB rate table**: "Enrolment only - sub does visa only" = 700/900/1100K (Under/Meet/Over)
5. **D2.R1 priority partner bonus %**: EQI 30%, RMIT 20%, VIC DET 20%, Griffith 30%, Macquarie 30%, etc.
6. **D2.R2 + D4.R9 priority formula**: bonus_enrolled × bonus_pct × (1.0 if KPI met else 0.5)
7. **D11.R4 Superior CO bonus +500K stacking**
8. **D11.R5 Premium CO bonus +500K stacking**
9. **D6.R8 Guardian AU addon +125K stacking (after Aug 2022)**

### B. NEW rules discovered from BC samples

These rules are NOT explicit in the procedural docs but appear in BC behavior:

1. **Fees-paid 400K rate fires only when fee is RETAINED**: Cancelled cases retain fee → 400K. Visa-refused cases on Superior/Premium packages get 100% refund → 0 bonus. The engine MUST check the package's refund policy on visa-refused.
2. **CO_SUB has two sub-schemes**: "Enrolment only - sub does visa only" and "Enrolment + visa - in system" — different rate tables. Each staff in CO_SUB scheme uses one or the other. Both Trường An and Loi use "Enrolment only".
3. **Multi-office tier independence**: when staff has targets in 2+ offices, each office computes own tier from own target × own enrolments. Rates use that office's rate sheet.
4. **Cross-office case routing**: Counsellor in one office may pair with CO in another office. Package availability follows Counsellor's office (e.g., Premium HCM-only); CO's office determines CO's rate sheet.
5. **Stacking order**: Base rate (per office tier) + Package CO bonus (per Counsellor's package) + Guardian AU addon (if applicable) → all sum into BONUS Enrolled.

### C. Discrepancies found

None at the case-level math. BC totals match calculated totals to the đồng across all 4 samples.

### D. Things this validation does NOT cover

The samples don't exercise these rules — they remain unvalidated:

1. **Section II contract target bonus** (D1.R28-R34): No CounsELLOR-side BCs sampled
2. **Premium contract tier** (D1.R32, 2.2M per excess contract)
3. **Out-of-scope contract bonus** (D9.R5, highest standard + 20% excess)
4. **Team excess bonuses** (D1.R25-R27)
5. **Departure rules** (D1.R20-R23)
6. **Complaint deductions** (D1.R16-R19)
7. **2-out-target = 1 target arithmetic** (D1.R6)
8. **Pre-sales bonus** (user-confirmed not yet defined)
9. **VP office bonus** (user-confirmed not yet defined)
10. **MEET_HIGH vs MEET_LOW resolution** by 5M incentive threshold (no Meet-tier cases in samples)
11. **MASTER_AGENT tier-based rate** (Step 7A in VBA)
12. **Vietnam-domestic rate** (D4.R2 0.5 weight)
13. **Summer study rate**

---

## Phase 3 Summary

The 4-BC sample successfully validates the core enrolment-bonus calculation flow against the Phase 1 rule inventory. All BC totals match calculated totals exactly (variance = 0 across 4 files).

Key rule additions/refinements needed for the rebuild:

| New rule / refinement | Where in rebuild |
|---|---|
| Fees-paid 400K only fires on retained-fee cases (per package refund policy) | New: `ref_package_refund_policy` table; engine checks before applying 400K |
| CO_SUB sub-scheme indicator (Enrolment-only-sub-does-visa-only vs Enrolment-plus-visa) | New column on `ref_staff` (or `ref_staff_target.subscheme`) |
| Multi-office tier independence | Engine: process each (staff, office) pair independently when both have non-zero targets |
| Tier inheritance (when secondary office target = 0) | Engine: when secondary office target = 0, inherit tier from primary office (matches VBA `inheritedTier`) |
| Stacking order (Base + Package CO + Addon) | Engine: explicit calculation order with separate columns for tier_bonus / package_bonus / addon_bonus |
| Cross-office case: package by Counsellor's office, rate by CO's office | New rule in engine routing |

These will need to be incorporated when designing schema + DDL in Phases 4-5 tomorrow.

---

## Status

✅ **Phase 1 complete** — `phase1_rules/rule_inventory.md` (64 KB, 13 docs end-to-end)
✅ **Phase 2 complete** — `phase2_recon/reconciliation_report.md` (22 KB, VBA + Python recon)
✅ **Phase 3 complete** — `phase3_validation/validation_report.md` (this file)
⏸ **Phase 4 (schema design)** — pending tomorrow
⏸ **Phase 5 (PostgreSQL DDL + INSERT statements)** — pending tomorrow
