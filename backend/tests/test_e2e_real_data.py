"""
End-to-end smoke test for the data layer + engine.

Run from the backend directory:
    python -m tests.test_e2e_real_data

Goal:
  Prove that calculate_case(...) runs successfully against a
  ReferenceData built from the live Postgres database — not
  from in-memory fixtures. This is the first time the engine
  has touched real data.

Approach:
  1. Load ReferenceData from Postgres.
  2. Pick a real status_code, real institution, real staff member.
  3. Build a hand-crafted CaseInput pointing at those real IDs.
  4. Build a minimal RunContext.
  5. Call calculate_case and print the result.

Real staff (per ref_staff seed data, May 2026):
  Counsellors (COUNS_DIR): La Tất Thành, Nguyễn Thị Hồng Hạnh,
                           Trần Khiết Oanh
  CO_DIR:                  Quan Hoàng Yến, Đoàn Ngọc Trúc Quỳnh,
                           Trần Thanh Gia Mẫn, Thái Thị Huỳnh Anh,
                           Nguyễn Hoàng Thúy An, Trần Nguyễn Tâm Nguyên
  CO_SUB:                  Lê Thị Trường An, Phạm Thị Ngọc Thảo,
                           Phạm Thị Ngọc Viên, Phạm Thị Lợi
This script picks staff dynamically by role_id from the database —
whichever rows the DB returns for COUNS_DIR and CO_DIR are used.

This is a SMOKE test, not an assertion test — its job is to
surface mismatches between engine assumptions and real data
shape, NOT to validate any specific bonus amount. Whatever
amount the engine produces tells us the wiring works; we'd
need a second pass with hand-computed expected values to
validate correctness.

Diagnostic-first: every step prints what it found. If something
errors, the printout shows exactly which step.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from data.connection import get_connection
from data.reference_data import load_reference_data
from engine.models import CaseInput, RunContext, Slot
from engine.calc import calculate_case


# ---------------------------------------------------------------------------
# Helpers — find real IDs by their stable code/name
# ---------------------------------------------------------------------------

def _find_one(rows: dict, **predicates) -> dict | None:
    """Return the first row whose columns match every predicate, or None."""
    for row in rows.values():
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    return None


def _find_status(ref, code_substring: str) -> str | None:
    """Find a status_code that contains the given substring."""
    for status_code in ref.status_splits:
        if code_substring.lower() in status_code.lower():
            return status_code
    return None


# ---------------------------------------------------------------------------
# Step 1 — Load ref data
# ---------------------------------------------------------------------------

print("=" * 80)
print("STEP 1: Load ReferenceData from Postgres")
print("=" * 80)

with get_connection() as conn:
    ref = load_reference_data(conn)

print(f"  Loaded {sum(1 for _ in [ref.countries, ref.offices, ref.roles])} dim tables, "
      f"{len(ref.rates)} rate rows, {len(ref.staff)} staff.")


# ---------------------------------------------------------------------------
# Step 2 — Resolve real IDs
# ---------------------------------------------------------------------------

print()
print("=" * 80)
print("STEP 2: Resolve real entities by code/name")
print("=" * 80)

# Office: Ho Chi Minh
office = _find_one(ref.offices, code='HCM')
assert office is not None, "Couldn't find HCM office"
print(f"  Office:        {office['name']} (id={office['id']})")

# Country: Australia
country = _find_one(ref.countries, code='AU')
assert country is not None, "Couldn't find AU"
print(f"  Country:       {country['name']} (id={country['id']})")

# Role: COUNS_DIR
counsellor_role = _find_one(ref.roles, code='COUNS_DIR')
assert counsellor_role is not None, "Couldn't find COUNS_DIR role"
print(f"  Role (couns):  {counsellor_role['name']} (id={counsellor_role['id']})")

co_dir_role = _find_one(ref.roles, code='CO_DIR')
assert co_dir_role is not None, "Couldn't find CO_DIR role"
print(f"  Role (CO):     {co_dir_role['name']} (id={co_dir_role['id']})")

# Pick a real counsellor — first staff member with COUNS_DIR role
counsellor_staff = _find_one(ref.staff, role_id=counsellor_role['id'])
assert counsellor_staff is not None, "No COUNS_DIR staff in ref_staff"
print(f"  Counsellor:    {counsellor_staff['name']} (id={counsellor_staff['id']})")

# Pick a real CO — first staff member with CO_DIR role
co_staff = _find_one(ref.staff, role_id=co_dir_role['id'])
assert co_staff is not None, "No CO_DIR staff in ref_staff"
print(f"  CO:            {co_staff['name']} (id={co_staff['id']})")

# Pick an institution in Australia — first one
institution = next(
    (inst for inst in ref.institutions.values()
     if inst['country_id'] == country['id']),
    None,
)
assert institution is not None, "No AU institution in ref_institution"
print(f"  Institution:   {institution['canonical_name']} (id={institution['id']})")
# print(f"                  classification: {institution['classification']}")

# Find a status code that means "closed, visa granted, enrolled" — full bonus.
status_code = _find_status(ref, "Visa granted (plus enrolled)")
if status_code is None:
    # Fallback — pick any non-zero-bonus, non-carry-over status
    for sc, row in ref.status_splits.items():
        if (not row.get('is_zero_bonus')
                and not row.get('is_carry_over')
                and not row.get('is_current_enrolled')):
            status_code = sc
            break
assert status_code is not None, "No usable status_code found"
print(f"  Status:        {status_code!r}")


# ---------------------------------------------------------------------------
# Step 3 — Build a hand-crafted CaseInput
# ---------------------------------------------------------------------------

print()
print("=" * 80)
print("STEP 3: Build CaseInput")
print("=" * 80)

case = CaseInput(
    case_id=999_999,                       # Synthetic — not in tx_case
    contract_id="SMOKE-001",
    student_id="SMOKE-S001",
    student_name="Smoke Test Student",
    notes="End-to-end smoke test case",
    institution_id=institution['id'],
    institution_text_raw=institution['canonical_name'],
    referring_partner_id=None,
    referring_sub_agent_id=None,
    referring_agent_text_raw=None,
    system_type_observed=None,
    country_id=country['id'],
    package_service_fee_id=None,           # No package
    status_code=status_code,
    application_status_text=None,
    client_type_code='AE',
    office_id=office['id'],
    counsellor=Slot(
        staff_id=counsellor_staff['id'],
        staff_name=counsellor_staff['name'],
        role_id=counsellor_role['id'],
    ),
    case_officer=Slot(
        staff_id=co_staff['id'],
        staff_name=co_staff['name'],
        role_id=co_dir_role['id'],
    ),
    presales=Slot(staff_id=None, staff_name=None, role_id=None),
    vp=Slot(staff_id=None, staff_name=None, role_id=None),
    presales_share_pct=Decimal("0"),
    contract_signed_date=date(2024, 6, 15),  # Mid-2024, well within rate validity
    fee_paid_date=None,
    visa_received_date=None,
    enrolled_date=None,
    course_start_date=None,
    course_status=None,
    file_closed_date=None,
)
print(f"  Case built. Counsellor + CO at HCM, AU institution, "
      f"status={status_code!r}")


# ---------------------------------------------------------------------------
# Step 4 — Build RunContext
# ---------------------------------------------------------------------------

print()
print("=" * 80)
print("STEP 4: Build RunContext")
print("=" * 80)

# Set both staff to "hit target" so they end up at MEET_LOW or MEET_HIGH
# (which has rate rows). The actual target value comes from
# ref.staff_targets but we shortcut here for the smoke test.
ctx = RunContext(
    year=2024, month=6,
    enrolments_by_staff_office={
        (counsellor_staff['id'], office['id']): 5,
        (co_staff['id'], office['id']): 5,
    },
    targets_by_staff_office={
        (counsellor_staff['id'], office['id']): 5,
        (co_staff['id'], office['id']): 5,
    },
    enrolments_by_priority_list_ytd={},
    clawback_balances_by_staff={},
    prior_withholdings_by_case_staff={},
)
print(f"  Run: 2024-06, both staff at 5/5 (target hit).")


# ---------------------------------------------------------------------------
# Step 5 — Call the engine
# ---------------------------------------------------------------------------

print()
print("=" * 80)
print("STEP 5: Run calculate_case")
print("=" * 80)

try:
    payments = calculate_case(case, ctx, ref)
except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    raise

print(f"  Got {len(payments)} payment row(s):")
for p in payments:
    print(f"    {p.slot_label:13s} {p.staff_name:25s} "
          f"tier={p.tier_bonus:>10,}  "
          f"package={p.package_bonus:>9,}  "
          f"priority={p.priority_bonus:>9,}  "
          f"gross={p.gross_bonus:>10,}  "
          f"net={p.net_payable:>10,}")

print()
print("=" * 80)
print("[PASS] End-to-end pipeline works against real DB data.")
print("=" * 80)
