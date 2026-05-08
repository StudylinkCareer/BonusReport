"""
Tier bonus calculation for the BonusReport engine.

Resolves the rate-card base bonus for one slot on one case by:
  1. Classifying the country bucket.
  2. Classifying the performance tier.
  3. Looking up the matching ref_rate row.
  4. Returning amount + the matched row for audit.

Per architecture.md §6.

CHANGES IN THIS REVISION (Phase 14a — DD-§I.6):
  - NEW BRANCH: is_visa_only_paid status flag → TIER_VISA_ONLY rate lookup
    in ref_rate. Fires for visa-only contracts (485 work visa, etc.) where
    fees were paid. No institution required (NULL institution_id permitted
    for these cases — adapter.py relaxes its check accordingly). Per DD-§I.6.
  - REWRITTEN BRANCH: fees_paid_non_enrolled status flag now triggers a
    proper ref_rate lookup at TIER_OUT_SYSTEM (per role/office) instead
    of the previous hardcoded 400k flat rate from
    ref_calculation_param.FEES_PAID_NON_ENROLLED_RATE. The previous
    'is_via_partner' agreement check has been DROPPED — the policy is
    that any fees-paid-non-enrolled case (in-system or out-of-system)
    pays at the OUT_SYSTEM tier rate. Per DD-§I.6.

PRESERVED FROM PRIOR REVISION:
  - Carry-over rate locking (is_carry_over + prior_month_rate).
  - CO_SUB subscheme resolution.
  - Standard tier lookup flow for all other cases.
"""

from __future__ import annotations

from datetime import date

from .classifiers import (
    BUCKET_TARGET,
    TIER_OUT_SYSTEM,
    TIER_VISA_ONLY,
    classify_country_bucket,
    classify_tier,
)
from .lookups import lookup_rate, resolve_co_sub_subscheme
from .models import CaseInput, ReferenceData, RunContext, Slot


# ---------------------------------------------------------------------------
# Helper — resolve as-of date for rate lookup
# ---------------------------------------------------------------------------

def _as_of_date(case: CaseInput) -> date:
    """
    Effective date for rate lookup is contract_signed_date per policy.
    Fall back to fee_paid_date if contract_signed_date is unset.
    Raises if neither is available.
    """
    as_of = case.contract_signed_date or case.fee_paid_date
    if as_of is None:
        raise ValueError(
            f"case_id={case.case_id} has no contract_signed_date or "
            f"fee_paid_date — cannot determine rate effective date."
        )
    return as_of


# ---------------------------------------------------------------------------
# Helper — resolve CO_SUB subscheme if applicable
# ---------------------------------------------------------------------------

def _resolve_co_sub_subscheme(
    case: CaseInput,
    slot: Slot,
    ctx: RunContext,
    ref: ReferenceData,
) -> str | None:
    """
    Resolve CO_SUB subscheme for the slot, or None if slot is not CO_SUB.
    Extracted so all branches (visa-only, fees-paid, standard) can share it.
    """
    role_row = ref.roles.get(slot.role_id, {})
    if role_row.get('code') != 'CO_SUB':
        return None
    return resolve_co_sub_subscheme(
        case,
        staff_id=slot.staff_id,
        role_id=slot.role_id,
        office_id=case.office_id,
        year=ctx.year,
        month=ctx.month,
        ref=ref,
    )


# ---------------------------------------------------------------------------
# Main calc
# ---------------------------------------------------------------------------

def calc_tier_bonus(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    ctx: RunContext,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """
    Calculate the tier (rate-card base) bonus for one slot.

    Branch order (each short-circuits):
      1. Carry-over rate lock (is_carry_over + prior_month_rate).
      2. Visa-only paid (is_visa_only_paid) → TIER_VISA_ONLY rate lookup.
      3. Fees-paid-non-enrolled → TIER_OUT_SYSTEM rate lookup.
      4. Standard tier lookup (country bucket + performance tier).

    Returns:
        (amount_dong, audit_record).
    """
    assert slot.staff_id is not None, "calc_tier_bonus called with empty slot"
    assert slot.role_id is not None, "slot has no role_id"

    # Look up the status row first — drives branching.
    status_row = ref.status_splits.get(case.status_code)

    # 1. Carry-over rate lock --------------------------------------------------
    if (status_row is not None
            and status_row.get('is_carry_over', False)
            and case.prior_month_rate is not None):
        return case.prior_month_rate, {
            'special_case': 'carry_over_rate_lock',
            'locked_rate': case.prior_month_rate,
            'reason': 'is_carry_over=Y, using case.prior_month_rate per §3.4',
        }

    # 2. Visa-only paid (NEW — DD-§I.6) ----------------------------------------
    # Triggered by ref_status_split.is_visa_only_paid = TRUE.
    # Used for visa-only contracts (485 post-grad work visa, etc.) where
    # service fees were paid. No institution required.
    if status_row is not None and status_row.get('is_visa_only_paid', False):
        as_of = _as_of_date(case)
        co_sub_subscheme = _resolve_co_sub_subscheme(case, slot, ctx, ref)
        row = lookup_rate(
            ref,
            office_id=case.office_id,
            role_id=slot.role_id,
            co_sub_subscheme=co_sub_subscheme,
            country_bucket=BUCKET_TARGET,  # visa-only rates are TARGET-bucketed
            tier=TIER_VISA_ONLY,
            as_of_date=as_of,
        )
        return row['amount'], {
            'special_case': 'visa_only_paid',
            'tier': TIER_VISA_ONLY,
            'country_bucket': BUCKET_TARGET,
            'co_sub_subscheme': co_sub_subscheme,
            'as_of_date': as_of.isoformat(),
            'rate_row_id': row.get('id'),
            'rate_amount': row['amount'],
            'reason': (
                'is_visa_only_paid=Y → TIER_VISA_ONLY rate per role/office '
                '(DD-§I.6)'
            ),
        }

    # 3. Fees-paid-non-enrolled (REWRITTEN — DD-§I.6) --------------------------
    # Triggered by ref_status_split.fees_paid_non_enrolled = TRUE.
    # Used for study-abroad cases where fees were paid but enrolment didn't
    # happen (cancelled, visa refused, etc.). Pays at OUT_SYSTEM tier rate
    # via ref_rate lookup (not the old hardcoded FEES_PAID_NON_ENROLLED_RATE
    # param, which has been retired).
    #
    # The previous 'via partner' check has been DROPPED — policy is that
    # any fees-paid-non-enrolled case pays at OUT_SYSTEM rate regardless
    # of routing.
    if status_row is not None and status_row.get('fees_paid_non_enrolled', False):
        as_of = _as_of_date(case)
        co_sub_subscheme = _resolve_co_sub_subscheme(case, slot, ctx, ref)
        row = lookup_rate(
            ref,
            office_id=case.office_id,
            role_id=slot.role_id,
            co_sub_subscheme=co_sub_subscheme,
            country_bucket=BUCKET_TARGET,
            tier=TIER_OUT_SYSTEM,
            as_of_date=as_of,
        )
        return row['amount'], {
            'special_case': 'fees_paid_non_enrolled',
            'tier': TIER_OUT_SYSTEM,
            'country_bucket': BUCKET_TARGET,
            'co_sub_subscheme': co_sub_subscheme,
            'as_of_date': as_of.isoformat(),
            'rate_row_id': row.get('id'),
            'rate_amount': row['amount'],
            'reason': (
                'fees_paid_non_enrolled=Y → TIER_OUT_SYSTEM rate per role/office '
                '(DD-§I.6)'
            ),
        }

    # 4. Standard tier lookup --------------------------------------------------
    country_bucket = classify_country_bucket(case, ref)
    tier = classify_tier(case, slot, country_bucket, ctx, ref)
    as_of = _as_of_date(case)
    co_sub_subscheme = _resolve_co_sub_subscheme(case, slot, ctx, ref)

    row = lookup_rate(
        ref,
        office_id=case.office_id,
        role_id=slot.role_id,
        co_sub_subscheme=co_sub_subscheme,
        country_bucket=country_bucket,
        tier=tier,
        as_of_date=as_of,
    )

    audit = {
        'country_bucket': country_bucket,
        'tier': tier,
        'co_sub_subscheme': co_sub_subscheme,
        'as_of_date': as_of.isoformat(),
        'rate_row_id': row.get('id'),
        'rate_amount': row['amount'],
    }
    return row['amount'], audit
