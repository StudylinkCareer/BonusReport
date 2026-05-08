"""
backend/importer/transformer.py

Convert a RawRow (from reader.py) into a CaseRecord ready for tx_case
insertion, plus zero or more NoteRecords for tx_case_notes_staging.

The transformer reads (via resolvers) and produces dataclasses. It does NOT
execute SQL writes.

KEY POLICY CHANGES (Phase7prep_v2_extension, 2026-05-05):

1. Asterisks in institution names are LEGACY DATA and should never be parsed
   as syntax. They are alias variants — the team adds asterisk-decorated
   forms to ref_institution_alias as needed. The transformer just looks up
   the raw string in the alias table; if it doesn't resolve, the row gets
   an UNRESOLVED_INSTITUTION warning and the team adds the alias.

2. Routing partner (Group / Master Agent) is NOT recorded on tx_case from
   institution name parsing. It is derivable at engine runtime from the
   institution's active VIA_PARTNER agreement in ref_institution_agreement.

3. The Refer Source Agent column is the ONLY source of routing info recorded
   on tx_case. Resolution order (Phase 11b, 2026-05-08): office → sub_agent
   → partner. Office-first protects against accidental matches when a
   personal-name variant (e.g. 'Hoang Le – VP Mel') collides with a
   sub-agent or partner string. If blank → OFFICE_ONLY with no
   referring_office_id. If neither resolves → UNRESOLVED.

4. System Type vs. agreement-existence cross-check (replaces the old
   classification-based check):
     - If System Type says "Trong hệ thống" (in-system) but institution has
       no active agreement at contract_signed_date → mismatch
     - If System Type says "Ngoài hệ thống" (out-of-system) but institution
       DOES have an active agreement → mismatch

5. CO_SUB slot rule (patch4): CO_SUB staff always populate the case_officer
   slot, never the counsellor slot, regardless of which Excel column they
   appeared in. Same-person-both-columns collapses to a single slot.
   Different-person-each-column with the counsellor being CO_SUB triggers
   a CO_SUB_SLOT_CONFLICT warning. This prevents the engine from emitting
   two BonusPayment rows per case for sub-agent files.

6. Departed-staff warning suppression (Phase 11b, 2026-05-08): when
   DEPARTED_STAFF fires for a name in either staff column, the redundant
   UNRESOLVED_COUNSELLOR / UNRESOLVED_CASE_OFFICER warning for the same
   name is suppressed. The departed-staff list is the authoritative reason
   the lookup misses; the second warning is noise.

OTHER LOCKED POLICY (do not re-derive):
  * Role is intrinsic to the staff member, not the column. The role_id
    always comes from ref_staff.primary_role_id.
  * Departed staff cases are marked SCRAP and skipped from engine processing.
  * Office-only cases (empty Refer Source, no other partner signal) =>
    source_type='OFFICE_ONLY'.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from backend.importer.reader import RawRow
from backend.importer.resolvers import (
    resolve_country,
    resolve_institution,
    resolve_office,
    resolve_partner,
    resolve_staff,
    resolve_staff_employment,
    resolve_staff_role,
    resolve_status,
    resolve_sub_agent,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEPARTED_STAFF_NAMES: frozenset[str] = frozenset({
    "Đào Ngọc Sơn",
    "Nguyễn Thị Kim Dung",
})

INCENTIVE_THRESHOLD_VND = 5_000_000

# Role identifiers (matches dim_role.id)
ROLE_ID_CO_SUB = 18  # dim_role.code = 'CO_SUB' (D6.R6 sub-agent CO scheme)

# CRM column keys
COL_CONTRACT_ID = "Contract ID"
COL_STUDENT_ID = "Student ID"
COL_STUDENT_NAME = "Student Name"
COL_CONTRACT_SIGNED = "Contract Signed Date"
COL_CLIENT_TYPE = "Client Type"
COL_COUNTRY = "Country of Study"
COL_REFER_SOURCE = "Refer Source Agent"
COL_SYSTEM_TYPE = "System Type"
COL_APPLICATION_STATUS = "Application Report Status"
COL_VISA_RECEIVED = "Visa Received Date"
COL_INSTITUTION = "Institution Name"
COL_COURSE_START = "Course Start Date"
COL_COURSE_STATUS = "Course Status"
COL_COUNSELLOR = "Counsellor Name"
COL_CASE_OFFICER = "Case Officer Name"
COL_NOTES = "Notes"
COL_INCENTIVE_PREFIX = "Customer Incentive"

# referring_source_type values
SOURCE_PARTNER = "PARTNER"
SOURCE_SUB_AGENT = "SUB_AGENT"
SOURCE_OFFICE_ONLY = "OFFICE_ONLY"
SOURCE_UNRESOLVED = "UNRESOLVED"
SOURCE_NONE = "NONE"

# import_status values
STATUS_OK = "OK"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_UNRESOLVED_PARTNER = "UNRESOLVED-PARTNER"
STATUS_SCRAP = "SCRAP"
STATUS_WARN_MISMATCH = "WARN-MISMATCH"

SYSTEM_TYPE_IN_VN = "Trong hệ thống"
SYSTEM_TYPE_OUT_VN = "Ngoài hệ thống"


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseRecord:
    contract_id: str
    student_id: Optional[str]
    student_name: str
    contract_signed_date: Optional[date]
    course_start_date: Optional[date]
    visa_received_date: Optional[date]
    case_office_id: int
    country_id: int
    institution_id: Optional[int]
    referring_partner_id: Optional[int]
    referring_sub_agent_id: Optional[int]
    referring_office_id: Optional[int]
    institution_text_raw: Optional[str]
    referring_agent_text_raw: Optional[str]
    client_type_code: Optional[str]
    application_status: Optional[str]
    course_status: Optional[str]
    counsellor_staff_id: Optional[int]
    counsellor_role_id: Optional[int]
    case_officer_staff_id: Optional[int]
    case_officer_role_id: Optional[int]
    referring_source_type: str
    import_status: str
    incentive_amount: int
    notes: Optional[str]
    run_year: int
    run_month: int


@dataclass(frozen=True)
class NoteRecord:
    warning_type: str
    raw_value: Optional[str]
    note: str


# ---------------------------------------------------------------------------
# Parsing helpers (value coercion only — no semantic parsing)
# ---------------------------------------------------------------------------

def _parse_system_type(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    s = str(text).strip()
    if s == SYSTEM_TYPE_IN_VN:
        return "IN"
    if s == SYSTEM_TYPE_OUT_VN:
        return "OUT"
    return None


def _parse_incentive(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return INCENTIVE_THRESHOLD_VND if value else 0
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else 0
    s = str(value).strip().lower()
    if s in {"yes", "y"}:
        return INCENTIVE_THRESHOLD_VND
    if s in {"no", "n", ""}:
        return 0
    digits = s.replace(",", "").replace(".", "").replace(" ", "")
    if digits.isdigit():
        return int(digits)
    return 0


def _coerce_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    s = str(value).strip()
    return s if s else None


def _is_datetime_value(value: Any) -> bool:
    return isinstance(value, (datetime, date))


# ---------------------------------------------------------------------------
# DB-touching helpers
# ---------------------------------------------------------------------------

def _get_staff_office(cursor, staff_id: Optional[int]) -> Optional[int]:
    if staff_id is None:
        return None
    cursor.execute(
        "SELECT home_office_id FROM ref_staff WHERE id = %s",
        (staff_id,),
    )
    row = cursor.fetchone()
    return row["home_office_id"] if row else None


def _has_active_agreement(
    cursor,
    institution_id: Optional[int],
    case_date: Optional[date],
) -> bool:
    """Does this institution have an active agreement at the given date?

    Used by the System Type cross-check. Returns True if at least one row in
    ref_institution_agreement covers the case date for this institution.

    If case_date is None we fall back to "currently active" (effective_to NULL
    or in the future).
    """
    if institution_id is None:
        return False

    if case_date is None:
        cursor.execute(
            """SELECT 1 FROM ref_institution_agreement
                WHERE institution_id = %s
                  AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                LIMIT 1""",
            (institution_id,),
        )
    else:
        cursor.execute(
            """SELECT 1 FROM ref_institution_agreement
                WHERE institution_id = %s
                  AND effective_from <= %s
                  AND (effective_to IS NULL OR effective_to >= %s)
                LIMIT 1""",
            (institution_id, case_date, case_date),
        )
    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Status escalation
# ---------------------------------------------------------------------------

_STATUS_SEVERITY = {
    STATUS_OK: 0,
    STATUS_WARN_MISMATCH: 1,
    STATUS_UNRESOLVED_PARTNER: 2,
    STATUS_UNRESOLVED: 3,
    STATUS_SCRAP: 4,
}


def _escalate(current: str, candidate: str) -> str:
    return candidate if _STATUS_SEVERITY[candidate] > _STATUS_SEVERITY[current] else current


# ---------------------------------------------------------------------------
# Header lookup (handles 17- vs 18-column variants)
# ---------------------------------------------------------------------------

def _get_incentive_value(data: dict[str, Any]) -> Any:
    for header, value in data.items():
        if header.startswith(COL_INCENTIVE_PREFIX):
            return value
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def transform_row(
    cursor,
    raw: RawRow,
    *,
    run_year: int,
    run_month: int,
) -> tuple[Optional[CaseRecord], list[NoteRecord]]:
    notes: list[NoteRecord] = []
    data = raw.data
    import_status = STATUS_OK

    # ---- Identity ---------------------------------------------------------
    contract_id = _string_or_none(data.get(COL_CONTRACT_ID))
    if not contract_id:
        notes.append(NoteRecord(
            warning_type="MISSING_CONTRACT_ID",
            raw_value=None,
            note=f"Row {raw.row_number}: blank Contract ID — row skipped.",
        ))
        return None, notes

    student_id = _string_or_none(data.get(COL_STUDENT_ID))
    student_name = _string_or_none(data.get(COL_STUDENT_NAME)) or ""

    # ---- Date-in-text-field SCRAP detection -------------------------------
    for col in (COL_REFER_SOURCE, COL_INSTITUTION, COL_COUNSELLOR,
                COL_CASE_OFFICER, COL_NOTES, COL_CLIENT_TYPE,
                COL_SYSTEM_TYPE, COL_APPLICATION_STATUS):
        if _is_datetime_value(data.get(col)):
            notes.append(NoteRecord(
                warning_type="DATE_IN_TEXT_FIELD",
                raw_value=str(data.get(col)),
                note=f"Row {raw.row_number}: {col!r} contains a datetime value.",
            ))
            import_status = _escalate(import_status, STATUS_SCRAP)

    # ---- Staff resolution -------------------------------------------------
    counsellor_text = _string_or_none(data.get(COL_COUNSELLOR))
    case_officer_text = _string_or_none(data.get(COL_CASE_OFFICER))

    # Track whether each slot's name is on the departed list. When True, we
    # suppress the redundant UNRESOLVED_COUNSELLOR / UNRESOLVED_CASE_OFFICER
    # warning for that slot — DEPARTED_STAFF is the authoritative reason and
    # the second warning is noise (Phase 11b cleanup).
    counsellor_is_departed = counsellor_text in DEPARTED_STAFF_NAMES
    case_officer_is_departed = case_officer_text in DEPARTED_STAFF_NAMES

    if counsellor_is_departed or case_officer_is_departed:
        notes.append(NoteRecord(
            warning_type="DEPARTED_STAFF",
            raw_value=counsellor_text if counsellor_is_departed else case_officer_text,
            note=f"Row {raw.row_number}: case attributed to a departed staff member.",
        ))
        import_status = _escalate(import_status, STATUS_SCRAP)

    counsellor_staff_id = resolve_staff(cursor, counsellor_text) if counsellor_text else None
    case_officer_staff_id = resolve_staff(cursor, case_officer_text) if case_officer_text else None

    if counsellor_text and counsellor_staff_id is None and not counsellor_is_departed:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_COUNSELLOR",
            raw_value=counsellor_text,
            note=f"Row {raw.row_number}: counsellor name not found in ref_staff.",
        ))
        import_status = _escalate(import_status, STATUS_UNRESOLVED)
    if case_officer_text and case_officer_staff_id is None and not case_officer_is_departed:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_CASE_OFFICER",
            raw_value=case_officer_text,
            note=f"Row {raw.row_number}: case officer name not found in ref_staff.",
        ))
        import_status = _escalate(import_status, STATUS_UNRESOLVED)

    counsellor_role_id = resolve_staff_role(cursor, counsellor_staff_id)
    case_officer_role_id = resolve_staff_role(cursor, case_officer_staff_id)

    for sid, label in (
        (counsellor_staff_id, "counsellor"),
        (case_officer_staff_id, "case_officer"),
    ):
        if sid is not None and resolve_staff_employment(cursor, sid) == "DEPARTED":
            notes.append(NoteRecord(
                warning_type="DEPARTED_STAFF",
                raw_value=str(sid),
                note=f"Row {raw.row_number}: {label} marked DEPARTED in ref_staff.",
            ))
            import_status = _escalate(import_status, STATUS_SCRAP)

    # ---- CO_SUB slot rule -------------------------------------------------
    # CO_SUB staff always populate case_officer slot, never counsellor slot,
    # regardless of which Excel column they appeared in. Per the locked
    # policy decision: role is intrinsic to the staff member.
    #
    # Three cases this handles:
    #   1. Same CO_SUB person in both columns (the typical sub-agent file
    #      pattern, e.g. Phạm Thị Lợi cases): counsellor cleared,
    #      case_officer keeps the staff.
    #   2. CO_SUB in counsellor column only (case_officer empty): migrate
    #      across — CO_SUB doesn't belong in counsellor slot.
    #   3. CO_SUB in counsellor + different person in case_officer: keep
    #      case_officer's existing staff, drop the CO_SUB from counsellor,
    #      and surface a warning for operator review.
    if counsellor_role_id == ROLE_ID_CO_SUB:
        if case_officer_staff_id is None:
            # Migrate counsellor → case_officer slot
            case_officer_staff_id = counsellor_staff_id
            case_officer_role_id = counsellor_role_id
        elif case_officer_staff_id != counsellor_staff_id:
            notes.append(NoteRecord(
                warning_type="CO_SUB_SLOT_CONFLICT",
                raw_value=f"counsellor={counsellor_text!r}, "
                          f"case_officer={case_officer_text!r}",
                note=(f"Row {raw.row_number}: Counsellor column has CO_SUB "
                      f"staff {counsellor_text!r} but Case Officer column "
                      f"has a different staff member {case_officer_text!r}. "
                      f"The CO_SUB entry is being dropped from counsellor "
                      f"slot per the CO_SUB-only-in-case_officer rule. "
                      f"Verify intended assignment."),
            ))
        # All three branches: clear the counsellor slot
        counsellor_staff_id = None
        counsellor_role_id = None

    # ---- Office derivation ------------------------------------------------
    case_office_id = (
        _get_staff_office(cursor, counsellor_staff_id)
        or _get_staff_office(cursor, case_officer_staff_id)
    )
    if case_office_id is None:
        notes.append(NoteRecord(
            warning_type="NO_RESOLVABLE_OFFICE",
            raw_value=None,
            note=(f"Row {raw.row_number}: cannot derive case_office_id — "
                  f"no resolved staff member has a home_office_id."),
        ))
        return None, notes

    # ---- Country ---------------------------------------------------------
    country_text = _string_or_none(data.get(COL_COUNTRY))
    country_id = resolve_country(cursor, country_text) if country_text else None
    if country_id is None:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_COUNTRY",
            raw_value=country_text,
            note=f"Row {raw.row_number}: Country of Study not in dim_country.",
        ))
        return None, notes

    # ---- Dates we'll need ------------------------------------------------
    contract_signed_date = _coerce_date(data.get(COL_CONTRACT_SIGNED))

    # ---- Institution resolution (pure alias lookup, no asterisk parsing) -
    # Asterisk-decorated forms are aliases. If "WSU College *" is in the alias
    # table, it resolves. If not, log UNRESOLVED_INSTITUTION; the team adds
    # the alias and the next import resolves cleanly.
    institution_raw = _string_or_none(data.get(COL_INSTITUTION))
    institution_id = resolve_institution(cursor, institution_raw) if institution_raw else None
    if institution_raw and institution_id is None:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_INSTITUTION",
            raw_value=institution_raw,
            note=(f"Row {raw.row_number}: institution {institution_raw!r} not in "
                  f"ref_institution / ref_institution_alias. Add the variant as an "
                  f"alias if it's a known institution."),
        ))
        import_status = _escalate(import_status, STATUS_UNRESOLVED)

    # ---- Refer Source Agent → routing ------------------------------------
    # Resolution order (Phase 11b, 2026-05-08): office → sub_agent → partner.
    # Office-first is intentional: a personal-name variant like
    # 'Hoang Le – VP Mel' might collide with a sub-agent or partner
    # name, and we want internal-office matches to take precedence.
    #
    # The institution's partner relationship (Group / Master Agent) is
    # derivable at engine runtime from ref_institution_agreement; we do
    # NOT record it on tx_case from institution name parsing.
    refer_text = _string_or_none(data.get(COL_REFER_SOURCE))
    referring_partner_id: Optional[int] = None
    referring_sub_agent_id: Optional[int] = None
    referring_office_id: Optional[int] = None

    if not refer_text:
        # Blank Refer Source → office-only with no specific referring office
        source_type = SOURCE_OFFICE_ONLY
    else:
        office_id = resolve_office(cursor, refer_text)
        if office_id is not None:
            referring_office_id = office_id
            source_type = SOURCE_OFFICE_ONLY
        else:
            sa_id = resolve_sub_agent(cursor, refer_text)
            if sa_id is not None:
                referring_sub_agent_id = sa_id
                source_type = SOURCE_SUB_AGENT
            else:
                p_id = resolve_partner(cursor, refer_text)
                if p_id is not None:
                    referring_partner_id = p_id
                    source_type = SOURCE_PARTNER
                else:
                    source_type = SOURCE_UNRESOLVED
                    notes.append(NoteRecord(
                        warning_type="UNRESOLVED_REFER_SOURCE",
                        raw_value=refer_text,
                        note=(f"Row {raw.row_number}: Refer Source Agent "
                              f"{refer_text!r} resolved to neither office, "
                              f"sub-agent, nor partner."),
                    ))
                    import_status = _escalate(import_status, STATUS_UNRESOLVED)

    # ---- System Type vs agreement-existence cross-check -----------------
    # In-system / out-of-system is now derived from whether the institution
    # has an active agreement at the contract date (see Phase7prep_v2_extension).
    system_type = _parse_system_type(data.get(COL_SYSTEM_TYPE))
    if system_type is not None and institution_id is not None:
        has_agreement = _has_active_agreement(
            cursor, institution_id, contract_signed_date
        )
        mismatch = (
            (system_type == "IN" and not has_agreement)
            or (system_type == "OUT" and has_agreement)
        )
        if mismatch:
            notes.append(NoteRecord(
                warning_type="SYSTEM_TYPE_MISMATCH",
                raw_value=f"{data.get(COL_SYSTEM_TYPE)} vs has_agreement={has_agreement}",
                note=(f"Row {raw.row_number}: System Type "
                      f"{data.get(COL_SYSTEM_TYPE)!r} disagrees with database "
                      f"state (institution has "
                      f"{'an active' if has_agreement else 'no active'} "
                      f"agreement at case date)."),
            ))
            import_status = _escalate(import_status, STATUS_WARN_MISMATCH)

    # ---- Application status sanity check ---------------------------------
    application_status_text = _string_or_none(data.get(COL_APPLICATION_STATUS))
    if application_status_text and resolve_status(cursor, application_status_text) is None:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_APPLICATION_STATUS",
            raw_value=application_status_text,
            note=f"Row {raw.row_number}: Application Report Status not in ref_status_split.",
        ))
        import_status = _escalate(import_status, STATUS_UNRESOLVED)

    # ---- Build the record ------------------------------------------------
    record = CaseRecord(
        contract_id=contract_id,
        student_id=student_id,
        student_name=student_name,
        contract_signed_date=contract_signed_date,
        course_start_date=_coerce_date(data.get(COL_COURSE_START)),
        visa_received_date=_coerce_date(data.get(COL_VISA_RECEIVED)),
        case_office_id=case_office_id,
        country_id=country_id,
        institution_id=institution_id,
        referring_partner_id=referring_partner_id,
        referring_sub_agent_id=referring_sub_agent_id,
        referring_office_id=referring_office_id,
        institution_text_raw=institution_raw,
        referring_agent_text_raw=refer_text,
        client_type_code=_string_or_none(data.get(COL_CLIENT_TYPE)),
        application_status=application_status_text,
        course_status=_string_or_none(data.get(COL_COURSE_STATUS)),
        counsellor_staff_id=counsellor_staff_id,
        counsellor_role_id=counsellor_role_id,
        case_officer_staff_id=case_officer_staff_id,
        case_officer_role_id=case_officer_role_id,
        referring_source_type=source_type,
        import_status=import_status,
        incentive_amount=_parse_incentive(_get_incentive_value(data)),
        notes=_string_or_none(data.get(COL_NOTES)),
        run_year=run_year,
        run_month=run_month,
    )
    return record, notes
