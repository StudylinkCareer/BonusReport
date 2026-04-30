"""
Priority partner bonus calculation.

Formula (per VBA_modCalc and 01_POLICY_SUMMARY in the engine workbook):

    priority_bonus = tier_bonus × bonus_pct × achievement_factor

Where:
  bonus_pct          → annual % from ref_priority_target for the run year
  achievement_factor → 1.0 if YTD enrolments ≥ annual target, else 0.5

Institution → priority partner is via either:
  - ref_institution.priority_partner_id           (direct match, e.g. Monash)
  - ref_institution.aggregate_priority_partner_id (bucket, e.g. "Other Navitas AU")

If the institution has neither, the case is not a priority case and
priority_bonus is 0. If bonus_pct is 0 for the year (all of 2025), the
result is 0 — but the lookup still runs to give an audit trail.

The 50%-at-enrolment / 50%-at-KPI-achievement payment-timing rule lives
in the payment timing layer, not here. This calc returns the *full*
annual amount the case has earned given current achievement.

Per architecture.md §6.
"""

from __future__ import annotations

from decimal import Decimal

from .models import CaseInput, ReferenceData, RunContext, Slot


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PriorityPartnerNotFoundError(LookupError):
    """
    The institution refers to a priority_partner_id (or aggregate_id)
    that doesn't exist in ref.priority_partners. Means data is broken
    upstream.
    """


class PriorityTargetNotFoundError(LookupError):
    """
    A priority partner exists but has no ref_priority_target row for
    ctx.year. Most likely a data-load gap — the calc can't proceed
    without knowing the partner's annual target and bonus_pct.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_priority_partner_id(institution: dict) -> tuple[int | None, str | None]:
    """
    Returns (priority_partner_id, link_kind) for the institution.

    link_kind is 'direct' if matched via priority_partner_id, 'aggregate'
    if matched via aggregate_priority_partner_id, or None if neither.
    The direct link wins if both are set (shouldn't happen in clean
    data, but we choose the more specific link).
    """
    direct = institution.get('priority_partner_id')
    if direct is not None:
        return direct, 'direct'
    aggregate = institution.get('aggregate_priority_partner_id')
    if aggregate is not None:
        return aggregate, 'aggregate'
    return None, None


def _lookup_priority_target(
    ref: ReferenceData,
    priority_partner_id: int,
    year: int,
) -> dict:
    """
    Find the single ref_priority_target row for (partner, year).

    Schema's UNIQUE (priority_partner_id, year) constraint guarantees
    at most one row, so we don't bother with an ambiguity check.
    """
    for row in ref.priority_targets.values():
        if row['priority_partner_id'] != priority_partner_id:
            continue
        if row['year'] != year:
            continue
        return row
    raise PriorityTargetNotFoundError(
        f"No ref_priority_target for partner_id={priority_partner_id}, "
        f"year={year}."
    )


def _achievement_factor(ytd_enrolments: int, annual_target: int) -> Decimal:
    """1.0 if hit, 0.5 otherwise. Decimal for clean arithmetic."""
    if ytd_enrolments >= annual_target:
        return Decimal('1.0')
    return Decimal('0.5')


# ---------------------------------------------------------------------------
# Main calc
# ---------------------------------------------------------------------------

def calc_priority_bonus(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    tier_bonus: int,
    ctx: RunContext,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """
    Calculate the priority partner bonus for one slot on one case.

    Args:
        case:        CaseInput.
        slot:        Filled slot (staff_id is not None).
        slot_label:  'counsellor' | 'case_officer' | 'presales' | 'vp'.
                     Currently unused — every filled slot earns priority
                     proportionally to its tier_bonus. Kept for symmetry
                     with other calc_* signatures.
        tier_bonus:  The slot's tier_bonus amount, in đồng. Caller must
                     pass this in — priority is multiplicative on top.
        ctx:         RunContext (drives YTD enrolments and run year).
        ref:         ReferenceData snapshot.

    Returns:
        (amount_dong, audit_record). Amount is 0 if the institution
        isn't a priority partner, or if bonus_pct is 0 for the year.
        Audit record always populated.
    """
    # If there's no tier_bonus, priority is also 0 (multiplicative).
    if tier_bonus == 0:
        return 0, {'applied': False, 'reason': 'tier_bonus_zero'}

    # Resolve institution → priority partner.
    institution = ref.institutions.get(case.institution_id)
    if institution is None:
        return 0, {'applied': False, 'reason': 'institution_not_found'}

    partner_id, link_kind = _resolve_priority_partner_id(institution)
    if partner_id is None:
        return 0, {'applied': False, 'reason': 'institution_not_priority'}

    partner = ref.priority_partners.get(partner_id)
    if partner is None:
        raise PriorityPartnerNotFoundError(
            f"institution_id={case.institution_id} links to "
            f"priority_partner_id={partner_id} (via {link_kind}), but no "
            f"row exists in ref.priority_partners. Data integrity bug."
        )

    # Look up the annual target + bonus_pct for the run year.
    target_row = _lookup_priority_target(ref, partner_id, ctx.year)
    bonus_pct = Decimal(str(target_row['bonus_pct']))
    annual_target = target_row['total_target']

    # Short-circuit when bonus_pct is 0 (e.g. all of 2025).
    if bonus_pct == 0:
        return 0, {
            'applied': False,
            'reason': 'bonus_pct_zero',
            'partner_id': partner_id,
            'partner_name': partner.get('name'),
            'link_kind': link_kind,
            'year': ctx.year,
        }

    # Achievement factor based on YTD enrolments for this partner.
    ytd = ctx.enrolments_by_priority_partner_ytd.get(partner_id, 0)
    af = _achievement_factor(ytd, annual_target)

    amount = int(Decimal(tier_bonus) * bonus_pct * af)

    audit = {
        'applied': True,
        'partner_id': partner_id,
        'partner_name': partner.get('name'),
        'link_kind': link_kind,
        'year': ctx.year,
        'bonus_pct': str(bonus_pct),
        'annual_target': annual_target,
        'ytd_enrolments': ytd,
        'achievement_factor': str(af),
        'tier_bonus_input': tier_bonus,
    }
    return amount, audit
