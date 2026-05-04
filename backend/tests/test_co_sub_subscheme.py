"""Smoke test for the CO_SUB subscheme resolution (item 3).

Run from the backend directory:
    python -m tests.test_co_sub_subscheme

Four scenarios covering every path in resolve_co_sub_subscheme:

  1. ref_staff_target row → ENROL_ONLY_VISA_ONLY rate (real-world Trường An)
  2. ref_staff_target row → ENROL_PLUS_VISA rate (different subscheme)
  3. case.co_sub_subscheme_override wins over ref_staff_target row
  4. No override + no matching row → CoSubSubschemeNotFoundError

The four scenarios prove:
  - The right rate row is selected per subscheme (different rate cards)
  - Pattern Y override hatch works (per-case override beats DB)
  - Hard fail fires when both fail (consistent with rest of engine)
"""

from datetime import date
from decimal import Decimal

from engine.models import CaseInput, RunContext, ReferenceData, Slot
from engine.calc import calculate_case
from engine.lookups import CoSubSubschemeNotFoundError
from tests._timing_fixtures import (
    TIMING_NEUTRAL_STATUS_SPLITS,
    TIMING_TEST_STAFF,
)


# =============================================================================
# Reference data
# =============================================================================

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

# Roles — we need CO_SUB (id=4) for these tests.
ROLES = {
    1: {"id": 1, "code": "COUNS_DIR", "name": "Counsellor"},
    2: {"id": 2, "code": "CO_DIR",    "name": "Case Officer Direct"},
    3: {"id": 3, "code": "PRESALES",  "name": "Pre-Sales"},
    4: {"id": 4, "code": "CO_SUB",    "name": "Case Officer Sub-Agent"},
}

# Rate rows for both subschemes. Real values from D6.R6 (per Phase5_02
# seed data line 524, MEET_HIGH and MEET_LOW have identical amounts).
# Both UNDER and OVER tiers included so the test isn't brittle to
# whatever tier the classifier picks.
RATES = {
    1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW", "amount": 1_400_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
    # ENROL_ONLY_VISA_ONLY — flat 900K across MEET tiers, plus UNDER/OVER
    100: {"id": 100, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_ONLY_VISA_ONLY",
          "country_bucket": "TARGET", "tier": "UNDER", "amount": 700_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    101: {"id": 101, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_ONLY_VISA_ONLY",
          "country_bucket": "TARGET", "tier": "MEET_LOW", "amount": 900_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    102: {"id": 102, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_ONLY_VISA_ONLY",
          "country_bucket": "TARGET", "tier": "MEET_HIGH", "amount": 900_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    103: {"id": 103, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_ONLY_VISA_ONLY",
          "country_bucket": "TARGET", "tier": "OVER", "amount": 1_100_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    # ENROL_PLUS_VISA — flat 1.1M across MEET tiers, plus UNDER/OVER
    110: {"id": 110, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_PLUS_VISA",
          "country_bucket": "TARGET", "tier": "UNDER", "amount": 800_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    111: {"id": 111, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_PLUS_VISA",
          "country_bucket": "TARGET", "tier": "MEET_LOW", "amount": 1_100_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    112: {"id": 112, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_PLUS_VISA",
          "country_bucket": "TARGET", "tier": "MEET_HIGH", "amount": 1_100_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
    113: {"id": 113, "office_id": 1, "role_id": 4,
          "co_sub_subscheme": "ENROL_PLUS_VISA",
          "country_bucket": "TARGET", "tier": "OVER", "amount": 1_300_000,
          "effective_from": date(2024, 1, 1), "effective_to": None},
}

# Lê Thị Trường An is a real CO_SUB.
STAFF = {
    **TIMING_TEST_STAFF,
    40: {"id": 40, "name": "Lê Thị Trường An", "office_id": 1,
         "departure_date": None},
}

# ref_staff_target rows. Two scenarios use this:
#   scenario 1 → row says ENROL_ONLY_VISA_ONLY (her real-world subscheme)
#   scenario 2 → row says ENROL_PLUS_VISA (hypothetical alternate)
# Each scenario builds its own STAFF_TARGETS dict by re-using the helper.

def _staff_targets_with_subscheme(subscheme: str) -> dict:
    """Build a ref_staff_target dict with one row for staff 40 in 2025-06."""
    return {
        1: {
            "id": 1,
            "staff_id": 40,
            "role_id": 4,
            "office_id": 1,
            "year": 2025,
            "month": 6,
            "target": 13,
            "co_sub_subscheme": subscheme,
        },
    }


def _make_ref(*, staff_targets: dict) -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=INSTITUTIONS,
        rates=RATES,
        roles=ROLES,
        staff=STAFF,
        status_splits=TIMING_NEUTRAL_STATUS_SPLITS,
        staff_targets=staff_targets,
    )


def _make_ctx() -> RunContext:
    return RunContext(
        year=2025, month=6,
        # CO_SUB staff 40 hits target → MEET_LOW tier
        enrolments_by_staff_office={(40, 1): 13},
        targets_by_staff_office={(40, 1): 13},
    )


def _make_case(
    case_id: int,
    *,
    co_sub_override: str | None = None,
) -> CaseInput:
    """Case with a CO_SUB slot filled by Lê Thị Trường An (id 40)."""
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=1, institution_text_raw="(test)",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=None,
        status_code="ENROLLED", application_status_text=None,
        client_type_code="AE", office_id=1,
        # Counsellor slot is left empty — we're testing the CO_SUB path.
        counsellor=Slot(staff_id=None, staff_name=None, role_id=None),
        case_officer=Slot(staff_id=40, staff_name="Lê Thị Trường An", role_id=4),
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2025, 6, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
        co_sub_subscheme_override=co_sub_override,
    )


# =============================================================================
# Pretty-printer
# =============================================================================

def run_scenario(label: str, formula: str) -> None:
    print()
    print("=" * 100)
    print(f"  {label}")
    print("=" * 100)
    print(f"  {formula}")


def check(p, *, expected_tier: int, expected_subscheme: str | None) -> bool:
    """Compare BonusPayment tier against expectation, plus audit subscheme."""
    audit_subscheme = p.audit_json.get('tier', {}).get('co_sub_subscheme')
    tier_ok = p.tier_bonus == expected_tier
    sub_ok = audit_subscheme == expected_subscheme
    ok = tier_ok and sub_ok
    marker = "[ok]" if ok else "[BAD]"
    print(f"  {marker} {p.slot_label:13s} {p.staff_name:18s} "
          f"tier={p.tier_bonus:>10,}  "
          f"audit_subscheme={audit_subscheme!r}")
    if not tier_ok:
        print(f"        tier mismatch: got {p.tier_bonus:,}, "
              f"expected {expected_tier:,}")
    if not sub_ok:
        print(f"        subscheme mismatch: got {audit_subscheme!r}, "
              f"expected {expected_subscheme!r}")
    return ok


# =============================================================================
# Scenarios
# =============================================================================

results: list[bool] = []


# -----------------------------------------------------------------------------
# Scenario 1: ENROL_ONLY_VISA_ONLY via ref_staff_target
# -----------------------------------------------------------------------------

run_scenario(
    "Scenario 1: CO_SUB resolves to ENROL_ONLY_VISA_ONLY via ref_staff_target",
    "Lê Thị Trường An (CO_SUB) at MEET_LOW, scheme = ENROL_ONLY_VISA_ONLY → 900,000.",
)
ref = _make_ref(staff_targets=_staff_targets_with_subscheme("ENROL_ONLY_VISA_ONLY"))
ctx = _make_ctx()
case = _make_case(1)
payments = calculate_case(case, ctx, ref)
ok = check(payments[0], expected_tier=900_000,
           expected_subscheme="ENROL_ONLY_VISA_ONLY")
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 2: ENROL_PLUS_VISA via ref_staff_target
# -----------------------------------------------------------------------------

run_scenario(
    "Scenario 2: CO_SUB resolves to ENROL_PLUS_VISA via ref_staff_target",
    "Lê Thị Trường An at MEET_LOW, scheme = ENROL_PLUS_VISA → 1,100,000.",
)
ref = _make_ref(staff_targets=_staff_targets_with_subscheme("ENROL_PLUS_VISA"))
ctx = _make_ctx()
case = _make_case(2)
payments = calculate_case(case, ctx, ref)
ok = check(payments[0], expected_tier=1_100_000,
           expected_subscheme="ENROL_PLUS_VISA")
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 3: case override beats ref_staff_target
# -----------------------------------------------------------------------------

run_scenario(
    "Scenario 3: case.co_sub_subscheme_override wins over ref_staff_target",
    "Target row says ENROL_ONLY_VISA_ONLY (900K), override says ENROL_PLUS_VISA (1.1M). "
    "Override should win.",
)
# Target row says ENROL_ONLY_VISA_ONLY but case overrides to ENROL_PLUS_VISA.
ref = _make_ref(staff_targets=_staff_targets_with_subscheme("ENROL_ONLY_VISA_ONLY"))
ctx = _make_ctx()
case = _make_case(3, co_sub_override="ENROL_PLUS_VISA")
payments = calculate_case(case, ctx, ref)
ok = check(payments[0], expected_tier=1_100_000,
           expected_subscheme="ENROL_PLUS_VISA")
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 4: No override + no matching row → hard fail
# -----------------------------------------------------------------------------

run_scenario(
    "Scenario 4: No override + no matching ref_staff_target row → hard fail",
    "CoSubSubschemeNotFoundError should be raised — no fallback to a default.",
)
# Empty staff_targets dict, no override on case.
ref = _make_ref(staff_targets={})
ctx = _make_ctx()
case = _make_case(4)
ok = False
try:
    calculate_case(case, ctx, ref)
    print("  [BAD] Expected CoSubSubschemeNotFoundError but no exception was raised.")
except CoSubSubschemeNotFoundError as e:
    print(f"  [ok] Raised CoSubSubschemeNotFoundError as expected.")
    print(f"        message: {str(e)[:120]}...")
    ok = True
except Exception as e:
    print(f"  [BAD] Raised {type(e).__name__} instead of CoSubSubschemeNotFoundError.")
    print(f"        message: {e}")
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# =============================================================================
# Summary
# =============================================================================

print()
print("=" * 100)
passed = sum(results)
total = len(results)
if passed == total:
    print(f"  ALL PASS ({passed}/{total})")
else:
    print(f"  FAILED: {total - passed}/{total} scenario(s) did not match")
print("=" * 100)
