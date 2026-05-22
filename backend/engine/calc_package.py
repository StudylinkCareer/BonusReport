"""
Package bonus calculation.

Stacks ON TOP of tier_bonus when a case carries a "PACKAGE" service fee
(e.g., AP Superior 6tr, AP Premium 9tr, Canada Standard 9.5tr).

Lookup table: ref_service_fee.
  category                   → must equal 'PACKAGE' (other rows handled
                                elsewhere: 'SERVICE_FEE' → tier_bonus
                                special tiers, 'ADDON' → future
                                addon_bonus, 'CONTRACT' → not yet
                                covered).
  counsellor_signing_bonus   → counsellor's amount, đồng
  co_signing_bonus           → case_officer's amount, đồng
  is_active                  → must be TRUE
  effective_from / _to       → must cover the case's effective date

Slot eligibility:
  counsellor (any role)             → eligible (gets counsellor_signing_bonus)
  case_officer with CO_DIR role     → eligible (gets co_signing_bonus)
  case_officer with CO_SUB role     → NOT eligible (Phase 14c business rule:
                                        packages are promoted by Counsellors
                                        and CO_DIRs only; CO_SUB staff work
                                        with sub-agents and do not earn the
                                        package signing bonus.)
  presales / vp                     → not eligible (always 0)

Payment timing:
  Counsellor's amount is "at signing", CO's is "at enrolment". Both
  have clawback rules on visa refused / cancel. Those rules belong in
  the payment-timing layer (alongside priority's 50/50 rule), NOT here.
  This calc returns the full earned amount.

Per architecture.md §6.
"""

from __future__ import annotations

from datetime import date

from .models import CaseInput, ReferenceData, Slot


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_ID_CO_SUB = 18  # dim_role.id for CO_SUB — locked


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ServiceFeeNotFoundError(LookupError):
    """case.package_service_fee_id doesn't match any row in ref.service_fees."""


class ServiceFeeInactiveOrExpiredError(LookupError):
    """
    Service fee row exists but is_active=False or out of effective range.
    Surfaced as a hard error (rather than a silent 0) because it usually
    means stale data — caller should investigate, not absorb.
    """


# ---------------------------------------------------------------------------
# Helper
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

def calc_package_bonus(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """
    Calculate the package bonus for one slot on one case.

    Returns (amount_dong, audit_record). Amount is 0 if:
      - case has no package (package_service_fee_id is None)
      - the row's category != 'PACKAGE' (it's a SERVICE_FEE / ADDON /
        CONTRACT row — handled by other calcs)
      - slot is presales or vp
      - slot is case_officer AND staff role is CO_SUB (Phase 14c rule)
      - the matched amount column is 0

    Raises:
      ServiceFeeNotFoundError if the ID doesn't resolve.
      ServiceFeeInactiveOrExpiredError if the row is inactive or
      outside its effective date range.
    """
    # No package → 0.
    if case.package_service_fee_id is None:
        return 0, {'applied': False, 'reason': 'no_package_on_case'}

    # Only counsellor/CO earn from this column.
    if slot_label not in ('counsellor', 'case_officer'):
        return 0, {'applied': False, 'reason': f'slot_{slot_label}_ineligible'}

    # CO_SUB exclusion (Phase 14c): packages are promoted by Counsellors
    # and CO_DIRs only; CO_SUB staff work with sub-agents and do not earn
    # the package signing bonus.
    if slot_label == 'case_officer' and slot.role_id == ROLE_ID_CO_SUB:
        return 0, {
            'applied': False,
            'reason': 'co_sub_ineligible_for_package',
            'role_id': slot.role_id,
        }

    # Resolve the row.
    row = ref.service_fees.get(case.package_service_fee_id)
    if row is None:
        raise ServiceFeeNotFoundError(
            f"case_id={case.case_id} references "
            f"package_service_fee_id={case.package_service_fee_id} "
            f"which is not in ref.service_fees."
        )

    # Filter to PACKAGE category only.
    if row.get('category') != 'PACKAGE':
        return 0, {
            'applied': False,
            'reason': f"row_category_{row.get('category')}_not_PACKAGE",
            'service_fee_id': case.package_service_fee_id,
        }

    # Effective date — same policy as tier_bonus.
    as_of = case.contract_signed_date or case.fee_paid_date
    if as_of is None:
        raise ValueError(
            f"case_id={case.case_id} has no contract_signed_date or "
            f"fee_paid_date — cannot determine package effective date."
        )

    if not row.get('is_active', True):
        raise ServiceFeeInactiveOrExpiredError(
            f"service_fee id={row.get('id')} is inactive."
        )
    if not _is_in_effective_range(row, as_of):
        raise ServiceFeeInactiveOrExpiredError(
            f"service_fee id={row.get('id')} not in effective range "
            f"for as_of_date={as_of} "
            f"(from {row.get('effective_from')} to {row.get('effective_to')})."
        )

    # Pick the right amount column for this slot.
    if slot_label == 'counsellor':
        amount = row.get('counsellor_signing_bonus', 0)
    else:  # case_officer (CO_DIR — CO_SUB already filtered above)
        amount = row.get('co_signing_bonus', 0)

    audit = {
        'applied': True,
        'service_fee_id': row.get('id'),
        'service_code': row.get('service_code'),
        'category': row.get('category'),
        'slot_amount_column': (
            'counsellor_signing_bonus' if slot_label == 'counsellor'
            else 'co_signing_bonus'
        ),
        'amount': amount,
        'as_of_date': as_of.isoformat(),
    }
    return int(amount), audit
