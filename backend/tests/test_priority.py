"""Smoke test for the priority_bonus chain.

Run from the backend directory:
    python -m tests.test_priority

Three scenarios:
  1. Direct priority partner (Monash), target HIT → AF=1.0, full bonus.
  2. Direct priority partner (Monash), target NOT hit → AF=0.5, half bonus.
  3. Aggregate priority partner (Navitas group) → resolves via
     aggregate_priority_partner_id, full bonus.

All scenarios use 2024 rates (where bonus_pct was non-zero).
"""

from datetime import date
from decimal import Decimal

from engine.models import CaseInput, RunContext, ReferenceData, Slot
from engine.calc import calculate_case
from tests._timing_fixtures import (
    TIMING_NEUTRAL_STATUS_SPLITS,
    TIMING_TEST_ROLES,
    TIMING_TEST_STAFF,
)


# -----------------------------------------------------------------------------
# Reference data
# -----------------------------------------------------------------------------

PRIORITY_PARTNERS = {
    100: {"id": 100, "name": "Monash University",
          "country_id": 1, "is_aggregate": False},
    200: {"id": 200, "name": "Other Navitas AU",
          "country_id": 1, "is_aggregate": True},
}

# 2024 targets and bonus percentages — taken from the Bonus_Splits sheet.
PRIORITY_TARGETS = {
    1: {"id": 1, "priority_partner_id": 100, "year": 2024,
        "total_target": 10, "direct_target": 3, "sub_target": 7,
        "bonus_pct": Decimal("0.5"), "prior_year_owing": 0},
    2: {"id": 2, "priority_partner_id": 200, "year": 2024,
        "total_target": 7, "direct_target": 3, "sub_target": 4,
        "bonus_pct": Decimal("0.3"), "prior_year_owing": 0},
}

INSTITUTIONS = {
    1: {"id": 1, "canonical_name": "Monash University", "country_id": 1,
        "classification": "IN_SYSTEM_PRIORITY",
        "priority_partner_id": 100, "aggregate_priority_partner_id": None},
    2: {"id": 2, "canonical_name": "La Trobe College Melbourne",
        "country_id": 1, "classification": "IN_SYSTEM_PRIORITY",
        "priority_partner_id": None, "aggregate_priority_partner_id": 200},
}

COUNTRIES = {
    1: {"id": 1, "code": "AU", "name": "Australia",
        "is_target_country": True, "is_flat_country": False,
        "is_domestic_for": None},
}

# Rate row that yields a tier_bonus of 1,400,000 for a counsellor at
# MEET_LOW tier.
RATES = {
    1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_400_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
}


def _make_ref() -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=INSTITUTIONS,
        rates=RATES,
        priority_partners=PRIORITY_PARTNERS,
        priority_targets=PRIORITY_TARGETS,
        status_splits=TIMING_NEUTRAL_STATUS_SPLITS,
        roles=TIMING_TEST_ROLES,
        staff=TIMING_TEST_STAFF,
    )


def _make_ctx(*, ytd_for_partner: dict[int, int]) -> RunContext:
    """RunContext for 2024, staff_id=10 hits target of 2 → MEET_LOW tier."""
    return RunContext(
        year=2024, month=6,
        enrolments_by_staff_office={(10, 1): 2},
        targets_by_staff_office={(10, 1): 2},
        enrolments_by_priority_partner_ytd=ytd_for_partner,
    )


def _make_case(case_id: int, *, institution_id: int) -> CaseInput:
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=institution_id, institution_text_raw="(test)",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=None,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=Slot(staff_id=10, staff_name="Trần Khiết Oanh", role_id=1),
        case_officer=Slot(staff_id=None, staff_name=None, role_id=None),
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2024, 6, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
    )


# -----------------------------------------------------------------------------
# Pretty-printer for one scenario
# -----------------------------------------------------------------------------

def run_scenario(
    label: str,
    case: CaseInput,
    ctx: RunContext,
    ref: ReferenceData,
    *,
    expected_tier: int,
    expected_priority: int,
    formula: str,
) -> bool:
    """Run one scenario, print the math, return True if it passes."""
    print()
    print("=" * 70)
    print(f"  {label}")
    print("=" * 70)
    print(f"  Formula:  {formula}")
    print(f"  Expected: tier={expected_tier:>11,}   "
          f"priority={expected_priority:>11,}   "
          f"gross={expected_tier + expected_priority:>11,}")

    payments = calculate_case(case, ctx, ref)
    if not payments:
        print("  [FAIL] No payments returned.")
        return False

    p = payments[0]
    print(f"  Actual:   tier={p.tier_bonus:>11,}   "
          f"priority={p.priority_bonus:>11,}   "
          f"gross={p.gross_bonus:>11,}")

    tier_ok = p.tier_bonus == expected_tier
    priority_ok = p.priority_bonus == expected_priority
    gross_ok = p.gross_bonus == expected_tier + expected_priority

    if tier_ok and priority_ok and gross_ok:
        print("  [PASS]")
        return True

    print("  [FAIL]")
    if not tier_ok:
        print(f"         tier mismatch: got {p.tier_bonus:,}, "
              f"expected {expected_tier:,}")
    if not priority_ok:
        print(f"         priority mismatch: got {p.priority_bonus:,}, "
              f"expected {expected_priority:,}")
    if not gross_ok:
        print(f"         gross mismatch: got {p.gross_bonus:,}, "
              f"expected {expected_tier + expected_priority:,}")
    return False


# -----------------------------------------------------------------------------
# Run all three scenarios
# -----------------------------------------------------------------------------

results: list[bool] = []

results.append(run_scenario(
    "Scenario 1: Monash (direct priority partner), target HIT",
    case=_make_case(1, institution_id=1),
    ctx=_make_ctx(ytd_for_partner={100: 10}),
    ref=_make_ref(),
    expected_tier=1_400_000,
    expected_priority=700_000,
    formula="priority = 1,400,000 (tier) × 0.5 (Monash 2024 pct) × 1.0 (AF, hit) = 700,000",
))

results.append(run_scenario(
    "Scenario 2: Monash (direct priority partner), target NOT hit",
    case=_make_case(2, institution_id=1),
    ctx=_make_ctx(ytd_for_partner={100: 4}),
    ref=_make_ref(),
    expected_tier=1_400_000,
    expected_priority=350_000,
    formula="priority = 1,400,000 (tier) × 0.5 (Monash 2024 pct) × 0.5 (AF, not hit) = 350,000",
))

results.append(run_scenario(
    "Scenario 3: La Trobe College via Navitas aggregate, target HIT",
    case=_make_case(3, institution_id=2),
    ctx=_make_ctx(ytd_for_partner={200: 7}),
    ref=_make_ref(),
    expected_tier=1_400_000,
    expected_priority=420_000,
    formula="priority = 1,400,000 (tier) × 0.3 (Navitas 2024 pct) × 1.0 (AF, hit) = 420,000",
))


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

print()
print("=" * 70)
passed = sum(results)
total = len(results)
if passed == total:
    print(f"  ALL PASS ({passed}/{total})")
else:
    print(f"  FAILED: {total - passed}/{total} scenario(s) did not match")
print("=" * 70)
