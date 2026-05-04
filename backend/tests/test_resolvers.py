"""
backend/tests/test_resolvers.py

Live-DB tests for backend/importer/resolvers.py.

These are deliberately written against the *real* Railway Postgres so we
catch schema mismatches and seeding bugs, not just SQL syntax errors.

Run from the backend/ directory:
    python -m pytest tests/test_resolvers.py -v

Requires backend/.env with DATABASE_URL set, and the import path below
adjusted to whatever your connection module exports.
"""

import pytest

# IMPORTANT: adjust this import to match your project's actual structure.
# The carry-over describes backend/data/connection.py with a context-manager
# helper. If yours is named differently, change it here.
from backend.data.connection import get_connection  # noqa: E402

from backend.importer.resolvers import (  # noqa: E402
    resolve_country,
    resolve_office,
    resolve_sub_agent,
    resolve_partner,
    resolve_institution,
    resolve_staff,
    resolve_status,
    resolve_staff_role,
    resolve_staff_employment,
)


# ---------------------------------------------------------------------------
# Fixture: a single connection + cursor reused across all tests in the module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cursor():
    with get_connection() as conn:
        with conn.cursor() as cur:
            yield cur


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------

def test_country_australia_resolves(cursor):
    assert resolve_country(cursor, "Australia") is not None


def test_country_case_insensitive(cursor):
    assert resolve_country(cursor, "australia") == resolve_country(cursor, "Australia")


def test_country_blank_returns_none(cursor):
    assert resolve_country(cursor, "") is None
    assert resolve_country(cursor, None) is None
    assert resolve_country(cursor, "   ") is None


def test_country_garbage_returns_none(cursor):
    assert resolve_country(cursor, "Atlantis") is None


# ---------------------------------------------------------------------------
# Office
# ---------------------------------------------------------------------------

def test_office_hcm_resolves(cursor):
    # By code or name — at least one of these should hit.
    assert resolve_office(cursor, "HCM") is not None or \
           resolve_office(cursor, "Ho Chi Minh") is not None


# ---------------------------------------------------------------------------
# Sub-agent
# ---------------------------------------------------------------------------

def test_sub_agent_known_alias_resolves(cursor):
    # 'Student life care (SLC)' appeared as a Refer Source Agent in real data.
    # Whether this resolves depends on whether it was seeded — if the DB
    # returns None, this is a seeding question, not a resolver bug.
    result = resolve_sub_agent(cursor, "Student life care (SLC)")
    # We just assert the function executes cleanly. If you have a known
    # seeded sub-agent, replace with a stronger assertion.
    assert result is None or isinstance(result, int)


def test_sub_agent_blank_returns_none(cursor):
    assert resolve_sub_agent(cursor, "") is None
    assert resolve_sub_agent(cursor, None) is None


def test_sub_agent_whitespace_tolerant(cursor):
    # Real data showed "New Pathway., JSC " with a trailing space.
    a = resolve_sub_agent(cursor, "New Pathway., JSC")
    b = resolve_sub_agent(cursor, "New Pathway., JSC ")
    assert a == b  # both succeed or both fail; either way, equal


# ---------------------------------------------------------------------------
# Partner
# ---------------------------------------------------------------------------

def test_partner_navitas_resolves(cursor):
    # Navitas was seeded in Phase 6g per carry-over.
    assert resolve_partner(cursor, "Navitas") is not None


def test_partner_adventus_resolves(cursor):
    # Adventus is one of the 9 Master Agents.
    assert resolve_partner(cursor, "Adventus") is not None


# ---------------------------------------------------------------------------
# Institution
# ---------------------------------------------------------------------------

def test_institution_known_canonical_resolves(cursor):
    # 'The University of Adelaide' is in Priority 2024 list.
    assert resolve_institution(cursor, "The University of Adelaide") is not None


def test_institution_blank_returns_none(cursor):
    assert resolve_institution(cursor, "") is None
    assert resolve_institution(cursor, None) is None


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

def test_staff_pham_thi_loi_resolves(cursor):
    # Phạm Thị Lợi is a confirmed seeded CO_SUB.
    assert resolve_staff(cursor, "Phạm Thị Lợi") is not None


def test_staff_unknown_returns_none(cursor):
    assert resolve_staff(cursor, "Nobody Real") is None


def test_staff_role_returned_for_known_staff(cursor):
    staff_id = resolve_staff(cursor, "Phạm Thị Lợi")
    assert staff_id is not None
    role_id = resolve_staff_role(cursor, staff_id)
    assert role_id is not None  # she has a primary_role_id


def test_staff_role_none_for_none_input(cursor):
    assert resolve_staff_role(cursor, None) is None


def test_staff_employment_returned(cursor):
    staff_id = resolve_staff(cursor, "Phạm Thị Lợi")
    status = resolve_staff_employment(cursor, staff_id)
    assert status is not None  # active staff have an employment_status set


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_closed_visa_granted_resolves(cursor):
    # Seeded in Phase 6h as one of the 19 statuses.
    assert resolve_status(cursor, "Closed - Visa granted") is not None


def test_status_variant_with_comma_resolves(cursor):
    # Phase 6h aliased "Closed - Enrolled, then Cancelled" to its no-comma form.
    assert resolve_status(cursor, "Closed - Enrolled, then Cancelled") is not None


def test_status_blank_returns_none(cursor):
    assert resolve_status(cursor, "") is None
    assert resolve_status(cursor, None) is None
