"""
backend/importer/transformer.py

Convert a RawRow (from reader.py) into a CaseRecord ready for tx_case
insertion, plus zero or more NoteRecords for tx_case_notes_staging.

The transformer is where all the business rules live. It does NOT execute
SQL writes — it only reads (via resolvers) and produces dataclasses.

Asterisk convention in institution names (corrected per chat 2026-05-03):
  * (single)  : institution is reached via a routing partner. The partner
                may be a Group OR a Master Agent — ref_partner.classification
                determines which. If the CRM text includes a suffix
                (e.g. "X * - Navitas"), the suffix names the specific partner.
                If the suffix is missing (bare *), the partner is auto-resolved
                from ref_partner_institution if exactly one active link
                exists for this institution at the case date.
  ** (double) : institution is OUT OF SYSTEM. No partner involvement.
                referring_source_type = 'NONE'.
  none        : use the Refer Source Agent CRM column to determine routing.

Other locked policy decisions implemented here (do not re-derive):
  * Role is intrinsic to the staff member, not the column. The Excel column
    determines slot placement (counsellor_* vs case_officer_*); the role_id
    always comes from ref_staff.primary_role_id.
  * Departed staff cases are marked SCRAP and skipped from engine processing.
  * System Type vs institution.classification mismatch => WARN-MISMATCH.
  * Office-only cases (asterisk_count == 0 and empty Refer Source) =>
    source_type='OFFICE_ONLY'.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from backend.importer.reader import RawRow
from backend.importer.resolvers import (
    lookup_partner_institution_links,
    resolve_country,
    resolve_institution,
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

CLASSIFICATION_IN_PREFIX = "IN_"
CLASSIFICATION_OUT_PREFIX = "OUT_"


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
# Parsing helpers
# ---------------------------------------------------------------------------

# Matches institution name with trailing asterisks and optional partner suffix.
# Examples:
#   "Eynesbury College * - Navitas"  -> ("Eynesbury College", "*",  "Navitas")
#   "SAIBT *"                         -> ("SAIBT",             "*",  None)
#   "Some College **"                 -> ("Some College",      "**", None)
#   "Some College ** - Adventus"      -> ("Some College",      "**", "Adventus")  (rare)
_INSTITUTION_PATTERN = re.compile(
    r"^(?P<name>.+?)\s*(?P<stars>\*+)\s*(?:-\s*(?P<partner>.+?))?\s*$"
)


def _parse_institution_field(text: Optional[str]) -> tuple[Optional[str], int, Optional[str]]:
    """Split an Institution Name cell into (cleaned_name, asterisk_count, partner_text)."""
    if text is None:
        return None, 0, None
    s = str(text).strip()
    if not s:
        return None, 0, None
    match = _INSTITUTION_PATTERN.match(s)
    if not match:
        return s, 0, None
    name = match.group("name").strip()
    stars = match.group("stars") or ""
    partner = match.group("partner")
    if not stars:
        return s, 0, None
    return name, len(stars), (partner.strip() if partner else None)


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


def _get_institution_classification(cursor, institution_id: int) -> Optional[str]:
    cursor.execute(
        "SELECT classification FROM ref_institution WHERE id = %s",
        (institution_id,),
    )
    row = cursor.fetchone()
    return row["classification"] if row else None


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
# Asterisk routing — encapsulates the new partner-resolution logic
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _AsteriskRouting:
    """Result of asterisk parsing and partner lookup.

    partner_id           : resolved referring_partner_id, or None.
    source_type          : one of the SOURCE_* constants.
    notes                : list of NoteRecords to append for this row.
    status_to_escalate   : a STATUS_* constant the caller should _escalate against.
    """
    partner_id: Optional[int]
    source_type: str
    notes: list
    status_to_escalate: str


def _route_via_asterisk(
    cursor,
    asterisk_count: int,
    partner_suffix_text: Optional[str],
    institution_id: Optional[int],
    institution_text_raw: Optional[str],
    contract_signed_date: Optional[date],
    row_number: int,
) -> _AsteriskRouting:
    """Decide partner routing from the institution's asterisk markers.

    See the file-level docstring for the asterisk convention.
    """
    notes: list = []

    # ** (double asterisk) — out of system, no partner.
    if asterisk_count == 2:
        return _AsteriskRouting(
            partner_id=None,
            source_type=SOURCE_NONE,
            notes=notes,
            status_to_escalate=STATUS_OK,
        )

    # * (single asterisk) — routed via a partner.
    if asterisk_count == 1:
        if partner_suffix_text:
            # Suffix names the specific partner.
            partner_id = resolve_partner(cursor, partner_suffix_text)
            if partner_id is None:
                notes.append(NoteRecord(
                    warning_type="UNRESOLVED_PARTNER_SUFFIX",
                    raw_value=partner_suffix_text,
                    note=(f"Row {row_number}: '* - {partner_suffix_text}' did not "
                          f"resolve to a partner."),
                ))
                return _AsteriskRouting(None, SOURCE_UNRESOLVED, notes, STATUS_UNRESOLVED)

            # Optional verification — flag a soft warning if the suffix-named
            # partner doesn't have an active partner_institution link for this
            # institution. This catches CRM typos / stale data without blocking.
            if institution_id is not None:
                active_partners = lookup_partner_institution_links(
                    cursor, institution_id, contract_signed_date
                )
                if partner_id not in active_partners:
                    notes.append(NoteRecord(
                        warning_type="PARTNER_LINK_NOT_VERIFIED",
                        raw_value=partner_suffix_text,
                        note=(f"Row {row_number}: '{partner_suffix_text}' has no active "
                              f"link to this institution at case date — using suffix anyway."),
                    ))
                    # Informational; do not escalate import_status.

            return _AsteriskRouting(partner_id, SOURCE_PARTNER, notes, STATUS_OK)

        # Bare * — auto-resolve via partner_institution links.
        if institution_id is None:
            notes.append(NoteRecord(
                warning_type="BARE_ASTERISK_NO_INSTITUTION",
                raw_value=institution_text_raw,
                note=(f"Row {row_number}: bare * but institution did not resolve — "
                      f"cannot auto-detect partner."),
            ))
            return _AsteriskRouting(None, SOURCE_UNRESOLVED, notes, STATUS_UNRESOLVED_PARTNER)

        active_partners = lookup_partner_institution_links(
            cursor, institution_id, contract_signed_date
        )
        if len(active_partners) == 1:
            return _AsteriskRouting(active_partners[0], SOURCE_PARTNER, notes, STATUS_OK)
        elif len(active_partners) == 0:
            notes.append(NoteRecord(
                warning_type="BARE_ASTERISK_NO_LINKS",
                raw_value=institution_text_raw,
                note=(f"Row {row_number}: bare * but institution has no active "
                      f"partner links at case date."),
            ))
            return _AsteriskRouting(None, SOURCE_UNRESOLVED, notes, STATUS_UNRESOLVED_PARTNER)
        else:
            notes.append(NoteRecord(
                warning_type="BARE_ASTERISK_AMBIGUOUS",
                raw_value=institution_text_raw,
                note=(f"Row {row_number}: bare * with multiple active partners "
                      f"({len(active_partners)} candidates) — partner ambiguous."),
            ))
            return _AsteriskRouting(None, SOURCE_UNRESOLVED, notes, STATUS_UNRESOLVED_PARTNER)

    # Three or more asterisks — undefined; flag and treat as UNRESOLVED.
    if asterisk_count >= 3:
        notes.append(NoteRecord(
            warning_type="UNEXPECTED_ASTERISK_COUNT",
            raw_value=institution_text_raw,
            note=f"Row {row_number}: institution has {asterisk_count} asterisks; rule undefined.",
        ))
        return _AsteriskRouting(None, SOURCE_UNRESOLVED, notes, STATUS_UNRESOLVED)

    # asterisk_count == 0 — caller handles via Refer Source Agent column.
    return _AsteriskRouting(None, SOURCE_NONE, notes, STATUS_OK)


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

    if counsellor_text in DEPARTED_STAFF_NAMES or case_officer_text in DEPARTED_STAFF_NAMES:
        notes.append(NoteRecord(
            warning_type="DEPARTED_STAFF",
            raw_value=counsellor_text or case_officer_text,
            note=f"Row {raw.row_number}: case attributed to a departed staff member.",
        ))
        import_status = _escalate(import_status, STATUS_SCRAP)

    counsellor_staff_id = resolve_staff(cursor, counsellor_text) if counsellor_text else None
    case_officer_staff_id = resolve_staff(cursor, case_officer_text) if case_officer_text else None

    if counsellor_text and counsellor_staff_id is None:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_COUNSELLOR",
            raw_value=counsellor_text,
            note=f"Row {raw.row_number}: counsellor name not found in ref_staff.",
        ))
        import_status = _escalate(import_status, STATUS_UNRESOLVED)
    if case_officer_text and case_officer_staff_id is None:
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

    # ---- Institution parsing + resolution --------------------------------
    institution_raw = _string_or_none(data.get(COL_INSTITUTION))
    inst_clean, asterisk_count, partner_suffix_text = _parse_institution_field(
        data.get(COL_INSTITUTION)
    )
    institution_id = resolve_institution(cursor, inst_clean) if inst_clean else None
    if inst_clean and institution_id is None:
        notes.append(NoteRecord(
            warning_type="UNRESOLVED_INSTITUTION",
            raw_value=institution_raw,
            note=f"Row {raw.row_number}: institution not in ref_institution.",
        ))
        import_status = _escalate(import_status, STATUS_UNRESOLVED)

    # ---- Asterisk-based routing ------------------------------------------
    routing = _route_via_asterisk(
        cursor=cursor,
        asterisk_count=asterisk_count,
        partner_suffix_text=partner_suffix_text,
        institution_id=institution_id,
        institution_text_raw=institution_raw,
        contract_signed_date=contract_signed_date,
        row_number=raw.row_number,
    )
    notes.extend(routing.notes)
    import_status = _escalate(import_status, routing.status_to_escalate)

    referring_partner_id: Optional[int] = routing.partner_id
    referring_sub_agent_id: Optional[int] = None
    source_type = routing.source_type

    # ---- Refer Source Agent fallback (only when no asterisk in name) -----
    refer_text = _string_or_none(data.get(COL_REFER_SOURCE))
    if asterisk_count == 0:
        if not refer_text:
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
                        note=f"Row {raw.row_number}: Refer Source Agent did not resolve.",
                    ))
                    import_status = _escalate(import_status, STATUS_UNRESOLVED)

    # ---- System type vs institution.classification cross-check -----------
    system_type = _parse_system_type(data.get(COL_SYSTEM_TYPE))
    if institution_id is not None and system_type is not None:
        classification = _get_institution_classification(cursor, institution_id)
        if classification:
            mismatch = (
                (system_type == "IN" and not classification.startswith(CLASSIFICATION_IN_PREFIX))
                or (system_type == "OUT" and not classification.startswith(CLASSIFICATION_OUT_PREFIX))
            )
            if mismatch:
                notes.append(NoteRecord(
                    warning_type="SYSTEM_TYPE_MISMATCH",
                    raw_value=f"{data.get(COL_SYSTEM_TYPE)} vs {classification}",
                    note=(f"Row {raw.row_number}: System Type "
                          f"{data.get(COL_SYSTEM_TYPE)!r} disagrees with "
                          f"institution classification {classification!r}."),
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
