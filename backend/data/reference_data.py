"""
ReferenceData assembly for the BonusReport engine.

Single public function — load_reference_data — that takes an open
psycopg connection, runs all sixteen ref_loaders, and assembles a
ReferenceData dataclass instance. This is the bridge between the
data layer (DB I/O) and the engine layer (pure calculation).

Usage:
    from data.connection import get_connection
    from data.reference_data import load_reference_data

    with get_connection() as conn:
        ref = load_reference_data(conn)

    # ref is now a fully-populated engine.models.ReferenceData
    payments = calculate_case(case_input, run_context, ref)

Why a single function?
  - The engine treats ReferenceData as immutable input. Any code
    path that builds one should go through here so the assembly
    order, field names, and population rules stay consistent.
  - Tests can swap this for an in-memory factory and the rest of
    the pipeline doesn't care.

Why not load lazily?
  - Reference data is small (~hundreds of rows total). A full
    eager load is microseconds. The engine reads from these dicts
    millions of times per run — pre-loading is the right call.
"""

from __future__ import annotations

import psycopg

from engine.models import ReferenceData

from .ref_loaders import (
    load_calculation_params,
    load_complaint_deductions,
    load_contract_target_tiers,
    load_countries,
    load_departure_rules,
    load_institutions,
    load_local_enrolment_bonuses,
    load_offices,
    load_priority_partners,
    load_priority_targets,
    load_rates,
    load_roles,
    load_service_fees,
    load_staff,
    load_staff_targets,
    load_status_splits,
)


def load_reference_data(conn: psycopg.Connection) -> ReferenceData:
    """
    Load every ref_/dim_ table and return a populated ReferenceData.

    Args:
        conn: An open psycopg connection. Caller manages lifecycle
              (recommended via data.connection.get_connection).

    Returns:
        A ReferenceData with every field populated. Frozen — callers
        should treat it as immutable.

    Notes:
        - sub_agents is currently empty: ref_sub_agent loader hasn't
          been written yet (Phase 5b table). Add when sub-agent
          alias/CO_SUB resolution gets fully wired into case loading.
        - Each loader does its own SELECT. We don't share a transaction
          because reference data is read-only and snapshot consistency
          across tables doesn't matter for correctness — the unique
          constraints on each table prevent inconsistency at the row
          level.
    """
    return ReferenceData(
        # Dimension tables
        countries=load_countries(conn),
        offices=load_offices(conn),
        roles=load_roles(conn),

        # Reference tables — entities
        institutions=load_institutions(conn),
        staff=load_staff(conn),
        priority_partners=load_priority_partners(conn),

        # Reference tables — rates and amounts
        rates=load_rates(conn),
        service_fees=load_service_fees(conn),
        local_enrolment_bonuses=load_local_enrolment_bonuses(conn),
        calculation_params=load_calculation_params(conn),

        # Reference tables — targets and rules
        priority_targets=load_priority_targets(conn),
        staff_targets=load_staff_targets(conn),
        contract_target_tiers=load_contract_target_tiers(conn),

        # Reference tables — status / timing / penalty rules
        status_splits=load_status_splits(conn),
        departure_rules=load_departure_rules(conn),
        complaint_deductions=load_complaint_deductions(conn),

        # Not yet loaded — sub_agents loader pending Phase 5b wiring.
        # Defaults to {} via dataclass field(default_factory=dict).
    )


# ---------------------------------------------------------------------------
# Smoke test — `python -m data.reference_data` runs this.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .connection import get_connection

    with get_connection() as conn:
        ref = load_reference_data(conn)

    # Count populated fields and report total row count.
    field_counts = [
        ('countries', len(ref.countries)),
        ('offices', len(ref.offices)),
        ('roles', len(ref.roles)),
        ('institutions', len(ref.institutions)),
        ('staff', len(ref.staff)),
        ('priority_partners', len(ref.priority_partners)),
        ('rates', len(ref.rates)),
        ('service_fees', len(ref.service_fees)),
        ('local_enrolment_bonuses', len(ref.local_enrolment_bonuses)),
        ('calculation_params', len(ref.calculation_params)),
        ('priority_targets', len(ref.priority_targets)),
        ('staff_targets', len(ref.staff_targets)),
        ('contract_target_tiers', len(ref.contract_target_tiers)),
        ('status_splits', len(ref.status_splits)),
        ('departure_rules', len(ref.departure_rules)),
        ('complaint_deductions', len(ref.complaint_deductions)),
        ('sub_agents', len(ref.sub_agents)),
    ]

    print("ReferenceData loaded:")
    for name, count in field_counts:
        marker = " " if count > 0 else "."
        print(f"  {marker} {name:28s} {count:>4} rows")

    total = sum(c for _, c in field_counts)
    print(f"\nTotal rows: {total}")
