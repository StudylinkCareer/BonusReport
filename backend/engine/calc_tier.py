"""
Tier bonus calculation for the BonusReport engine.

Resolves the rate-card base bonus for one slot on one case by:
  1. Classifying the country bucket.
  2. Classifying the performance tier.
  3. Looking up the matching ref_rate row.
  4. Returning amount + the matched row for audit.

Per architecture.md §6.

CHANGES IN THIS REVISION (Phase 14b — Client Type Canonicalisation):
  - DELETED BRANCH: 'Visa-only paid' branch (was triggered by the fabricated
    ref_status_split.is_visa_only_paid flag). The is_visa_only_paid mechanism
    was conflating workflow state with contract type. Per Phase 14a
    (migration 14a_v2), visa-only is now a client_type concept
    (VISA_ONLY_SERVICE).
  - NEW BRANCH 0: service-only client_types (VISA_ONLY_SERVICE, GUARDIAN_VISA,
    TOURIST_VISA, MIGRATION_VISA, DEPENDANT_VISA) return tier_bonus = 0
    BEFORE any rate-card lookup. Their bonuses come exclusively from
    calc_addon reading the service_fee catalog (tx_case_service →
    ref_service_fee). The tier rate card applies only to enrolment-based
    cases (DU_HOC_FULL, DU_HOC_ENROL_ONLY, SUMMER_STUDY, VIETNAM_DOMESTIC).
  - REMOVED IMPORT: TIER_VISA_ONLY constant (was used only by the deleted
    Branch 2). The constant itself still exists in .classifiers for now;
    its cleanup is a separate task.

PRESERVED FROM PRIOR REVISION:
  - Branch 1 — Carry-over rate locking (is_carry_over + prior_month_rate).
  - Branch 3 — Fees-paid-non-enrolled (status-driven, legitimate per §I.6).
  - Branch 4 — Standard tier lookup flow.
  - CO_SUB subscheme resolution.

Citations:
  - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.2 (KPI weights — 5 of 9
    client types are weight 0 across all routes; they don't earn tier bonus)
  - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.6 (fees-paid-non-enrolled
    handling — Out-system rate; Branch 3 unchanged)
  - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §3.4 (carry-over rate lock;
    Branch 1 unchanged)
  - User specification (this session) — 9 canonical client types; the 5
    service-only types pay through service_fee catalog, not tier rate card
"""

from __future__ import annotations

from datetime import date

from .classifiers import (
    BUCKET_TARGET,
    TIER_OUT_SYSTEM,
    classify_country_bucket,
    classify_tier,
)
from .lookups import lookup_rate, resolve_co_sub_subscheme
from .models import CaseInput, ReferenceData, RunContext, Slot


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical client_type_code values where tier_bonus = 0.
# These are pure-service contracts. Their bonus comes exclusively from
# calc_addon (ref_service_fee lookup), not from the tier rate card.
#
# Mirrors CLIENT_TYPES_NO_INSTITUTION in adapter.py — same 5 codes for the
# same reason (no enrolment at an institution → no tier rate-card payout).
CLIENT_TYPES_SERVICE_ONLY: frozenset[str] = frozenset({
    "VISA_ONLY_SERVICE",  # Visa Du học only
    "GUARDIAN_VISA",      # Visa Giám hộ
    "TOURIST_VISA",       # Visa Du lịch
    "MIGRATION_VISA",     # Visa Định cư
    "DEPENDANT_VISA",     # Visa Phụ thuộc
})


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
    Extracted so all branches can share it.
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
      0. Service-only client_type → tier_bonus = 0 (bonus comes via calc_addon).
      1. Carry-over rate lock (is_carry_over + prior_month_rate).
      2. (DELETED — was the fabricated is_visa_only_paid branch.)
      3. Fees-paid-non-enrolled → TIER_OUT_SYSTEM rate lookup.
      4. Standard tier lookup (country bucket + performance tier).

    Returns:
        (amount_dong, audit_record).
    """
    assert slot.staff_id is not None, "calc_tier_bonus called with empty slot"
    assert slot.role_id is not None, "slot has no role_id"

    # 0. Service-only client_type — no tier bonus ------------------------------
    # The 5 fixed-rate client types (visa-only, guardian, tourist, migration,
    # dependant) earn no rate-card tier bonus. Their entire compensation
    # comes from calc_addon's service_fee lookup.
    #
    # Per §I.2 KPI weight table (5 weight-0 client types) and user spec.
    if case.client_type_code in CLIENT_TYPES_SERVICE_ONLY:
        return 0, {
            'special_case': 'service_only_client_type',
            'client_type_code': case.client_type_code,
            'tier_bonus': 0,
            'reason': (
                f"client_type_code={case.client_type_code!r} is a "
                f"service-only contract; tier rate card does not apply. "
                f"Bonus comes via calc_addon (ref_service_fee lookup)."
            ),
        }

    # Look up the status row — drives branches 1 and 3.
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

    # 2. (DELETED — Phase 14b cleanup) -----------------------------------------
    # Previously: visa-only paid branch triggered by ref_status_split.
    # is_visa_only_paid. Removed because visa-only is a client_type concept,
    # not a status flag — now handled at Branch 0 above.

    # 3. Fees-paid-non-enrolled ------------------------------------------------
    # Triggered by ref_status_split.fees_paid_non_enrolled = TRUE.
    # Used for study-abroad cases where fees were paid but enrolment didn't
    # happen (cancelled, visa refused, etc.). Pays at OUT_SYSTEM tier rate
    # via ref_rate lookup. Per §I.6.
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
                '(§I.6)'
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
