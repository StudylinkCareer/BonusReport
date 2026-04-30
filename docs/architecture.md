# BonusReport — Architecture & Phase 6 Plan

**Project:** StudyLink Vietnam Bonus Reconciliation Engine
**Status:** Phases 1–5b complete. Phase 6 (calculation engine) starting.
**Last updated:** 2026-04-29

---

## 1. Project context

StudyLink Vietnam is an education agency with ~9 active staff across HCM, HN, DN, and MEL offices. Each month, finance reconciles bonuses for counsellors, case officers, sub-agent COs, pre-sales staff, and VPs based on cases that closed/enrolled in that month. Calculation rules span 13 procedural documents, multiple offices, multiple roles, country-specific rate sheets, priority-partner overrides, package signing bonuses, and temporal advance/carry-over patterns.

This system rebuilds the calculation, replacing a brittle Excel + VBA pipeline. The goal is a transparent, auditable engine that anyone can trace from raw case to final đồng paid.

---

## 2. Stack (locked)

| Layer | Choice |
|---|---|
| Backend language | Python 3.11.9 |
| Web framework | FastAPI |
| Database | PostgreSQL 15+ |
| DB driver | `psycopg` v3 (no ORM — raw SQL) |
| Migrations | Alembic (Phase 7+) |
| Frontend | React (Vite, Phase 8) |
| Hosting | Railway (API + DB), Netlify (frontend) |
| Auth | Deferred until review-board phase |

**Dependency philosophy:** as few third-party packages as possible. No bcrypt, no Node.js anywhere on the backend. The backend's `requirements.txt` is intentionally tiny: `fastapi`, `uvicorn`, `psycopg[binary]`, `pytest`, `python-dotenv`.

---

## 3. Architectural principles (locked)

These are non-negotiable. Past attempts violated them and collapsed.

1. **Data goes in tables; logic goes in code.** No hardcoded rates, classifications, country flags, or rule constants in Python. Every configurable value lives in a `ref_*` or `dim_*` table.

2. **Pure calculation engine.** The engine is a function: `(case, refdata, context) → list[BonusPayment]`. No DB calls, no HTTP, no file I/O. Reference data is loaded externally and passed in as a frozen snapshot.

3. **Layered separation.**
   - `engine/` — pure functions, no I/O
   - `data/` — DB → ReferenceData hydration (Phase 7)
   - `api/` — FastAPI routes (Phase 7)
   - `frontend/` — React, talks only to API (Phase 8)
   - `admin/` — reference data + UNVERIFIED review screens (Phase 8)

4. **Frontend has no business logic.** Display only. Anything resembling a calculation in JavaScript is a bug.

5. **Money is integer đồng.** No floats anywhere in calculations. Percentages use `Decimal`.

---

## 4. Repository layout

```
BonusReport/                                 ← Git repo root
├── .gitignore                               ← excludes Supporting content/, venv/, node_modules/
├── README.md
├── docs/                                    ← project knowledge (markdown)
│   ├── architecture.md                      ← this file
│   ├── Phase1_rule_inventory.md             ← 117 rules, all 13 procedural docs
│   ├── Phase2_reconciliation_report.md      ← VBA + old-Python reconciliation
│   ├── Phase3_validation_report.md          ← 4 BC samples, validated to the đồng
│   └── Phase4_schema_proposal.md            ← schema rationale
│
├── Application/                             ← deliverable code (Railway "Root Directory")
│   ├── backend/
│   │   ├── requirements.txt
│   │   ├── Procfile                         ← Railway start command
│   │   ├── runtime.txt                      ← python-3.11.9
│   │   ├── .env.example
│   │   ├── main.py                          ← FastAPI app entry
│   │   ├── engine/                          ← Phase 6 lives here
│   │   │   ├── __init__.py
│   │   │   ├── types.py
│   │   │   ├── enums.py
│   │   │   ├── classify.py
│   │   │   ├── rates.py
│   │   │   ├── splits.py
│   │   │   ├── packages.py
│   │   │   ├── addons.py
│   │   │   ├── priorities.py
│   │   │   ├── presales.py
│   │   │   ├── vietnam_local.py
│   │   │   ├── advance.py
│   │   │   └── calc.py
│   │   ├── data/                            ← Phase 7
│   │   ├── api/                             ← Phase 7
│   │   ├── sql/                             ← source-of-truth SQL
│   │   │   ├── Phase5_01_schema.sql
│   │   │   ├── Phase5_02_reference_data.sql
│   │   │   ├── Phase5_03_staff_data.sql
│   │   │   └── Phase5b_sub_agent_addition.sql
│   │   ├── migrations/                      ← Alembic, Phase 7
│   │   │   └── versions/
│   │   └── tests/
│   │       ├── fixtures/
│   │       └── test_engine.py
│   └── frontend/                            ← Phase 8
│
└── Supporting content/                      ← LOCAL ONLY — excluded from Git
```

**Railway configuration:** Root Directory must be set to `Application/backend` (not `backend`).

---

## 5. Domain model (locked)

### 5.1 Four-slot case structure

Each case has four nullable `(staff_id, role_id)` slots:

1. **Counsellor slot** — `COUNS_DIR` or empty (sub-agent referrals leave this empty)
2. **Case Officer slot** — `CO_DIR` or `CO_SUB` or empty
3. **Pre-sales slot** — `PRESALES` or empty
4. **VP slot** — `VP` or empty (only when VP actively works the case)

Each filled slot produces one row in `tx_bonus_payment`. The role on the slot governs the calculation, not the staff member's home/primary role. A staff member can be COUNS_DIR on one case and VP on another — Phạm Thị Lợi is the canonical example (VP_DN on some cases, CO_SUB on others).

### 5.2 Five roles

`COUNS_DIR`, `CO_DIR`, `CO_SUB`, `PRESALES`, `VP`. Office-role allowed combinations live in `dim_role_office_allowed`. VP scheme starts as a copy of the same office's COUNS_DIR rates, configurable per office.

### 5.3 Cross-office model

Each case has an office (HCM/HN/DN/MEL/HK). The bonus calc for a slot uses **the case's office × the slot's role**, not the staff's home office. Multi-office staff (e.g., Quan Hoàng Yến with HCM+HN simultaneously) compute tier independently per office.

### 5.4 Institution classification (4 + UNVERIFIED)

| Classification | Weight | Rate sheet |
|---|---|---|
| `IN_SYSTEM_REGULAR` | 1.0 | In-system |
| `IN_SYSTEM_PRIORITY` | 1.0 | In-system + priority bonus |
| `OUT_SYSTEM_GROUP` | 1.0 | In-system (group is relationship distinction, not rate distinction) |
| `OUT_SYSTEM_MASTER_AGENT` | 0.7 | Sub-referral |
| `UNVERIFIED` | (treated as regular) | In-system |

**Eynesbury pattern:** Group classification + aggregate priority bonus simultaneously. A Navitas Group institution that's part of "Other Navitas Colleges (AU)" priority bucket gets BOTH `OUT_SYSTEM_GROUP` classification AND aggregate priority bonus via `aggregate_priority_partner_id` FK lookup.

### 5.5 Master Agent vs Sub-Agent (distinct concepts)

- **Master Agents / Groups** (`ref_partner`) — institution-side classification. Tells us how StudyLink accesses a school.
- **Sub-Agents** (`ref_sub_agent`, added Phase 5b) — case-side referrers. External partners who hand cases to StudyLink for CO_SUB processing. Informational only; finance uses for accounts-payable reconciliation.
- **Mutual exclusivity** — a case cannot be both Master-Agent-routed AND sub-agent-referred. Enforced by `chk_tx_case_partner_xor_subagent` CHECK constraint.

### 5.6 Country buckets (6)

Per Doc 6 procedural structure: `TARGET`, `FLAT`, `VN_RMIT`, `VN_BUV`, `VN_OTHER`, `SUMMER`.

### 5.7 CO_SUB sub-schemes

`ENROL_ONLY_VISA_ONLY` and `ENROL_PLUS_VISA`. Different rate tables. Set per-staff. Both Trường An and Lợi use `ENROL_ONLY_VISA_ONLY`. New sub-schemes can be added without schema change (stored as `VARCHAR(32)`).

### 5.8 Pre-sales rules (both apply, competing)

- **Rule A** — when slot filled: 200,000đ flat per case (always).
- **Rule B** — when case-level `presales_share_pct` non-null/non-zero: Pre-sales also takes share% of total Counsellor bonus. Counsellor receives `total × (1 − share%)`, Pre-sales receives `200K + (total × share%)`.

### 5.9 Vietnam-domestic flat 1M rule

Supersedes Doc 4 sheet 1's 0.5 weight rule for VN-domestic cases:
- 1,000,000đ flat per case
- Couns_Dir alone: 100% → 1M
- Couns_Dir + CO: 50/50 → 500K each
- Pre-sales rules apply on top, against Counsellor's portion
- Configurable per country in `ref_local_enrolment_bonus` (HK extension ready)

---

## 6. Phase 6: calculation engine

### 6.1 Public API

```python
def calculate_case_month(
    case: CaseInput,
    refdata: ReferenceData,
    context: RunContext,
) -> list[BonusPayment]:
    """Returns 0–4 BonusPayment rows, one per filled slot."""
```

This is the only function `data/` and `api/` will call. Phase 7 wraps it. Phase 6 stops here.

### 6.2 Module layout (`Application/backend/engine/`)

| File | Responsibility |
|---|---|
| `types.py` | Frozen dataclasses (CaseInput, ReferenceData, BonusPayment, RunContext, Slot, etc.) |
| `enums.py` | String constants for slots, tiers, country buckets, status codes, classifications |
| `classify.py` | country_id → bucket; (target, actual) → tier; staff → CO_SUB subscheme |
| `rates.py` | `ref_rate` lookup |
| `splits.py` | status_code → split_pct |
| `packages.py` | `ref_service_fee` lookup; refund-on-refused retention check |
| `addons.py` | Guardian AU and similar |
| `priorities.py` | Priority partner % + KPI multiplier |
| `presales.py` | 200K flat + share% redistribution |
| `vietnam_local.py` | VN-domestic flat 1M rule |
| `advance.py` | D1.R12 advance/carry-over event detection |
| `calc.py` | Orchestrates all of the above with explicit stacking order |

### 6.3 Core dataclasses

All `frozen=True`. Money as `int` (đồng). Percentages as `Decimal`.

#### `Slot`

```python
@dataclass(frozen=True)
class Slot:
    staff_id: int | None    # None = empty slot
    role_id: int | None
```

#### `CaseInput`

Organized by purpose. Identity/audit fields pass through to `BonusPayment.audit_json`; calculation fields drive engine logic.

| Group | Field | Drives calc? |
|---|---|---|
| **Identity** | `case_id`, `contract_id`, `student_id`, `student_name`, `notes` | No (audit) |
| **Institution & sourcing** | `institution_id` (resolved FK) | Yes — rate, priority |
| | `institution_text_raw` | No (audit) |
| | `referring_partner_id` (Master Agent, nullable, mutually exclusive with sub-agent) | Yes — OUT_SYSTEM_MA classification |
| | `referring_sub_agent_id` (sub-agent referrer, nullable) | No (audit + finance reconciliation) |
| | `referring_agent_text_raw` | No (audit) |
| | `system_type_observed` | No (cross-check vs engine-resolved) |
| **Country & package** | `country_id` | Yes — country bucket |
| | `package_service_fee_id` (nullable) | Yes — package_bonus, refund check |
| **Status** | `status_code` (canonical) | Yes — split + retention |
| | `application_status_text` | No (audit) |
| | `client_type_code` | Yes — D4.R3 weight cap |
| **Office & slots** | `office_id` (case office) | Yes |
| | `counsellor`, `case_officer`, `presales`, `vp` (Slot fields) | Yes |
| | `presales_share_pct` (Decimal 0–1) | Yes |
| **Dates** | `contract_signed_date`, `fee_paid_date`, `visa_received_date`, `enrolled_date`, `course_start_date`, `course_status`, `file_closed_date` (all nullable) | Yes — D1.R12 advance/carry-over |
| **Prior payments** | `prior_payments_by_slot` | Yes — D1.R12 |

Field list is intentionally extensible — new fields go into the right group as the model evolves.

#### `RunContext`

```python
@dataclass(frozen=True)
class RunContext:
    year: int
    month: int
    enrolments_by_staff_office: dict[tuple[int, int], int]  # weighted count
    targets_by_staff_office: dict[tuple[int, int], int]
```

#### `ReferenceData`

Pre-indexed snapshot of all `ref_` and `dim_` tables. Loaded once per run by the data layer. Engine never touches DB. Dict-based for O(1) lookups.

#### `BonusPayment`

Maps 1:1 to the `tx_bonus_payment` schema. Decomposed columns (`tier_bonus`, `package_bonus`, `addon_bonus`, `priority_bonus`, `presales_share_taken`, `flat_local_enrolment_bonus`, `advance_offset`, `gross_bonus`, `net_payable`) plus `calc_notes` (human-readable) and `audit_json` (full lookup trace).

### 6.4 Calculation order

For each filled slot on the case:

1. Determine context — country bucket, tier (multi-office independence + secondary-office inheritance), CO_SUB subscheme if applicable.
2. Look up `split_pct` from status code.
3. **Special case: VN-domestic** — apply flat-1M rule, skip steps 4–7. Pre-sales and offsets still apply.
4. **Special case: fees-paid retained** — if status is "Visa refused" with package, check `service_fee.refund_on_visa_refused` against `service_fee.fee_amount`. Full refund → 0 bonus. Otherwise 400K rate fires.
5. Look up `base_rate` from `ref_rate`.
6. `tier_bonus = base_rate × split_pct`
7. `package_bonus` — only if slot's role earns package bonus on this package.
8. `addon_bonus` — Guardian AU etc.
9. `priority_bonus` — institution's priority % × `tier_bonus` × KPI multiplier (0.5 pre-KPI, 1.0 post).
10. **Pre-sales redistribution** — if `presales_share_pct > 0`: deduct from Counsellor row, add to Presales row. Pre-sales also gets flat 200K when filled.
11. `advance_offset` — D1.R12. Enrolment-before-visa → 50% advance. Visa-grant + file-close where 50% paid earlier → +50% offset. Status reverts to cancelled/refused after advance → −50% clawback.
12. `gross_bonus = sum of all components`; `net_payable = gross_bonus + advance_offset`.
13. Write `audit_json` — every lookup key, intermediate value, rule citation.

Each step writes a `calc_notes` line. Lookup misses do not crash; engine sets that component to 0, flags it in `audit_json`, continues. Review board UI surfaces flags later.

### 6.5 Testing strategy

**Per-case + per-slot validation, not just totals.** Totals can match by coincidence; per-row asserts cannot.

For each of the 4 BC samples from Phase 3:

```python
for case, expected_payments in fixture.cases:
    actual_payments = calculate_case_month(case, refdata, context)
    for actual, expected in zip(actual_payments, expected_payments):
        assert actual.tier_bonus      == expected.tier_bonus
        assert actual.package_bonus   == expected.package_bonus
        assert actual.priority_bonus  == expected.priority_bonus
        assert actual.gross_bonus     == expected.gross_bonus
        assert actual.net_payable     == expected.net_payable

# Plus belt-and-braces final cross-check
assert sum(p.net_payable for ...) == bc_grand_total
```

Mismatches dump `audit_json` for forensic debugging.

**Sample order (incremental complexity):**

1. **Trường An Jan 2024** (CO_SUB, OVER tier, full month) — validates rate lookup + status splits + carry-over + priority basics.
2. **Lợi Jan 2025 sub-agent** (CO_SUB, UNDER tier) — validates UNDER tier path.
3. **Lợi Jan 2024 VP_ĐN** (CO_DIR DN, packages + 400K retention) — validates fees-paid retention rule + DN rate sheet + cross-office routing.
4. **Yến Jan 2024 VP_HCM + VP_HN** (multi-office, package + Guardian AU stacking) — validates multi-office tier independence + Guardian AU stacking + Premium HCM-only with DN CO.

If 1–4 all pass to the đồng (per-row + total), Phase 6 is done.

---

## 7. Deferred to later phases

Phase 6 explicitly does **not** cover:

| Topic | Phase | Why deferred |
|---|---|---|
| Section II contract target bonus (D1.R28–34) | 6.5 | Different domain (Counsellor's contract count, not enrolment) |
| Team excess bonuses (D1.R25–27) | 6.5 | Aggregate-level, not case-level |
| Departure rules (D1.R20–23) | 6.5 | Admin event, applied as overlay at run time |
| Complaint deductions (D1.R16–19) | 6.5 | Admin-driven |
| 2-out-target = 1 target arithmetic (D1.R6) | data layer | Affects tier counting, not bonus calc — handled at `RunContext` aggregation |
| Data layer (DB → ReferenceData) | 7 | Not engine concern |
| FastAPI routes | 7 | Not engine concern |
| Persistence of cases and payments | 7 | Not engine concern |
| Alembic migrations setup | 7 | Generated against current schema once Phase 6 stable |
| React frontend (case entry, review board, admin) | 8 | After API is stable |
| Auth (Clerk / Auth0 / Supabase / FastAPI custom) | review-board phase | Deferred per stack lock |

---

## 8. What this document is for

A future session (or future-you) should be able to read this file and resume work without re-deriving any decisions made. If a decision has been locked through Q&A, it lives here. Phase 1–4 reports remain authoritative for the rule inventory and sample validation; this file references them rather than duplicating.

Updates to this document happen when:
- A new architectural principle is locked
- A domain model decision changes
- A phase deliverable changes scope

Don't update for implementation details — those belong in code comments and module docstrings.
