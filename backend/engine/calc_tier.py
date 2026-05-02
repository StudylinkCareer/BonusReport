"""
Tier bonus calculation for the BonusReport engine.

Resolves the rate-card base bonus for one slot on one case by:
  1. Classifying the country bucket.
  2. Classifying the performance tier.
  3. Looking up the matching ref_rate row.
  4. Returning amount + the matched row for audit.

Per architecture.md §6.

CHANGES IN THIS REVISION (Phase 6c):
  - Carry-over rate locking: when ref_status_split.is_carry_over=Y AND
    case.prior_month_rate is set, return the locked rate instead of doing
    a fresh ref_rate lookup. Per Q3.4 (POLICY_MODEL.md Chunk 3): the rate
    used for the deferred CO 50% is the rate from the original enrolment
    month, not the rate at payment month.
  - Fees-paid-non-enrolled override: when ref_status_split.fees_paid_non_enrolled=Y
    AND the institution is OUT_SYSTEM_MA / OUT_SYSTEM_GROUP, use the
    400k flat-fee rate (read from ref_calculation_param) instead of
    the standard rate. Per Decision 1.
"""

from __future__ import annotations

from .classifiers import classify_country_bucket, classify_tier
from .lookups import lookup_rate
from .models import CaseInput, ReferenceData, RunContext, Slot


# Calculation parameter code for the fees-paid-non-enrolled flat rate.
# Read from ref_calculation_param at runtime; default 400_000 if absent.
FEES_PAID_NON_ENROLLED_PARAM_CODE = 'FEES_PAID_NON_ENROLLED_RATE'
FEES_PAID_NON_ENROLLED_DEFAULT = 400_000

# Institution classifications that trigger the fees-paid-non-enrolled rate.
_FEES_PAID_INSTITUTION_CLASSIFICATIONS = frozenset({
    'OUT_SYSTEM_MASTER_AGENT',
    'OUT_SYSTEM_GROUP',
})


def calc_tier_bonus(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    ctx: RunContext,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """
    Calculate the tier (rate-card base) bonus for one slot.

    Args:
        case:        CaseInput.
        slot:        Filled slot (staff_id is not None).
        slot_label:  'counsellor' | 'case_officer' | 'presales' | 'vp'.
        ctx:         RunContext.
        ref:         ReferenceData snapshot.

    Returns:
        (amount_dong, audit_record).

    Notes:
        - Effective date for rate lookup is contract_signed_date per
          policy. If a case has no contract_signed_date set we fall
          back to fee_paid_date; this is rare but defensive.
        - co_sub_subscheme is None today. When sub-agent CO bonuses are
          implemented (item 3 from post-Phase-6 backlog), this function
          will pass the right scheme based on slot.role_id.
    """
    assert slot.staff_id is not None, "calc_tier_bonus called with empty slot"
    assert slot.role_id is not None, "slot has no role_id"

    # Look up the status row first — it may force special-case behaviour.
    status_row = ref.status_splits.get(case.status_code)

    # Carry-over rate lock (Phase 6c) ----------------------------------------
    # Per Q3.4 (POLICY_MODEL.md Chunk 3): when a case is in carry-over status
    # (prior month already paid the enrolment portion, this month pays the
    # deferred visa-grant portion), the rate is locked to the original
    # enrolment month. The data layer populates case.prior_month_rate when
    # carrying a case forward; we use it directly here.
    if (status_row is not None
            and status_row.get('is_carry_over', False)
            and case.prior_month_rate is not None):
        return case.prior_month_rate, {
            'special_case': 'carry_over_rate_lock',
            'locked_rate': case.prior_month_rate,
            'reason': 'is_carry_over=Y, using case.prior_month_rate per §3.4',
        }

    # Fees-paid-non-enrolled override (Phase 6c, Decision 1) -----------------
    # Per ref_status_split: certain "Closed" statuses with fees collected but
    # no enrolment trigger a 400k flat rate for OUT_SYSTEM_MA / OUT_SYSTEM_GROUP
    # institutions. The flag is on the status row; the rate is in
    # ref_calculation_param.
    if (status_row is not None
            and status_row.get('fees_paid_non_enrolled', False)):
        institution = ref.institutions.get(case.institution_id, {})
        institution_class = institution.get('classification', '')
        if institution_class in _FEES_PAID_INSTITUTION_CLASSIFICATIONS:
            param = ref.calculation_params.get(FEES_PAID_NON_ENROLLED_PARAM_CODE, {})
            flat_rate = int(param.get('value_numeric', FEES_PAID_NON_ENROLLED_DEFAULT))
            return flat_rate, {
                'special_case': 'fees_paid_non_enrolled',
                'flat_rate': flat_rate,
                'institution_classification': institution_class,
                'reason': (
                    f"fees_paid_non_enrolled=Y for {institution_class} → "
                    f"{flat_rate:,}đ flat (Decision 1)"
                ),
            }

    # Standard tier lookup ---------------------------------------------------
    country_bucket = classify_country_bucket(case, ref)
    tier = classify_tier(case, slot, country_bucket, ctx, ref)

    as_of = case.contract_signed_date or case.fee_paid_date
    if as_of is None:
        raise ValueError(
            f"case_id={case.case_id} has no contract_signed_date or "
            f"fee_paid_date — cannot determine rate effective date."
        )

    row = lookup_rate(
        ref,
        office_id=case.office_id,
        role_id=slot.role_id,
        co_sub_subscheme=None,  # TODO: item 3 — sub-agent CO scheme
        country_bucket=country_bucket,
        tier=tier,
        as_of_date=as_of,
    )

    audit = {
        'country_bucket': country_bucket,
        'tier': tier,
        'as_of_date': as_of.isoformat(),
        'rate_row_id': row.get('id'),
        'rate_amount': row['amount'],
    }
    return row['amount'], audit
