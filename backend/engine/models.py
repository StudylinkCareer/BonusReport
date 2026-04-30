"""
Core dataclasses for the BonusReport calculation engine.

All dataclasses are frozen (immutable) to prevent accidental mutation
during calculation. Money is stored as int (đồng, no decimals).
Percentages are stored as Decimal for precision.

Per architecture.md §6.3.
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

    # --- Prior payments (D1.R12) ---
    # Key: (slot_label, staff_id) — e.g. ("counsellor", 12)
    # Value: đồng already paid to that person on this case in prior months
    prior_payments_by_slot: dict[tuple[str, int], int] = field(default_factory=dict)


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
    """
    year: int
    month: int
    enrolments_by_staff_office: dict[tuple[int, int], int]   # weighted count
    targets_by_staff_office: dict[tuple[int, int], int]


# ---------------------------------------------------------------------------
# ReferenceData — pre-indexed snapshot of all ref_/dim_ tables
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceData:
    """
    Pre-indexed snapshot of all reference and dimension tables.

    Loaded once per run by the data layer (backend/data/). The engine
    never touches the database — it only reads from this snapshot.

    Dict-based for O(1) lookups. Concrete fields will be added as each
    engine module is built; placeholders here keep the import surface
    stable.
    """
    # Populated by data layer in later phases. Each dict maps a primary
    # key to a row dict (or a typed sub-record once we formalise them).
    institutions: dict[int, dict] = field(default_factory=dict)
    countries: dict[int, dict] = field(default_factory=dict)
    offices: dict[int, dict] = field(default_factory=dict)
    roles: dict[int, dict] = field(default_factory=dict)
    staff: dict[int, dict] = field(default_factory=dict)
    priority_partners: dict[int, dict] = field(default_factory=dict)
    priority_targets: dict[int, dict] = field(default_factory=dict)
    service_fees: dict[int, dict] = field(default_factory=dict)
    rates: dict[int, dict] = field(default_factory=dict)
    status_splits: dict[str, dict] = field(default_factory=dict)
    sub_agents: dict[int, dict] = field(default_factory=dict)


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

    # Decomposed bonus columns (all đồng)
    tier_bonus: int                              # rate-card base
    package_bonus: int                           # gói dịch vụ premium
    addon_bonus: int                             # multi-school, referrals, etc.
    priority_bonus: int                          # priority partner uplift
    presales_share_taken: int                    # subtracted if presales involved
    flat_local_enrolment_bonus: int              # local programs flat amount

    # Adjustments
    advance_offset: int                          # subtracted if prior payment exists

    # Totals
    gross_bonus: int                             # sum of components before retention
    net_payable: int                             # what actually pays out this month

    # Audit
    calc_notes: str                              # human-readable trail
    audit_json: dict                             # full structured lookup trace
