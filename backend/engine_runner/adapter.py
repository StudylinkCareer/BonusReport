"""
backend/engine_runner/adapter.py

Converts a tx_case row (as a dict) into a CaseInput dataclass for the engine.

The engine never touches the database. The adapter is the bridge between the
DB-shaped representation (rows from tx_case) and the engine's input dataclass.

Design notes
------------
* Pure function — no side effects, no DB calls. Takes a dict + ReferenceData,
  returns a CaseInput.
* Skip rules — rows with non-adaptable import_status raise CaseNotAdaptableError.
  NULL institution_id is rejected EXCEPT when client_type_code is one of the
  service-only types (visa-only, guardian, tourist, migration, dependant)
  which have no underlying educational-institution enrolment.
* Loud on data-integrity issues — if a tx_case row references a staff_id not
  in ReferenceData.staff, that's a real bug and we raise rather than papering
  over it.

CHANGES IN THIS REVISION (Phase 14b — Client Type Canonicalisation):
  - Replaced status-flag-driven null-institution check (was: looking up
    ref_status_split.is_visa_only_paid) with client_type-driven check.
    The prior approach conflated workflow state (status) with contract type
    (client_type) — a fabrication of a prior session, not in any procedural
    document.
  - Helper renamed: _status_allows_null_institution → _client_type_allows_null_institution.
  - No longer needs ReferenceData lookup for the null-institution check.
  - UNRESOLVED client_type_code values are filtered upstream via
    import_status='UNRESOLVED' (already handled at line ~100 in is_adaptable)
    so this helper does not need a special UNRESOLVED branch.

Citations:
  - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.2 (KPI weights per service
    type — 5 of the 9 canonical client types have weight 0 across all routes,
    indicating no enrolment)
  - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.6 (fees-paid-non-enrolled
    handling — separate concept, driven by application_status, untouched here)
  - Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.7 (Vietnam domestic =
    Counsellor only, no CO involvement — informs that VIETNAM_DOMESTIC IS
    enrolment-based and so NOT in the no-institution set)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from backend.engine.models import CaseInput, ReferenceData, Slot


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# import_status values that indicate the row cannot be processed by the engine
NON_ADAPTABLE_STATUSES: frozenset[str] = frozenset({
    "SCRAP",
    "UNRESOLVED",
    "UNRESOLVED-PARTNER",
})


# Canonical client_type_code values where institution_id may legitimately be NULL.
# These are pure-service contracts with no enrolment at an educational
# institution behind them.
#
# Per ref_client_type seed (Phase 14a migration 14a_v2). All 5 are weight-0
# in §I.2 KPI calculations because no enrolment occurs. The other 4 canonical
# client types (DU_HOC_FULL, DU_HOC_ENROL_ONLY, SUMMER_STUDY, VIETNAM_DOMESTIC)
# all involve enrolment at an institution and so require institution_id.
CLIENT_TYPES_NO_INSTITUTION: frozenset[str] = frozenset({
    "VISA_ONLY_SERVICE",  # Visa Du học only — visa service, student enrolment elsewhere or none
    "GUARDIAN_VISA",      # Visa Giám hộ
    "TOURIST_VISA",       # Visa Du lịch
    "MIGRATION_VISA",     # Visa Định cư
    "DEPENDANT_VISA",     # Visa Phụ thuộc
})


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class CaseNotAdaptableError(Exception):
    """
    Raised when a tx_case row cannot be converted to a CaseInput.

    Attributes:
        contract_id: the contract_id of the offending row (for logging)
        reason: human-readable explanation
    """

    def __init__(self, contract_id: str, reason: str) -> None:
        self.contract_id = contract_id
        self.reason = reason
        super().__init__(f"Cannot adapt case {contract_id!r}: {reason}")


# ---------------------------------------------------------------------------
# Helper — does this client_type allow NULL institution_id?
# ---------------------------------------------------------------------------

def _client_type_allows_null_institution(
    client_type_code: str | None,
) -> bool:
    """
    NULL institution_id is permitted only for service-only client types
    (visa-only, guardian, tourist, migration, dependant) which have no
    underlying educational-institution enrolment.

    Per Chính_sách_chỉ_tiêu__bonus__final_1_6_24.pdf §I.2 KPI weight table
    (5 client types weight 0 across all routes — no enrolment) and §I.7
    (Vietnam domestic IS an enrolment, so NOT in this set).

    Returns False for None and for UNRESOLVED — both indicate the case
    is not safe to process. (UNRESOLVED is typically filtered upstream
    via import_status check, but this helper is defensive.)
    """
    if client_type_code is None:
        return False
    return client_type_code in CLIENT_TYPES_NO_INSTITUTION


# ---------------------------------------------------------------------------
# Pre-flight check
# ---------------------------------------------------------------------------

def is_adaptable(tx_case_row: dict[str, Any], ref: ReferenceData) -> bool:
    """
    Return True if this tx_case row can be converted to a CaseInput.

    Rules:
      * import_status must NOT be in NON_ADAPTABLE_STATUSES
      * institution_id must NOT be NULL (UNLESS client_type is service-only)
      * country_id must NOT be NULL
      * case_office_id must NOT be NULL

    Note: ref parameter retained for signature stability; not used by the
    null-institution check in this revision (was used to look up
    ref_status_split.is_visa_only_paid in the prior revision).
    """
    if tx_case_row.get("import_status") in NON_ADAPTABLE_STATUSES:
        return False
    if tx_case_row.get("institution_id") is None:
        if not _client_type_allows_null_institution(
            tx_case_row.get("client_type_code")
        ):
            return False
    if tx_case_row.get("country_id") is None:
        return False
    if tx_case_row.get("case_office_id") is None:
        return False
    return True


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def adapt_case(
    tx_case_row: dict[str, Any],
    ref: ReferenceData,
    *,
    prior_payments_by_slot: dict[tuple[str, int], int] | None = None,
    addon_items: list[tuple[int, int]] | None = None,
) -> CaseInput:
    """
    Convert a tx_case row dict to a CaseInput dataclass.

    Args:
        tx_case_row: dict with column names from tx_case as keys
        ref: ReferenceData snapshot (needed for staff name lookups)
        prior_payments_by_slot: optional, populated by the runner
        addon_items: optional, populated by the runner

    Returns:
        A CaseInput dataclass ready to be passed to the engine.

    Raises:
        CaseNotAdaptableError: if the row fails pre-flight checks.
    """
    contract_id = tx_case_row.get("contract_id") or "<unknown>"

    # Pre-flight
    if tx_case_row.get("import_status") in NON_ADAPTABLE_STATUSES:
        raise CaseNotAdaptableError(
            contract_id,
            f"import_status={tx_case_row.get('import_status')}",
        )

    # NULL institution_id allowed only for service-only client types
    if tx_case_row.get("institution_id") is None:
        if not _client_type_allows_null_institution(
            tx_case_row.get("client_type_code")
        ):
            raise CaseNotAdaptableError(
                contract_id,
                f"institution_id is NULL and client_type_code="
                f"{tx_case_row.get('client_type_code')!r} is not in "
                f"CLIENT_TYPES_NO_INSTITUTION",
            )

    if tx_case_row.get("country_id") is None:
        raise CaseNotAdaptableError(contract_id, "country_id is NULL")
    if tx_case_row.get("case_office_id") is None:
        raise CaseNotAdaptableError(contract_id, "case_office_id is NULL")

    # Build all four slots
    counsellor = _make_slot(
        tx_case_row.get("counsellor_staff_id"),
        tx_case_row.get("counsellor_role_id"),
        ref,
        contract_id,
        slot_label="counsellor",
    )
    case_officer = _make_slot(
        tx_case_row.get("case_officer_staff_id"),
        tx_case_row.get("case_officer_role_id"),
        ref,
        contract_id,
        slot_label="case_officer",
    )
    presales = _make_slot(
        tx_case_row.get("presales_staff_id"),
        tx_case_row.get("presales_role_id"),
        ref,
        contract_id,
        slot_label="presales",
    )
    vp = _make_slot(
        tx_case_row.get("vp_staff_id"),
        tx_case_row.get("vp_role_id"),
        ref,
        contract_id,
        slot_label="vp",
    )

    application_status = tx_case_row.get("application_status")
    if application_status is None:
        raise CaseNotAdaptableError(contract_id, "application_status is NULL")

    return CaseInput(
        case_id=tx_case_row["id"],
        contract_id=contract_id,
        student_id=tx_case_row.get("student_id") or "",
        student_name=tx_case_row.get("student_name") or "",
        notes=tx_case_row.get("notes"),

        institution_id=tx_case_row.get("institution_id"),  # May be None for service-only client types
        institution_text_raw=tx_case_row.get("institution_text_raw") or "",
        referring_partner_id=tx_case_row.get("referring_partner_id"),
        referring_sub_agent_id=tx_case_row.get("referring_sub_agent_id"),
        referring_agent_text_raw=tx_case_row.get("referring_agent_text_raw"),
        system_type_observed=None,

        country_id=tx_case_row["country_id"],
        package_service_fee_id=tx_case_row.get("service_fee_id"),

        status_code=application_status,
        application_status_text=application_status,
        client_type_code=tx_case_row.get("client_type_code") or "",

        office_id=tx_case_row["case_office_id"],
        counsellor=counsellor,
        case_officer=case_officer,
        presales=presales,
        vp=vp,
        presales_share_pct=_to_decimal(tx_case_row.get("presales_share_pct")),

        contract_signed_date=tx_case_row.get("contract_signed_date"),
        fee_paid_date=None,
        visa_received_date=tx_case_row.get("visa_received_date"),
        enrolled_date=None,
        course_start_date=tx_case_row.get("course_start_date"),
        course_status=tx_case_row.get("course_status"),
        file_closed_date=None,

        prior_month_rate=tx_case_row.get("prior_month_rate"),
        co_sub_subscheme_override=None,

        prior_payments_by_slot=prior_payments_by_slot or {},
        addon_items=addon_items or [],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slot(
    staff_id: int | None,
    role_id: int | None,
    ref: ReferenceData,
    contract_id: str,
    *,
    slot_label: str,
) -> Slot:
    if staff_id is None:
        return Slot(staff_id=None, staff_name=None, role_id=None)

    staff_record = ref.staff.get(staff_id)
    if staff_record is None:
        raise CaseNotAdaptableError(
            contract_id,
            f"{slot_label}.staff_id={staff_id} not found in ReferenceData.staff",
        )

    staff_name = (
        staff_record.get("canonical_name")
        or staff_record.get("name")
        or f"<staff_id={staff_id}>"
    )

    return Slot(
        staff_id=staff_id,
        staff_name=staff_name,
        role_id=role_id,
    )


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
