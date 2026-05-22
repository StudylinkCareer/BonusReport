"""
Core dataclasses for the BonusReport calculation engine.

All dataclasses are frozen (immutable) to prevent accidental mutation
during calculation. Money is stored as int (đồng, no decimals).
Percentages are stored as Decimal for precision.

Per architecture.md §6.3.

CHANGES:
  Phase 6c — payment timing:
    - RunContext: added clawback_balances_by_staff and prior_withholdings_by_case_staff
    - ReferenceData: added departure_rules, complaint_deductions, contract_target_tiers
    - BonusPayment: added withheld_amount, unlocked_amount, clawback_applied,
                    bank_transfer_required

  Phase 7 — agreement-based schema + priority Lists:
    - ReferenceData.priority_partners → priority_lists (rename for the
      ref_priority_partner → ref_priority_list table rename)
    - ReferenceData adds: priority_groups, priority_list_institutions,
      partners, partner_classifications, partner_flat_rates,
      institution_agreements
    - RunContext.enrolments_by_priority_partner_ytd →
      enrolments_by_priority_list_ytd (rename to match the new keying)
    - RunContext adds: enrolments_by_priority_list_institution_ytd
      (separate YTD bucket for carved-out institutions within an
      aggregate List — see calc_priority.py)

  Phase 7 (carry-over key fix):
    - RunContext.prior_withholdings_by_case_staff →
      prior_withholdings_by_contract_staff. Key changes from
      (case_id, staff_id) to (contract_id, staff_id). Reason: tx_case
      is keyed on (contract_id, run_year, run_month) — same contract
      gets a different case_id every month. Carry-over balances need
      to match across months by contract, not case.

  Phase 8 — priority retroactive layer:
    - RunContext.enrolments_by_priority_list_ytd and
      enrolments_by_priority_list_institution_ytd → collapsed into a
      single priority_ytd: PriorityYtdSnapshot field. The snapshot
      carries channel-split YTD counts (direct/sub/total) at both
      list and institution levels, so calc_priority can apply the
      role-based threshold rule (CO_SUB gates on sub_target,
      COUNS_DIR/CO_DIR gate on direct_target, both also gate on
      total_target).

  Phase 12b — priority 25/25/50 split rule:
    - BonusPayment: added priority_withheld_amount, priority_unlocked_amount,
                    priority_schedule_type. All default-zero/STANDARD so
                    every existing constructor still works unchanged.
    - RunContext: added prior_priority_withholdings_by_contract_staff,
                  priority_quota_state, seen_priority_case_ids. The
                  priority_quota_state and seen set are mutated in-place
                  during the run by payment_timing — this is a deliberate
                  exception to the otherwise-immutable RunContext, mirroring
                  the existing pattern where dict contents (not the dict
                  reference) are mutable inside a frozen dataclass.

  Phase 14b — management override mechanism:
    - RunContext: added overrides_by_case_staff. Keyed by
      (case_id, staff_id), value is (total_amount, joined_reasons).
      Loaded from tx_case_override by the data layer. Override sticks
      to the (case, staff) pair regardless of run period — if the case
      is re-calculated in any period, the same override applies.
    - BonusPayment: added override_applied, override_reason. Default
      zero / None so every existing constructor still works. Surfaced
      in tx_bonus_payment so the UI can show "Δ Override" alongside
      the underlying calculation.

    Per Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.5.3, CLAWBACK
    is a separate concept (policy-driven reversal of prior payment, with
    its own running-balance accounting in tx_clawback_balance). Overrides
    in tx_case_override are positive-only and discretionary; clawback
    has its own table and engine path. Do not conflate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from backend.engine_runner.ytd_aggregator import PriorityYtdSnapshot


# ---------------------------------------------------------------------------
# Slot — represents one of the four roles that can earn bonus on a case
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """
    A slot on a case (counsellor, case_officer, presales, or vp).

    staff_id is the canonical identifier used for lookups and dedup.
    staff_name is carried alongside for display in reports — staff
    don't recognise IDs.

    All fields are nullable to represent an empty/unfilled slot.
    """
    staff_id: int | None
    staff_name: str | None
    role_id: int | None


# ---------------------------------------------------------------------------
# CaseInput — everything the engine needs to calculate bonus for one case
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseInput:
    """
    Input for a single case calculation.

    Field groups (per architecture.md §6.3):
      - Identity: pass-through to BonusPayment.audit_json, doesn't drive calc
      - Institution & sourcing: drives rate lookup and OUT_SYSTEM_MA classification
      - Country & package: drives country bucket and package_bonus
      - Status: drives split percentages and retention
      - Office & slots: who gets paid
      - Dates: drives D1.R12 advance/carry-over logic
      - Prior payments: drives D1.R12 (what's already been paid this case)
      - Addon items: drives addon_bonus (multi-school etc.)
    """

    # --- Identity (audit only) ---
    case_id: int
    contract_id: str
    student_id: str
    student_name: str
    notes: str | None

    # --- Institution & sourcing ---
    institution_id: int                          # resolved FK — drives rate, priority
    institution_text_raw: str                    # audit
    referring_partner_id: int | None             # Master Agent — drives OUT_SYSTEM_MA
    referring_sub_agent_id: int | None           # sub-agent referrer — audit + AP recon only
    referring_agent_text_raw: str | None         # audit
    system_type_observed: str | None             # cross-check vs engine-resolved

    # --- Country & package ---
    country_id: int                              # drives country bucket
    package_service_fee_id: int | None           # drives package_bonus, refund check

    # --- Status ---
    status_code: str                             # canonical — drives split + retention
    application_status_text: str | None          # audit
    client_type_code: str                        # drives D4.R3 weight cap

    # --- Office & slots ---
    office_id: int                               # case office
    counsellor: Slot
    case_officer: Slot
    presales: Slot
    vp: Slot
    presales_share_pct: Decimal                  # 0–1

    # --- Dates (all nullable) ---
    contract_signed_date: date | None
    fee_paid_date: date | None
    visa_received_date: date | None
    enrolled_date: date | None
    course_start_date: date | None
    course_status: str | None
    file_closed_date: date | None

    # --- Carry-over rate locking (Phase 6c) ---
    prior_month_rate: int | None = None

    # --- CO_SUB subscheme override (item 3 from post-Phase-6 backlog) ---
    co_sub_subscheme_override: str | None = None

    # --- Prior payments (D1.R12) ---
    prior_payments_by_slot: dict[tuple[str, int], int] = field(default_factory=dict)

    # --- Addon items (drives addon_bonus) ---
    addon_items: list[tuple[int, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RunContext — month-level state that applies to every case in a run
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunContext:
    """
    Context for a single calculation run (one month, one office scope).

    enrolments_by_staff_office: weighted enrolment counts for the month.
    Key is (staff_id, office_id) to handle staff who work across offices.

    targets_by_staff_office: monthly enrolment targets, same key shape.

    priority_ytd (Phase 8): year-to-date enrolment counts split by
    channel (direct/sub/total) at both list and institution levels.
    Replaces the prior pair of unsplit dicts. calc_priority reads:

        priority_ytd.list_count(list_id, channel)
            for non-carve-out institutions, where channel is the slot's
            role-mapped channel ('direct' for COUNS_DIR/CO_DIR slots,
            'sub' for CO_SUB slots, or 'total' for the list's total
            target gate)

        priority_ytd.institution_count(list_id, inst_id, channel)
            for carve-out institutions

    Phase 6c — payment timing:
      clawback_balances_by_staff: §I.5.3 running clawback owed by each staff
        coming into this run. Key is staff_id, value is đồng owed (>= 0).
        Engine reads, applies to current-month payable, writes new balance
        to tx_clawback_balance.

    Phase 7 carry-over key fix (renamed from prior_withholdings_by_case_staff):
      prior_withholdings_by_contract_staff: amounts withheld in prior
        runs that should release this month under is_carry_over rules.
        Key is (contract_id, staff_id), value is đồng. The CONTRACT id
        is the right key here — tx_case has a different case_id row for
        every (contract, run_year, run_month) tuple, so a withholding
        opened by Feb's case_id won't match April's case_id for the
        same contract. Loaded by data layer from tx_carry_over_balance,
        joined to tx_case to fetch contract_id.

    Phase 12b — priority 25/25/50 split rule:
      prior_priority_withholdings_by_contract_staff: parallel to
        prior_withholdings_by_contract_staff but tracks the priority
        portion withheld under SPLIT_25_25_50. Loaded from
        tx_bonus_payment.priority_withheld_amount where the case has
        not yet had its visa-receipt carry-over fire. Released in the
        carry-over (a) multi-month branch.

      priority_quota_state: running enrolment count keyed by
        priority_list_institution_id. Loaded from tx_priority_quota_tracker
        at run start, MUTATED IN PLACE by payment_timing as cases are
        processed (this is the one explicit exception to the otherwise-
        immutable RunContext — only the dict contents change, not the
        dict reference). Persisted back to tx_priority_quota_tracker
        by the engine_runner after all cases process.

        Shape: {pli_id: {'count_direct': int, 'count_sub': int}}

      seen_priority_case_ids: per-run set of case_ids that have already
        had their priority quota incremented. Prevents double-counting
        across multiple slot rows for the same case (counsellor +
        case_officer + presales). Mutated in place. Reset per run.

    Phase 14b — management overrides:
      overrides_by_case_staff: discretionary management overrides from
        tx_case_override, applied as a final additive step to net_payable
        (and to the addon-bypass path inside _zeroed_payment).

        Key: (case_id, staff_id).
        Value: (total_amount, joined_reasons).
          - total_amount: SUM of all tx_case_override.amount rows for
            this (case, staff). Always > 0 by CHECK constraint.
            Multiple rows are allowed (e.g. an initial 500k override
            in one month, plus another 200k later — they sum to 700k).
          - joined_reasons: ' | '-joined tx_case_override.reason values
            for surfacing in BonusPayment.calc_notes / audit_json.

        Sticks to the (case, staff) pair regardless of run period —
        if the case is re-calculated in any period, the same override
        applies. (Override is a decision about a case, not a period.)

        Per Chính_sách §I.5.3, CLAWBACK is a SEPARATE mechanism with
        its own table (tx_clawback_balance) and engine path. Overrides
        are positive-only; do not conflate the two.
    """
    year: int
    month: int
    enrolments_by_staff_office: dict[tuple[int, int], int]
    targets_by_staff_office: dict[tuple[int, int], int]

    # Phase 8 — channel-split YTD snapshot (replaces the prior two dicts)
    priority_ytd: PriorityYtdSnapshot = field(default_factory=PriorityYtdSnapshot)

    # Phase 6c additions
    clawback_balances_by_staff: dict[int, int] = field(default_factory=dict)

    # Phase 7 carry-over key fix — keyed by (contract_id, staff_id), not (case_id, staff_id)
    prior_withholdings_by_contract_staff: dict[tuple[str, int], int] = field(default_factory=dict)

    # Phase 12b additions — priority 25/25/50 split rule
    prior_priority_withholdings_by_contract_staff: dict[tuple[str, int], int] = field(default_factory=dict)
    priority_quota_state: dict[int, dict] = field(default_factory=dict)
    seen_priority_case_ids: set[int] = field(default_factory=set)

    # Phase 14b additions — management overrides (per (case, staff))
    overrides_by_case_staff: dict[tuple[int, int], tuple[int, str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ReferenceData — pre-indexed snapshot of all ref_/dim_ tables
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceData:
    """
    Pre-indexed snapshot of all reference and dimension tables.

    Loaded once per run by the data layer (backend/data/). The engine
    never touches the database — it only reads from this snapshot.

    Dict-based for O(1) lookups.
    """
    # Core dimensions
    institutions: dict[int, dict] = field(default_factory=dict)
    countries: dict[int, dict] = field(default_factory=dict)
    offices: dict[int, dict] = field(default_factory=dict)
    roles: dict[int, dict] = field(default_factory=dict)
    staff: dict[int, dict] = field(default_factory=dict)
    sub_agents: dict[int, dict] = field(default_factory=dict)

    # Phase 7 — agreements & partners (replaces classification column)
    institution_agreements: dict[int, dict] = field(default_factory=dict)
    partners: dict[int, dict] = field(default_factory=dict)
    partner_classifications: dict[int, dict] = field(default_factory=dict)
    partner_flat_rates: dict[int, dict] = field(default_factory=dict)

    # Phase 7 — priority structure (Group → List → Institution).
    # Phase 12b note: ref_priority_group rows now carry priority_split_rule_type;
    # payment_timing walks institution → list_institution → list → group to
    # determine the active rule for a case.
    priority_groups: dict[int, dict] = field(default_factory=dict)
    priority_lists: dict[int, dict] = field(default_factory=dict)
    priority_list_institutions: dict[int, dict] = field(default_factory=dict)
    priority_targets: dict[int, dict] = field(default_factory=dict)

    # Rates & fees
    service_fees: dict[int, dict] = field(default_factory=dict)
    rates: dict[int, dict] = field(default_factory=dict)
    local_enrolment_bonuses: dict[int, dict] = field(default_factory=dict)

    # Status & params
    status_splits: dict[str, dict] = field(default_factory=dict)
    calculation_params: dict[str, dict] = field(default_factory=dict)

    # Phase 6c additions
    departure_rules: dict[int, dict] = field(default_factory=dict)
    complaint_deductions: dict[str, dict] = field(default_factory=dict)
    contract_target_tiers: dict[int, dict] = field(default_factory=dict)

    # Item 3 — Sub-agent CO scheme
    staff_targets: dict[int, dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BonusPayment — engine output, maps 1:1 to tx_bonus_payment schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BonusPayment:
    """
    Calculated bonus for one (case, staff, role) combination.

    Maps 1:1 to the tx_bonus_payment table. Decomposed columns let
    finance see exactly how the gross_bonus was assembled — every
    figure is independently testable.

    Payment timing math (Phase 6c):
      base_payable_this_run = gross_bonus × split_pct (from ref_status_split)
      withheld_amount      = portion held back this run (current-enrolled,
                             post-resignation deferral, etc.)
      unlocked_amount      = portion released this run from prior holds
                             (carry-over from previous month)
      clawback_applied     = §I.5.3 clawback consumed this month from
                             running balance
      net_payable = base_payable_this_run
                  - withheld_amount        (held for future runs)
                  + unlocked_amount        (released from prior runs)
                  - clawback_applied
                  - advance_offset         (D1.R12 prior payment)
                  + override_applied       (Phase 14b mgmt override)

    Phase 12b — priority 25/25/50 split rule additions:
      priority_withheld_amount: the portion of the at-enrolment priority
        bonus deferred to the visa-receipt month. Non-zero only when
        priority_schedule_type == 'SPLIT_25_25_50'. The carry-over
        visa-receipt run releases this via priority_unlocked_amount.
      priority_unlocked_amount: priority withhold released this run
        from a prior SPLIT_25_25_50 case. Added to net_payable in the
        carry-over branch.
      priority_schedule_type: 'STANDARD' (default) or 'SPLIT_25_25_50'.
        Locked at first-pay; not re-evaluated if quota state changes
        between enrolment and visa.

    Phase 14b — management override fields:
      override_applied: sum of tx_case_override.amount rows matching
        this payment's (case_id, staff_id). Always >= 0 (per CHECK
        constraint on tx_case_override). Added as the final step to
        net_payable. Zero when no override exists for this (case, staff).
      override_reason: ' | '-joined tx_case_override.reason values when
        an override is applied, else None. Surfaced so the UI's
        "Overrides" pill and "Δ Override" column can render the manager's
        rationale alongside the engine's calculation.

      Override is a SEPARATE concept from clawback (§I.5.3). Clawback
      lives in tx_clawback_balance with its own per-staff running balance.
      Do not store clawback amounts here.

    calc_notes: human-readable explanation of how this row was built.
    audit_json: full lookup trace (which rate row, which split row,
    which priority partner, etc.) for debugging and reconciliation.
    """
    # Identity
    case_id: int
    staff_id: int
    staff_name: str
    role_id: int
    slot_label: str                              # "counsellor", "case_officer", etc.

    # Decomposed bonus columns (all đồng) — pre-timing
    tier_bonus: int                              # rate-card base
    package_bonus: int                           # gói dịch vụ premium
    addon_bonus: int                             # multi-school, referrals, etc.
    priority_bonus: int                          # priority partner uplift
    presales_share_taken: int                    # subtracted if presales involved
    flat_local_enrolment_bonus: int              # local programs flat amount

    # Adjustments
    advance_offset: int                          # subtracted if prior payment exists

    # Totals
    gross_bonus: int                             # sum of components before timing

    # Phase 6c additions — payment timing
    withheld_amount: int                         # held back this run (splittable)
    unlocked_amount: int                         # released this run (prior splittable holds)
    clawback_applied: int                        # §I.5.3 clawback this run
    bank_transfer_required: bool                 # clawback couldn't be offset

    net_payable: int                             # final amount paid this month

    # Audit
    calc_notes: str                              # human-readable trail
    audit_json: dict                             # full structured lookup trace

    # Phase 12b additions — priority 25/25/50 split rule.
    # Defaults provided so every existing constructor still works.
    priority_withheld_amount: int = 0
    priority_unlocked_amount: int = 0
    priority_schedule_type: str = 'STANDARD'

    # Phase 14b additions — management override.
    # Defaults provided so every existing constructor still works.
    # See class docstring above for semantics; see tx_case_override
    # table and CHECK constraint chk_tx_case_override_amount_positive.
    override_applied: int = 0
    override_reason: str | None = None
