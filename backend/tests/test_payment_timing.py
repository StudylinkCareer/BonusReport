"""Smoke test for the payment_timing layer (Phase 6c).

Run from the backend directory:
    python -m tests.test_payment_timing

Nine scenarios covering every code path in apply_payment_timing:

  1. is_zero_bonus=Y               → all amounts zeroed, no payment
  2. is_current_enrolled=Y         → CO 50% withheld, counsellor 100% paid
  3. is_carry_over=Y + locked rate → uses prior_month_rate, releases prior hold
  4. fees_paid_non_enrolled=Y      → 400k flat tier for OUT_SYSTEM_MA
  5. Recent resignation (<6mo)     → entire bonus deferred (§I.6.4)
  6. Old resignation (6+mo ago)    → bonus released
  7. Clawback fully offset         → applied against current bonus
  8. Clawback exceeds bonus        → bank_transfer_required=True
  9. CO_SUB role split column      → uses split_co_sub_pct, not co_dir

Each scenario uses a fresh ReferenceData and CaseInput so they don't
share state. Output uses the same PASS/FAIL marker pattern as the
other test files.
"""

from datetime import date
from decimal import Decimal

from engine.models import CaseInput, RunContext, ReferenceData, Slot
from engine.calc import calculate_case
from tests._timing_fixtures import TIMING_TEST_STAFF


# =============================================================================
# Shared base reference data
# =============================================================================
# These are the standard fixtures used across most scenarios. Individual
# scenarios override status_splits, staff, or rates as needed.

COUNTRIES = {
    1: {"id": 1, "code": "AU", "name": "Australia",
        "is_target_country": True, "is_flat_country": False,
        "is_domestic_for": None},
}

# Three institution classifications so we can test the
# fees_paid_non_enrolled override.
INSTITUTIONS = {
    1: {"id": 1, "canonical_name": "Generic AU University", "country_id": 1,
        "classification": "IN_SYSTEM_REGULAR",
        "priority_partner_id": None, "aggregate_priority_partner_id": None},
    2: {"id": 2, "canonical_name": "Out-System Master Agent Uni",
        "country_id": 1, "classification": "OUT_SYSTEM_MASTER_AGENT",
        "priority_partner_id": None, "aggregate_priority_partner_id": None},
}

# Standard rate rows: counsellor 1,400,000 / CO 1,000,000 at MEET_LOW.
# Plus a CO_SUB rate (role 4) for scenario 9.
RATES = {
    1: {"id": 1, "office_id": 1, "role_id": 1, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_400_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
    2: {"id": 2, "office_id": 1, "role_id": 2, "co_sub_subscheme": None,
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 1_000_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
    # CO_SUB at MEET_LOW = 800k (lower than CO_DIR by convention).
    # Subscheme matches what scenario 9 overrides on the case.
    4: {"id": 4, "office_id": 1, "role_id": 4,
        "co_sub_subscheme": "ENROL_ONLY_VISA_ONLY",
        "country_bucket": "TARGET", "tier": "MEET_LOW",
        "amount": 800_000,
        "effective_from": date(2024, 1, 1), "effective_to": None},
}

# Roles — extended from _timing_fixtures to add CO_SUB.
ROLES = {
    1: {"id": 1, "code": "COUNS_DIR", "name": "Counsellor"},
    2: {"id": 2, "code": "CO_DIR", "name": "Case Officer Direct"},
    3: {"id": 3, "code": "PRESALES", "name": "Pre-Sales"},
    4: {"id": 4, "code": "CO_SUB", "name": "Case Officer Sub-Agent"},
}

# Calculation params — needed for fees_paid_non_enrolled scenario.
CALCULATION_PARAMS = {
    "FEES_PAID_NON_ENROLLED_RATE": {
        "code": "FEES_PAID_NON_ENROLLED_RATE",
        "value_numeric": 400_000,
        "description": "Flat fee for OUT_SYSTEM_MA cases with fees paid but no enrolment",
    },
}


# =============================================================================
# Status split fixtures — one per scenario, named clearly
# =============================================================================

def _split_row(
    code: str,
    *,
    couns_pct: str = "1.0",
    co_dir_pct: str = "1.0",
    co_sub_pct: str = "1.0",
    is_carry_over: bool = False,
    is_current_enrolled: bool = False,
    is_zero_bonus: bool = False,
    fees_paid_non_enrolled: bool = False,
) -> dict:
    """Helper to build a status_split row with sensible defaults."""
    return {
        "id": 1,
        "status_code": code,
        "split_couns_pct": couns_pct,
        "split_co_dir_pct": co_dir_pct,
        "split_co_sub_pct": co_sub_pct,
        "is_carry_over": is_carry_over,
        "is_current_enrolled": is_current_enrolled,
        "is_zero_bonus": is_zero_bonus,
        "fees_paid_non_enrolled": fees_paid_non_enrolled,
        "is_visa_granted": False,
        "counts_as_enrolled": True,
        "deduplication_rank": 5,
    }


# =============================================================================
# Helpers
# =============================================================================

def _make_ctx(
    *,
    clawback_balances: dict[int, int] | None = None,
    prior_withholdings: dict[tuple[int, int], int] | None = None,
    year: int = 2025,
    month: int = 6,
) -> RunContext:
    return RunContext(
        year=year, month=month,
        enrolments_by_staff_office={(10, 1): 2, (20, 1): 2, (40, 1): 2},
        targets_by_staff_office={(10, 1): 2, (20, 1): 2, (40, 1): 2},
        enrolments_by_priority_partner_ytd={},
        clawback_balances_by_staff=clawback_balances or {},
        prior_withholdings_by_case_staff=prior_withholdings or {},
    )


def _make_ref(
    status_splits: dict,
    *,
    staff: dict | None = None,
    institutions: dict | None = None,
) -> ReferenceData:
    return ReferenceData(
        countries=COUNTRIES,
        institutions=institutions or INSTITUTIONS,
        rates=RATES,
        roles=ROLES,
        staff=staff or TIMING_TEST_STAFF,
        status_splits=status_splits,
        calculation_params=CALCULATION_PARAMS,
    )


def _make_case(
    case_id: int,
    *,
    status_code: str,
    institution_id: int = 1,
    counsellor_role: int = 1,
    co_role: int | None = 2,
    co_staff_id: int = 20,
    co_staff_name: str = "Quan Hoàng Yến",
    prior_month_rate: int | None = None,
    co_sub_override: str | None = None,
) -> CaseInput:
    return CaseInput(
        case_id=case_id, contract_id=f"C{case_id:03d}",
        student_id=f"S{case_id:03d}", student_name="Test Student", notes=None,
        institution_id=institution_id, institution_text_raw="(test)",
        referring_partner_id=None, referring_sub_agent_id=None,
        referring_agent_text_raw=None, system_type_observed=None,
        country_id=1, package_service_fee_id=None,
        status_code=status_code, application_status_text=None,
        client_type_code="AE", office_id=1,
        counsellor=Slot(staff_id=10, staff_name="Trần Khiết Oanh",
                        role_id=counsellor_role),
        case_officer=(
            Slot(staff_id=co_staff_id, staff_name=co_staff_name, role_id=co_role)
            if co_role is not None else
            Slot(staff_id=None, staff_name=None, role_id=None)
        ),
        presales=Slot(staff_id=None, staff_name=None, role_id=None),
        vp=Slot(staff_id=None, staff_name=None, role_id=None),
        presales_share_pct=Decimal("0"),
        contract_signed_date=date(2025, 6, 15), fee_paid_date=None,
        visa_received_date=None, enrolled_date=None,
        course_start_date=None, course_status=None, file_closed_date=None,
        prior_month_rate=prior_month_rate,
        co_sub_subscheme_override=co_sub_override,
    )


# =============================================================================
# Pretty-printer
# =============================================================================

def run_scenario(label: str, formula: str) -> bool:
    """Decorator-like context: returns a function that runs and prints."""
    print()
    print("=" * 100)
    print(f"  {label}")
    print("=" * 100)
    print(f"  {formula}")
    return True


def check_payment(p, slot_label: str, *, expected: dict) -> bool:
    """
    Compare one BonusPayment against a dict of expected values.
    Returns True if all match. Prints a per-line marker.
    """
    checks = {
        'tier': p.tier_bonus,
        'gross': p.gross_bonus,
        'net': p.net_payable,
        'withheld': p.withheld_amount,
        'unlocked': p.unlocked_amount,
        'clawback': p.clawback_applied,
        'btr': p.bank_transfer_required,
    }
    # Only compare keys present in `expected`.
    diffs = {k: (v, expected[k]) for k, v in checks.items()
             if k in expected and v != expected[k]}
    ok = (p.slot_label == slot_label) and not diffs
    marker = "[ok]" if ok else "[BAD]"
    print(f"  {marker} {p.slot_label:13s} {p.staff_name:18s} "
          f"tier={p.tier_bonus:>10,}  "
          f"gross={p.gross_bonus:>10,}  "
          f"net={p.net_payable:>10,}  "
          f"withheld={p.withheld_amount:>10,}  "
          f"unlocked={p.unlocked_amount:>10,}  "
          f"clawback={p.clawback_applied:>10,}  "
          f"btr={p.bank_transfer_required}")
    if diffs:
        for field, (got, want) in diffs.items():
            print(f"        {field}: got {got!r}, expected {want!r}")
    return ok


# =============================================================================
# Scenarios
# =============================================================================

results: list[bool] = []


# -----------------------------------------------------------------------------
# Scenario 1: is_zero_bonus=Y
# -----------------------------------------------------------------------------
# A "Closed - Cancelled" case. All amounts zeroed, no payment.

run_scenario(
    "Scenario 1: is_zero_bonus=Y → all amounts zeroed",
    "Closed - Cancelled status: zero bonus across the board, no payment.",
)
splits = {"CLOSED_CANCELLED": _split_row("CLOSED_CANCELLED", is_zero_bonus=True)}
ref = _make_ref(splits)
ctx = _make_ctx()
case = _make_case(1, status_code="CLOSED_CANCELLED")
payments = calculate_case(case, ctx, ref)

ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 0, 'gross': 0, 'net': 0,
                            'withheld': 0, 'unlocked': 0, 'clawback': 0,
                            'btr': False})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 0, 'gross': 0, 'net': 0,
                                'withheld': 0, 'unlocked': 0, 'clawback': 0,
                                'btr': False})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 2: is_current_enrolled=Y → CO 50% withheld
# -----------------------------------------------------------------------------
# "Current - Enrolled": Counsellor paid 100% now, CO paid 50% now with
# the other 50% deferred until visa is granted.

run_scenario(
    "Scenario 2: is_current_enrolled=Y → counsellor 100%, CO 50% (50% withheld)",
    "Current - Enrolled status: counsellor 1,400,000 / CO 500,000 paid now; CO 500,000 withheld.",
)
splits = {"CURRENT_ENROLLED": _split_row(
    "CURRENT_ENROLLED",
    couns_pct="1.0", co_dir_pct="0.5", co_sub_pct="0.5",
    is_current_enrolled=True,
)}
ref = _make_ref(splits)
ctx = _make_ctx()
case = _make_case(2, status_code="CURRENT_ENROLLED")
payments = calculate_case(case, ctx, ref)

ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_400_000, 'gross': 1_400_000,
                            'net': 1_400_000, 'withheld': 0})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 1_000_000, 'gross': 1_000_000,
                                'net': 500_000, 'withheld': 500_000})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 3: is_carry_over=Y with prior_month_rate locked
# -----------------------------------------------------------------------------
# "Closed - Enrolled, then Visa granted". Counsellor 0% (already paid
# last month), CO 50% (the deferred half from last month). Tier locks
# to prior_month_rate per Q3.4. Prior withholding of 500,000 unlocks
# this run.

run_scenario(
    "Scenario 3: is_carry_over=Y + prior_month_rate locked → CO releases the deferred 50%",
    "CO uses locked rate 1,000,000; prior withhold 500,000 reported as unlocked.",
)
splits = {"CARRY_OVER": _split_row(
    "CARRY_OVER",
    couns_pct="0.0", co_dir_pct="0.5", co_sub_pct="0.5",
    is_carry_over=True,
)}
ref = _make_ref(splits)
ctx = _make_ctx(prior_withholdings={(3, 20): 500_000})
case = _make_case(3, status_code="CARRY_OVER", prior_month_rate=1_000_000)
payments = calculate_case(case, ctx, ref)

# Counsellor: 0% split, no prior hold to release → all zero.
# CO: tier=1,000,000 (locked), gross=1,000,000, base_payable=500,000
#     unlocked=500,000 (released from prior month's withhold)
#     net = 500,000 + 500,000 = 1,000,000
ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_000_000, 'gross': 1_000_000,
                            'net': 0, 'withheld': 0, 'unlocked': 0})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 1_000_000, 'gross': 1_000_000,
                                'net': 1_000_000, 'withheld': 0,
                                'unlocked': 500_000})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 4: fees_paid_non_enrolled=Y on OUT_SYSTEM_MA case
# -----------------------------------------------------------------------------
# "Closed - Visa granted then cancelled" on an OUT_SYSTEM_MA institution.
# Tier overrides to 400k flat for both counsellor and CO. No carry-over
# or current-enrolled flags, just the tier-level override (Decision 1).
#
# Note: the row also sets pcts to 1.0 because the override is a tier
# rule, not a timing rule — payment then flows at full amount.

run_scenario(
    "Scenario 4: fees_paid_non_enrolled=Y on OUT_SYSTEM_MA → tier overrides to 400k flat",
    "Counsellor and CO both get 400k flat tier (Decision 1, calc_tier override).",
)
splits = {"FEES_PAID_NO_ENROL": _split_row(
    "FEES_PAID_NO_ENROL",
    fees_paid_non_enrolled=True,
)}
ref = _make_ref(splits)
ctx = _make_ctx()
case = _make_case(4, status_code="FEES_PAID_NO_ENROL", institution_id=2)  # OUT_SYSTEM_MA
payments = calculate_case(case, ctx, ref)

ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 400_000, 'gross': 400_000,
                            'net': 400_000, 'withheld': 0})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 400_000, 'gross': 400_000,
                                'net': 400_000, 'withheld': 0})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 5: Recent resignation (< 6 months) → all bonus deferred
# -----------------------------------------------------------------------------
# Staff resigned 3 months ago. Per §I.6.4, entire bonus is held until
# 6 months past resignation date.

run_scenario(
    "Scenario 5: Resigned 3 months ago → all bonus deferred (§I.6.4)",
    "Counsellor's full 1,400,000 withheld; CO unaffected (still active).",
)
splits = {"NORMAL": _split_row("NORMAL")}
# Counsellor (staff 10) resigned 3 months before run-month (Jun 2025) → Mar 2025.
# CO (staff 20) is still active.
staff_with_resignation = {
    10: {"id": 10, "name": "Trần Khiết Oanh", "office_id": 1,
         "departure_date": date(2025, 3, 15)},
    20: {"id": 20, "name": "Quan Hoàng Yến", "office_id": 1,
         "departure_date": None},
}
ref = _make_ref(splits, staff=staff_with_resignation)
ctx = _make_ctx(year=2025, month=6)
case = _make_case(5, status_code="NORMAL")
payments = calculate_case(case, ctx, ref)

# Counsellor: resigned Mar 2025, run Jun 2025 → 3 months → all withheld.
# CO: not resigned → paid normally.
ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_400_000, 'gross': 1_400_000,
                            'net': 0, 'withheld': 1_400_000})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 1_000_000, 'gross': 1_000_000,
                                'net': 1_000_000, 'withheld': 0})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 6: Old resignation (6+ months ago) → bonus released
# -----------------------------------------------------------------------------
# Staff resigned 7 months ago — past the 6-month deferral threshold.
# Bonus pays out normally.

run_scenario(
    "Scenario 6: Resigned 7 months ago → bonus released (§I.6.4 threshold met)",
    "Counsellor's full 1,400,000 paid out; CO unaffected.",
)
splits = {"NORMAL": _split_row("NORMAL")}
staff_with_old_resignation = {
    10: {"id": 10, "name": "Trần Khiết Oanh", "office_id": 1,
         "departure_date": date(2024, 11, 15)},  # 7 months before Jun 2025
    20: {"id": 20, "name": "Quan Hoàng Yến", "office_id": 1,
         "departure_date": None},
}
ref = _make_ref(splits, staff=staff_with_old_resignation)
ctx = _make_ctx(year=2025, month=6)
case = _make_case(6, status_code="NORMAL")
payments = calculate_case(case, ctx, ref)

ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_400_000, 'gross': 1_400_000,
                            'net': 1_400_000, 'withheld': 0})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 1_000_000, 'gross': 1_000_000,
                                'net': 1_000_000, 'withheld': 0})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 7: Clawback fully offset by current bonus
# -----------------------------------------------------------------------------
# Counsellor has a 600k clawback balance. Current bonus is 1,400,000.
# Clawback fully consumed; net = 1,400,000 - 600,000 = 800,000.
# bank_transfer_required = False (offset succeeded).

run_scenario(
    "Scenario 7: Clawback fully offset → net reduced, no bank transfer",
    "Counsellor: 1,400,000 gross, 600,000 clawback applied → net 800,000.",
)
splits = {"NORMAL": _split_row("NORMAL")}
ref = _make_ref(splits)
ctx = _make_ctx(clawback_balances={10: 600_000})
case = _make_case(7, status_code="NORMAL")
payments = calculate_case(case, ctx, ref)

ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_400_000, 'gross': 1_400_000,
                            'net': 800_000, 'clawback': 600_000,
                            'btr': False})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 1_000_000, 'gross': 1_000_000,
                                'net': 1_000_000, 'clawback': 0,
                                'btr': False})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 8: Clawback exceeds current bonus → bank transfer flagged
# -----------------------------------------------------------------------------
# Counsellor resigned 2 months ago AND has a 2,000,000 clawback balance.
# All current bonus deferred (recent resignation), so clawback can't be
# offset against current pay → bank_transfer_required = True.
#
# This combines deferral and clawback in the same case to exercise the
# "balance can't be offset" path.

run_scenario(
    "Scenario 8: Clawback can't offset (resigned + balance > 0) → bank transfer flagged",
    "Counsellor resigned 2mo ago + clawback 2,000,000; base_payable=0 → bank_transfer_required.",
)
splits = {"NORMAL": _split_row("NORMAL")}
staff_recent_resigned = {
    10: {"id": 10, "name": "Trần Khiết Oanh", "office_id": 1,
         "departure_date": date(2025, 4, 15)},  # 2 months before Jun 2025
    20: {"id": 20, "name": "Quan Hoàng Yến", "office_id": 1,
         "departure_date": None},
}
ref = _make_ref(splits, staff=staff_recent_resigned)
ctx = _make_ctx(year=2025, month=6, clawback_balances={10: 2_000_000})
case = _make_case(8, status_code="NORMAL")
payments = calculate_case(case, ctx, ref)

# Counsellor: gross 1,400,000 → all deferred (base_payable=0) →
#             clawback can't apply → bank_transfer_required=True
ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_400_000, 'gross': 1_400_000,
                            'net': 0, 'withheld': 1_400_000,
                            'clawback': 0, 'btr': True})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 1_000_000, 'gross': 1_000_000,
                                'net': 1_000_000, 'btr': False})
)
print(f"  {'[PASS]' if ok else '[FAIL]'}")
results.append(ok)


# -----------------------------------------------------------------------------
# Scenario 9: CO_SUB role uses split_co_sub_pct column
# -----------------------------------------------------------------------------
# Per Decision 2: CO_DIR and CO_SUB never share a bonus on the same case;
# the column to read is selected by the slot's role_id. This scenario uses
# a status row where CO_DIR and CO_SUB have different percentages, and
# verifies a CO_SUB slot reads the right column.

run_scenario(
    "Scenario 9: CO_SUB role reads split_co_sub_pct (not split_co_dir_pct)",
    "Status: co_dir_pct=1.0 / co_sub_pct=0.0 → CO_SUB gets 0, proves column selection by role.",
)
splits = {"VISA_ONLY": _split_row(
    "VISA_ONLY",
    couns_pct="1.0", co_dir_pct="1.0", co_sub_pct="0.0",
)}
# Add staff 40 (a CO_SUB).
staff_with_co_sub = {
    **TIMING_TEST_STAFF,
    40: {"id": 40, "name": "Lê Thị Trường An", "office_id": 1,
         "departure_date": None},
}
ref = _make_ref(splits, staff=staff_with_co_sub)
ctx = _make_ctx()
# CO slot is filled by a CO_SUB (role_id=4) instead of CO_DIR (role_id=2).
case = _make_case(
    9, status_code="VISA_ONLY",
    co_role=4, co_staff_id=40, co_staff_name="Lê Thị Trường An",
    co_sub_override="ENROL_ONLY_VISA_ONLY",
)
payments = calculate_case(case, ctx, ref)

# Counsellor: 100% (split_couns_pct = 1.0)
# CO_SUB: 0% (split_co_sub_pct = 0.0) → all withheld
ok = (
    check_payment(payments[0], "counsellor",
                  expected={'tier': 1_400_000, 'gross': 1_400_000,
                            'net': 1_400_000, 'withheld': 0})
    and check_payment(payments[1], "case_officer",
                      expected={'tier': 800_000, 'gross': 800_000,
                                'net': 0, 'withheld': 0})
    # Note: withheld=0 because is_current_enrolled=False → split=0%
    # means the unpaid 50% is just "not earned this run", not "withheld
    # for next run". The withhold mechanism only fires when
    # is_current_enrolled=Y. CO_SUB earning 0 for visa-only is the
    # policy data bug you flagged — the engine respects the data.
)
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
