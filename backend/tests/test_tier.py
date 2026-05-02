"""Smoke test for the tier_bonus chain.

Run from the backend directory:
    python -m tests.test_tier

Expected output:
    counsellor: Trần Khiết Oanh tier_bonus=1000000 gross=1000000 notes=...
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


# Minimal ReferenceData with one country, one institution, one rate row.
ref = ReferenceData(
    countries={
        1: {"id": 1, "code": "AU", "name": "Australia",
            "is_target_country": True, "is_flat_country": False,
            "is_domestic_for": None},
    },
    institutions={
        1: {"id": 1, "canonical_name": "Monash University", "country_id": 1,
            "classification": "IN_SYSTEM_REGULAR"},
    },
    rates={
        1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
            "country_bucket": "TARGET", "tier": "MEET_LOW", "amount": 1_000_000,
            "effective_from": date(2024, 1, 1), "effective_to": None},
    },
    status_splits=TIMING_NEUTRAL_STATUS_SPLITS,
    roles=TIMING_TEST_ROLES,
    staff=TIMING_TEST_STAFF,
)

# RunContext: staff_id=10 hit their target of 2 (will be classified MEET_LOW).
ctx = RunContext(
    year=2025, month=1,
    enrolments_by_staff_office={(10, 1): 2},
    targets_by_staff_office={(10, 1): 2},
)

# Case: AU enrolment, signed 15 Jan 2025, counsellor only.
case = CaseInput(
    case_id=1, contract_id="C001", student_id="S001",
    student_name="Test Student", notes=None,
    institution_id=1, institution_text_raw="Monash",
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
    contract_signed_date=date(2025, 1, 15), fee_paid_date=None,
    visa_received_date=None, enrolled_date=None,
    course_start_date=None, course_status=None, file_closed_date=None,
)

payments = calculate_case(case, ctx, ref)
print(f"Got {len(payments)} payment(s):")
for p in payments:
    print(f"  {p.slot_label}: {p.staff_name} "
          f"tier_bonus={p.tier_bonus} gross={p.gross_bonus} "
          f"notes={p.calc_notes}")
