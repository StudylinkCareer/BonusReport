"""
Orchestrator for the BonusReport calculation engine.

Entry point for calculating bonus on a single case. Takes a CaseInput
plus RunContext and ReferenceData, and returns a list of BonusPayment
rows — one per filled slot.

Per-column calc functions live in their own modules:
  calc_tier.py        — tier_bonus (rate-card base)
  calc_flat_local.py  — flat_local_enrolment_bonus (VN-domestic etc.)
  calc_*.py (TODO)    — package, addon, priority, presales

The orchestrator stays thin: pull values, sum them, build the
BonusPayment record, attach audit. Real calc logic lives elsewhere.

Per architecture.md §6.
"""

from __future__ import annotations

from .calc_flat_local import calc_flat_local_bonus, is_local_enrolment_case
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
# Per-column calc dispatchers
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
    """
    return 0


def _flat_local_enrolment_bonus(
    case: CaseInput,
    slot_label: str,
    slot: Slot,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """Flat per-country bonus (e.g. VN-domestic 1M rule). Returns (amount, audit)."""
    return calc_flat_local_bonus(case, slot, slot_label, ref)


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

    Returns one BonusPayment per filled slot. With remaining stubs in
    place, package/addon/priority/presales return 0 — but tier and
    flat_local are now real.
    """
    payments: list[BonusPayment] = []

    # Local-enrolment classification is per-case, so compute once here
    # rather than re-running it inside every slot iteration.
    is_local = is_local_enrolment_case(case, ref)

    for slot_label, slot in _iter_filled_slots(case):
        # Tier bonus is bypassed entirely for local-enrolment cases —
        # the flat_local column carries the whole amount instead.
        if is_local:
            tier = 0
            tier_audit = {
                'applied': False,
                'reason': 'local_enrolment_case_uses_flat_local',
            }
        else:
            tier, tier_audit = _tier_bonus(case, slot_label, slot, ctx, ref)

        package = _package_bonus(case, slot_label, slot, ref)
        addon = _addon_bonus(case, slot_label, slot, ref)
        priority = _priority_bonus(case, slot_label, slot, ref)
        flat_local, flat_local_audit = _flat_local_enrolment_bonus(
            case, slot_label, slot, ref,
        )

        gross_before_share = tier + package + addon + priority + flat_local
        presales_share = _presales_share_taken(
            case, slot_label, slot, ref, gross_before_share,
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
                calc_notes=(
                    f"local_enrolment={is_local}; "
                    f"tier_audit={tier_audit}; "
                    f"flat_local_audit={flat_local_audit}; "
                    "package/addon/priority/presales stubbed"
                ),
                audit_json={
                    "tier": tier_audit,
                    "flat_local": flat_local_audit,
                    "stub_other": True,
                },
            )
        )

    return payments
