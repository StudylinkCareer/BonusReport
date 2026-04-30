"""
Tier bonus calculation for the BonusReport engine.

Resolves the rate-card base bonus for one slot on one case by:
  1. Classifying the country bucket.
  2. Classifying the performance tier.
  3. Looking up the matching ref_rate row.
  4. Returning amount + the matched row for audit.

Per architecture.md §6.
"""

from __future__ import annotations

from .classifiers import classify_country_bucket, classify_tier
from .lookups import lookup_rate
from .models import CaseInput, ReferenceData, RunContext, Slot


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
                     Currently unused inside this function but accepted
                     for symmetry with other calc_* functions and for
                     future per-slot rule variations.
        ctx:         RunContext.
        ref:         ReferenceData snapshot.

    Returns:
        (amount_dong, audit_record) where:
          amount_dong:  the bonus amount in đồng (int).
          audit_record: dict capturing the lookup keys used and the
                        ref_rate row matched. Caller folds this into
                        BonusPayment.audit_json for full traceability.

    Notes:
        - Effective date for rate lookup is contract_signed_date per
          policy. If a case has no contract_signed_date set we fall
          back to fee_paid_date; this is rare but defensive.
        - co_sub_subscheme is None today. When sub-agent CO bonuses are
          implemented, this function will be split or extended to pass
          the right scheme based on referring_sub_agent_id.
    """
    assert slot.staff_id is not None, "calc_tier_bonus called with empty slot"
    assert slot.role_id is not None, "slot has no role_id"

    # Classify the bucket and tier.
    country_bucket = classify_country_bucket(case, ref)
    tier = classify_tier(case, slot, country_bucket, ctx, ref)

    # Effective date — contract_signed_date is the policy answer.
    as_of = case.contract_signed_date or case.fee_paid_date
    if as_of is None:
        raise ValueError(
            f"case_id={case.case_id} has no contract_signed_date or "
            f"fee_paid_date — cannot determine rate effective date."
        )

    # Look up the rate row.
    row = lookup_rate(
        ref,
        office_id=case.office_id,
        role_id=slot.role_id,
        co_sub_subscheme=None,  # TODO: sub-agent CO scheme support
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
