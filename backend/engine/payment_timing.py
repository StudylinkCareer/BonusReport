"""
Payment timing layer for the BonusReport engine.

Sits between gross calculation (calc_tier + calc_package + calc_addon +
calc_priority + calc_flat_local + calc_presales) and the final
BonusPayment.net_payable. Applies four sets of rules in order:

  1. ref_status_split percentages — how much of gross is payable this run
     (e.g. Current-Enrolled CO gets 50% now, 50% deferred)
  2. Carry-over release — if status flags is_carry_over=Y, this run is
     paying out a prior run's withheld amount
  3. §I.6.4 6-month deferral — if staff has resigned, hold all bonus
     until 6 months past resignation_date
  4. §I.5.3 retrospective clawback — apply running clawback balance
     against this month's payable; flag for bank transfer if balance
     can't be fully offset

Decision 1 (confirmed): fees_paid_non_enrolled lives in calc_tier.py
(not here). By the time gross arrives at this layer, the 400k flat-fee
rate has already been applied to tier_bonus where applicable.

Decision 2 (confirmed): CO_DIR vs CO_SUB selection is by the slot's
role_id, NOT by case.referring_sub_agent_id. CO_DIR and CO_SUB never
share a bonus on the same case — the three split columns in
ref_status_split are independent percentages, where exactly one applies
per slot based on the staff's role.

Decision 3 (confirmed): Full scope — includes deferral and clawback.

Per architecture.md §6 and POLICY_MODEL.md Chunks 3, 10, 11.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import BonusPayment, CaseInput, ReferenceData, RunContext


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class StatusSplitNotFoundError(LookupError):
    """case.status_code doesn't match any row in ref.status_splits."""


class StaffNotFoundError(LookupError):
    """payment.staff_id doesn't match any row in ref.staff. Data layer bug."""


class RoleCodeNotFoundError(LookupError):
    """payment.role_id doesn't match any row in ref.roles."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _months_between(earlier: date, later: date) -> int:
    """
    Number of complete months between two dates.

    Used for §I.6.4: bonus releases when run-month is >= resignation+6 months.
    A staff who resigns 2024-09-15 has bonuses payable from 2025-03-01 onwards.
    """
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _resolve_split_pct(
    slot_label: str,
    role_code: str,
    status_row: dict,
) -> Decimal:
    """
    Pick the right split percentage column from a ref_status_split row.

    Three columns exist: split_couns_pct, split_co_dir_pct, split_co_sub_pct.
    Per Decision 2, the column is selected by the slot's role:
      counsellor   → split_couns_pct
      CO_DIR       → split_co_dir_pct
      CO_SUB       → split_co_sub_pct
      presales/vp  → not applicable, return 1.0 (full payment, no status gating)
    """
    if slot_label == 'counsellor':
        return Decimal(str(status_row['split_couns_pct']))
    if slot_label == 'case_officer':
        if role_code == 'CO_SUB':
            return Decimal(str(status_row['split_co_sub_pct']))
        # CO_DIR (or any other CO role variant)
        return Decimal(str(status_row['split_co_dir_pct']))
    # presales / vp — status splits don't apply
    return Decimal('1.0')


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_payment_timing(
    case: CaseInput,
    payment_in: BonusPayment,
    ctx: RunContext,
    ref: ReferenceData,
) -> BonusPayment:
    """
    Apply all four payment-timing rules to a gross-only BonusPayment.

    Args:
        case:        The CaseInput (drives status lookup, prior-payment data).
        payment_in:  A BonusPayment with gross_bonus computed and timing
                     fields all zeroed. Pre-timing version produced by calc.py.
        ctx:         RunContext (clawback balances, prior withholdings).
        ref:         ReferenceData (status splits, staff, roles).

    Returns:
        A new BonusPayment with timing fields populated and net_payable
        correctly computed.

    Order of operations:
        1. Look up status row, handle is_zero_bonus
        2. Apply split percentage → base_payable
        3. Compute withheld (is_current_enrolled withholds the rest)
        4. Compute unlocked (is_carry_over releases prior month's withholding)
        5. Apply §I.6.4 6-month deferral (if staff resigned)
        6. Apply §I.5.3 clawback against base_payable
        7. Compute net_payable
    """
    # 1. Status row lookup -----------------------------------------------------
    status_row = ref.status_splits.get(case.status_code)
    if status_row is None:
        raise StatusSplitNotFoundError(
            f"case_id={case.case_id} status_code={case.status_code!r} "
            f"has no row in ref.status_splits."
        )

    timing_audit: dict = {
        'status_code': case.status_code,
        'status_flags': {
            'is_zero_bonus': status_row.get('is_zero_bonus', False),
            'is_carry_over': status_row.get('is_carry_over', False),
            'is_current_enrolled': status_row.get('is_current_enrolled', False),
            'fees_paid_non_enrolled': status_row.get('fees_paid_non_enrolled', False),
        },
    }

    # Zero-bonus shortcut — return everything zeroed.
    if status_row.get('is_zero_bonus', False):
        timing_audit['outcome'] = 'is_zero_bonus_no_payment'
        return _zeroed_payment(payment_in, timing_audit, calc_notes_extra=(
            f"Zero bonus per ref_status_split (status={case.status_code})."
        ))

    # 2. Resolve role + apply split percentage --------------------------------
    role_row = ref.roles.get(payment_in.role_id)
    if role_row is None:
        raise RoleCodeNotFoundError(
            f"payment.role_id={payment_in.role_id} not in ref.roles."
        )
    role_code = role_row.get('code', '')

    split_pct = _resolve_split_pct(payment_in.slot_label, role_code, status_row)
    base_payable = int(Decimal(payment_in.gross_bonus) * split_pct)
    withheld_from_split = payment_in.gross_bonus - base_payable

    timing_audit['split_pct'] = str(split_pct)
    timing_audit['role_code'] = role_code
    timing_audit['base_payable_after_split'] = base_payable

    # 3. Withholding ----------------------------------------------------------
    # If status is "Current - Enrolled" (is_current_enrolled=Y), the portion
    # not paid this month is withheld for next month (when visa is granted
    # and status moves to "Closed - Enrolled, then Visa granted").
    withheld = 0
    if status_row.get('is_current_enrolled', False):
        withheld = withheld_from_split
        timing_audit['withheld_reason'] = 'is_current_enrolled'

    # 4. Carry-over unlock ----------------------------------------------------
    # If status is "Closed - Enrolled, then Visa granted" (is_carry_over=Y),
    # the prior month already paid Counsellor 100% / CO 50%. THIS month's
    # gross_bonus represents the remaining portion. We expose the prior
    # withheld amount as "unlocked" for finance reporting.
    unlocked = 0
    if status_row.get('is_carry_over', False):
        unlocked = ctx.prior_withholdings_by_case_staff.get(
            (payment_in.case_id, payment_in.staff_id), 0
        )
        timing_audit['unlocked_from_prior'] = unlocked

    # 5. §I.6.4 6-month deferral ---------------------------------------------
    deferred_until = None
    deferred_this_run = False
    staff_row = ref.staff.get(payment_in.staff_id)
    if staff_row is None:
        raise StaffNotFoundError(
            f"payment.staff_id={payment_in.staff_id} not in ref.staff."
        )
    resignation_date = staff_row.get('departure_date')
    if resignation_date is not None:
        run_start = date(ctx.year, ctx.month, 1)
        months_since = _months_between(resignation_date, run_start)
        if months_since < 6:
            # All payable amounts deferred until 6 months past resignation
            withheld += base_payable
            base_payable = 0
            deferred_until = date(
                resignation_date.year + (resignation_date.month + 6 - 1) // 12,
                ((resignation_date.month + 6 - 1) % 12) + 1,
                1,
            )
            deferred_this_run = True
            timing_audit['deferral'] = {
                'rule': 'I.6.4_post_resignation_6_month_hold',
                'resignation_date': resignation_date.isoformat(),
                'months_since_resignation': months_since,
                'released_after': deferred_until.isoformat(),
            }

    # 6. §I.5.3 clawback ------------------------------------------------------
    clawback_balance_in = ctx.clawback_balances_by_staff.get(payment_in.staff_id, 0)
    clawback_applied = min(clawback_balance_in, base_payable)
    bank_transfer_required = False

    if clawback_balance_in > 0:
        new_balance = clawback_balance_in - clawback_applied
        if new_balance > 0 and base_payable == 0:
            # No bonus available to offset — flag bank transfer
            bank_transfer_required = True
        timing_audit['clawback'] = {
            'rule': 'I.5.3_retrospective_clawback',
            'balance_in': clawback_balance_in,
            'applied_this_run': clawback_applied,
            'balance_carry_forward': new_balance,
            'bank_transfer_required': bank_transfer_required,
        }

    # 7. Net payable ----------------------------------------------------------
    net_payable = (
        base_payable
        - clawback_applied
        - payment_in.advance_offset
        + unlocked
    )
    # Note: withheld_amount is NOT subtracted here — it's already excluded
    # from base_payable via the split_pct calculation. We track it
    # separately for finance audit and to drive prior_withholdings on the
    # next run.

    timing_audit['final'] = {
        'net_payable': net_payable,
        'withheld_amount': withheld,
        'unlocked_amount': unlocked,
        'clawback_applied': clawback_applied,
        'deferred_this_run': deferred_this_run,
    }

    # 8. Build the output payment ---------------------------------------------
    new_audit = dict(payment_in.audit_json)
    new_audit['payment_timing'] = timing_audit

    notes_extras = []
    if deferred_this_run:
        notes_extras.append(
            f"Deferred §I.6.4 (resigned {resignation_date}, releases {deferred_until})"
        )
    if status_row.get('is_current_enrolled'):
        notes_extras.append(f"Withheld {withheld:,} via is_current_enrolled")
    if status_row.get('is_carry_over') and unlocked:
        notes_extras.append(f"Released {unlocked:,} from prior carry-over")
    if clawback_applied:
        notes_extras.append(
            f"Clawback applied {clawback_applied:,} (§I.5.3, balance was {clawback_balance_in:,})"
        )
    if bank_transfer_required:
        notes_extras.append("Bank transfer required — clawback exceeds available bonus")

    extra_note = " | ".join(notes_extras)
    new_calc_notes = (
        f"{payment_in.calc_notes} | {extra_note}" if extra_note
        else payment_in.calc_notes
    )

    return BonusPayment(
        case_id=payment_in.case_id,
        staff_id=payment_in.staff_id,
        staff_name=payment_in.staff_name,
        role_id=payment_in.role_id,
        slot_label=payment_in.slot_label,
        tier_bonus=payment_in.tier_bonus,
        package_bonus=payment_in.package_bonus,
        addon_bonus=payment_in.addon_bonus,
        priority_bonus=payment_in.priority_bonus,
        presales_share_taken=payment_in.presales_share_taken,
        flat_local_enrolment_bonus=payment_in.flat_local_enrolment_bonus,
        advance_offset=payment_in.advance_offset,
        gross_bonus=payment_in.gross_bonus,
        # Timing fields
        withheld_amount=withheld,
        unlocked_amount=unlocked,
        clawback_applied=clawback_applied,
        bank_transfer_required=bank_transfer_required,
        net_payable=net_payable,
        # Audit
        calc_notes=new_calc_notes,
        audit_json=new_audit,
    )


def _zeroed_payment(
    payment_in: BonusPayment,
    timing_audit: dict,
    calc_notes_extra: str,
) -> BonusPayment:
    """Return a BonusPayment with all amounts zero — used for is_zero_bonus."""
    new_audit = dict(payment_in.audit_json)
    new_audit['payment_timing'] = timing_audit
    return BonusPayment(
        case_id=payment_in.case_id,
        staff_id=payment_in.staff_id,
        staff_name=payment_in.staff_name,
        role_id=payment_in.role_id,
        slot_label=payment_in.slot_label,
        tier_bonus=0,
        package_bonus=0,
        addon_bonus=0,
        priority_bonus=0,
        presales_share_taken=0,
        flat_local_enrolment_bonus=0,
        advance_offset=0,
        gross_bonus=0,
        withheld_amount=0,
        unlocked_amount=0,
        clawback_applied=0,
        bank_transfer_required=False,
        net_payable=0,
        calc_notes=f"{payment_in.calc_notes} | {calc_notes_extra}",
        audit_json=new_audit,
    )
