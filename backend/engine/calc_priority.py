"""
Priority List bonus calculation — at-enrolment half (Reading Y).

# Formula

    priority_bonus = tier_bonus × bonus_pct × 0.5

Where:
  bonus_pct  → from ref_priority_target.bonus_pct, or
               junction.bonus_pct_override if the junction row carries
               a per-institution promotional rate
  0.5        → the "at-enrolment half" — half the full priority
               entitlement, paid unconditionally when a student
               enrols at a priority partner.

# Two halves of priority — Reading Y

Per Priority_2024_final_v2.pdf footnote:
  "Individual bonus paid 50% at enrolment, 50% after KPI reached
   for each partner"

Two independent payment triggers:

  At-enrolment 50% (THIS MODULE)
    Pays for every enrolment at a priority partner, regardless of
    whether the partner KPI is ever reached during the year.
    Calculated and paid case-by-case, in the month the case enrols.

  Post-KPI 50% (separate year-end module — not yet built)
    Pays at year-end for partners whose annual KPI was reached.
    For partners whose KPI was NOT reached, the at-enrolment half
    paid throughout the year is clawed back via the existing
    company clawback procedure.

The at-enrolment half here is therefore PROVISIONAL: it pays now,
on expectation that KPI will be reached. If KPI is missed by year-end,
year-end logic will reverse it.

# Effectivity date

Priority lookup uses the run period (date(ctx.year, ctx.month, 1)),
not the contract signing date. Priority is structurally annual —
bonus_pct, targets, and YTD buckets are all keyed by year. A contract
signed late in year N enrolling in N+1 should be rated at year N+1's
priority terms.

# Status splits do NOT apply to priority

Per §3 of the main policy, Current-Enrolled cases have tier bonus
withheld 50/50 (50% at enrolment, 50% at visa). Priority is exempt:
it has its own payment timing structure (50/50 at enrolment / KPI),
not visa-contingent. payment_timing.py handles the exemption by
splitting gross_bonus into a "splittable" portion (everything else)
and a "passthrough" portion (priority).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import CaseInput, ReferenceData, RunContext, Slot


# ---------------------------------------------------------------------------
# Role → channel mapping
# ---------------------------------------------------------------------------

_DIRECT_ROLE_CODES = frozenset({'COUNS_DIR', 'CO_DIR'})
_SUB_ROLE_CODES = frozenset({'CO_SUB'})


# At-enrolment fraction. The other 50% is the post-KPI half, paid by
# year-end logic if the partner KPI is reached, or clawed back otherwise.
_AT_ENROLMENT_FRACTION = Decimal('0.5')


def _role_channel(role_code: str | None) -> str | None:
    """
    Map a role code to the channel it counts toward.

    Returns 'direct', 'sub', or None (slot doesn't earn priority).
    Year-end logic uses the recorded channel to decide which target
    the case counted toward when checking KPI achievement.
    """
    if role_code in _DIRECT_ROLE_CODES:
        return 'direct'
    if role_code in _SUB_ROLE_CODES:
        return 'sub'
    return None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PriorityListNotFoundError(LookupError):
    """A junction row points to a priority_list_id that doesn't exist."""


class PriorityTargetNotFoundError(LookupError):
    """A priority list has no active ref_priority_target row at the run period."""


# ---------------------------------------------------------------------------
# Junction membership helpers
# ---------------------------------------------------------------------------

def _active_at(row: dict, as_of: date) -> bool:
    """True if row's effective range covers as_of."""
    if row.get('effective_from') is not None and row['effective_from'] > as_of:
        return False
    if row.get('effective_to') is not None and row['effective_to'] < as_of:
        return False
    return True


def _resolve_junction(
    institution_id: int,
    case_date: date,
    ref: ReferenceData,
) -> tuple[dict | None, str]:
    """
    Find the active priority-list junction row for an institution.

    Returns (junction_row, reason_tag).
    """
    matches = [
        jct for jct in ref.priority_list_institutions.values()
        if jct['institution_id'] == institution_id
        and _active_at(jct, case_date)
    ]

    if not matches:
        return None, 'not_priority'
    if len(matches) == 1:
        return matches[0], 'single_match'

    non_agg = []
    for jct in matches:
        list_row = ref.priority_lists.get(jct['priority_list_id'])
        if list_row is not None and not list_row.get('is_aggregate', False):
            non_agg.append(jct)

    if len(non_agg) == 1:
        return non_agg[0], 'preferred_non_aggregate'
    if len(non_agg) > 1:
        return non_agg[0], 'first_of_many_non_aggregate'

    return matches[0], 'first_of_many_aggregate'


def _lookup_active_target(
    ref: ReferenceData,
    priority_list_id: int,
    as_of: date,
) -> dict:
    """Find the active ref_priority_target row for a list at a date."""
    matches = [
        row for row in ref.priority_targets.values()
        if row['priority_list_id'] == priority_list_id
        and _active_at(row, as_of)
    ]
    if not matches:
        raise PriorityTargetNotFoundError(
            f"No active ref_priority_target for priority_list_id={priority_list_id} "
            f"at {as_of.isoformat()}."
        )
    if len(matches) > 1:
        matches.sort(key=lambda r: r['effective_from'], reverse=True)
    return matches[0]


# ---------------------------------------------------------------------------
# Main calc — at-enrolment half (Reading Y)
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
    Calculate the at-enrolment 50% priority bonus for one slot on one case.

    Pays unconditionally for any priority-eligible case at a priority
    partner. No threshold gate — KPI achievement governs only the
    SECOND half (post-KPI), handled by separate year-end logic.

    Returns (amount, audit). Audit always includes enough to let
    year-end logic reverse or top up this case.
    """
    if tier_bonus == 0:
        return 0, {'applied': False, 'reason': 'tier_bonus_zero'}

    institution = ref.institutions.get(case.institution_id)
    if institution is None:
        return 0, {'applied': False, 'reason': 'institution_not_found'}

    role_code = ref.roles.get(slot.role_id, {}).get('code') if slot.role_id else None
    channel = _role_channel(role_code)
    if channel is None:
        return 0, {
            'applied': False,
            'reason': 'role_not_priority_eligible',
            'role_code': role_code,
        }

    # Priority effectivity = run period (annual semantics).
    case_date = date(ctx.year, ctx.month, 1)

    jct, jct_reason = _resolve_junction(case.institution_id, case_date, ref)
    if jct is None:
        return 0, {'applied': False, 'reason': 'institution_not_priority'}

    list_id = jct['priority_list_id']
    list_row = ref.priority_lists.get(list_id)
    if list_row is None:
        raise PriorityListNotFoundError(
            f"institution_id={case.institution_id} junction (id={jct.get('id')}) "
            f"points to priority_list_id={list_id}, but no row exists in "
            f"ref.priority_lists. Data integrity bug."
        )

    target_row = _lookup_active_target(ref, list_id, case_date)

    # Effective bonus_pct: junction override wins.
    if jct.get('bonus_pct_override') is not None:
        bonus_pct = Decimal(str(jct['bonus_pct_override']))
        bonus_pct_source = 'junction_override'
    else:
        bonus_pct = Decimal(str(target_row['bonus_pct']))
        bonus_pct_source = 'list_target'

    if bonus_pct == 0:
        return 0, {
            'applied': False,
            'reason': 'bonus_pct_zero',
            'list_id': list_id,
            'list_name': list_row.get('canonical_name'),
            'bonus_pct_source': bonus_pct_source,
            'junction_resolution': jct_reason,
            'role_code': role_code,
            'channel': channel,
        }

    amount = int(Decimal(tier_bonus) * bonus_pct * _AT_ENROLMENT_FRACTION)

    audit = {
        'applied': True,
        # Identification — year-end logic uses these to find this row.
        'list_id': list_id,
        'list_name': list_row.get('canonical_name'),
        'is_aggregate': list_row.get('is_aggregate'),
        'group_id': list_row.get('group_id'),
        'junction_id': jct.get('id'),
        'junction_resolution': jct_reason,
        # Channel that this case counted toward (year-end checks the
        # corresponding channel target for KPI achievement).
        'role_code': role_code,
        'channel': channel,
        # Pricing inputs — used to recompute or clawback.
        'tier_bonus_input': tier_bonus,
        'bonus_pct': str(bonus_pct),
        'bonus_pct_source': bonus_pct_source,
        'at_enrolment_fraction': str(_AT_ENROLMENT_FRACTION),
        # KPI status at time of payment — informational. Year-end logic
        # re-evaluates against final-year YTD, doesn't trust this snapshot.
        'kpi_status_at_payment': 'pending_year_end',
        'half_kind': 'at_enrolment',
        'case_date': case_date.isoformat(),
        'case_date_source': 'run_period',
    }
    return amount, audit
