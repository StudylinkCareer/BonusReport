"""
ReferenceData assembly — calls every loader once and packages the
results into a frozen ReferenceData snapshot for the engine.

This module is the single integration point between the data layer
(data/ref_loaders.py) and the engine (engine/models.py). The engine
NEVER calls a loader directly; it only reads ref.* fields.

Phase 7 update: aligned with the new schema (priority Lists/Groups,
agreements, partner classifications, partner flat rates). Removed
load_priority_partners (renamed to load_priority_lists) and added
six new loaders.
"""

from __future__ import annotations

import logging

from backend.data.ref_loaders import (
    load_calculation_params,
    load_complaint_deductions,
    load_contract_target_tiers,
    load_countries,
    load_departure_rules,
    load_institution_agreements,
    load_institutions,
    load_local_enrolment_bonuses,
    load_offices,
    load_partner_classifications,
    load_partner_flat_rates,
    load_partners,
    load_priority_groups,
    load_priority_list_institutions,
    load_priority_lists,
    load_priority_targets,
    load_rates,
    load_roles,
    load_service_fees,
    load_staff,
    load_staff_targets,
    load_status_splits,
)
from backend.engine.models import ReferenceData


log = logging.getLogger(__name__)


def load_reference_data(conn) -> ReferenceData:
    """
    Load every ref_/dim_ table into a single immutable snapshot.

    The connection is borrowed; the caller manages its lifecycle. We
    don't commit or rollback here — these are pure SELECTs.
    """
    ref = ReferenceData(
        # Core dimensions
        institutions=load_institutions(conn),
        countries=load_countries(conn),
        offices=load_offices(conn),
        roles=load_roles(conn),
        staff=load_staff(conn),

        # Phase 7 — agreements & partners
        institution_agreements=load_institution_agreements(conn),
        partners=load_partners(conn),
        partner_classifications=load_partner_classifications(conn),
        partner_flat_rates=load_partner_flat_rates(conn),

        # Phase 7 — priority structure
        priority_groups=load_priority_groups(conn),
        priority_lists=load_priority_lists(conn),
        priority_list_institutions=load_priority_list_institutions(conn),
        priority_targets=load_priority_targets(conn),

        # Rates & fees
        service_fees=load_service_fees(conn),
        rates=load_rates(conn),
        local_enrolment_bonuses=load_local_enrolment_bonuses(conn),

        # Status & params
        status_splits=load_status_splits(conn),
        calculation_params=load_calculation_params(conn),

        # Phase 6c additions
        departure_rules=load_departure_rules(conn),
        complaint_deductions=load_complaint_deductions(conn),
        contract_target_tiers=load_contract_target_tiers(conn),

        # Item 3 — sub-agent CO scheme
        staff_targets=load_staff_targets(conn),
    )

    summary = [
        ('institutions',                len(ref.institutions)),
        ('countries',                   len(ref.countries)),
        ('offices',                     len(ref.offices)),
        ('roles',                       len(ref.roles)),
        ('staff',                       len(ref.staff)),
        ('institution_agreements',      len(ref.institution_agreements)),
        ('partners',                    len(ref.partners)),
        ('partner_classifications',     len(ref.partner_classifications)),
        ('partner_flat_rates',          len(ref.partner_flat_rates)),
        ('priority_groups',             len(ref.priority_groups)),
        ('priority_lists',              len(ref.priority_lists)),
        ('priority_list_institutions',  len(ref.priority_list_institutions)),
        ('priority_targets',            len(ref.priority_targets)),
        ('service_fees',                len(ref.service_fees)),
        ('rates',                       len(ref.rates)),
        ('local_enrolment_bonuses',     len(ref.local_enrolment_bonuses)),
        ('status_splits',               len(ref.status_splits)),
        ('calculation_params',          len(ref.calculation_params)),
        ('departure_rules',             len(ref.departure_rules)),
        ('complaint_deductions',        len(ref.complaint_deductions)),
        ('contract_target_tiers',       len(ref.contract_target_tiers)),
        ('staff_targets',               len(ref.staff_targets)),
    ]
    log.info("ReferenceData loaded: %s",
             ", ".join(f"{k}={v}" for k, v in summary))

    return ref


if __name__ == "__main__":
    from backend.data.connection import get_connection

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    with get_connection() as conn:
        ref = load_reference_data(conn)
    print(f"\nLoaded ReferenceData with {len(ref.institutions)} institutions, "
          f"{len(ref.priority_lists)} priority Lists, "
          f"{len(ref.institution_agreements)} agreements.")
