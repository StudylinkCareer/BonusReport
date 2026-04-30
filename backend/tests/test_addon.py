"""Smoke test for the addon_bonus chain.

Run from the backend directory:
    python -m tests.test_addon

Three scenarios:
  1. Single addon item with count=2 → unit_rate × 2, both slots.
  2. Multiple addon items → sums across all entries.
  3. No addon items → 0 for all slots.

Reference data uses fictional ADDON-category rows since the production
data has no real ADDON rows yet (per VBA v6.2 architecture review).
"""

from datetime import date
from decimal import Decimal

from engine.models import CaseInput, RunContext, ReferenceData, Slot
from engine.calc import calculate_case


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

# Tier rates: 1,400,000 for counsellor, 1,000,000 for CO at MEET_LOW.
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

# Two ADDON-category rows. EXTRA_SCHOOL pays 100k counsellor / 250k CO
# per unit; PARTNER_REFERRAL pays 50k counsellor only per unit.
SERVICE_FEES = {
    300: {"id": 300, "service_code": "EXTRA_SCHOOL", "category": "ADDON",
          "country_id": None, "fee_amount": 0,
          "counsellor_signing_bonus": 100_000, "co_signing_bonus": 250_000,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    301: {"id": 301, "service_code": "PARTNER_REFERRAL", "category": "ADDON",
          "country_id": None, "fee_amount": 0,
          "counsellor_signing_bonus": 50_000, "co_signing_bonus": 0,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
}


def _make_ref() -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=INSTITUTIONS,
        rates=RATES,
        service_fees=SERVICE_FEES,
    )


def _make_ctx() -> RunContext:
    return RunContext(
        year=2024, month=6,
        enrolments_by_staff_office={(10, 1): 2, (20, 1): 2},
        targets_by_staff_office={(10, 1): 2, (20, 1): 2},
        enrolments_by_priority_partner_ytd={},
    )


def _make_case(case_id: int, *, addon_items: list[tuple[int, int]]) -> CaseInput:
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=1, institution_text_raw="(test)",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=None,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=Slot(staff_id=10, staff_name="Truong An", role_id=1),
        case_officer=Slot(staff_id=20, staff_name="Hoang Yen", role_id=2),
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2024, 6, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
        addon_items=addon_items,
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
    expected: list[tuple[str, int, int, int]],  # (slot_label, tier, addon, gross)
    formula: str,
) -> bool:
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
    for p, (e_label, e_tier, e_addon, e_gross) in zip(payments, expected):
        if p.slot_label != e_label:
            print(f"  [FAIL] Slot order mismatch: got {p.slot_label}, expected {e_label}")
            all_ok = False
            continue
        ok = (p.tier_bonus == e_tier
              and p.addon_bonus == e_addon
              and p.gross_bonus == e_gross)
        marker = "[ok]" if ok else "[BAD]"
        print(f"  {marker} {p.slot_label:13s} {p.staff_name:12s} "
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
# Scenario 1 — single addon, count=2
# -----------------------------------------------------------------------------

results: list[bool] = []

results.append(run_scenario(
    "Scenario 1: 2 extra schools (EXTRA_SCHOOL × 2)",
    case=_make_case(1, addon_items=[(300, 2)]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        # slot,         tier,        addon,    gross
        ("counsellor",   1_400_000, 200_000, 1_600_000),  # 100k × 2
        ("case_officer", 1_000_000, 500_000, 1_500_000),  # 250k × 2
    ],
    formula=("counsellor: 100,000 × 2 = 200,000  |  "
             "CO: 250,000 × 2 = 500,000"),
))


# -----------------------------------------------------------------------------
# Scenario 2 — two different addon items
# -----------------------------------------------------------------------------

results.append(run_scenario(
    "Scenario 2: 1 extra school + 3 partner referrals",
    case=_make_case(2, addon_items=[(300, 1), (301, 3)]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        # counsellor: 100k×1 + 50k×3 = 250k
        ("counsellor",   1_400_000, 250_000, 1_650_000),
        # CO: 250k×1 + 0×3 = 250k
        ("case_officer", 1_000_000, 250_000, 1_250_000),
    ],
    formula=("counsellor: (100k × 1) + (50k × 3) = 250k  |  "
             "CO: (250k × 1) + (0 × 3) = 250k"),
))


# -----------------------------------------------------------------------------
# Scenario 3 — no addons
# -----------------------------------------------------------------------------

results.append(run_scenario(
    "Scenario 3: No addon items (empty list)",
    case=_make_case(3, addon_items=[]),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        ("counsellor",   1_400_000, 0, 1_400_000),
        ("case_officer", 1_000_000, 0, 1_000_000),
    ],
    formula="No addons → addon_bonus = 0 for both slots",
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
