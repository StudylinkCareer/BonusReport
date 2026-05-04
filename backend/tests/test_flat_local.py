"""Smoke test for the flat_local_enrolment_bonus chain.

Run from the backend directory:
    python -m tests.test_flat_local

Three scenarios:
  1. Solo counsellor on a VN-domestic case → counsellor gets 100% of
     flat_local, tier_bonus is bypassed.
  2. Counsellor + CO paired → 50/50 split of flat_local, tier_bonus
     still bypassed.
  3. Counsellor + presales (item 5) → presales takes 50% share of
     counsellor's flat_local, same way it shares tier+package+priority.
     Confirms flat_local IS in the share base (per Pass 2 in calc.py).
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
# Shared reference data — VN as a domestic country, with one local-bonus row
# -----------------------------------------------------------------------------

ref = ReferenceData(
    countries={
        1: {"id": 1, "code": "VN", "name": "Vietnam",
            "is_target_country": False, "is_flat_country": False,
            "is_domestic_for": 1},
    },
    institutions={
        1: {"id": 1, "canonical_name": "RMIT University Vietnam",
            "country_id": 1, "classification": "IN_SYSTEM_REGULAR"},
    },
    local_enrolment_bonuses={
        1: {"id": 1, "country_id": 1, "flat_total_amount": 1_000_000,
            "couns_dir_alone_pct": Decimal("1.000"),
            "couns_dir_with_co_pct": Decimal("0.500"),
            "co_pct_when_paired": Decimal("0.500"),
            "effective_from": date(2024, 1, 1), "effective_to": None},
    },
    status_splits=TIMING_NEUTRAL_STATUS_SPLITS,
    roles=TIMING_TEST_ROLES,
    staff=TIMING_TEST_STAFF,
)

ctx = RunContext(
    year=2025, month=1,
    enrolments_by_staff_office={},
    targets_by_staff_office={},
)


def _make_case(
    case_id: int,
    *,
    with_co: bool = False,
    with_presales: bool = False,
) -> CaseInput:
    """Build a VN-domestic case, optionally with CO and/or presales slots filled."""
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=1, institution_text_raw="RMIT VN",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=None,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=Slot(staff_id=10, staff_name="Trần Khiết Oanh", role_id=1),
        case_officer=(
            Slot(staff_id=20, staff_name="Quan Hoàng Yến", role_id=2)
            if with_co else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
        presales=(
            Slot(staff_id=30, staff_name="Pre Sales Bee", role_id=3)
            if with_presales else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0.5") if with_presales else Decimal("0"),
        contract_signed_date=date(2025, 1, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
    )


# -----------------------------------------------------------------------------
# Pretty-printer
# -----------------------------------------------------------------------------

def run_scenario(
    label: str,
    case: CaseInput,
    *,
    expected: list[dict],
    formula: str,
) -> bool:
    """
    expected: list of dicts with keys
       slot_label, staff_id, tier, flat_local, share, gross
    """
    print()
    print("=" * 100)
    print(f"  {label}")
    print("=" * 100)
    print(f"  {formula}")
    payments = calculate_case(case, ctx, ref)

    if len(payments) != len(expected):
        print(f"  [FAIL] Expected {len(expected)} payments, got {len(payments)}")
        for p in payments:
            print(f"          actual: {p.slot_label} {p.staff_name} gross={p.gross_bonus:,}")
        return False

    all_ok = True
    for p, e in zip(payments, expected):
        ok = (p.slot_label == e['slot_label']
              and p.tier_bonus == e['tier']
              and p.flat_local_enrolment_bonus == e['flat_local']
              and p.presales_share_taken == e['share']
              and p.gross_bonus == e['gross'])
        marker = "[ok]" if ok else "[BAD]"
        print(f"  {marker} {p.slot_label:13s} {p.staff_name:18s} "
              f"tier={p.tier_bonus:>10,}  "
              f"flat_local={p.flat_local_enrolment_bonus:>10,}  "
              f"share={p.presales_share_taken:>+11,}  "
              f"gross={p.gross_bonus:>11,}")
        if not ok:
            print(f"        expected:                "
                  f"tier={e['tier']:>10,}  "
                  f"flat_local={e['flat_local']:>10,}  "
                  f"share={e['share']:>+11,}  "
                  f"gross={e['gross']:>11,}")
            all_ok = False

    print(f"  {'[PASS]' if all_ok else '[FAIL]'}")
    return all_ok


# -----------------------------------------------------------------------------
# Scenarios
# -----------------------------------------------------------------------------

results: list[bool] = []

# Scenario 1: solo counsellor → 100% of flat_local
results.append(run_scenario(
    "Scenario 1: Solo counsellor on VN case → 100% of flat_local",
    case=_make_case(1),
    expected=[
        {"slot_label": "counsellor", "staff_id": 10,
         "tier": 0, "flat_local": 1_000_000, "share": 0,
         "gross": 1_000_000},
    ],
    formula="counsellor_alone_pct = 1.0 → flat_local 1,000,000, no split.",
))

# Scenario 2: counsellor + CO paired → 50/50
results.append(run_scenario(
    "Scenario 2: Counsellor + CO paired → 50/50 split of flat_local",
    case=_make_case(2, with_co=True),
    expected=[
        {"slot_label": "counsellor", "staff_id": 10,
         "tier": 0, "flat_local": 500_000, "share": 0,
         "gross": 500_000},
        {"slot_label": "case_officer", "staff_id": 20,
         "tier": 0, "flat_local": 500_000, "share": 0,
         "gross": 500_000},
    ],
    formula=("couns_with_co_pct = 0.5, co_pct_when_paired = 0.5 → "
             "1,000,000 split 500,000 / 500,000."),
))

# Scenario 3 (item 5): counsellor + presales on VN case
# Counsellor solo (no CO), gets 100% of flat_local = 1,000,000.
# Presales takes 50% → counsellor share = 500,000, presales receives 500,000.
results.append(run_scenario(
    "Scenario 3: Counsellor + presales on VN case → presales shares flat_local (item 5)",
    case=_make_case(3, with_presales=True),
    expected=[
        # Counsellor: flat_local 1,000,000, share +500,000 (gives up half),
        #             gross = 1,000,000 - 500,000 = 500,000
        {"slot_label": "counsellor", "staff_id": 10,
         "tier": 0, "flat_local": 1_000_000, "share": 500_000,
         "gross": 500_000},
        # Presales: flat_local 0, share -500,000 (receives half),
        #           gross = 0 - (-500,000) = 500,000
        {"slot_label": "presales", "staff_id": 30,
         "tier": 0, "flat_local": 0, "share": -500_000,
         "gross": 500_000},
    ],
    formula=("Counsellor full flat_local = 1,000,000. Presales takes 50% → "
             "counsellor 500,000, presales 500,000 (proves flat_local IS in share base)."),
))


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

print()
print("=" * 100)
passed = sum(results)
total = len(results)
if passed == total:
    print(f"  ALL PASS ({passed}/{total})")
else:
    print(f"  FAILED: {total - passed}/{total} scenario(s) did not match")
print("=" * 100)
