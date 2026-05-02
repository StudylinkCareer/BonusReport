"""
Shared test fixtures for the timing layer (Phase 6c).

The pre-Phase-6c tests build their own ReferenceData with hard-coded
countries / rates / etc., focused on whatever bonus column they're
testing. They didn't need status_splits or roles because there was no
payment-timing layer.

Now that calc.py runs apply_payment_timing() unconditionally, every
test needs:
  - a status_splits row keyed by case.status_code (so the lookup finds
    something — otherwise StatusSplitNotFoundError)
  - a roles dict keyed by every role_id used by any slot in the test
    (so payment_timing can read role.code to pick the split column)
  - a staff dict keyed by every staff_id used by any slot in the test
    (so payment_timing can check departure_date for §I.6.4)

The fixtures here are deliberately MINIMAL and timing-NEUTRAL:
  - splits = 100% / 100% / 100% → timing layer is a no-op
  - all flags False → no withholding, deferral, or carry-over
  - staff have no departure_date → no §I.6.4 deferral

Result: existing tests pass unchanged, gross_bonus == net_payable.
"""

# Status_splits keyed by the placeholder status code used in tests.
# All percentages 100%, all flags False — timing is a pass-through.
TIMING_NEUTRAL_STATUS_SPLITS = {
    "ENROLLED": {
        "id": 1,
        "status_code": "ENROLLED",
        "split_couns_pct": "1.0",
        "split_co_dir_pct": "1.0",
        "split_co_sub_pct": "1.0",
        "is_carry_over": False,
        "is_current_enrolled": False,
        "is_zero_bonus": False,
        "fees_paid_non_enrolled": False,
        "is_visa_granted": False,
        "counts_as_enrolled": True,
        "deduplication_rank": 5,
    },
}

# Role IDs used across the test suite:
#   role 1 = COUNS_DIR  (counsellor / counsellor director)
#   role 2 = CO_DIR     (case officer direct)
#   role 3 = PRESALES   (presales)
TIMING_TEST_ROLES = {
    1: {"id": 1, "code": "COUNS_DIR", "name": "Counsellor"},
    2: {"id": 2, "code": "CO_DIR", "name": "Case Officer Direct"},
    3: {"id": 3, "code": "PRESALES", "name": "Pre-Sales"},
}

# Staff IDs used across the test suite. departure_date is None for all,
# so §I.6.4 6-month deferral never fires in existing tests.
TIMING_TEST_STAFF = {
    10: {"id": 10, "name": "Trần Khiết Oanh", "office_id": 1,
         "departure_date": None},
    20: {"id": 20, "name": "Quan Hoàng Yến", "office_id": 1,
         "departure_date": None},
    30: {"id": 30, "name": "Pre Sales Bee", "office_id": 1,
         "departure_date": None},
}
