"""Smoke test for the flat_local_enrolment_bonus chain.

Run from the backend directory:
    python -m tests.test_flat_local

Two scenarios:
  1. Solo counsellor on a VN-domestic case → counsellor gets 100%,
     tier_bonus is bypassed.
  2. Counsellor + CO paired → 50/50 split, tier_bonus still bypassed.

Expected output:
    Scenario 1 (solo counsellor):
      counsellor: Trần Khiết Oanh tier=0 flat_local=1000000 gross=1000000

    Scenario 2 (counsellor + CO paired):
      counsellor: Trần Khiết Oanh tier=0 flat_local=500000 gross=500000
      case_officer: Quan Hoàng Yến tier=0 flat_local=500000 gross=500000
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
            "is_domestic_for": 1},  # VN is domestic for office 1
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


def _make_case(case_id: int, *, with_co: bool) -> CaseInput:
    """Build a VN-domestic case, optionally with a CO slot filled."""
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
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2025, 1, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
    )


# -----------------------------------------------------------------------------
# Scenario 1 — solo counsellor
# -----------------------------------------------------------------------------

print("Scenario 1 (solo counsellor on VN case):")
for p in calculate_case(_make_case(1, with_co=False), ctx, ref):
    print(f"  {p.slot_label}: {p.staff_name} "
          f"tier={p.tier_bonus} flat_local={p.flat_local_enrolment_bonus} "
          f"gross={p.gross_bonus}")

# -----------------------------------------------------------------------------
# Scenario 2 — counsellor + CO paired
# -----------------------------------------------------------------------------

print()
print("Scenario 2 (counsellor + CO paired on VN case):")
for p in calculate_case(_make_case(2, with_co=True), ctx, ref):
    print(f"  {p.slot_label}: {p.staff_name} "
          f"tier={p.tier_bonus} flat_local={p.flat_local_enrolment_bonus} "
          f"gross={p.gross_bonus}")
