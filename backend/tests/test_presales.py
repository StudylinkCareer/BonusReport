"""Smoke test for the presales_share_taken chain.

Run from the backend directory:
    python -m tests.test_presales

Three scenarios:
  1. Different people: counsellor (Person A) + presales (Person B)
     → counsellor keeps 50%, presales receives 50%, of TOTAL counsellor bonus.
  2. Same person both slots: Person X is both counsellor and presales
     → net 100% to Person X (across the two rows).
  3. No presales: counsellor keeps everything.
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
# Reference data — uses package + priority so we can prove the split applies
# to ALL counsellor-side columns, not just tier_bonus.
# -----------------------------------------------------------------------------

COUNTRIES = {
    1: {"id": 1, "code": "AU", "name": "Australia",
        "is_target_country": True, "is_flat_country": False,
        "is_domestic_for": None},
}

INSTITUTIONS = {
    1: {"id": 1, "canonical_name": "Monash University", "country_id": 1,
        "classification": "IN_SYSTEM_PRIORITY",
        "priority_partner_id": 100, "aggregate_priority_partner_id": None},
}

RATES = {
    1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_400_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
    2: {"id": 2, "office_id": 1, "role_id": 2, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_000_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
    3: {"id": 3, "office_id": 1, "role_id": 3, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 0,
        "effective_from": date(2024, 1, 1), "effective_to": None},
}

SERVICE_FEES = {
    100: {"id": 100, "service_code": "SUPERIOR_6TR", "category": "PACKAGE",
          "country_id": None, "fee_amount": 6_000_000,
          "counsellor_signing_bonus": 1_000_000, "co_signing_bonus": 500_000,
          "is_active": True,
          "effective_from": date(2024, 1, 1), "effective_to": None},
}

PRIORITY_PARTNERS = {
    100: {"id": 100, "name": "Monash University",
          "country_id": 1, "is_aggregate": False},
}

PRIORITY_TARGETS = {
    1: {"id": 1, "priority_partner_id": 100, "year": 2024,
        "total_target": 10, "direct_target": 3, "sub_target": 7,
        "bonus_pct": Decimal("0.5"), "prior_year_owing": 0},
}


def _make_ref() -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=INSTITUTIONS,
        rates=RATES,
        service_fees=SERVICE_FEES,
        priority_lists=PRIORITY_PARTNERS,
        priority_targets=PRIORITY_TARGETS,
        status_splits=TIMING_NEUTRAL_STATUS_SPLITS,
        roles=TIMING_TEST_ROLES,
        staff=TIMING_TEST_STAFF,
    )


def _make_ctx() -> RunContext:
    return RunContext(
        year=2024, month=6,
        enrolments_by_staff_office={(10, 1): 2, (20, 1): 2, (30, 1): 2},
        targets_by_staff_office={(10, 1): 2, (20, 1): 2, (30, 1): 2},
        enrolments_by_priority_list_ytd={100: 10},
    )


def _make_case(
    case_id: int,
    *,
    counsellor_staff_id: int,
    counsellor_name: str,
    presales_staff_id: int | None = None,
    presales_name: str | None = None,
) -> CaseInput:
    """Counsellor + presales on a Monash case with Superior package."""
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=1, institution_text_raw="Monash",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=100,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=Slot(staff_id=counsellor_staff_id,
                        staff_name=counsellor_name, role_id=1),
        case_officer=Slot(staff_id=None, staff_name=None, role_id=None),
        presales=(
            Slot(staff_id=presales_staff_id, staff_name=presales_name, role_id=3)
            if presales_staff_id is not None else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0.5"),
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
    expected: list[dict],
    formula: str,
) -> bool:
    """
    expected is a list of dicts, one per BonusPayment, with keys:
      slot_label, staff_id, tier, package, priority, share, gross
    """
    print()
    print("=" * 90)
    print(f"  {label}")
    print("=" * 90)
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
              and p.package_bonus == e['package']
              and p.priority_bonus == e['priority']
              and p.presales_share_taken == e['share']
              and p.gross_bonus == e['gross'])
        marker = "[ok]" if ok else "[BAD]"
        print(f"  {marker} {p.slot_label:13s} {p.staff_name:18s} "
              f"tier={p.tier_bonus:>10,}  "
              f"pkg={p.package_bonus:>10,}  "
              f"prio={p.priority_bonus:>10,}  "
              f"share={p.presales_share_taken:>+11,}  "
              f"gross={p.gross_bonus:>11,}")
        if not ok:
            print(f"        expected:                "
                  f"tier={e['tier']:>10,}  "
                  f"pkg={e['package']:>10,}  "
                  f"prio={e['priority']:>10,}  "
                  f"share={e['share']:>+11,}  "
                  f"gross={e['gross']:>11,}")
            all_ok = False

    print(f"  {'[PASS]' if all_ok else '[FAIL]'}")
    return all_ok


# -----------------------------------------------------------------------------
# Scenario 1 — Different people, 50/50 split
# -----------------------------------------------------------------------------

results: list[bool] = []

results.append(run_scenario(
    "Scenario 1: Different people — counsellor (A) + presales (B), 50/50",
    case=_make_case(
        1,
        counsellor_staff_id=10, counsellor_name="Trần Khiết Oanh",
        presales_staff_id=30, presales_name="Pre Sales Bee",
    ),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        {"slot_label": "counsellor", "staff_id": 10,
         "tier": 1_400_000, "package": 1_000_000, "priority": 700_000,
         "share": 1_550_000,
         "gross": 1_550_000},
        {"slot_label": "presales", "staff_id": 30,
         "tier": 0, "package": 0, "priority": 0,
         "share": -1_550_000,
         "gross": 1_550_000},
    ],
    formula=("Counsellor full bonus = tier 1,400,000 + package 1,000,000 + "
             "priority 700,000 = 3,100,000.  "
             "50% split → each gets 1,550,000."),
))


# -----------------------------------------------------------------------------
# Scenario 2 — Same person in both slots
# -----------------------------------------------------------------------------

results.append(run_scenario(
    "Scenario 2: Same person both slots — Person X is counsellor + presales",
    case=_make_case(
        2,
        counsellor_staff_id=10, counsellor_name="Trần Khiết Oanh",
        presales_staff_id=10, presales_name="Trần Khiết Oanh",
    ),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        {"slot_label": "counsellor", "staff_id": 10,
         "tier": 1_400_000, "package": 1_000_000, "priority": 700_000,
         "share": 1_550_000,
         "gross": 1_550_000},
        {"slot_label": "presales", "staff_id": 10,
         "tier": 0, "package": 0, "priority": 0,
         "share": -1_550_000,
         "gross": 1_550_000},
    ],
    formula=("Same person on both slots: each row 1,550,000. "
             "Net to Person X across both rows = 3,100,000."),
))


# -----------------------------------------------------------------------------
# Scenario 3 — No presales: counsellor keeps everything
# -----------------------------------------------------------------------------

results.append(run_scenario(
    "Scenario 3: No presales — counsellor keeps 100%",
    case=_make_case(
        3,
        counsellor_staff_id=10, counsellor_name="Trần Khiết Oanh",
        presales_staff_id=None,
    ),
    ctx=_make_ctx(),
    ref=_make_ref(),
    expected=[
        {"slot_label": "counsellor", "staff_id": 10,
         "tier": 1_400_000, "package": 1_000_000, "priority": 700_000,
         "share": 0,
         "gross": 3_100_000},
    ],
    formula="No presales → no split → counsellor keeps 3,100,000.",
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
