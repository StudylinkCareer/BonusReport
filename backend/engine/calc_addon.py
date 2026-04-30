"""
Add-on bonus calculation.

Stacks ON TOP of tier_bonus + package_bonus when a case carries one or
more "ADDON" service fees (e.g. multi-school enrolment, partner add-on
referrals).

Lookup table: ref_service_fee with category='ADDON'.
  counsellor_signing_bonus / co_signing_bonus → unit rate per slot
  case.addon_items                            → list of (id, count) tuples

For each addon item:
  amount_for_slot = unit_rate_for_slot × count

Slot eligibility:
  counsellor    → eligible (sums counsellor_signing_bonus × count)
  case_officer  → eligible (sums co_signing_bonus × count)
  presales / vp → not eligible (always 0)

Notes for future:
  - The current 09_SERVICE_FEE_RATES has ZERO rows in category='ADDON'.
    The schema CHECK constraint allows it, the VBA v6.2 introduced
    handling for it, but no real ADDON rows have been seeded yet. This
    calc is rails-only until that happens.
  - Multi-school cases today are still handled via SERVICE_FEE rows
    (EXTRA_SCHOOL) which fire at the tier_bonus level, not here.

Per architecture.md §6.
"""

from __future__ import annotations

from datetime import date

from .models import CaseInput, ReferenceData, Slot


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AddonServiceFeeNotFoundError(LookupError):
    """An addon_items entry references a service_fee_id not in ref."""


class AddonNotAddonCategoryError(LookupError):
    """
    An addon_items entry references a row where category != 'ADDON'.
    Surfaces upstream data bugs (e.g. someone put a PACKAGE id in
    addon_items by mistake).
    """


class AddonInactiveOrExpiredError(LookupError):
    """
    Addon row is inactive or out of effective date range.
    Surfaced as a hard error rather than a silent 0 — usually means
    stale data that someone needs to investigate.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_in_effective_range(row: dict, as_of: date) -> bool:
    if row['effective_from'] > as_of:
        return False
    if row['effective_to'] is not None and row['effective_to'] < as_of:
        return False
    return True


# ---------------------------------------------------------------------------
# Main calc
# ---------------------------------------------------------------------------

def calc_addon_bonus(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """
    Sum the addon bonuses for one slot on one case.

    Returns (amount_dong, audit_record). Amount is 0 if:
      - case.addon_items is empty
      - slot is presales or vp
      - all matched rows have a 0 unit rate for this slot

    Raises:
      AddonServiceFeeNotFoundError if an id doesn't resolve.
      AddonNotAddonCategoryError if a row's category != 'ADDON'.
      AddonInactiveOrExpiredError if a row is inactive or out of range.
    """
    # Empty list → 0 (the common case today).
    if not case.addon_items:
        return 0, {'applied': False, 'reason': 'no_addon_items'}

    # Only counsellor/CO earn from this column.
    if slot_label not in ('counsellor', 'case_officer'):
        return 0, {'applied': False, 'reason': f'slot_{slot_label}_ineligible'}

    # Effective date — same policy as tier_bonus / package_bonus.
    as_of = case.contract_signed_date or case.fee_paid_date
    if as_of is None:
        raise ValueError(
            f"case_id={case.case_id} has no contract_signed_date or "
            f"fee_paid_date — cannot determine addon effective date."
        )

    amount_column = (
        'counsellor_signing_bonus' if slot_label == 'counsellor'
        else 'co_signing_bonus'
    )

    total = 0
    items_audit: list[dict] = []

    for service_fee_id, count in case.addon_items:
        row = ref.service_fees.get(service_fee_id)
        if row is None:
            raise AddonServiceFeeNotFoundError(
                f"case_id={case.case_id} addon_items references "
                f"service_fee_id={service_fee_id} which is not in "
                f"ref.service_fees."
            )
        if row.get('category') != 'ADDON':
            raise AddonNotAddonCategoryError(
                f"case_id={case.case_id} addon_items references "
                f"service_fee_id={service_fee_id} but its category is "
                f"{row.get('category')!r}, not 'ADDON'. Did the data "
                f"layer mistakenly put a non-addon row in addon_items?"
            )
        if not row.get('is_active', True):
            raise AddonInactiveOrExpiredError(
                f"addon service_fee id={service_fee_id} is inactive."
            )
        if not _is_in_effective_range(row, as_of):
            raise AddonInactiveOrExpiredError(
                f"addon service_fee id={service_fee_id} not in effective "
                f"range for as_of_date={as_of} "
                f"(from {row.get('effective_from')} to {row.get('effective_to')})."
            )

        unit_rate = int(row.get(amount_column, 0))
        line_amount = unit_rate * int(count)
        total += line_amount

        items_audit.append({
            'service_fee_id': service_fee_id,
            'service_code': row.get('service_code'),
            'count': count,
            'unit_rate': unit_rate,
            'line_amount': line_amount,
        })

    audit = {
        'applied': True,
        'slot_amount_column': amount_column,
        'as_of_date': as_of.isoformat(),
        'items': items_audit,
        'total': total,
    }
    return total, audit
