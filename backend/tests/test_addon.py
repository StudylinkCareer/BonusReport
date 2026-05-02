"""Smoke test for the addon_bonus chain.

Run from the backend directory:
    python -m tests.test_addon

Five scenarios:
  1. Single ADDON-category item with count=2 → unit_rate × 2.
  2. Multiple ADDON-category items → sums across all entries.
  3. No addon items → 0 for all slots.
  4. SERVICE_FEE-category row stacked on a regular enrolment case
     (per StudyLink policy: bonuses are ADDITIVE, not replacement).
  5. Pure service-fee-only case (no enrolment) → CO earns service fee,
     counsellor earns 0, no tier_bonus involved.
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

# Tier rates: counsellor 1,400,000 / CO 1,000,000 at MEET_LOW.
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

# Mix of ADDON and SERVICE_FEE rows so we can prove both work additively.
SERVICE_FEES = {
    # ADDON-category — synthetic / fictional.
    300: {"id": 300, "service_code": "EXTRA_SCHOOL_ADDON", "category": "ADDON",
          "country_id": None, "fee_amount": 0,
          "counsellor_signing_bonus": 100_000, "co_signing_bonus": 250_000,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    301: {"id": 301, "service_code": "PARTNER_REFERRAL", "category": "ADDON",
          "country_id": None, "fee_amount": 0,
          "counsellor_signing_bonus": 50_000, "co_signing_bonus": 0,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    # SERVICE_FEE-category — taken from real 09_SERVICE_FEE_RATES.
    400: {"id": 400, "service_code": "GUARDIAN_CHANGE", "category": "SERVICE_FEE",
          "country_id": None, "fee_amount": 0,
          "counsellor_signing_bonus": 0, "co_signing_bonus": 250_000,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    401: {"id": 401, "service_code": "VISA_485", "category": "SERVICE_FEE",
          "country_id": None, "fee_amount": 0,
          "counsellor_signing_bonus": 0, "co_signing_bonus": 600_000,
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
    return RunContext(
        year=2024, month=6,
        enrolments_by_staff_office={(10, 1): 2, (20, 1): 2},
        targets_by_staff_office={(10, 1): 2, (20, 1): 2},
        enrolments_by_priority_partner_ytd={},
    )


def _make_case(
    case_id: int,
    *,
    addon_items: list[tuple[int, int]],
    counsellor_filled: bool = True,
    co_filled: bool = True,
) -> CaseInput:
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=1, institution_text_raw="(test)",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=None,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=(
            Slot(staff_id=10, staff_name="Trần Khiết Oanh", role_id=1)
            if counsellor_filled else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
        case_officer=(
            Slot(staff_id=20, staff_name="Quan Hoàng Yến", role_id=2)
            if co_filled else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2024, 6, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
        addon_items=addon_items,
    )


# -----------------------------------------------------------------------------
# Pretty-printer
# -----------------------------------------------------------------------------

def run_scenario(
    label: str,
    case: CaseInput,
    ctx: RunContext,
    ref: ReferenceData,
    *,
    expected: list[tuple[str, int, int, int]],   # (slot_label, tier, addon, gross)
    formula: str,
) -> bool:
    print()
    print("=" * 90)
    print(f"  {label}")
    print("=" * 90)
    print(f"  Formula:  {formula}")
    payments = calculate_case(case, ctx, ref)

    if len(payments) != len(expected):
        print(f"  [FAIL] Expected {len(expected)} payments, got {len(payments)}")
        return False

    all_ok = True
    for p, (e_label, e_tier, e_addon, e_gross) in zip(payments, expected):
        if p.slot_label != e_label:
            print(f"  [FAIL] Slot order mismatch: got {p.slot_label}, expected {e_label}")
            all_ok = False
            continue
        ok = (p.tier_bonus == e_tier
              and p.addon_bonus == e_addon
              and p.gross_bonus == e_gross)
        marker = "[ok]" if ok else "[BAD]"
        print(f"  {marker} {p.slot_label:13s} {p.staff_name:18s} "
              f"tier={p.tier_bonus:>11,}  "
              f"addon={p.addon_bonus:>11,}  "
              f"gross={p.gross_bonus:>11,}")
        if not ok:
            print(f"        expected:                  "
                  f"tier={e_tier:>11,}  "
                  f"addon={e_addon:>11,}  "
                  f"gross={e_gross:>11,}")
            all_ok = False

    print(f"  {'[PASS]' if all_ok else '[FAIL]'}")
    return all_ok


# -----------------------------------------------------------------------------
# Run scenarios
# -----------------------------------------------------------------------------

results: list[bool] = []

# Scenario 1: ADDON x2
results.append(run_scenario(
    "Scenario 1: 2 extra schools (ADDON × 2)",
    case=_make_case(1, addon_items=[(300, 2)]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 200_000, 1_600_000),
        ("case_officer", 1_000_000, 500_000, 1_500_000),
    ],
    formula="counsellor: 100,000 × 2 = 200,000  |  CO: 250,000 × 2 = 500,000",
))

# Scenario 2: two ADDON items
results.append(run_scenario(
    "Scenario 2: 1 extra school + 3 partner referrals",
    case=_make_case(2, addon_items=[(300, 1), (301, 3)]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 250_000, 1_650_000),
        ("case_officer", 1_000_000, 250_000, 1_250_000),
    ],
    formula=("counsellor: (100k × 1) + (50k × 3) = 250k  |  "
             "CO: (250k × 1) + (0 × 3) = 250k"),
))

# Scenario 3: no addons
results.append(run_scenario(
    "Scenario 3: No addon items",
    case=_make_case(3, addon_items=[]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 0, 1_400_000),
        ("case_officer", 1_000_000, 0, 1_000_000),
    ],
    formula="No addons → addon_bonus = 0 for both slots",
))

# Scenario 4: SERVICE_FEE row stacked additively
results.append(run_scenario(
    "Scenario 4: Enrolment case + GUARDIAN_CHANGE service fee (ADDITIVE)",
    case=_make_case(4, addon_items=[(400, 1)]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 0,        1_400_000),
        ("case_officer", 1_000_000, 250_000,  1_250_000),
    ],
    formula=("Enrolment + Guardian change: CO gets tier 1,000,000 + service fee "
             "250,000 = 1,250,000 (ADDITIVE — workbook 'fire and exit' rule does NOT apply)"),
))

# Scenario 5: pure service-fee-only case
results.append(run_scenario(
    "Scenario 5: Pure VISA_485 case (no enrolment, only counsellor present)",
    case=_make_case(5, addon_items=[(401, 1)]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 0,       1_400_000),
        ("case_officer", 1_000_000, 600_000, 1_600_000),
    ],
    formula=("VISA_485 service: counsellor row 0 + tier 1.4M = 1.4M; "
             "CO row 600k + tier 1M = 1.6M (additive)"),
))

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

print()
print("=" * 90)
passed = sum(results)
total = len(results)
if passed == total:
    print(f"  ALL PASS ({passed}/{total})")
else:
    print(f"  FAILED: {total - passed}/{total} scenario(s) did not match")
print("=" * 90)
