"""Smoke test for the package_bonus chain.

Run from the backend directory:
    python -m tests.test_package

Three scenarios:
  1. Superior Package (6tr), counsellor only.
  2. Premium Package (9tr), counsellor + CO paired.
  3. No package on case → both slots get 0 from this column.

Reference amounts (from 07_CONTRACT_BONUS / 09_SERVICE_FEE_RATES in
the engine workbook):
  Superior:  counsellor=1,000,000  CO=500,000
  Premium:   counsellor=1,500,000  CO=500,000
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

COUNTRIES = {
    1: {"id": 1, "code": "AU", "name": "Australia",
        "is_target_country": True, "is_flat_country": False,
        "is_domestic_for": None},
}

INSTITUTIONS = {
    1: {"id": 1, "canonical_name": "Generic AU University", "country_id": 1,
        "classification": "IN_SYSTEM_REGULAR",
        "priority_partner_id": None, "aggregate_priority_partner_id": None},
}

# Rate row producing tier_bonus=1,400,000 for counsellor, 1,000,000 for CO
# at MEET_LOW tier — values picked to keep the math obvious.
RATES = {
    1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_400_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
    2: {"id": 2, "office_id": 1, "role_id": 2, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_000_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
}

# Package rows in ref_service_fee. category='PACKAGE' is what makes
# them visible to calc_package; the SERVICE_FEE / ADDON / CONTRACT
# rows would be filtered out.
SERVICE_FEES = {
    100: {"id": 100, "service_code": "SUPERIOR_6TR", "category": "PACKAGE",
          "country_id": None, "fee_amount": 6_000_000,
          "counsellor_signing_bonus": 1_000_000, "co_signing_bonus": 500_000,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    200: {"id": 200, "service_code": "PREMIUM_9TR", "category": "PACKAGE",
          "country_id": None, "fee_amount": 9_000_000,
          "counsellor_signing_bonus": 1_500_000, "co_signing_bonus": 500_000,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
}


def _make_ref() -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=INSTITUTIONS,
        rates=RATES,
        service_fees=SERVICE_FEES,
        status_splits=TIMING_NEUTRAL_STATUS_SPLITS,
        roles=TIMING_TEST_ROLES,
        staff=TIMING_TEST_STAFF,
    )


def _make_ctx() -> RunContext:
    """staff 10 (counsellor) and staff 20 (CO) both hit target → MEET_LOW tier."""
    return RunContext(
        year=2024, month=6,
        enrolments_by_staff_office={(10, 1): 2, (20, 1): 2},
        targets_by_staff_office={(10, 1): 2, (20, 1): 2},
        enrolments_by_priority_list_ytd={},
    )


def _make_case(case_id: int, *, package_id: int | None, with_co: bool) -> CaseInput:
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=1, institution_text_raw="(test)",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=package_id,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=Slot(staff_id=10, staff_name="Trần Khiết Oanh", role_id=1),
        case_officer=(
            Slot(staff_id=20, staff_name="Quan Hoàng Yến", role_id=2)
            if with_co else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
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
    expected: list[tuple[str, int, int, int]],  # (slot_label, tier, package, gross)
    formula: str,
) -> bool:
    """Run a scenario, print the math, return True if it passes."""
    print()
    print("=" * 78)
    print(f"  {label}")
    print("=" * 78)
    print(f"  Formula:  {formula}")
    payments = calculate_case(case, ctx, ref)

    if len(payments) != len(expected):
        print(f"  [FAIL] Expected {len(expected)} payments, got {len(payments)}")
        return False

    all_ok = True
    for p, (e_label, e_tier, e_package, e_gross) in zip(payments, expected):
        if p.slot_label != e_label:
            print(f"  [FAIL] Slot order mismatch: got {p.slot_label}, expected {e_label}")
            all_ok = False
            continue
        ok = (p.tier_bonus == e_tier
              and p.package_bonus == e_package
              and p.gross_bonus == e_gross)
        marker = "[ok]" if ok else "[BAD]"
        print(f"  {marker} {p.slot_label:13s} {p.staff_name:18s} "
              f"tier={p.tier_bonus:>11,}  "
              f"package={p.package_bonus:>11,}  "
              f"gross={p.gross_bonus:>11,}")
        if not ok:
            print(f"        expected:                  "
                  f"tier={e_tier:>11,}  "
                  f"package={e_package:>11,}  "
                  f"gross={e_gross:>11,}")
            all_ok = False

    print(f"  {'[PASS]' if all_ok else '[FAIL]'}")
    return all_ok


# -----------------------------------------------------------------------------
# Scenario 1 — Superior Package, counsellor only
# -----------------------------------------------------------------------------

results: list[bool] = []

results.append(run_scenario(
    "Scenario 1: Superior Package (6tr), counsellor only",
    case=_make_case(1, package_id=100, with_co=False),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor", 1_400_000, 1_000_000, 2_400_000),
    ],
    formula="counsellor: tier 1,400,000 + package 1,000,000 = 2,400,000",
))


# -----------------------------------------------------------------------------
# Scenario 2 — Premium Package, counsellor + CO paired
# -----------------------------------------------------------------------------

results.append(run_scenario(
    "Scenario 2: Premium Package (9tr), counsellor + CO paired",
    case=_make_case(2, package_id=200, with_co=True),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 1_500_000, 2_900_000),
        ("case_officer", 1_000_000, 500_000,   1_500_000),
    ],
    formula=("counsellor: 1,400,000 + 1,500,000 = 2,900,000  |  "
             "CO: 1,000,000 + 500,000 = 1,500,000"),
))


# -----------------------------------------------------------------------------
# Scenario 3 — No package
# -----------------------------------------------------------------------------

results.append(run_scenario(
    "Scenario 3: No package on case (package_service_fee_id is None)",
    case=_make_case(3, package_id=None, with_co=True),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 0, 1_400_000),
        ("case_officer", 1_000_000, 0, 1_000_000),
    ],
    formula="No package → package_bonus = 0 for both slots",
))


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

print()
print("=" * 78)
passed = sum(results)
total = len(results)
if passed == total:
    print(f"  ALL PASS ({passed}/{total})")
else:
    print(f"  FAILED: {total - passed}/{total} scenario(s) did not match")
print("=" * 78)
