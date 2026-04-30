"""
Flat local enrolment bonus calculation.

Handles the per-country flat-rate path for domestic enrolments
(e.g., VN 1,000,000đ per enrolment). Cases that route through this
column do NOT also earn tier_bonus — the orchestrator must zero
tier_bonus for these cases.

Lookup table: ref_local_enrolment_bonus.
  country_id              → match
  flat_total_amount       → đồng amount for the whole case
  couns_dir_alone_pct     → counsellor share when solo (default 1.000)
  couns_dir_with_co_pct   → counsellor share when paired (default 0.500)
  co_pct_when_paired      → CO share when paired (default 0.500)
  effective_from / _to    → date range filter

Slot eligibility:
  counsellor    → eligible (split depends on whether CO is filled)
  case_officer  → eligible only when paired with counsellor
  presales / vp → not eligible (always 0 from this column)

Per architecture.md §6.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import CaseInput, ReferenceData, Slot


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LocalBonusNotFoundError(LookupError):
    """No ref_local_enrolment_bonus row matches country_id + date."""


class AmbiguousLocalBonusError(LookupError):
    """More than one ref_local_enrolment_bonus row matches — schema bug."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lookup_local_bonus_row(
    ref: ReferenceData,
    country_id: int,
    as_of_date: date,
) -> dict:
    """
    Find the single ref_local_enrolment_bonus row for this country
    whose effective range covers as_of_date.

    Mirrors lookup_rate's pattern: linear scan, raise on miss/ambig.
    """
    matches: list[dict] = []
    # ReferenceData doesn't yet have a `local_enrolment_bonuses` field;
    # the data layer will add one. Until then, we accept it via a
    # generic dict on ref to avoid blocking the engine work. This will
    # be tightened when the data layer materialises.
    rows = getattr(ref, 'local_enrolment_bonuses', {})
    for row in rows.values():
        if row['country_id'] != country_id:
            continue
        if row['effective_from'] > as_of_date:
            continue
        if row['effective_to'] is not None and row['effective_to'] < as_of_date:
            continue
        matches.append(row)

    if not matches:
        raise LocalBonusNotFoundError(
            f"No ref_local_enrolment_bonus row for country_id={country_id}, "
            f"as_of_date={as_of_date}."
        )
    if len(matches) > 1:
        raise AmbiguousLocalBonusError(
            f"{len(matches)} ref_local_enrolment_bonus rows match "
            f"country_id={country_id}, as_of_date={as_of_date}. "
            f"UNIQUE constraint should prevent this — schema bug."
        )
    return matches[0]


def is_local_enrolment_case(case: CaseInput, ref: ReferenceData) -> bool:
    """
    True if this case should be paid via ref_local_enrolment_bonus
    instead of ref_rate.

    Today: any case whose country is the VN-domestic row (i.e.,
    is_domestic_for is set on dim_country). Easy to extend later if
    other countries gain domestic flat-rate treatment.
    """
    country = ref.countries.get(case.country_id)
    if country is None:
        return False
    return country.get('is_domestic_for') is not None


# ---------------------------------------------------------------------------
# Main calc
# ---------------------------------------------------------------------------

def calc_flat_local_bonus(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    ref: ReferenceData,
) -> tuple[int, dict]:
    """
    Calculate the flat local enrolment bonus for one slot on one case.

    Returns (amount_dong, audit_record). Amount is 0 if:
      - case is not a local-enrolment case
      - slot is not counsellor or case_officer
      - slot is case_officer but no counsellor is filled

    Audit record always populated; caller folds it into BonusPayment.audit_json.
    """
    # Quick exit if not a local-enrolment case.
    if not is_local_enrolment_case(case, ref):
        return 0, {'applied': False, 'reason': 'not_local_enrolment_case'}

    # Only counsellor and case_officer earn from this column.
    if slot_label not in ('counsellor', 'case_officer'):
        return 0, {'applied': False, 'reason': f'slot_{slot_label}_ineligible'}

    # Effective date — same policy as tier_bonus.
    as_of = case.contract_signed_date or case.fee_paid_date
    if as_of is None:
        raise ValueError(
            f"case_id={case.case_id} has no contract_signed_date or "
            f"fee_paid_date — cannot determine local-bonus effective date."
        )

    # Look up the row.
    row = _lookup_local_bonus_row(ref, case.country_id, as_of)
    flat_total = row['flat_total_amount']
    co_filled = case.case_officer.staff_id is not None
    couns_filled = case.counsellor.staff_id is not None

    # Determine the share for this slot.
    if slot_label == 'counsellor':
        if co_filled:
            pct = Decimal(str(row['couns_dir_with_co_pct']))
            mode = 'paired_with_co'
        else:
            pct = Decimal(str(row['couns_dir_alone_pct']))
            mode = 'solo'
    else:  # case_officer
        if not couns_filled:
            # CO without a counsellor — undefined by the rate card.
            # Pay 0 and flag for review rather than guess.
            return 0, {
                'applied': False,
                'reason': 'co_without_counsellor_undefined',
                'row_id': row.get('id'),
            }
        pct = Decimal(str(row['co_pct_when_paired']))
        mode = 'paired_with_counsellor'

    amount = int(Decimal(flat_total) * pct)

    audit = {
        'applied': True,
        'mode': mode,
        'row_id': row.get('id'),
        'flat_total_amount': flat_total,
        'pct_applied': str(pct),
        'as_of_date': as_of.isoformat(),
    }
    return amount, audit
