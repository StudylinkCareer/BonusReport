"""Smoke test for the priority_bonus chain.

Run from the backend directory:
    python -m tests.test_priority

Three scenarios:
  1. Direct priority partner (Monash), target HIT → AF=1.0, full bonus.
  2. Direct priority partner (Monash), target NOT hit → AF=0.5, half bonus.
  3. Aggregate priority partner (Navitas group) → resolves via
     aggregate_priority_partner_id, full bonus.

All scenarios use 2024 rates (where bonus_pct was non-zero); 2025 had
all percentages set to 0, which we'll cover separately if needed.

Expected output:

    Scenario 1 (Monash, target hit, AF=1.0):
      counsellor: Truong An tier=1400000 priority=700000 gross=2100000

    Scenario 2 (Monash, target NOT hit, AF=0.5):
      counsellor: Truong An tier=1400000 priority=350000 gross=1750000

    Scenario 3 (La Trobe College via Navitas aggregate, target hit):
      counsellor: Truong An tier=1400000 priority=420000 gross=1820000
"""

from datetime import date
from decimal import Decimal

from engine.models import CaseInput, RunContext, ReferenceData, Slot
from engine.calc import calculate_case


# -----------------------------------------------------------------------------
# Shared reference data
# -----------------------------------------------------------------------------

# Two priority partner rows: a direct one (Monash) and an aggregate one
# (Other Navitas AU). La Trobe College Melbourne links to the aggregate
# via aggregate_priority_partner_id.
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

# Rate row that yields a tier_bonus of 1,400,000 for a counsellor
# meeting target — matches the HCM rate-card row "Meet target,
# incentive < 5M, AU/NZ/SG/...".
RATES = {
    1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_400_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
}


def _make_ref(*, ytd_for_partner: dict[int, int] | None = None) -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=INSTITUTIONS,
        rates=RATES,
        priority_partners=PRIORITY_PARTNERS,
        priority_targets=PRIORITY_TARGETS,
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
        counsellor=Slot(staff_id=10, staff_name="Truong An", role_id=1),
        case_officer=Slot(staff_id=None, staff_name=None, role_id=None),
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2024, 6, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
    )


# -----------------------------------------------------------------------------
# Scenario 1 — direct priority partner, target hit (AF=1.0)
# -----------------------------------------------------------------------------

print("Scenario 1 (Monash, target hit, AF=1.0):")
print("  expected: tier=1400000, priority=700000 (1.4M × 0.5 × 1.0)")
ref = _make_ref()
ctx = _make_ctx(ytd_for_partner={100: 10})  # met target of 10
for p in calculate_case(_make_case(1, institution_id=1), ctx, ref):
    print(f"  {p.slot_label}: {p.staff_name} "
          f"tier={p.tier_bonus} priority={p.priority_bonus} "
          f"gross={p.gross_bonus}")


# -----------------------------------------------------------------------------
# Scenario 2 — direct priority partner, target NOT hit (AF=0.5)
# -----------------------------------------------------------------------------

print()
print("Scenario 2 (Monash, target NOT hit, AF=0.5):")
print("  expected: tier=1400000, priority=350000 (1.4M × 0.5 × 0.5)")
ref = _make_ref()
ctx = _make_ctx(ytd_for_partner={100: 4})  # below target of 10
for p in calculate_case(_make_case(2, institution_id=1), ctx, ref):
    print(f"  {p.slot_label}: {p.staff_name} "
          f"tier={p.tier_bonus} priority={p.priority_bonus} "
          f"gross={p.gross_bonus}")


# -----------------------------------------------------------------------------
# Scenario 3 — aggregate priority partner (Navitas), target hit
# -----------------------------------------------------------------------------

print()
print("Scenario 3 (La Trobe College via Navitas aggregate, target hit):")
print("  expected: tier=1400000, priority=420000 (1.4M × 0.3 × 1.0)")
ref = _make_ref()
ctx = _make_ctx(ytd_for_partner={200: 7})  # met aggregate target of 7
for p in calculate_case(_make_case(3, institution_id=2), ctx, ref):
    print(f"  {p.slot_label}: {p.staff_name} "
          f"tier={p.tier_bonus} priority={p.priority_bonus} "
          f"gross={p.gross_bonus}")
