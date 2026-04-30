"""
Orchestrator for the BonusReport calculation engine.

Entry point for calculating bonus on a single case. Takes a CaseInput
plus RunContext and ReferenceData, and returns a list of BonusPayment
rows — one per filled slot.

Each per-column calc is currently a stub returning 0. As individual
modules (calc_tier.py, calc_priority.py, etc.) are built, the stubs
will be replaced with real implementations. The orchestrator structure
itself stays stable.

Per architecture.md §6.
"""

from __future__ import annotations

from .calc_tier import calc_tier_bonus
from .models import (
    BonusPayment,
    CaseInput,
    ReferenceData,
    RunContext,
    Slot,
)


# ---------------------------------------------------------------------------
# Slot iteration
# ---------------------------------------------------------------------------

# (slot_label, attribute_name_on_CaseInput).
# Order is significant — defines the order BonusPayment rows appear.
SLOT_LABELS: tuple[tuple[str, str], ...] = (
    ("counsellor", "counsellor"),
    ("case_officer", "case_officer"),
    ("presales", "presales"),
    ("vp", "vp"),
)


def _iter_filled_slots(case: CaseInput):
    """
    Yield (slot_label, slot) for each slot that has a staff_id assigned.
    Empty slots (staff_id is None) are skipped.
    """
    for label, attr in SLOT_LABELS:
        slot: Slot = getattr(case, attr)
        if slot.staff_id is not None:
            yield label, slot


# ---------------------------------------------------------------------------
# Per-column calc stubs — to be replaced module by module
# ---------------------------------------------------------------------------

def _tier_bonus(
    case: CaseInput,
    slot_label: str,
    slot: Slot,
    ctx: RunContext,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """Rate-card base bonus. Returns (amount, audit_dict)."""
    return calc_tier_bonus(case, slot, slot_label, ctx, ref)

def _package_bonus(case: CaseInput, slot_label: str, slot: Slot, ref: ReferenceData) -> int:
    """Premium package uplift. TODO: implement in engine/calc_package.py."""
    return 0


def _addon_bonus(case: CaseInput, slot_label: str, slot: Slot, ref: ReferenceData) -> int:
    """Add-ons (multi-school, referral, etc.). TODO: implement in engine/calc_addon.py."""
    return 0


def _priority_bonus(case: CaseInput, slot_label: str, slot: Slot, ref: ReferenceData) -> int:
    """Priority-partner uplift. TODO: implement in engine/calc_priority.py."""
    return 0


def _presales_share_taken(
    case: CaseInput,
    slot_label: str,
    slot: Slot,
    ref: ReferenceData,
    base_before_share: int,
) -> int:
    """
    Share of the bonus pool taken by the presales slot.
    TODO: implement in engine/calc_presales.py.

    Note: depending on the final rule reading, presales may earn its own
    row (current skeleton) or only show up as a deduction on counsellor
    / case_officer rows. Will be revisited when we wire this up.
    """
    return 0


def _flat_local_enrolment_bonus(case: CaseInput, slot_label: str, slot: Slot, ref: ReferenceData) -> int:
    """Flat amounts for local programs (e.g. Lovely Cup of Coffee referrals). TODO."""
    return 0


def _advance_offset(case: CaseInput, slot_label: str, slot: Slot) -> int:
    """
    D1.R12 — subtract amounts already paid to this person on this case
    in prior months. Pure lookup on CaseInput, no ref data needed.
    """
    if slot.staff_id is None:
        return 0
    return case.prior_payments_by_slot.get((slot_label, slot.staff_id), 0)


def _net_payable(gross: int, advance_offset: int) -> int:
    """Floor at zero — never claw back via a negative payment."""
    return max(0, gross - advance_offset)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def calculate_case(
    case: CaseInput,
    ctx: RunContext,
    ref: ReferenceData,
) -> list[BonusPayment]:
    """
    Calculate bonus payments for one case.

    Returns one BonusPayment per filled slot. With stubs in place, all
    columns return 0 — but the structure runs end-to-end and produces
    valid BonusPayment objects.
    """
    payments: list[BonusPayment] = []

    for slot_label, slot in _iter_filled_slots(case):
        tier, tier_audit = _tier_bonus(case, slot_label, slot, ctx, ref)
        package = _package_bonus(case, slot_label, slot, ref)
        addon = _addon_bonus(case, slot_label, slot, ref)
        priority = _priority_bonus(case, slot_label, slot, ref)
        flat_local = _flat_local_enrolment_bonus(case, slot_label, slot, ref)

        gross_before_share = tier + package + addon + priority + flat_local
        presales_share = _presales_share_taken(
            case, slot_label, slot, ref, gross_before_share
        )

        gross = gross_before_share - presales_share
        offset = _advance_offset(case, slot_label, slot)
        net = _net_payable(gross, offset)

        # slot.staff_id is guaranteed non-None here (filtered by _iter_filled_slots)
        assert slot.staff_id is not None

        payments.append(
            BonusPayment(
                case_id=case.case_id,
                staff_id=slot.staff_id,
                staff_name=slot.staff_name or "",
                role_id=slot.role_id or 0,
                slot_label=slot_label,
                tier_bonus=tier,
                package_bonus=package,
                addon_bonus=addon,
                priority_bonus=priority,
                presales_share_taken=presales_share,
                flat_local_enrolment_bonus=flat_local,
                advance_offset=offset,
                gross_bonus=gross,
                net_payable=net,
                calc_notes=f"tier={tier_audit['tier']} bucket={tier_audit['country_bucket']}; other columns stubbed",
                audit_json={"tier": tier_audit, "stub_other": True},
            )
        )

    return payments
