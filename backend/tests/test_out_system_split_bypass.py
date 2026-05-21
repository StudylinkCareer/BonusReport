"""
Unit test for DD-OUT_SYSTEM_SPLIT_BYPASS (Decision 7).

Verifies that OUT_SYSTEM tier cases bypass the Current-Enrolled split
in payment_timing.py.

Run from project root with .venv active:
    python -m pytest backend/tests/test_out_system_split_bypass.py -v
"""
from __future__ import annotations

# Import order matters here: importing backend.engine_runner first lets
# the package finish initialising (resolving the models <-> ytd_aggregator
# <-> adapter cycle) before we directly import from backend.engine.models.
# Without this, the test module triggers a partially-initialized models
# import. Once engine_runner is fully loaded, all symbols below resolve
# normally.
import backend.engine_runner  # noqa: F401  -- import for side effects (cycle resolution)

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from backend.engine.models import (
    BonusPayment,
    CaseInput,
    ReferenceData,
    RunContext,
    Slot,
)
from backend.engine.payment_timing import apply_payment_timing


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

EMPTY_SLOT = Slot(staff_id=None, staff_name=None, role_id=None)


def _filled_slot(staff_id: int = 9, staff_name: str = 'Phạm Thị Lợi',
                 role_id: int = 18) -> Slot:
    return Slot(staff_id=staff_id, staff_name=staff_name, role_id=role_id)


def _make_case(status_code: str = 'Current - Enrolled',
               institution_text_raw: str = 'Victoria University - VU **'
               ) -> CaseInput:
    """SLC-13349-shaped case: out-system marker on institution name,
    sub-agent-referred. Tests can override the status_code or the
    institution_text_raw to flex different scenarios."""
    return CaseInput(
        case_id=231,
        contract_id='SLC-13349',
        student_id='C-11465',
        student_name='Strydom Emile',
        notes=None,
        institution_id=999,                       # dummy id, not looked up here
        institution_text_raw=institution_text_raw,
        referring_partner_id=None,
        referring_sub_agent_id=22,
        referring_agent_text_raw='Công ty TNHH Tư Vấn Di Trú Định Cư HALI',
        system_type_observed='Ngoài hệ thống',
        country_id=1,
        package_service_fee_id=None,
        status_code=status_code,
        application_status_text=status_code,
        client_type_code='DH_GHI_DANH',
        office_id=18,                              # DN
        counsellor=EMPTY_SLOT,
        case_officer=_filled_slot(),
        presales=EMPTY_SLOT,
        vp=EMPTY_SLOT,
        presales_share_pct=Decimal('0'),
        contract_signed_date=date(2023, 9, 26),
        fee_paid_date=date(2023, 9, 26),
        visa_received_date=None,
        enrolled_date=date(2024, 1, 29),
        course_start_date=date(2024, 1, 29),
        course_status=None,
        file_closed_date=None,
    )


def _make_ref(status_code: str = 'Current - Enrolled',
              split_co_sub_pct: Decimal = Decimal('0.5'),
              is_current_enrolled: bool = True,
              is_carry_over: bool = False) -> ReferenceData:
    """Minimal ReferenceData with just enough for payment_timing. Only the
    fields actually read by the timing layer need values; everything else
    uses dataclass defaults."""
    return ReferenceData(
        roles={
            18: {'id': 18, 'code': 'CO_SUB'},
        },
        staff={
            9: {'id': 9, 'canonical_name': 'Phạm Thị Lợi',
                'employment_status': 'ACTIVE',
                'departure_date': None},
        },
        status_splits={
            status_code: {
                'status': status_code,
                'is_current_enrolled': is_current_enrolled,
                'is_carry_over': is_carry_over,
                'is_zero_bonus': False,
                'fees_paid_non_enrolled': False,
                'is_visa_only_paid': False,
                'split_couns_pct': Decimal('1.0'),
                'split_co_dir_pct': Decimal('0.5'),
                'split_co_sub_pct': split_co_sub_pct,
            },
        },
    )


def _make_ctx() -> RunContext:
    """Empty mutable state — OUT_SYSTEM cases don't touch priority,
    clawback, or carry-over."""
    return RunContext(
        year=2024,
        month=1,
        enrolments_by_staff_office={},
        targets_by_staff_office={},
    )


def _make_payment(tier: str = 'OUT_SYSTEM',
                  tier_bonus: int = 400_000,
                  priority_bonus: int = 0) -> BonusPayment:
    """Pre-timing BonusPayment as calc.py would produce, ready for
    apply_payment_timing."""
    return BonusPayment(
        case_id=231,
        staff_id=9,
        staff_name='Phạm Thị Lợi',
        role_id=18,
        slot_label='case_officer',
        tier_bonus=tier_bonus,
        package_bonus=0,
        addon_bonus=0,
        priority_bonus=priority_bonus,
        presales_share_taken=0,
        flat_local_enrolment_bonus=0,
        advance_offset=0,
        gross_bonus=tier_bonus + priority_bonus,
        withheld_amount=0,
        unlocked_amount=0,
        clawback_applied=0,
        bank_transfer_required=False,
        net_payable=tier_bonus + priority_bonus,   # overridden by timing
        calc_notes='',
        audit_json={
            'tier': {
                'tier': tier,
                'as_of_date': '2023-09-26',
                'rate_amount': tier_bonus,
                'country_bucket': 'TARGET',
                'co_sub_subscheme': 'ENROL_ONLY_VISA_ONLY',
            },
        },
        priority_withheld_amount=0,
        priority_unlocked_amount=0,
        priority_schedule_type='STANDARD',
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_out_system_current_enrolled_pays_full_no_split():
    """The bug-fix case: SLC-13349 pattern. OUT_SYSTEM + Current-Enrolled
    should pay the full 400k (not 200k after 50/50 split)."""
    payment = _make_payment(tier='OUT_SYSTEM', tier_bonus=400_000)
    case = _make_case(status_code='Current - Enrolled')
    ref = _make_ref(status_code='Current - Enrolled')
    ctx = _make_ctx()

    result = apply_payment_timing(case, payment, ctx, ref)

    assert result.net_payable == 400_000, (
        f"Expected 400,000 (OUT_SYSTEM bypass pays full), "
        f"got {result.net_payable:,}"
    )
    assert result.withheld_amount == 0, (
        f"Expected 0 withheld (bypass means no deferral), "
        f"got {result.withheld_amount:,}"
    )
    bypass = result.audit_json['payment_timing'].get('out_system_split_bypass')
    assert bypass is not None, (
        "audit_json['payment_timing'] should record the bypass for traceability"
    )
    assert '0.5' in bypass['original_split_pct']


def test_under_tier_current_enrolled_still_applies_split():
    """Sanity: a normal UNDER-tier case should still get the 50/50 split.
    Confirms the bypass is narrowly scoped to OUT_SYSTEM."""
    payment = _make_payment(tier='UNDER', tier_bonus=700_000)
    # Strip the '**' from institution text so the case is hygienically
    # in-system (the bypass is read from audit_json, but the case shouldn't
    # contradict its own tier classification).
    case = _make_case(status_code='Current - Enrolled',
                      institution_text_raw='Some In-System University')
    ref = _make_ref(status_code='Current - Enrolled')
    ctx = _make_ctx()

    result = apply_payment_timing(case, payment, ctx, ref)

    assert result.net_payable == 350_000, (
        f"Expected 350,000 (50% of 700k UNDER), got {result.net_payable:,}"
    )
    assert result.withheld_amount == 350_000
    assert 'out_system_split_bypass' not in result.audit_json['payment_timing'], (
        "UNDER-tier case should NOT trigger the bypass"
    )


def test_out_system_closed_enrolled_no_spurious_bypass_note():
    """OUT_SYSTEM + Closed-Enrolled has split_pct=1.0 already. The bypass
    guard's `!= 1.0` check should prevent a meaningless audit note."""
    payment = _make_payment(tier='OUT_SYSTEM', tier_bonus=400_000)
    case = _make_case(status_code='Closed - Enrolled')
    ref = _make_ref(
        status_code='Closed - Enrolled',
        split_co_sub_pct=Decimal('1.0'),
        is_current_enrolled=False,
    )
    ctx = _make_ctx()

    result = apply_payment_timing(case, payment, ctx, ref)

    assert result.net_payable == 400_000
    assert result.withheld_amount == 0
    assert 'out_system_split_bypass' not in result.audit_json['payment_timing'], (
        "Bypass should not record a note when split_pct was already 1.0"
    )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
