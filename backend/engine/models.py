"""
Core dataclasses for the BonusReport calculation engine.

All dataclasses are frozen (immutable) to prevent accidental mutation
during calculation. Money is stored as int (đồng, no decimals).
Percentages are stored as Decimal for precision.

Per architecture.md §6.3.

CHANGES IN THIS REVISION (Phase 6c — payment timing):
  - RunContext: added clawback_balances_by_staff and prior_withholdings_by_case_staff
  - ReferenceData: added departure_rules, complaint_deductions, contract_target_tiers
  - BonusPayment: added withheld_amount, unlocked_amount, clawback_applied,
                  bank_transfer_required
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


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
    # When ref_status_split.is_carry_over=Y, calc_tier uses this locked rate
    # instead of doing a fresh lookup. Per Q3.4 (policy review):
    # "carry-over rate locks at original calculation period." The data layer
    # populates this when copying forward a case from a prior month's run.
    prior_month_rate: int | None = None

    # --- Prior payments (D1.R12) ---
    # Key: (slot_label, staff_id) — e.g. ("counsellor", 12)
    # Value: đồng already paid to that person on this case in prior months
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

    enrolments_by_priority_partner_ytd: YTD enrolment counts per priority
    partner for the run year. Key is priority_partner_id.

    NEW (Phase 6c — payment timing):
      clawback_balances_by_staff: §I.5.3 running clawback owed by each staff
        coming into this run. Key is staff_id, value is đồng owed (>= 0).
        Engine reads, applies to current-month payable, writes new balance
        to tx_clawback_balance.

      prior_withholdings_by_case_staff: amounts withheld in prior runs that
        should release this month under is_carry_over rules. Key is
        (case_id, staff_id), value is đồng. Loaded by data layer from
        tx_bonus_payment.withheld_amount in earlier runs.
    """
    year: int
    month: int
    enrolments_by_staff_office: dict[tuple[int, int], int]
    targets_by_staff_office: dict[tuple[int, int], int]
    enrolments_by_priority_partner_ytd: dict[int, int] = field(default_factory=dict)

    # Phase 6c additions
    clawback_balances_by_staff: dict[int, int] = field(default_factory=dict)
    prior_withholdings_by_case_staff: dict[tuple[int, int], int] = field(default_factory=dict)


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
    institutions: dict[int, dict] = field(default_factory=dict)
    countries: dict[int, dict] = field(default_factory=dict)
    offices: dict[int, dict] = field(default_factory=dict)
    roles: dict[int, dict] = field(default_factory=dict)
    staff: dict[int, dict] = field(default_factory=dict)
    priority_partners: dict[int, dict] = field(default_factory=dict)
    priority_targets: dict[int, dict] = field(default_factory=dict)
    service_fees: dict[int, dict] = field(default_factory=dict)
    rates: dict[int, dict] = field(default_factory=dict)
    local_enrolment_bonuses: dict[int, dict] = field(default_factory=dict)
    status_splits: dict[str, dict] = field(default_factory=dict)
    sub_agents: dict[int, dict] = field(default_factory=dict)
    calculation_params: dict[str, dict] = field(default_factory=dict)

    # Phase 6c additions
    departure_rules: dict[int, dict] = field(default_factory=dict)
    complaint_deductions: dict[str, dict] = field(default_factory=dict)
    contract_target_tiers: dict[int, dict] = field(default_factory=dict)


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
    withheld_amount: int                         # held back this run
    unlocked_amount: int                         # released this run (prior holds)
    clawback_applied: int                        # §I.5.3 clawback this run
    bank_transfer_required: bool                 # clawback couldn't be offset

    net_payable: int                             # final amount paid this month

    # Audit
    calc_notes: str                              # human-readable trail
    audit_json: dict                             # full structured lookup trace
