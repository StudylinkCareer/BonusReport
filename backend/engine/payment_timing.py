"""
Payment timing layer for the BonusReport engine.

Sits between gross calculation (calc_tier + calc_package + calc_addon +
calc_priority + calc_flat_local + calc_presales) and the final
BonusPayment.net_payable. Applies five sets of rules in order:

  1. ref_status_split percentages — how much of gross is payable this run
     (e.g. Current-Enrolled CO gets 50% now, 50% deferred). PRIORITY IS
     EXEMPT FROM THE STANDARD STATUS SPLIT — see "Priority exemption"
     below.
  2. Carry-over: when is_carry_over=Y, the unlocked prior withholding
     (BOTH splittable and priority halves where applicable) is the
     entire payment for this month. STRICT MODE for the data-gap case.
     SAME-MONTH ENROL+VISA is detected via course_start_date and paid
     at 100% (see "Same-month carry-over" below).
  3. Priority schedule decision (Phase 12b) — for cases at priority
     partners where the year's priority group has rule_type
     CURRENT_ENROL_25_25_50, defer half the at-enrolment priority to
     the visa-receipt month if the case is Current-Enrolled and the
     institution's quota has not yet been met. STANDARD_50_50 (current
     2024 behavior) is the default; the SPLIT branch only fires when
     the rule is explicitly active for the priority group.
  4. §I.6.4 6-month deferral — if staff has resigned, hold all bonus
     until 6 months past resignation_date.
  5. §I.5.3 retrospective clawback — apply running clawback balance
     against this month's payable; flag for bank transfer if balance
     can't be fully offset.

Decision 1 (confirmed): fees_paid_non_enrolled lives in calc_tier.py
(not here). By the time gross arrives at this layer, the 400k flat-fee
rate has already been applied to tier_bonus where applicable.

Decision 2 (confirmed): CO_DIR vs CO_SUB selection is by the slot's
role_id, NOT by case.referring_sub_agent_id. CO_DIR and CO_SUB never
share a bonus on the same case — the three split columns in
ref_status_split are independent percentages, where exactly one applies
per slot based on the staff's role.

Decision 3 (confirmed): Full scope — includes deferral and clawback.

Decision 4 (added 2026-05-05 then ROLLED BACK): A "future-enrolment
deferral" was briefly added as step 5b. The 80-file scan revealed that
this deferral is correctly handled by the status code itself —
bare "Closed - Visa granted" (id=57) should be flagged is_zero_bonus
in the data layer rather than special-cased in code. Patch5 applies
that data fix.

Decision 5 (added 2026-05-05): Carry-over supersede in STRICT mode for
the data-gap case. When is_carry_over=true fires AND a contract was
expected to have a prior withhold but none is tracked, payment is held
at 0 with a CARRY_OVER_NO_PRIOR warning. Rationale: over-payment
recovery from staff is operationally fragile and emotionally costly;
under-payment with a visible warning is the safer default.

Decision 6 (added 2026-05-07): Same-month enrol+visa carry-over.
Bao cao evidence shows that when a case enrols AND gets visa within
the same month, the case appears once with status "Closed - Enrolled,
then Visa granted" and is paid the FULL tier in that single month —
NOT the 50% the carry-over factors would imply. The conceptual model
(per RP): 'carry-over = 100% - already_paid'. Same-month case has
already_paid=0, so carry-over = 100% (full payment this month).

Detection: course_start_date is in the current run-month → genuinely
same-month. In that case base_payable becomes the full splittable_gross
(treating the case like a Closed-Enrolment / full-pay status for this
one month). The split_pct that was already applied to splittable_payable
is overridden.

The data-gap case (contract appeared in a prior month with
Current-Enrolled status but no withhold tracked) still falls under
STRICT mode and pays 0 with the warning. This protects against
double-payment when M1 history is missing.

Decision 7 (added 2026-05-20, DD-OUT_SYSTEM_SPLIT_BYPASS): OUT_SYSTEM
tier cases bypass the ref_status_split percentages and pay the full
tier_bonus in the run-month. Applies regardless of role (Counsellor,
CO_DIR, CO_SUB). The OUT_SYSTEM rate (Section A col 1 — Counsellor 600k
/ CO 400k; Section B col 1 — CO_SUB 400k fixed) represents
payment-for-work-completed at first appearance, not a placeholder
expecting in-system follow-up stages. For CO_SUB partner-routed cases
specifically, the visa work belongs to the partner agent — there is no
future StudyLink-side event to release a deferred half, so applying the
50/50 split would strand half the bonus. Detection: read
payment_in.audit_json['tier']['tier'] (set by calc_tier.py). When it
equals 'OUT_SYSTEM', force split_pct = 1.0 before computing
splittable_payable. The withheld_amount logic in step 3 then
short-circuits naturally because withheld_from_split = 0.

# Priority exemption (Reading Y, added 2026-05-07)

Priority bonus has its own payment-timing structure per the
Priority_2024 footnote: "Individual bonus paid 50% at enrolment, 50%
after KPI reached for each partner". The at-enrolment half is paid
unconditionally when a student enrols at a priority partner; the
post-KPI half is gated on (total_company_target AND individual_team_target)
both being met at year-end.

Implementation: split gross into a "splittable" portion
(tier + package + addon + flat_local + presales_share) and a
"passthrough" portion (priority). Apply split_pct only to the
splittable portion; add priority back in at full value (under
STANDARD_50_50) or at half value with the other half deferred (under
SPLIT_25_25_50 — see Phase 12b below).

Same-month carry-over also pays priority at full (consistent with the
splittable being paid at full).

# Row-level priority semantics (Phase 12c, 2026-05-07)

calc_priority computes a gross priority_bonus for every priority-eligible
case (full at-enrolment entitlement). Through the timing layer this
gross value can end up partially or fully unpaid:
  - Carry-over branch (a) multi-month release: base_payable zeroed,
    only priority_unlocked is paid (typically 0 under STANDARD_50_50)
  - Carry-over branch (c) STRICT-zero data-gap: nothing paid
  - SPLIT_25_25_50 first-pay: only the at-enrolment 25% paid now
  - §I.6.4 6-month deferral: everything moved to withheld

The output BonusPayment.priority_bonus column is rewritten in step 7.5
below to reflect priority **paid this month**, not the gross. This
aligns row-level reporting with bao cao "Priority bonus" column
semantics (which records actual payment) and removes regression-tool
noise on carry-over cases.

audit_json['payment_timing']['priority_passthrough'] preserves the
gross value for audit trail purposes.

# Phase 12b — Priority 25/25/50 split rule (added 2026-05-07)

ref_priority_group rows now carry priority_split_rule_type:
  - STANDARD_50_50 (default): 50% at enrolment + 50% at year-end KPI.
    Existing behavior, used by all 2024 priority groups.
  - CURRENT_ENROL_25_25_50: For Current-Enrolled cases at priority
    institutions where the institution's quota has NOT been met,
    defer half the at-enrolment priority bonus to the visa-receipt
    month. Effectively: 25% at enrolment + 25% at visa+file-closure +
    50% at year-end.

The SPLIT decision is locked at first-pay (priority_schedule_type
column on tx_bonus_payment). If quota state changes between enrolment
and visa, the case stays on its original schedule.

The quota tracker (tx_priority_quota_tracker / ctx.priority_quota_state)
is incremented for every priority-partner enrolment in years where the
rule is active, regardless of whether SPLIT applies to that specific
case. This keeps the count accurate so the WITHIN_QUOTA check is
meaningful for subsequent cases. Increment is once per case_id (the
seen_priority_case_ids set dedups across multiple slot rows for the
same case) and only on the case's first appearance (carry-over
re-appearances do NOT re-increment, but same-month enrol+visa cases DO).

Channel (direct vs sub) for the increment is determined by
case.referring_sub_agent_id (sub if non-null, direct otherwise) — NOT
by slot role.

The carry-over (a) multi-month-release branch additionally releases
ctx.prior_priority_withholdings_by_contract_staff[(contract_id, staff_id)]
when present.

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


def _is_same_month_enrol_visa(case: CaseInput, run_year: int, run_month: int) -> bool:
    """
    Detect the genuinely same-month enrol+visa case (Decision 6).

    Returns True when the course_start_date is in the current run-month —
    meaning this is the first month we're seeing this contract. The
    carry-over status fires because visa also came this month, but there
    was never a prior Current-Enrolled month to withhold from.

    Returns False when course_start_date is in a prior month (or year),
    which means we'd expect a prior withhold to release. If that prior
    withhold isn't tracked, the data-gap path holds payment at 0.

    Returns False when course_start_date is None — can't determine,
    fall back to STRICT mode for safety.
    """
    csd = case.course_start_date
    if csd is None:
        return False
    return csd.year == run_year and csd.month == run_month


def _resolve_priority_quota_status(
    institution_id: int,
    run_year: int,
    run_month: int,
    ref: ReferenceData,
    ctx: RunContext,
) -> dict | None:
    """
    Determine the priority quota status for a case at a given institution.

    Walks the ref tables in memory:
      institution_id → ref_priority_list_institution (effective-date filtered)
                     → ref_priority_list
                     → ref_priority_group (carries priority_split_rule_type)

    Returns None if the institution has no active priority list entry —
    the engine should treat the case as a non-priority enrolment with no
    quota tracking and standard payment timing.

    Returns a dict when a priority entry IS active. The 'within_quota'
    flag reflects state BEFORE this case's increment is applied; callers
    use it to decide whether SPLIT applies, then increment if appropriate.

    The ref dicts are loaded once per run by ref_loaders. The walk is
    O(n) over priority_list_institutions because we don't have a reverse
    index — fine for the row counts in play (sub-100), and the engine
    runs are not hot-path. Index later if it shows up in profiling.
    """
    run_date = date(run_year, run_month, 1)

    # 1. Find the active ref_priority_list_institution row(s) for this institution
    candidates = []
    for pli in ref.priority_list_institutions.values():
        if pli['institution_id'] != institution_id:
            continue
        eff_from = pli['effective_from']
        eff_to = pli['effective_to']
        if eff_from > run_date:
            continue
        if eff_to is not None and eff_to <= run_date:
            continue
        candidates.append(pli)

    if not candidates:
        return None

    # If multiple active rows, pick the most recent effective_from
    # (defensive: there shouldn't normally be overlapping active rows for
    # the same institution).
    pli = max(candidates, key=lambda p: p['effective_from'])

    # 2. Walk to the parent list and group
    plist = ref.priority_lists.get(pli['priority_list_id'])
    if plist is None:
        return None
    pgroup = ref.priority_groups.get(plist['group_id'])
    if pgroup is None:
        return None

    rule_type = pgroup.get('priority_split_rule_type', 'STANDARD_50_50')

    # 3. Compute target total (sum of per-institution direct + sub targets)
    target_direct = pli.get('institution_target_direct') or 0
    target_sub = pli.get('institution_target_sub') or 0
    target_total = target_direct + target_sub

    # 4. Read current count from in-memory tracker state
    tracker = ctx.priority_quota_state.get(pli['id'], {})
    count_direct = tracker.get('count_direct', 0)
    count_sub = tracker.get('count_sub', 0)
    count_total = count_direct + count_sub

    return {
        'rule_type': rule_type,
        'priority_list_institution_id': pli['id'],
        'priority_list_id': plist['id'],
        'priority_group_id': pgroup['id'],
        'institution_target_direct': target_direct,
        'institution_target_sub': target_sub,
        'institution_target_total': target_total,
        'count_direct_now': count_direct,
        'count_sub_now': count_sub,
        'count_total_now': count_total,
        # within_quota uses total target as the gate per the policy text;
        # if target_total is 0 (unset) treat as not-applicable (False).
        'within_quota': (target_total > 0 and count_total < target_total),
    }


def _channel_for_case(case: CaseInput) -> str:
    """
    Return 'sub' if the case came via a sub-agent, 'direct' otherwise.

    Used to bucket the priority quota tracker increment. Determined by
    case.referring_sub_agent_id, not by slot role — the channel is a
    property of the case, not the staff member working on it.
    """
    return 'sub' if case.referring_sub_agent_id is not None else 'direct'


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
    Apply all payment-timing rules to a gross-only BonusPayment.

    Args:
        case:        The CaseInput (drives status lookup, prior-payment data).
        payment_in:  A BonusPayment with gross_bonus computed and timing
                     fields all zeroed. Pre-timing version produced by calc.py.
        ctx:         RunContext (clawback balances, prior withholdings,
                     priority quota state).
        ref:         ReferenceData (status splits, staff, roles, priority
                     group/list/institution structure).

    Returns:
        A new BonusPayment with timing fields populated and net_payable
        correctly computed.

    Order of operations:
        1.   Look up status row, handle is_zero_bonus
        2.   Apply split percentage → base_payable (PRIORITY EXEMPT)
        3.   Compute splittable withheld (is_current_enrolled withholds the rest)
        3.5  Phase 12b: Priority schedule decision + tracker increment
        4.   Carry-over: three sub-cases (release prior / same-month full / strict-zero)
        5.   Apply §I.6.4 6-month deferral (if staff resigned)
        6.   Apply §I.5.3 clawback against base_payable
        7.   Compute net_payable
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
    #
    # EXCEPTION: when the case carries a confirmed service-fee earning
    # (addon_bonus > 0), the zero-bonus shortcut is SKIPPED. Service
    # fees are paid for work that was completed (visa renewal, guardian
    # change, etc.) even when the underlying study contract produced no
    # enrolment commission. The zero-bonus rule applies to tier/package/
    # priority earnings, not to ancillary service-fee earnings.
    #
    # In this branch the engine continues through the normal timing flow.
    # tier_bonus/package_bonus/priority_bonus are already 0 (the calc
    # modules saw the same status and didn't pay them), so net_payable
    # naturally lands at the addon_bonus amount.
    if status_row.get('is_zero_bonus', False):
        if payment_in.addon_bonus > 0:
            timing_audit['zero_bonus_bypass'] = (
                'addon_bonus_present_service_fee_path'
            )
            # Fall through to the normal timing flow below.
        else:
            timing_audit['outcome'] = 'is_zero_bonus_no_payment'
            return _zeroed_payment(payment_in, timing_audit, calc_notes_extra=(
                f"Zero bonus per ref_status_split (status={case.status_code})."
            ), ctx=ctx)

    # 2. Resolve role + apply split percentage --------------------------------
    role_row = ref.roles.get(payment_in.role_id)
    if role_row is None:
        raise RoleCodeNotFoundError(
            f"payment.role_id={payment_in.role_id} not in ref.roles."
        )
    role_code = role_row.get('code', '')

    split_pct = _resolve_split_pct(payment_in.slot_label, role_code, status_row)

    # OUT_SYSTEM tier bypass (Decision 7, DD-OUT_SYSTEM_SPLIT_BYPASS):
    # OUT_SYSTEM tier rates represent payment for work completed at the
    # case's first appearance — not a placeholder expecting later
    # in-system stages to release the remainder. There is no future
    # visa-receipt event to trigger the deferred half (for CO_SUB
    # partner-routed cases the visa work belongs to the partner; for
    # Counsellor+CO out-system cases the work is paid as a one-shot
    # OUT_SYSTEM rate). Force split_pct = 1.0 so the full tier_bonus
    # is paid this run. The withheld_amount block in step 3 then
    # short-circuits naturally because withheld_from_split = 0.
    #
    # Detection reads payment_in.audit_json['tier']['tier'] (set by
    # calc_tier.py). The audit dict is always populated for non-zeroed
    # payments; defensive .get() chain handles unexpected structure.
    is_out_system_tier = (
        payment_in.audit_json.get('tier', {}).get('tier') == 'OUT_SYSTEM'
    )
    if is_out_system_tier and split_pct != Decimal('1.0'):
        timing_audit['out_system_split_bypass'] = {
            'original_split_pct': str(split_pct),
            'reason': (
                'OUT_SYSTEM tier bypasses status-split per '
                'DD-OUT_SYSTEM_SPLIT_BYPASS (Decision 7)'
            ),
        }
        split_pct = Decimal('1.0')

    # Reading Y: priority is exempt from status splits. It has its own
    # payment-timing structure (50% at enrolment / 50% post-KPI), independent
    # of visa-contingent §3 splits. Apply split_pct only to the splittable
    # portion (tier + package + addon + flat_local - presales_share);
    # priority passes through at full value here. Step 3.5 may later halve
    # the priority portion under the SPLIT_25_25_50 rule.
    #
    # gross_bonus already accounts for presales_share (it was subtracted in
    # calc.py when constructing pre_timing). So gross_bonus - priority_bonus
    # gives the splittable portion correctly.
    priority_passthrough = payment_in.priority_bonus
    splittable_gross = payment_in.gross_bonus - priority_passthrough
    splittable_payable = int(Decimal(splittable_gross) * split_pct)
    base_payable = splittable_payable + priority_passthrough
    withheld_from_split = splittable_gross - splittable_payable

    timing_audit['split_pct'] = str(split_pct)
    timing_audit['role_code'] = role_code
    timing_audit['priority_passthrough'] = priority_passthrough
    timing_audit['splittable_gross'] = splittable_gross
    timing_audit['splittable_payable'] = splittable_payable
    timing_audit['base_payable_after_split'] = base_payable

    # 3. Splittable withholding -----------------------------------------------
    # If status is "Current - Enrolled" (is_current_enrolled=Y), the portion
    # of the SPLITTABLE gross not paid this month is withheld for next month
    # (when visa is granted and status moves to "Closed - Enrolled, then
    # Visa granted"). Priority withholding is handled separately in step 3.5.
    #
    # Note: when the OUT_SYSTEM bypass fired above, split_pct is 1.0 and
    # withheld_from_split is 0. The status flag may still be
    # is_current_enrolled=True, but with no actual withholding the audit
    # note is suppressed to avoid misleading entries.
    withheld = 0
    if status_row.get('is_current_enrolled', False):
        withheld = withheld_from_split
        if withheld > 0:
            timing_audit['withheld_reason'] = 'is_current_enrolled'

    # 3.5 Priority schedule decision (Phase 12b) ------------------------------
    # Walk the priority structure to determine if this case is at a priority
    # partner and, if so, which payment schedule applies. Increment the
    # in-memory quota tracker for first-appearance priority cases when the
    # rule is active for the case's year — regardless of whether SPLIT
    # actually applies to this specific case (so the count stays accurate).
    priority_withheld = 0
    priority_schedule_type = 'STANDARD'
    priority_quota_audit: dict | None = None

    if priority_passthrough > 0:
        quota_status = _resolve_priority_quota_status(
            case.institution_id, ctx.year, ctx.month, ref, ctx,
        )
        if quota_status is not None:
            priority_quota_audit = dict(quota_status)
            rule_active = (quota_status['rule_type'] == 'CURRENT_ENROL_25_25_50')

            # Determine if this is a "first appearance" of the case for
            # quota counting purposes. Carry-over re-appearances (visa
            # receipt month for an earlier Current-Enrolled case) MUST NOT
            # double-count — but same-month enrol+visa cases DO count
            # (they're the first and only appearance of that contract).
            is_first_appearance = (
                not status_row.get('is_carry_over', False)
                or _is_same_month_enrol_visa(case, ctx.year, ctx.month)
            )

            # Increment tracker once per case_id, only when the rule is
            # active for the year, only on first appearance.
            if (
                rule_active
                and is_first_appearance
                and case.case_id not in ctx.seen_priority_case_ids
            ):
                pli_id = quota_status['priority_list_institution_id']
                channel = _channel_for_case(case)
                tracker = ctx.priority_quota_state.setdefault(pli_id, {
                    'count_direct': 0,
                    'count_sub': 0,
                })
                if channel == 'sub':
                    tracker['count_sub'] = tracker.get('count_sub', 0) + 1
                else:
                    tracker['count_direct'] = tracker.get('count_direct', 0) + 1
                ctx.seen_priority_case_ids.add(case.case_id)
                priority_quota_audit['tracker_incremented'] = True
                priority_quota_audit['channel'] = channel
                priority_quota_audit['tracker_after'] = dict(tracker)

            # SPLIT decision: only for Current-Enrolled cases where the
            # quota was NOT met before this case's increment. Carry-over
            # cases (including same-month) skip this — they pay full
            # priority in step 4.
            if (
                rule_active
                and quota_status['within_quota']
                and status_row.get('is_current_enrolled', False)
                and not status_row.get('is_carry_over', False)
            ):
                # SPLIT applies. Halve priority_passthrough — pay 50% of
                # the at-enrolment portion now (= 25% of total entitlement),
                # withhold the other 50% (= 25% of total) until visa
                # receipt. The rest of the standard 50% structure (year-end
                # release of the second 50% of total) is handled by the
                # year-end finalizer, not here.
                priority_now = priority_passthrough // 2  # 25% of total
                priority_withheld = priority_passthrough - priority_now
                priority_schedule_type = 'SPLIT_25_25_50'
                # Replace the full priority in base_payable with just the
                # half being paid now.
                base_payable = splittable_payable + priority_now
                priority_quota_audit['split_applied'] = True
                priority_quota_audit['priority_full'] = priority_passthrough
                priority_quota_audit['priority_now'] = priority_now
                priority_quota_audit['priority_withheld'] = priority_withheld
            else:
                priority_quota_audit['split_applied'] = False

    if priority_quota_audit is not None:
        timing_audit['priority_schedule'] = priority_quota_audit

    # 4. Carry-over (three sub-cases) ----------------------------------------
    # Conceptual model (per RP, 2026-05-07):
    #   carry-over component = 100% - already_paid
    #
    # Three possibilities when is_carry_over fires:
    #
    # (a) Multi-month split: contract was paid 50% in a prior month
    #     (Current-Enrolled). Prior withhold IS tracked. Release it; the
    #     unlocked withhold IS the payment for this month. STRICT supersede:
    #     base_payable is zeroed because the split_pct factor (typically
    #     0.5 for carry-over status) would otherwise produce a duplicate
    #     half-payment alongside the unlocked half.
    #
    #     Phase 12b: ALSO release any prior priority withhold for this
    #     (contract_id, staff_id) — the deferred 25% from a SPLIT_25_25_50
    #     case at first-pay. priority_unlocked is added to net_payable
    #     in step 7.
    #
    # (b) Same-month enrol+visa: contract is appearing for the first time
    #     (course_start_date is in the current run-month). No prior
    #     withhold expected. Pay 100% of splittable + 100% of priority,
    #     same as if the case had status "Closed - Enrolment". Override
    #     the split_pct that step 2 applied — for this case it's wrong.
    #
    # (c) Data-gap: contract appeared in a prior month but no withhold
    #     was tracked (M1 history missing, or import bug). STRICT mode:
    #     hold payment at 0 and surface CARRY_OVER_NO_PRIOR warning.
    #     Operations resolves by re-importing prior months or manually
    #     triggering payment.
    #
    # Phase 7 carry-over key fix: lookup is by (contract_id, staff_id),
    # not (case_id, staff_id). tx_case has a different case_id row for
    # every (contract, run_year, run_month) tuple.
    unlocked = 0
    priority_unlocked = 0
    carry_over_no_prior_warning = False
    same_month_full_payment = False
    if status_row.get('is_carry_over', False):
        unlocked = ctx.prior_withholdings_by_contract_staff.get(
            (case.contract_id, payment_in.staff_id), 0
        )
        timing_audit['unlocked_from_prior'] = unlocked

        if unlocked > 0:
            # (a) Multi-month split — release the withhold, zero the base
            base_payable = 0
            timing_audit['carry_over'] = (
                'multi_month_release: unlocked prior withhold, base zeroed'
            )

            # Phase 12b: also release prior priority withhold if any
            priority_unlocked = ctx.prior_priority_withholdings_by_contract_staff.get(
                (case.contract_id, payment_in.staff_id), 0
            )
            if priority_unlocked > 0:
                timing_audit['priority_unlocked_from_prior'] = priority_unlocked
        elif _is_same_month_enrol_visa(case, ctx.year, ctx.month):
            # (b) Same-month enrol+visa — pay full splittable + full priority
            #
            # Override the split_pct factor that step 2 applied. The
            # case is paying its entire 100% in this single month
            # (carry-over component = 100% - 100% = 0%).
            base_payable = splittable_gross + priority_passthrough
            same_month_full_payment = True
            timing_audit['carry_over'] = (
                'same_month_enrol_visa: full payment (splittable+priority), '
                'split_pct override'
            )
            timing_audit['split_pct_override'] = '1.0'
            timing_audit['base_payable_after_carry_override'] = base_payable
            # No withhold for same-month case (everything paid this month)
            withheld = 0
            # Same-month case never has a prior priority withhold to release
            # (it didn't exist before this run), so priority_unlocked stays 0.
            # The priority_withheld stays 0 too (set above) — full priority
            # is paid via priority_passthrough already in base_payable.
        else:
            # (c) Data-gap — STRICT zero, surface warning
            base_payable = 0
            carry_over_no_prior_warning = True
            timing_audit['carry_over'] = (
                'data_gap_strict_zero: no prior withhold tracked, course_start '
                'predates run-month, payment held pending M1 re-import'
            )

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
        + priority_unlocked
    )
    # Note: withheld_amount and priority_withheld_amount are NOT subtracted
    # here — they're already excluded from base_payable via the split_pct
    # calculation (splittable) and the priority_now halving (Phase 12b).
    # They're tracked separately for finance audit and to drive
    # prior_withholdings on the next run.

    timing_audit['final'] = {
        'net_payable': net_payable,
        'withheld_amount': withheld,
        'unlocked_amount': unlocked,
        'priority_withheld_amount': priority_withheld,
        'priority_unlocked_amount': priority_unlocked,
        'priority_schedule_type': priority_schedule_type,
        'clawback_applied': clawback_applied,
        'deferred_this_run': deferred_this_run,
        'carry_over_no_prior_warning': carry_over_no_prior_warning,
        'same_month_full_payment': same_month_full_payment,
    }

    # 7.5 Priority paid this run (Phase 12c) ----------------------------------
    # Compute the priority amount actually paid into net_payable this month.
    # The output BonusPayment.priority_bonus column will be set to this value
    # rather than to the gross priority_passthrough — see "Row-level priority
    # semantics" in the module docstring.
    if deferred_this_run:
        # §I.6.4 deferral: everything moved to withheld; nothing paid this run
        priority_bonus_paid_this_run = 0
    elif status_row.get('is_carry_over', False):
        if unlocked > 0:
            # Branch (a) multi-month release: priority paid is the released
            # prior priority withhold (typically 0 under STANDARD_50_50 since
            # the full at-enrolment 50% was paid in the original enrolment
            # month with no withhold to release).
            priority_bonus_paid_this_run = priority_unlocked
        elif same_month_full_payment:
            # Branch (b) same-month enrol+visa: full priority paid via
            # base_payable (carry-over component = 100% - 0% = 100%).
            priority_bonus_paid_this_run = priority_passthrough
        else:
            # Branch (c) STRICT-zero data-gap: no priority paid.
            priority_bonus_paid_this_run = 0
    elif priority_schedule_type == 'SPLIT_25_25_50':
        # Phase 12b SPLIT first-pay: only the at-enrolment 25% (= priority_now
        # = priority_passthrough // 2) is paid this run. The 25% withheld
        # portion is in priority_withheld and pays out at visa-receipt month.
        priority_bonus_paid_this_run = priority_passthrough - priority_withheld
    else:
        # STANDARD_50_50 non-carry-over: full at-enrolment priority paid now.
        priority_bonus_paid_this_run = priority_passthrough

    timing_audit['final']['priority_bonus_paid_this_run'] = priority_bonus_paid_this_run
    timing_audit['final']['priority_bonus_gross'] = payment_in.priority_bonus

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
    if status_row.get('is_carry_over'):
        if unlocked > 0:
            release_note = (
                f"Carry-over multi-month release: paid {unlocked:,} from prior-month withholding"
            )
            if priority_unlocked > 0:
                release_note += f" + {priority_unlocked:,} priority withhold released"
            notes_extras.append(release_note)
        elif same_month_full_payment:
            notes_extras.append(
                f"Carry-over same-month enrol+visa: paid full {base_payable:,} "
                f"(carry-over component = 100% - 100% = 0%)"
            )
        else:
            notes_extras.append(
                "⚠ CARRY_OVER_NO_PRIOR: status flags carry-over but no "
                "prior withholding is tracked AND course_start predates run-month. "
                "Payment held at 0 pending M1 history re-import or manual trigger."
            )
    if clawback_applied:
        notes_extras.append(
            f"Clawback applied {clawback_applied:,} (§I.5.3, balance was {clawback_balance_in:,})"
        )
    if bank_transfer_required:
        notes_extras.append("Bank transfer required — clawback exceeds available bonus")
    if priority_passthrough > 0 and priority_schedule_type == 'STANDARD':
        notes_extras.append(
            f"Priority {priority_passthrough:,} exempt from split_pct (passthrough)"
        )
    elif priority_schedule_type == 'SPLIT_25_25_50':
        notes_extras.append(
            f"Priority SPLIT_25_25_50: paid {priority_passthrough - priority_withheld:,} "
            f"now, withheld {priority_withheld:,} for visa-receipt month "
            f"(quota not yet met for institution)"
        )

    # ─── Phase 14b: Management override (final additive step) ────────────────
    # Applied AFTER all timing math (split, withhold, carry-over, deferral,
    # clawback). An override is a discretionary mgmt decision to pay an
    # additional amount for this (case, staff). Per Chính_sách §I.5.3,
    # clawback is a SEPARATE concept — clawback already lives in
    # tx_clawback_balance and was applied above; overrides come from
    # tx_case_override and are positive-only by CHECK constraint.
    override_total, override_reason = ctx.overrides_by_case_staff.get(
        (payment_in.case_id, payment_in.staff_id), (0, None)
    )
    if override_total > 0:
        net_payable += override_total
        notes_extras.append(
            f"Mgmt override applied: +{override_total:,} đ ({override_reason})"
        )

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
        priority_bonus=priority_bonus_paid_this_run,  # Phase 12c: paid, not gross
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
        # Phase 12b — priority schedule fields
        priority_withheld_amount=priority_withheld,
        priority_unlocked_amount=priority_unlocked,
        priority_schedule_type=priority_schedule_type,
        # Phase 14b — management override
        override_applied=override_total,
        override_reason=override_reason,
    )


def _zeroed_payment(
    payment_in: BonusPayment,
    timing_audit: dict,
    calc_notes_extra: str,
    ctx: RunContext,
) -> BonusPayment:
    """
    Return a BonusPayment with all amounts zero — used for is_zero_bonus.

    Phase 14b: Even zero-bonus cases honour management overrides. If
    ctx.overrides_by_case_staff has a row for (case_id, staff_id), the
    override is applied as the net_payable (since all other components
    are zero).
    """
    new_audit = dict(payment_in.audit_json)
    new_audit['payment_timing'] = timing_audit

    # Phase 14b: zero-bonus cases can still receive a mgmt override
    override_total, override_reason = ctx.overrides_by_case_staff.get(
        (payment_in.case_id, payment_in.staff_id), (0, None)
    )
    if override_total > 0:
        final_extra = (
            f"{calc_notes_extra} | Mgmt override applied: "
            f"+{override_total:,} đ ({override_reason})"
        )
    else:
        final_extra = calc_notes_extra

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
        net_payable=override_total,         # the only non-zero amount
        calc_notes=f"{payment_in.calc_notes} | {final_extra}",
        audit_json=new_audit,
        # Phase 12b — defaults already zero/STANDARD on the dataclass,
        # but explicit for clarity.
        priority_withheld_amount=0,
        priority_unlocked_amount=0,
        priority_schedule_type='STANDARD',
        # Phase 14b — management override
        override_applied=override_total,
        override_reason=override_reason,
    )
