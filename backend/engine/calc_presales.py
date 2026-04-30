"""
Pre-sales bonus calculation.

Rule (per StudyLink policy):
  When the presales slot is filled, the presales agent receives 50% of
  the TOTAL bonus the counsellor would have earned if presales were
  not involved — i.e. tier + package + priority + addon + flat_local
  combined. The counsellor keeps the other 50%.

  This applies whether presales and counsellor are different people
  (the standard "presales opens, counsellor closes" pattern) or the
  same person (the case where the presales agent also closed the
  deal). When both slots reference the same staff_id, the math
  naturally produces 100% to that person — no special case needed.

  CO bonus is NOT affected. Only counsellor-side earnings are split.

Architectural model:
  In the engine output, this manifests as TWO bookkeeping changes:
    Counsellor row : presales_share_taken = +half  (subtracted from gross)
    Presales row   : presales_share_taken = -half  (added to gross,
                     since presales has no other earning columns)

  presales_share_taken sign convention:
    POSITIVE = subtracted from gross (counsellor giving up their share)
    NEGATIVE = added to gross (presales receiving)

  The orchestrator computes:
    gross = tier + package + addon + priority + flat_local - presales_share_taken
  so the sign convention works out for both slots.

  presales_share_pct on CaseInput overrides the default 50% if needed
  (some legacy cases use different splits).

Per architecture.md §6.
"""

from __future__ import annotations

from decimal import Decimal

from .models import CaseInput, Slot


def _is_presales_active(case: CaseInput) -> bool:
    """
    True iff both the counsellor and presales slots are filled.

    Empty counsellor with filled presales is undefined by policy and
    treated as inactive — see audit reason 'presales_without_counsellor_undefined'.
    """
    counsellor_filled = case.counsellor.staff_id is not None
    presales_filled = case.presales.staff_id is not None
    return counsellor_filled and presales_filled


def calc_presales_share(
    case: CaseInput,
    slot: Slot,
    slot_label: str,
    counsellor_total_bonus: int,
) -> tuple[int, dict]:
    """
    Compute the presales_share_taken value for one slot.

    Args:
        case:                    CaseInput.
        slot:                    The slot being computed.
        slot_label:              'counsellor' / 'case_officer' / 'presales' / 'vp'.
        counsellor_total_bonus:  The counsellor's full earnings BEFORE
                                 the presales split — sum of tier +
                                 package + priority + addon + flat_local
                                 as the counsellor would have received
                                 had no presales been involved.
                                 Caller (orchestrator) computes and
                                 passes this in.

    Returns:
        (share_amount, audit_record).

        Sign convention:
          POSITIVE → subtracted from this slot's gross
          NEGATIVE → added to this slot's gross (received)
          ZERO     → not applicable for this slot

        Specifically:
          counsellor: returns +half if presales is active, else 0
          presales:   returns -half if presales is active, else 0
          case_officer / vp: always 0 (presales doesn't affect them)
    """
    # If this slot isn't counsellor or presales, no effect.
    if slot_label not in ('counsellor', 'presales'):
        return 0, {'applied': False, 'reason': f'slot_{slot_label}_not_in_split'}

    # If presales is not active on this case, no effect.
    if not _is_presales_active(case):
        if case.presales.staff_id is None:
            reason = 'no_presales_on_case'
        elif case.counsellor.staff_id is None:
            reason = 'presales_without_counsellor_undefined'
        else:
            reason = 'presales_inactive'
        return 0, {'applied': False, 'reason': reason}

    # Honour presales_share_pct from CaseInput (default 50% per policy).
    pct = case.presales_share_pct
    if pct == 0:
        return 0, {
            'applied': False,
            'reason': 'presales_share_pct_zero',
        }

    # Apply pct to the counsellor's TOTAL bonus.
    share = int(Decimal(counsellor_total_bonus) * pct)

    if slot_label == 'counsellor':
        amount = share
        sign_meaning = 'subtracted_from_gross'
    else:  # presales
        amount = -share
        sign_meaning = 'received_into_gross'

    audit = {
        'applied': True,
        'pct': str(pct),
        'counsellor_total_bonus': counsellor_total_bonus,
        'half_amount': share,
        'sign_meaning': sign_meaning,
        'presales_staff_id': case.presales.staff_id,
        'presales_staff_name': case.presales.staff_name,
        'counsellor_staff_id': case.counsellor.staff_id,
        'same_person': (
            case.counsellor.staff_id == case.presales.staff_id
        ),
    }
    return amount, audit
