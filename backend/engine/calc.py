"""
Orchestrator for the BonusReport calculation engine.

Entry point for calculating bonus on a single case. Takes a CaseInput
plus RunContext and ReferenceData, and returns a list of BonusPayment
rows — one per filled slot.

Per-column calc functions live in their own modules:
  calc_tier.py        — tier_bonus (rate-card base)
  calc_flat_local.py  — flat_local_enrolment_bonus (VN-domestic etc.)
  calc_priority.py    — priority_bonus (uplift on tier_bonus)
  calc_package.py     — package_bonus (Superior/Premium/etc. signing bonus)
  calc_addon.py       — addon_bonus (multi-school, etc.)
  calc_presales.py    — presales_share_taken (50/50 split with counsellor)
  payment_timing.py   — status splits, deferral, clawback (Phase 6c)

Three-pass calculation:
  Pass 1: per-slot bonuses (everything except presales share).
  Pass 2: presales split — needs counsellor total from Pass 1.
  Pass 3: payment timing — splits, withholds, deferrals, clawback.

Per architecture.md §6.

CHANGES IN THIS REVISION (Phase 6c):
  - Added Pass 3: apply_payment_timing for each constructed BonusPayment.
  - BonusPayment construction now initializes timing fields to 0 / False;
    Pass 3 fills them in.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calc_addon import calc_addon_bonus
from .calc_flat_local import calc_flat_local_bonus, is_local_enrolment_case
from .calc_package import calc_package_bonus
from .calc_presales import calc_presales_share
from .calc_priority import calc_priority_bonus
from .calc_tier import calc_tier_bonus
from .models import (
    BonusPayment,
    CaseInput,
    ReferenceData,
    RunContext,
    Slot,
)
from .payment_timing import apply_payment_timing


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
# Per-slot intermediate result (Pass 1 output)
# ---------------------------------------------------------------------------

@dataclass
class _SlotResult:
    """Pass-1 buffer: everything except presales_share_taken."""
    slot_label: str
    slot: Slot
    tier: int
    package: int
    addon: int
    priority: int
    flat_local: int
    tier_audit: dict
    package_audit: dict
    addon_audit: dict
    priority_audit: dict
    flat_local_audit: dict


# ---------------------------------------------------------------------------
# Per-column calc dispatchers
# ---------------------------------------------------------------------------

def _tier_bonus(case, slot_label, slot, ctx, ref):
    return calc_tier_bonus(case, slot, slot_label, ctx, ref)


def _package_bonus(case, slot_label, slot, ref):
    return calc_package_bonus(case, slot, slot_label, ref)


def _addon_bonus(case, slot_label, slot, ref):
    return calc_addon_bonus(case, slot, slot_label, ref)


def _priority_bonus(case, slot_label, slot, tier_bonus, ctx, ref):
    return calc_priority_bonus(case, slot, slot_label, tier_bonus, ctx, ref)


def _flat_local_enrolment_bonus(case, slot_label, slot, ref):
    return calc_flat_local_bonus(case, slot, slot_label, ref)


def _advance_offset(case: CaseInput, slot_label: str, slot: Slot) -> int:
    """
    D1.R12 — subtract amounts already paid to this person on this case
    in prior months. Pure lookup on CaseInput, no ref data needed.
    """
    if slot.staff_id is None:
        return 0
    return case.prior_payments_by_slot.get((slot_label, slot.staff_id), 0)


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

    Returns one BonusPayment per filled slot, with all six gross columns
    plus payment-timing fields (withheld, unlocked, clawback, etc.) populated.
    """
    is_local = is_local_enrolment_case(case, ref)

    # ----- PASS 1: per-slot bonuses (everything except presales share) -----
    pass1: list[_SlotResult] = []

    for slot_label, slot in _iter_filled_slots(case):
        # Per-slot routing for VN-domestic cases:
        # COUNS_DIR / CO_DIR slots → ref_local_enrolment_bonus (skip tier).
        # CO_SUB slots → ref_rate VN_*/FLAT bucket (run tier, skip flat_local).
        # The local-bonus rate card is keyed on counsellor-pairing patterns,
        # and sub-agent COs sit outside that schema. ref_rate has dedicated
        # VN_RMIT/VN_BUV/VN_OTHER/SUMMER rows for CO_SUB (subscheme-keyed)
        # — those are the right path for sub-agent local enrolments.
        role_code = ref.roles.get(slot.role_id, {}).get('code') if slot.role_id else None
        use_flat_local_path = is_local and role_code != 'CO_SUB'

        if use_flat_local_path:
            tier = 0
            tier_audit = {
                'applied': False,
                'reason': 'local_enrolment_case_uses_flat_local',
            }
        else:
            tier, tier_audit = _tier_bonus(case, slot_label, slot, ctx, ref)

        package, package_audit = _package_bonus(case, slot_label, slot, ref)
        addon, addon_audit = _addon_bonus(case, slot_label, slot, ref)
        priority, priority_audit = _priority_bonus(
            case, slot_label, slot, tier, ctx, ref,
        )
        flat_local, flat_local_audit = _flat_local_enrolment_bonus(
            case, slot_label, slot, ref,
        )

        pass1.append(_SlotResult(
            slot_label=slot_label, slot=slot,
            tier=tier, package=package, addon=addon,
            priority=priority, flat_local=flat_local,
            tier_audit=tier_audit, package_audit=package_audit,
            addon_audit=addon_audit, priority_audit=priority_audit,
            flat_local_audit=flat_local_audit,
        ))

    # ----- PASS 2: counsellor total → presales split -----
    counsellor_total_bonus = 0
    for r in pass1:
        if r.slot_label == 'counsellor':
            counsellor_total_bonus = (
                r.tier + r.package + r.addon + r.priority + r.flat_local
            )
            break

    # ----- Build pre-timing BonusPayments, then apply Pass 3 -----
    payments: list[BonusPayment] = []
    for r in pass1:
        presales_share, presales_audit = calc_presales_share(
            case, r.slot, r.slot_label, counsellor_total_bonus,
        )

        gross_pre_share = r.tier + r.package + r.addon + r.priority + r.flat_local
        gross = gross_pre_share - presales_share
        offset = _advance_offset(case, r.slot_label, r.slot)

        assert r.slot.staff_id is not None  # filtered by _iter_filled_slots

        # Pre-timing BonusPayment: gross calculated, timing fields zeroed.
        # Pass 3 (apply_payment_timing) fills in the timing fields and
        # computes net_payable with all timing rules applied.
        pre_timing = BonusPayment(
            case_id=case.case_id,
            staff_id=r.slot.staff_id,
            staff_name=r.slot.staff_name or "",
            role_id=r.slot.role_id or 0,
            slot_label=r.slot_label,
            tier_bonus=r.tier,
            package_bonus=r.package,
            addon_bonus=r.addon,
            priority_bonus=r.priority,
            presales_share_taken=presales_share,
            flat_local_enrolment_bonus=r.flat_local,
            advance_offset=offset,
            gross_bonus=gross,
            # Timing fields — Pass 3 fills these in.
            withheld_amount=0,
            unlocked_amount=0,
            clawback_applied=0,
            bank_transfer_required=False,
            net_payable=0,  # Pass 3 computes this
            calc_notes=(
                f"local_enrolment={is_local}; "
                f"tier={r.tier}; "
                f"package={r.package} ({r.package_audit.get('reason') or r.package_audit.get('service_code')}); "
                f"addon={r.addon} ({r.addon_audit.get('reason') or 'sum of items'}); "
                f"priority={r.priority} ({r.priority_audit.get('reason') or r.priority_audit.get('partner_name')}); "
                f"flat_local={r.flat_local}; "
                f"presales_share={presales_share} ({presales_audit.get('reason') or presales_audit.get('sign_meaning')})"
            ),
            audit_json={
                "tier": r.tier_audit,
                "package": r.package_audit,
                "addon": r.addon_audit,
                "priority": r.priority_audit,
                "flat_local": r.flat_local_audit,
                "presales": presales_audit,
            },
        )

        # ----- PASS 3: apply payment timing -----
        final = apply_payment_timing(case, pre_timing, ctx, ref)
        payments.append(final)

    return payments
