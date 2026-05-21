"""
backend/importer/transformer.py

Convert a RawRow (from reader.py) into a CaseRecord ready for tx_case
insertion. The transformer reads (via resolvers) and produces dataclasses.
It does NOT execute SQL writes.

TRANSFORMER V2 — KEY POLICY (locked design decisions):

1. NEVER DROP A ROW. Every RawRow becomes a CaseRecord. If something
   can't be resolved, the record gets import_status='UNRESOLVED' and
   import_warnings populated. The writer always inserts. SCRAP is reserved
   for cases where the row is genuinely unusable (date in a text field,
   missing contract id, etc.).

2. APPLICATION STATUS resolves to a canonical id via the alias table
   (ref_status_split_alias). Both the canonical id and the raw text are
   stored on tx_case. Engine joins on the id.

3. DEPARTED STAFF — looked up from ref_staff.employment_status, NOT a
   hardcoded list. Cases attributed to departed staff get
   import_status='UNRESOLVED' with import_warnings explaining; DQO
   decides whether to release for engine processing.

4. WARNINGS ARE INLINE on import_warnings (concatenated semicolon-separated
   strings). No separate staging table. Note: flag_reason is a different
   column with workflow semantics (CORRECTIONS/ASSIGNMENTS) — not touched
   by the importer.

5. ROLE IS INTRINSIC to the staff member, not the column. role_id always
   comes from ref_staff.primary_role_id.

6. CO_SUB slot rule (preserved from v1): CO_SUB staff always populate
   case_officer slot, never counsellor slot, regardless of which Excel
   column they appeared in.

7. REFER SOURCE resolution order (preserved from v1): office → sub_agent
   → partner. Office-first protects against personal-name variants
   colliding with sub-agent or partner names.

8. INSTITUTION TYPE — DB is authoritative (Phase 1 of long-term
   institution-classification strategy). Logic:
     a) Compute marker-derived classification from institution name:
          `**` suffix → OUT_OF_SYSTEM
          `*`  suffix → VIA_PARTNER  (master agent or group routing)
          neither      → DIRECT
     b) Look up ref_institution_agreement by (institution_id, contract_date).
          When multiple rows match, VIA_PARTNER takes precedence over DIRECT
          (group agreement drives the algorithm; institution-level direct
           agreement only defines that institution's own target quota).
     c) Store DB's system_status in tx_case.institution_type.
     d) When marker-derived classification disagrees with DB row, flag
        INSTITUTION_TYPE_DISAGREEMENT — but DB still wins. Business uses
        the flag count over time to clean the DB; eventually markers
        become decorative.

9. SYSTEM TYPE — case-level routing from CRM (Trong/Ngoài hệ thống),
   stored on tx_case.system_type for audit. Cross-checked against the
   DB classification for sanity.

Import status escalation:
    OK < WARN-MISMATCH < UNRESOLVED < SCRAP
    Once at SCRAP the row is unusable for bonus calculation; engine
    skips. UNRESOLVED is recoverable — DQO can fix the underlying data
    and re-import.
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

INCENTIVE_THRESHOLD_VND = 5_000_000

# Role identifiers (matches dim_role.id)
ROLE_ID_CO_SUB = 18  # dim_role.code = 'CO_SUB' (D6.R6 sub-agent CO scheme)

# Canonical column names (must match ref_column_alias.canonical_name)
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
COL_PRE_SALES = "Pre-sales Name"
COL_NOTES = "Notes"
COL_INCENTIVE_PREFIX = "Customer Incentive"

# referring_source_type values
SOURCE_PARTNER = "PARTNER"
SOURCE_SUB_AGENT = "SUB_AGENT"
SOURCE_OFFICE_ONLY = "OFFICE_ONLY"
SOURCE_UNRESOLVED = "UNRESOLVED"

# import_status values
STATUS_OK = "OK"
STATUS_WARN_MISMATCH = "WARN-MISMATCH"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_SCRAP = "SCRAP"

# Vietnamese system_type strings (from CRM)
SYSTEM_TYPE_IN_VN = "Trong hệ thống"
SYSTEM_TYPE_OUT_VN = "Ngoài hệ thống"

# institution_type values (matches ref_institution_agreement.system_status)
INST_IN_SYSTEM = "IN_SYSTEM"
INST_OUT_OF_SYSTEM = "OUT_OF_SYSTEM"

# Marker-derived classifications (intermediate, not stored on tx_case;
# these are what the source-file asterisks ASSERT about the case routing)
MARKER_OUT_OF_SYSTEM = "OUT_OF_SYSTEM"
MARKER_VIA_PARTNER = "VIA_PARTNER"
MARKER_DIRECT = "DIRECT"


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseRecord:
    """The canonical, transformer-resolved form of one CRM row.

    Field types match tx_case columns. None = no value, no resolution,
    or explicitly absent in the source.
    """
    contract_id: str
    student_id: Optional[str]
    student_name: str
    contract_signed_date: Optional[date]
    course_start_date: Optional[date]
    visa_received_date: Optional[date]
    case_office_id: Optional[int]
    country_id: Optional[int]
    institution_id: Optional[int]
    referring_partner_id: Optional[int]
    referring_sub_agent_id: Optional[int]
    referring_office_id: Optional[int]
    institution_text_raw: Optional[str]
    referring_agent_text_raw: Optional[str]
    client_type_code: Optional[str]
    application_status: Optional[str]        # raw text (audit)
    application_status_id: Optional[int]     # canonical id (engine reads)
    course_status: Optional[str]
    counsellor_staff_id: Optional[int]
    counsellor_role_id: Optional[int]
    case_officer_staff_id: Optional[int]
    case_officer_role_id: Optional[int]
    pre_sales_staff_id: Optional[int]
    referring_source_type: str
    institution_type: Optional[str]          # DB-derived (IN_SYSTEM/OUT_OF_SYSTEM)
    system_type: Optional[str]               # CRM raw text (audit)
    import_status: str
    import_warnings: Optional[str]
    incentive_amount: int
    notes: Optional[str]
    run_year: int
    run_month: int
    bonus_year_month: str


# DEPRECATED — kept only so legacy code that still imports it doesn't
# crash. The new transformer never emits NoteRecords; warnings are now
# inline on CaseRecord.import_warnings. Remove this class once
# consolidated_orchestrator and any other legacy callers are migrated
# or removed.
@dataclass(frozen=True)
class NoteRecord:
    """Deprecated. Retained as an import-compatibility shim."""
    warning_type: str
    raw_value: Optional[str]
    note: str


# ---------------------------------------------------------------------------
# Status escalation
# ---------------------------------------------------------------------------

_STATUS_SEVERITY = {
    STATUS_OK: 0,
    STATUS_WARN_MISMATCH: 1,
    STATUS_UNRESOLVED: 2,
    STATUS_SCRAP: 3,
}


def _escalate(current: str, candidate: str) -> str:
    """Return whichever of current/candidate is more severe."""
    return candidate if _STATUS_SEVERITY[candidate] > _STATUS_SEVERITY[current] else current


# ---------------------------------------------------------------------------
# Flag accumulator
# ---------------------------------------------------------------------------

class _FlagBag:
    """Accumulates import_warnings fragments and escalates import_status.

    Use:
        flags = _FlagBag()
        flags.add("UNRESOLVED_COUNSELLOR: 'Some Name' not in ref_staff",
                  STATUS_UNRESOLVED)
        ...
        record = CaseRecord(..., import_status=flags.status,
                            import_warnings=flags.as_string())
    """

    def __init__(self) -> None:
        self.status: str = STATUS_OK
        self._parts: list[str] = []

    def add(self, msg: str, severity: str) -> None:
        self._parts.append(msg)
        self.status = _escalate(self.status, severity)

    def as_string(self) -> Optional[str]:
        if not self._parts:
            return None
        return "; ".join(self._parts)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _coerce_date(value: Any) -> Optional[date]:
    """datetime/date -> date. Anything else -> None.

    The reader has already converted d/m/yyyy strings to datetime, so
    by this point text values in date columns mean garbage we couldn't
    parse — caller should check separately and flag.
    """
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


def _parse_system_type(text: Optional[str]) -> Optional[str]:
    """'Trong hệ thống' -> 'IN', 'Ngoài hệ thống' -> 'OUT', else None."""
    if text is None:
        return None
    s = str(text).strip()
    if s == SYSTEM_TYPE_IN_VN:
        return "IN"
    if s == SYSTEM_TYPE_OUT_VN:
        return "OUT"
    return None


def _classify_from_markers(institution_raw: Optional[str]) -> str:
    """Derive routing classification from asterisk markers in the
    institution name.

    `**` suffix → OUT_OF_SYSTEM (canonical signal from source data)
    `*`  suffix → VIA_PARTNER   (master agent or group routing)
    neither      → DIRECT

    Note: `**` is checked first because every string with `**` also
    contains `*`.
    """
    if not institution_raw:
        return MARKER_DIRECT
    if "**" in institution_raw:
        return MARKER_OUT_OF_SYSTEM
    if "*" in institution_raw:
        return MARKER_VIA_PARTNER
    return MARKER_DIRECT


def _parse_incentive(value: Any) -> int:
    """Customer incentive amount: yes/no flag or VND value -> int đồng."""
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


def _normalize_pre_sales_name(name: Optional[str]) -> Optional[str]:
    """'SURNAME, Given Names' -> 'Surname Given Names'.

    Some Pre-sales entries use a Western convention where the surname
    is written first, in ALL CAPS, followed by a comma and given names.
    Example: 'MẠCH, Nguyễn Phi Vân' -> 'Mạch Nguyễn Phi Vân'.
    """
    if name is None:
        return None
    if "," not in name:
        return name.strip() or None
    surname, given = name.split(",", 1)
    surname = surname.strip().title()
    given = given.strip()
    if not surname and not given:
        return None
    if not given:
        return surname
    if not surname:
        return given
    return f"{surname} {given}"


def _get_incentive_value(data: dict[str, Any]) -> Any:
    """Find the Customer Incentive column (any tail variant)."""
    for header, value in data.items():
        if header.startswith(COL_INCENTIVE_PREFIX):
            return value
    return None


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


def _resolve_institution_classification(
    cursor,
    institution_id: Optional[int],
    case_date: Optional[date],
) -> Optional[str]:
    """Look up institution_type from ref_institution_agreement.

    Returns the institution's system_status (IN_SYSTEM / OUT_OF_SYSTEM)
    active at case_date. Returns None if no agreement row matches.

    PRECEDENCE RULE (locked):
        When the institution has both a VIA_PARTNER agreement (i.e. via
        a group) AND a DIRECT agreement active at the same date, the
        VIA_PARTNER agreement wins. The group agreement drives the bonus
        algorithm; a separate direct agreement on the same institution
        only defines that institution's own target quota.

        Tiebreaker: VIA_PARTNER > DIRECT.

    case_date is the contract_signed_date. If absent, defaults to
    CURRENT_DATE (acceptable because every row that gets here has
    already been written to disk; missing dates are flagged separately).
    """
    if institution_id is None:
        return None

    if case_date is None:
        cursor.execute(
            """SELECT system_status, agreement_type
                 FROM ref_institution_agreement
                WHERE institution_id = %s
                  AND effective_from <= CURRENT_DATE
                  AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                ORDER BY
                    CASE agreement_type WHEN 'VIA_PARTNER' THEN 0 ELSE 1 END,
                    effective_from DESC
                LIMIT 1""",
            (institution_id,),
        )
    else:
        cursor.execute(
            """SELECT system_status, agreement_type
                 FROM ref_institution_agreement
                WHERE institution_id = %s
                  AND effective_from <= %s
                  AND (effective_to IS NULL OR effective_to >= %s)
                ORDER BY
                    CASE agreement_type WHEN 'VIA_PARTNER' THEN 0 ELSE 1 END,
                    effective_from DESC
                LIMIT 1""",
            (institution_id, case_date, case_date),
        )

    row = cursor.fetchone()
    return row["system_status"] if row else None


def _resolve_application_status(
    cursor,
    raw_text: Optional[str],
) -> Optional[int]:
    """Resolve raw status text to ref_status_split.id.

    Tries alias table first, then canonical name. Returns None if no
    match. NBSP-tolerant, case-insensitive — matches the resolver
    semantics in resolvers.resolve_status.
    """
    if not raw_text:
        return None
    cleaned = " ".join(str(raw_text).split())
    if not cleaned:
        return None
    # Alias table first
    cursor.execute(
        """SELECT s.id
           FROM ref_status_split_alias a
           JOIN ref_status_split s ON s.id = a.status_id
           WHERE LOWER(a.alias) = LOWER(%s)""",
        (cleaned,),
    )
    row = cursor.fetchone()
    if row:
        return row["id"]
    # Canonical name fallback
    cursor.execute(
        "SELECT id FROM ref_status_split WHERE LOWER(status) = LOWER(%s)",
        (cleaned,),
    )
    row = cursor.fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def transform_row(
    cursor,
    raw: RawRow,
    *,
    run_year: int,
    run_month: int,
    bonus_year_month: str,
) -> CaseRecord:
    """Convert one RawRow into a CaseRecord. NEVER returns None.

    A row missing its Contract ID returns a SCRAP record with the
    contract_id field set to a placeholder so the writer still has
    something to UPSERT on. A row with garbage data returns the
    same — never lost, always inspectable.
    """
    flags = _FlagBag()
    data = raw.data

    # ---- Identity ---------------------------------------------------------
    contract_id_raw = _string_or_none(data.get(COL_CONTRACT_ID))
    if not contract_id_raw:
        # No contract id = the row can't be deduplicated or referenced.
        # SCRAP it with a synthetic id so it still gets written.
        flags.add(
            f"MISSING_CONTRACT_ID: row {raw.row_number} has no Contract ID",
            STATUS_SCRAP,
        )
        contract_id = f"NO-CONTRACT-ID-ROW-{raw.row_number}"
    else:
        contract_id = contract_id_raw

    student_id = _string_or_none(data.get(COL_STUDENT_ID))
    student_name = _string_or_none(data.get(COL_STUDENT_NAME)) or ""

    # ---- Date-in-text-field SCRAP detection ------------------------------
    for col in (COL_REFER_SOURCE, COL_INSTITUTION, COL_COUNSELLOR,
                COL_CASE_OFFICER, COL_PRE_SALES, COL_NOTES, COL_CLIENT_TYPE,
                COL_SYSTEM_TYPE, COL_APPLICATION_STATUS):
        if _is_datetime_value(data.get(col)):
            flags.add(
                f"DATE_IN_TEXT_FIELD: {col!r} contains a datetime value "
                f"({data.get(col)!r})",
                STATUS_SCRAP,
            )

    # ---- Staff resolution -------------------------------------------------
    counsellor_text = _string_or_none(data.get(COL_COUNSELLOR))
    case_officer_text = _string_or_none(data.get(COL_CASE_OFFICER))

    counsellor_staff_id = resolve_staff(cursor, counsellor_text) if counsellor_text else None
    case_officer_staff_id = resolve_staff(cursor, case_officer_text) if case_officer_text else None

    if counsellor_text and counsellor_staff_id is None:
        flags.add(
            f"UNRESOLVED_COUNSELLOR: {counsellor_text!r} not in ref_staff",
            STATUS_UNRESOLVED,
        )
    if case_officer_text and case_officer_staff_id is None:
        flags.add(
            f"UNRESOLVED_CASE_OFFICER: {case_officer_text!r} not in ref_staff",
            STATUS_UNRESOLVED,
        )

    counsellor_role_id = resolve_staff_role(cursor, counsellor_staff_id)
    case_officer_role_id = resolve_staff_role(cursor, case_officer_staff_id)

    # Departed-staff lookup via DB (no hardcoded list)
    for sid, label in (
        (counsellor_staff_id, "counsellor"),
        (case_officer_staff_id, "case_officer"),
    ):
        if sid is not None and resolve_staff_employment(cursor, sid) == "DEPARTED":
            flags.add(
                f"DEPARTED_STAFF: {label} (staff_id={sid}) is marked "
                f"DEPARTED in ref_staff",
                STATUS_UNRESOLVED,
            )

    # ---- Pre-sales resolution --------------------------------------------
    pre_sales_text_raw = _string_or_none(data.get(COL_PRE_SALES))
    pre_sales_text = _normalize_pre_sales_name(pre_sales_text_raw)
    pre_sales_staff_id = resolve_staff(cursor, pre_sales_text) if pre_sales_text else None

    if pre_sales_text and pre_sales_staff_id is None:
        flags.add(
            f"UNRESOLVED_PRE_SALES: {pre_sales_text_raw!r} (normalized "
            f"{pre_sales_text!r}) not in ref_staff",
            STATUS_UNRESOLVED,
        )

    if pre_sales_staff_id is not None and resolve_staff_employment(
            cursor, pre_sales_staff_id) == "DEPARTED":
        flags.add(
            f"DEPARTED_STAFF: pre_sales (staff_id={pre_sales_staff_id}) "
            f"is marked DEPARTED in ref_staff",
            STATUS_UNRESOLVED,
        )

    # ---- CO_SUB slot rule -------------------------------------------------
    # CO_SUB staff always populate case_officer slot, never counsellor slot.
    if counsellor_role_id == ROLE_ID_CO_SUB:
        if case_officer_staff_id is None:
            # Migrate counsellor → case_officer
            case_officer_staff_id = counsellor_staff_id
            case_officer_role_id = counsellor_role_id
        elif case_officer_staff_id != counsellor_staff_id:
            flags.add(
                f"CO_SUB_SLOT_CONFLICT: counsellor column has CO_SUB staff "
                f"{counsellor_text!r} but case_officer column has different "
                f"staff {case_officer_text!r}. CO_SUB entry dropped from "
                f"counsellor slot per CO_SUB-only-in-case_officer rule",
                STATUS_WARN_MISMATCH,
            )
        counsellor_staff_id = None
        counsellor_role_id = None

    # ---- Office derivation ------------------------------------------------
    case_office_id = (
        _get_staff_office(cursor, counsellor_staff_id)
        or _get_staff_office(cursor, case_officer_staff_id)
        or _get_staff_office(cursor, pre_sales_staff_id)
    )
    if case_office_id is None:
        flags.add(
            "NO_RESOLVABLE_OFFICE: no resolved staff member has a home_office_id",
            STATUS_UNRESOLVED,
        )

    # ---- Country ---------------------------------------------------------
    country_text = _string_or_none(data.get(COL_COUNTRY))
    country_id = resolve_country(cursor, country_text) if country_text else None
    if country_text and country_id is None:
        flags.add(
            f"UNRESOLVED_COUNTRY: {country_text!r} not in dim_country",
            STATUS_UNRESOLVED,
        )
    elif not country_text:
        flags.add(
            "MISSING_COUNTRY: Country of Study is blank",
            STATUS_UNRESOLVED,
        )

    # ---- Dates ------------------------------------------------------------
    contract_signed_date = _coerce_date(data.get(COL_CONTRACT_SIGNED))
    course_start_date = _coerce_date(data.get(COL_COURSE_START))
    visa_received_date = _coerce_date(data.get(COL_VISA_RECEIVED))

    # ---- Institution -----------------------------------------------------
    institution_raw = _string_or_none(data.get(COL_INSTITUTION))
    institution_id = resolve_institution(cursor, institution_raw) if institution_raw else None
    if institution_raw and institution_id is None:
        flags.add(
            f"UNRESOLVED_INSTITUTION: {institution_raw!r} not in "
            f"ref_institution / ref_institution_alias",
            STATUS_UNRESOLVED,
        )

    # ---- Refer Source Agent → routing ------------------------------------
    refer_text = _string_or_none(data.get(COL_REFER_SOURCE))
    referring_partner_id: Optional[int] = None
    referring_sub_agent_id: Optional[int] = None
    referring_office_id: Optional[int] = None

    if not refer_text:
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
                    flags.add(
                        f"UNRESOLVED_REFER_SOURCE: {refer_text!r} resolved "
                        f"to neither office, sub-agent, nor partner",
                        STATUS_UNRESOLVED,
                    )

    # ---- Institution type: DB-derived, marker-cross-checked --------------
    # DB is authoritative. Source-file asterisk markers are cross-checked
    # against the DB; disagreement is logged but DB still wins. Over time,
    # disagreements should drop to zero as the DB is cleaned up.
    institution_type = _resolve_institution_classification(
        cursor, institution_id, contract_signed_date
    )

    if institution_id is not None and institution_type is None:
        # Institution resolved but no agreement row found at case date.
        flags.add(
            f"NO_AGREEMENT: institution_id={institution_id} "
            f"({institution_raw!r}) has no ref_institution_agreement row "
            f"active at contract date {contract_signed_date}",
            STATUS_WARN_MISMATCH,
        )

    # Cross-check DB classification against marker-derived classification.
    # The marker classification is what the source file asserts; the DB is
    # what we trust. Disagreement → warning, but DB wins.
    marker_class = _classify_from_markers(institution_raw)
    if institution_type is not None:
        # Map DB system_status onto the marker space for comparison:
        #   DB OUT_OF_SYSTEM ↔ marker OUT_OF_SYSTEM (`**`)
        #   DB IN_SYSTEM     ↔ marker VIA_PARTNER OR DIRECT (`*` or none)
        db_expects_out = (institution_type == INST_OUT_OF_SYSTEM)
        marker_says_out = (marker_class == MARKER_OUT_OF_SYSTEM)
        if db_expects_out != marker_says_out:
            flags.add(
                f"INSTITUTION_TYPE_DISAGREEMENT: source markers say "
                f"{marker_class}, DB says {institution_type} "
                f"(institution_id={institution_id}, raw={institution_raw!r}). "
                f"Using DB value.",
                STATUS_WARN_MISMATCH,
            )

    # ---- System Type (CRM column, audit + sanity check) ------------------
    system_type_raw = _string_or_none(data.get(COL_SYSTEM_TYPE))
    system_type_parsed = _parse_system_type(data.get(COL_SYSTEM_TYPE))

    # Cross-check CRM system_type column against DB institution_type.
    if system_type_parsed is not None and institution_type is not None:
        crm_says_out = (system_type_parsed == "OUT")
        db_says_out = (institution_type == INST_OUT_OF_SYSTEM)
        if crm_says_out != db_says_out:
            flags.add(
                f"SYSTEM_TYPE_DISAGREEMENT: CRM System Type column says "
                f"{system_type_raw!r} ({'OUT' if crm_says_out else 'IN'}), "
                f"DB institution_type is {institution_type}. Using DB value.",
                STATUS_WARN_MISMATCH,
            )

    # ---- Application Status — canonical resolution ----------------------
    application_status_text = _string_or_none(data.get(COL_APPLICATION_STATUS))
    application_status_id = _resolve_application_status(
        cursor, application_status_text
    )
    if application_status_text and application_status_id is None:
        flags.add(
            f"UNRESOLVED_APPLICATION_STATUS: {application_status_text!r} "
            f"not in ref_status_split / ref_status_split_alias",
            STATUS_UNRESOLVED,
        )
    elif not application_status_text:
        flags.add(
            "MISSING_APPLICATION_STATUS: status column is blank",
            STATUS_UNRESOLVED,
        )

    # ---- Build the record ------------------------------------------------
    return CaseRecord(
        contract_id=contract_id,
        student_id=student_id,
        student_name=student_name,
        contract_signed_date=contract_signed_date,
        course_start_date=course_start_date,
        visa_received_date=visa_received_date,
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
        application_status_id=application_status_id,
        course_status=_string_or_none(data.get(COL_COURSE_STATUS)),
        counsellor_staff_id=counsellor_staff_id,
        counsellor_role_id=counsellor_role_id,
        case_officer_staff_id=case_officer_staff_id,
        case_officer_role_id=case_officer_role_id,
        pre_sales_staff_id=pre_sales_staff_id,
        referring_source_type=source_type,
        institution_type=institution_type,
        system_type=system_type_raw,
        import_status=flags.status,
        import_warnings=flags.as_string(),
        incentive_amount=_parse_incentive(_get_incentive_value(data)),
        notes=_string_or_none(data.get(COL_NOTES)),
        run_year=run_year,
        run_month=run_month,
        bonus_year_month=bonus_year_month,
    )
