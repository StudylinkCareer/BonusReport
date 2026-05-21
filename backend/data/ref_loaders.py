"""
Reference data loaders for the BonusReport engine.

One function per ref_* / dim_* table. Each loader:
  - opens a cursor on a passed-in connection (caller manages connection)
  - SELECTs an EXPLICIT column list (Option B — columns are documented
    and stable; new columns require an explicit code change to consume)
  - returns dict[id, dict] keyed by row.id, matching the shape that
    ReferenceData expects

Loaders never JOIN — each function reads one table only. The engine's
lookup functions (engine/lookups.py) cross-reference tables in memory
using the foreign-key columns we return.

Why explicit columns?
  - Defensive: a schema change that drops or renames a column we use
    fails loudly in the loader (clear error), not silently mid-calc.
  - Documenting: the column list IS the engine's data contract for
    that table. Read the loader, see what's consumed.
  - Selective: tables like ref_institution have alias-related columns
    we don't want pulled into ReferenceData.

Schema baselines:
  - Phase7prep_v2 (deployed): ref_priority_partner -> ref_priority_list,
    ref_priority_partner_institution -> ref_priority_list_institution,
    new ref_priority_group, ref_partner_classification, ref_partner_flat_rate.
  - Phase7prep_v2_extension (deployed): ref_partner_institution renamed and
    reshaped as ref_institution_agreement (agreement_type, kpi_weight,
    nullable partner_id); ref_institution.classification dropped;
    ref_institution_agreement and ref_partner gained effective_from/to;
    ref_priority_list_institution gained bonus_pct_override / weight_override.
  - Phase 14a (DD-§I.6): ref_status_split gained is_visa_only_paid column;
    added to STATUS_SPLIT_SELECT below so the engine sees the new flag.
"""

from __future__ import annotations

import psycopg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows_by_id(cur: psycopg.Cursor) -> dict[int, dict]:
    """
    Read all fetched rows and key them by 'id'.

    Assumes the cursor is using dict_row factory (set on the connection
    by data.connection.get_connection) so each row comes back as a dict.

    Raises KeyError if a row is missing 'id' — would only happen if the
    SELECT forgot to include id in its column list, which is a code bug.
    """
    return {row['id']: dict(row) for row in cur.fetchall()}


def _rows_by_column(cur: psycopg.Cursor, key_column: str) -> dict:
    """
    Read all fetched rows and key them by the given column.

    Used for tables the engine looks up by a string key rather than
    the integer primary key (e.g. ref_status_split keyed by 'status',
    ref_calculation_param keyed by 'param_code').
    """
    return {row[key_column]: dict(row) for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# dim_country
# ---------------------------------------------------------------------------

# Engine consumers:
#   - classifiers.classify_country_bucket reads:
#       code, is_target_country, is_flat_country, is_domestic_for
#   - audit/display: name
COUNTRY_COLUMNS = (
    "id",
    "code",
    "name",
    "is_target_country",
    "is_flat_country",
    "is_domestic_for",
)


def load_countries(conn: psycopg.Connection) -> dict[int, dict]:
    """Load dim_country into {country_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(COUNTRY_COLUMNS)} FROM dim_country"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# dim_office
# ---------------------------------------------------------------------------

# Engine consumers:
#   - office_id is a lookup key for ref_rate (lookups.lookup_rate).
#   - classifiers.classify_country_bucket cross-references office_id
#     with country.is_domestic_for to decide VN-domestic vs not.
OFFICE_COLUMNS = (
    "id",
    "code",
    "name",
)


def load_offices(conn: psycopg.Connection) -> dict[int, dict]:
    """Load dim_office into {office_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(OFFICE_COLUMNS)} FROM dim_office"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_institution
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority joins via ref_priority_list_institution rather than
#     reading direct columns from this table (the old priority_partner_id
#     and aggregate_priority_partner_id columns were dropped in Phase7prep_v2).
#   - audit/display: canonical_name, country_id.
#   - merged_into_id is needed if any consumer wants to dereference
#     superseded rows; verification_status is informational.
#
# DROPPED in Phase7prep_v2_extension: classification.
#   In-system / out-of-system status is now derived from active agreements
#   in ref_institution_agreement at a given case date.
INSTITUTION_COLUMNS = (
    "id",
    "canonical_name",
    "country_id",
    "verification_status",
    "merged_into_id",
)


def load_institutions(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_institution into {institution_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(INSTITUTION_COLUMNS)} FROM ref_institution"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_institution_agreement
# ---------------------------------------------------------------------------

# Engine consumers:
#   - The "is this institution in-system at this date" question is answered
#     by checking for any active agreement row at the case date.
#   - Routing (DIRECT vs VIA_PARTNER + which partner) drives:
#       * fees_paid_non_enrolled override (was: classification == OUT_SYSTEM_MASTER_AGENT;
#         now: agreement_type == 'VIA_PARTNER' AND partner has MASTER_AGENT classification)
#       * KPI weighting (kpi_weight column directly).
#   - effective_from/to gate validity.
INSTITUTION_AGREEMENT_COLUMNS = (
    "id",
    "institution_id",
    "agreement_type",
    "partner_id",
    "kpi_weight",
    "effective_from",
    "effective_to",
)


def load_institution_agreements(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_institution_agreement into {agreement_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(INSTITUTION_AGREEMENT_COLUMNS)} FROM ref_institution_agreement"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_partner
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority and calc_tier resolve a partner's GROUP/MASTER_AGENT
#     classification via ref_partner_classification; this loader provides
#     the partner identity (name) and validity dates only.
#   - effective_from/to gate validity at the StudyLink↔partner level.
#
# Note: ref_partner uses 'name' (not 'canonical_name') for historical reasons.
PARTNER_COLUMNS = (
    "id",
    "name",
    "classification",
    "is_active",
    "effective_from",
    "effective_to",
)


def load_partners(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_partner into {partner_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PARTNER_COLUMNS)} FROM ref_partner"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_partner_classification
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority reads category to distinguish GROUP / MASTER_AGENT_OOS
#     / MASTER_AGENT_GENUINE and select the right bonus path.
#   - calc_tier reads kpi_weight (1.0 for GROUP, 0.7 for MA) to weight
#     enrolment counting against targets.
#   - bonus_model carries a key indicating which bonus algorithm to apply
#     for cases routed via this partner (FLAT vs PRIORITY_LIST etc).
PARTNER_CLASSIFICATION_COLUMNS = (
    "id",
    "partner_id",
    "category",
    "kpi_weight",
    "bonus_model",
    "effective_from",
    "effective_to",
)


def load_partner_classifications(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_partner_classification into {row_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PARTNER_CLASSIFICATION_COLUMNS)} FROM ref_partner_classification"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_partner_flat_rate
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_tier reads this when a case routes via a partner whose
#     bonus_model == 'FLAT' (currently ApplyBoard and Can-Achieve).
#   - Lookup key: (partner_id, office_id, role_id, as_of_date).
PARTNER_FLAT_RATE_COLUMNS = (
    "id",
    "partner_id",
    "office_id",
    "role_id",
    "amount",
    "effective_from",
    "effective_to",
)


def load_partner_flat_rates(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_partner_flat_rate into {row_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PARTNER_FLAT_RATE_COLUMNS)} FROM ref_partner_flat_rate"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# dim_role
# ---------------------------------------------------------------------------

# Engine consumers:
#   - payment_timing._resolve_split_pct branches on role 'code'
#     ('CO_SUB' vs 'CO_DIR' picks split column).
#   - calc_tier checks for 'CO_SUB' to trigger subscheme resolution.
ROLE_COLUMNS = (
    "id",
    "code",
    "name",
)


def load_roles(conn: psycopg.Connection) -> dict[int, dict]:
    """Load dim_role into {role_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(ROLE_COLUMNS)} FROM dim_role"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_staff
# ---------------------------------------------------------------------------

# Engine consumers:
#   - payment_timing reads departure_date for §I.6.4 6-month deferral.
#   - audit/display: name (mapped from canonical_name).
# Schema-to-engine column renames (engine fixtures use these names):
#   canonical_name → name
#   home_office_id → office_id
# We do the rename via SQL `AS` so consumers see the engine-style keys.
STAFF_SELECT = """
    id,
    canonical_name      AS name,
    email,
    home_office_id      AS office_id,
    primary_role_id     AS role_id,
    employment_status,
    departure_date
"""


def load_staff(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_staff into {staff_id: {col: val, ...}}."""
    sql = f"SELECT {STAFF_SELECT} FROM ref_staff"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_rate
# ---------------------------------------------------------------------------

# Engine consumers:
#   - lookups.lookup_rate scans by all five lookup keys + as_of_date.
#     office_id, role_id, co_sub_subscheme, country_bucket, tier are
#     match keys; amount is the result; effective_from/to gate validity.
RATE_COLUMNS = (
    "id",
    "office_id",
    "role_id",
    "co_sub_subscheme",
    "country_bucket",
    "tier",
    "amount",
    "effective_from",
    "effective_to",
)


def load_rates(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_rate into {rate_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(RATE_COLUMNS)} FROM ref_rate"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_priority_group
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority reads canonical_name for audit/display when reporting
#     a case's contribution against a Group's collective List target.
#   - country_id used for filtering / sanity checks.
#   - effective_from/to gate validity.
PRIORITY_GROUP_COLUMNS = (
    "id",
    "canonical_name",
    "country_id",
    "effective_from",
    "effective_to",
    # Phase 12b — payment timing rule for the group.
    # Values: 'STANDARD_50_50' (default) | 'CURRENT_ENROL_25_25_50'.
    # Read by payment_timing._resolve_priority_quota_status to decide
    # whether to apply the SPLIT branch for Current-Enrolled cases.
    "priority_split_rule_type",
)


def load_priority_groups(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_priority_group into {group_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PRIORITY_GROUP_COLUMNS)} FROM ref_priority_group"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_priority_list
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority reads:
#       canonical_name (display)
#       is_aggregate (resolution path: a List can have one or many member
#         institutions linked via ref_priority_list_institution)
#       group_id (Lists belong to Groups; KPI rolls up at Group level)
#       country_id (filter / sanity)
#   - effective_from/to gate validity (Lists can be retired or replaced).
#
# RENAMED from ref_priority_partner in Phase7prep_v2.
PRIORITY_LIST_COLUMNS = (
    "id",
    "canonical_name",
    "country_id",
    "is_aggregate",
    "group_id",
    "effective_from",
    "effective_to",
)


def load_priority_lists(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_priority_list into {list_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PRIORITY_LIST_COLUMNS)} FROM ref_priority_list"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_priority_list_institution
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority builds an in-memory map {institution_id: [list_ids]}
#     from this table to answer "what priority Lists does this institution
#     belong to at the case date?".
#   - institution_target_direct / institution_target_sub provide the
#     per-institution sub-targets within an aggregate List (e.g. each
#     Navitas college's own slice of the 'Other Navitas AU' total).
#   - bonus_pct_override and weight_override (Phase7prep_v2_extension):
#     when set, override the List-level ref_priority_target.bonus_pct
#     and the partner-level kpi_weight respectively, for promotional
#     periods at institution-within-list granularity.
#   - effective_from/to gate validity.
PRIORITY_LIST_INSTITUTION_COLUMNS = (
    "id",
    "priority_list_id",
    "institution_id",
    "institution_target_direct",
    "institution_target_sub",
    "bonus_pct_override",
    "weight_override",
    "effective_from",
    "effective_to",
)


def load_priority_list_institutions(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_priority_list_institution into {row_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PRIORITY_LIST_INSTITUTION_COLUMNS)} FROM ref_priority_list_institution"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_priority_target
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority reads bonus_pct (uplift % applied to tier_bonus) and
#     total_target / direct_target / sub_target (used to compute the
#     achievement factor against ctx.enrolments_by_priority_list_ytd).
#   - prior_year_owing affects target calculation in some scenarios.
#   - effective_from/to gate validity (replaced annual 'year' column;
#     promotions can now overlay temporary boosted rates).
#
# COLUMN RENAMED in Phase7prep_v2: priority_partner_id -> priority_list_id.
PRIORITY_TARGET_COLUMNS = (
    "id",
    "priority_list_id",
    "total_target",
    "direct_target",
    "sub_target",
    "bonus_pct",
    "prior_year_owing",
    "effective_from",
    "effective_to",
)


def load_priority_targets(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_priority_target into {target_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PRIORITY_TARGET_COLUMNS)} FROM ref_priority_target"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_status_split
# ---------------------------------------------------------------------------

# Engine consumers:
#   - payment_timing.apply_payment_timing reads everything: the three
#     split percentages and all four flag columns drive every timing
#     outcome (zero bonus, current-enrolled withhold, carry-over
#     unlock, fees-paid-non-enrolled override).
#   - calc_tier reads is_carry_over, fees_paid_non_enrolled, and
#     is_visa_only_paid (Phase 14a — DD-§I.6) to decide special-case
#     rate behavior.
#   - adapter._status_allows_null_institution reads is_visa_only_paid
#     to decide whether to permit NULL institution_id.
# Schema-to-engine column rename:
#   status → status_code (the engine refers to it as case.status_code,
#   so the row's own copy of that value is also called status_code)
# Keyed by the status string, not the row id, because that's how the
# engine looks it up: ref.status_splits[case.status_code].
#
# Alias expansion (added 2026-05-20):
#   ref_status_alias maps CRM-variant spellings (e.g. comma'd or
#   parenthesised forms) to a canonical ref_status_split.status. After
#   loading the canonical rows, load_status_splits expands the dict
#   so that ref.status_splits[alias_text] returns the same dict object
#   as ref.status_splits[canonical_status]. This means engine code
#   doesn't need to know about aliases — it just looks up whatever
#   status string the case has. The 'status_code' field inside the
#   row dict always carries the CANONICAL status, not the alias.
STATUS_SPLIT_SELECT = """
    id,
    status                  AS status_code,
    counts_as_enrolled,
    split_couns_pct,
    split_co_dir_pct,
    split_co_sub_pct,
    is_carry_over,
    is_current_enrolled,
    is_zero_bonus,
    fees_paid_non_enrolled,
    is_visa_only_paid,
    is_visa_granted,
    deduplication_rank
"""


def load_status_aliases(conn: psycopg.Connection) -> dict[str, str]:
    """Load ref_status_alias into {alias_text: canonical_status}.

    Returns an empty dict if the table doesn't exist (defensive — allows
    the engine to keep running pre-Phase-13b without alias support).
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT alias_text, canonical_status FROM ref_status_alias")
            return dict(cur.fetchall())
    except psycopg.errors.UndefinedTable:
        # Table doesn't exist yet — return empty to preserve backward compat
        conn.rollback()  # clear the failed-query state
        return {}


def load_status_splits(conn: psycopg.Connection) -> dict[str, dict]:
    """Load ref_status_split into {status_code: {col: val, ...}}.

    Also expands the dict with ref_status_alias entries: for each alias,
    the alias_text maps to the SAME row dict as the canonical_status.
    The engine looks up case.application_status verbatim against this
    dict; alias resolution is invisible to the engine.

    The 'status_code' field within each row dict is always the
    canonical status, regardless of which key (canonical or alias)
    was used to retrieve it.
    """
    sql = f"SELECT {STATUS_SPLIT_SELECT} FROM ref_status_split"
    with conn.cursor() as cur:
        cur.execute(sql)
        canonical = _rows_by_column(cur, 'status_code')

    # Expand with aliases — each alias resolves to the same row dict
    # as its canonical_status. Skip aliases whose canonical isn't loaded
    # (shouldn't happen given the FK, but defensive).
    aliases = load_status_aliases(conn)
    for alias_text, canonical_status in aliases.items():
        row = canonical.get(canonical_status)
        if row is None:
            continue  # canonical missing — alias is dead, ignore
        # Map the alias_text to the SAME row object. Sharing the dict
        # reference is intentional — any future mutation reaches both.
        canonical[alias_text] = row

    return canonical


# ---------------------------------------------------------------------------
# ref_service_fee
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_package: rows with category='PACKAGE' provide signing bonuses
#     for Superior/Premium/etc. packages.
#   - calc_addon: rows with category='ADDON' or 'SERVICE_FEE' or 'CONTRACT'
#     stack additively when the case has the matching service_code.
SERVICE_FEE_COLUMNS = (
    "id",
    "service_code",
    "category",
    "country_id",
    "fee_amount",
    "counsellor_signing_bonus",
    "co_signing_bonus",
    "is_active",
    "effective_from",
    "effective_to",
)


def load_service_fees(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_service_fee into {service_fee_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(SERVICE_FEE_COLUMNS)} FROM ref_service_fee"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_local_enrolment_bonus
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_flat_local reads flat_total_amount and the three pct columns
#     to compute counsellor / CO shares for VN-domestic cases (and any
#     other domestic-program countries when added).
LOCAL_ENROLMENT_BONUS_COLUMNS = (
    "id",
    "country_id",
    "flat_total_amount",
    "couns_dir_alone_pct",
    "couns_dir_with_co_pct",
    "co_pct_when_paired",
    "effective_from",
    "effective_to",
)


def load_local_enrolment_bonuses(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_local_enrolment_bonus into {row_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(LOCAL_ENROLMENT_BONUS_COLUMNS)} FROM ref_local_enrolment_bonus"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_calculation_param
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_tier reads FEES_PAID_NON_ENROLLED_RATE for the Phase 6c
#     fees_paid_non_enrolled override (Decision 1).
#   - Other params (INCENTIVE_THRESHOLD, PRESALES_FLAT_FEE,
#     LOVELY_COFFEE_REFERRAL) are scalars used by various calc functions.
# Keyed by param_code (string) because that's how the engine looks
# them up: ref.calculation_params['FEES_PAID_NON_ENROLLED_RATE'].
CALCULATION_PARAM_COLUMNS = (
    "id",
    "param_code",
    "value_numeric",
    "value_text",
    "effective_from",
    "effective_to",
)


def load_calculation_params(conn: psycopg.Connection) -> dict[str, dict]:
    """Load ref_calculation_param into {param_code: {col: val, ...}}."""
    sql = f"SELECT {', '.join(CALCULATION_PARAM_COLUMNS)} FROM ref_calculation_param"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_column(cur, 'param_code')


# ---------------------------------------------------------------------------
# ref_departure_rule
# ---------------------------------------------------------------------------

# Engine consumers:
#   - payment_timing currently uses a hardcoded 6-month threshold for
#     §I.6.4. This table provides the configurable rules: monthly
#     allowance per file-count band, settlement_delay_months, etc.
#   - Wired in fully when the departure handover work resumes (currently
#     blocked on policy questions Q11.2 et al).
DEPARTURE_RULE_COLUMNS = (
    "id",
    "rule_code",
    "files_count_min",
    "files_count_max",
    "monthly_allowance",
    "duration_months",
    "case_stage",
    "settlement_delay_months",
    "effective_from",
    "effective_to",
)


def load_departure_rules(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_departure_rule into {rule_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(DEPARTURE_RULE_COLUMNS)} FROM ref_departure_rule"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_complaint_deduction
# ---------------------------------------------------------------------------

# Engine consumers:
#   - payment_timing will read deduction_scope to decide which past
#     payments forfeit when a complaint is registered (whole month,
#     up-to-date, post-departure, etc.).
#   - Wiring is partial today; full implementation blocked on policy
#     questions about complaint signal mechanisms.
COMPLAINT_DEDUCTION_COLUMNS = (
    "id",
    "rule_code",
    "description",
    "deduction_scope",
    "effective_from",
    "effective_to",
)


def load_complaint_deductions(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_complaint_deduction into {rule_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(COMPLAINT_DEDUCTION_COLUMNS)} FROM ref_complaint_deduction"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_contract_target_tier
# ---------------------------------------------------------------------------

# Engine consumers:
#   - Section II contract bonus calculation (per-office target tiers and
#     per-contract excess amounts). Wiring blocked on Q9.1 — contract
#     target source resolution.
CONTRACT_TARGET_TIER_COLUMNS = (
    "id",
    "office_id",
    "target_min",
    "target_max",
    "excess_per_contract_amount",
    "consecutive_3mo_per_contract",
    "premium_min_target",
    "premium_per_contract_amount",
    "in_system_min_pct",
    "visa_pass_min_pct",
    "effective_from",
    "effective_to",
)


def load_contract_target_tiers(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_contract_target_tier into {tier_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(CONTRACT_TARGET_TIER_COLUMNS)} FROM ref_contract_target_tier"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_staff_target
# ---------------------------------------------------------------------------

# Engine consumers:
#   - lookups.resolve_co_sub_subscheme scans this for the matching
#     (staff_id, role_id, office_id, year, month) tuple and reads
#     co_sub_subscheme.
#   - Future: tier classification will also use the per-month target
#     (currently RunContext.targets_by_staff_office is built from
#     this table by the orchestrator).
STAFF_TARGET_COLUMNS = (
    "id",
    "staff_id",
    "role_id",
    "office_id",
    "year",
    "month",
    "target",
    "co_sub_subscheme",
)


def load_staff_targets(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_staff_target into {row_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(STAFF_TARGET_COLUMNS)} FROM ref_staff_target"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# tx_priority_quota_tracker (Phase 12b)
# ---------------------------------------------------------------------------

# Engine consumers:
#   - The engine_runner loads the current state of this table into
#     RunContext.priority_quota_state at run start, mutates it in place
#     as cases are processed by payment_timing, then UPSERTs the updated
#     state back at run end.
#
# This is a TRANSACTIONAL table (tx_*), not strictly a reference table,
# but it lives alongside the ref_* loaders here because the engine_runner
# loads it the same way during run setup and treats it as
# point-in-time-snapshot input, just like clawback balances.
PRIORITY_QUOTA_TRACKER_COLUMNS = (
    "id",
    "priority_list_institution_id",
    "enrolment_count_direct",
    "enrolment_count_sub",
    "last_updated_run_year",
    "last_updated_run_month",
)


def load_priority_quota_tracker(conn: psycopg.Connection) -> dict[int, dict]:
    """Load tx_priority_quota_tracker rows keyed by priority_list_institution_id.

    Returns {pli_id: {'count_direct': int, 'count_sub': int, ...}} suitable
    for assignment to ctx.priority_quota_state. The engine_runner is
    responsible for transforming this dict into the in-run shape (it
    stores both the count fields the engine needs and the audit fields
    the writer uses for UPSERTing).

    Returns an empty dict if the table is empty (e.g. fresh year, no
    priority enrolments yet — engine treats every case as quota-not-met
    until the first increment).
    """
    sql = f"SELECT {', '.join(PRIORITY_QUOTA_TRACKER_COLUMNS)} FROM tx_priority_quota_tracker"
    with conn.cursor() as cur:
        cur.execute(sql)
        out: dict[int, dict] = {}
        for row in cur.fetchall():
            pli_id = row['priority_list_institution_id']
            out[pli_id] = {
                'count_direct': row['enrolment_count_direct'] or 0,
                'count_sub':    row['enrolment_count_sub'] or 0,
                'last_updated_run_year':  row['last_updated_run_year'],
                'last_updated_run_month': row['last_updated_run_month'],
            }
        return out


# ---------------------------------------------------------------------------
# Smoke test — `python -m data.ref_loaders` runs this.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .connection import get_connection

    with get_connection() as conn:
        countries = load_countries(conn)
        offices = load_offices(conn)
        institutions = load_institutions(conn)
        institution_agreements = load_institution_agreements(conn)
        partners = load_partners(conn)
        partner_classifications = load_partner_classifications(conn)
        partner_flat_rates = load_partner_flat_rates(conn)
        roles = load_roles(conn)
        staff = load_staff(conn)
        rates = load_rates(conn)
        priority_groups = load_priority_groups(conn)
        priority_lists = load_priority_lists(conn)
        priority_list_institutions = load_priority_list_institutions(conn)
        priority_targets = load_priority_targets(conn)
        status_splits = load_status_splits(conn)
        service_fees = load_service_fees(conn)
        local_enrolment_bonuses = load_local_enrolment_bonuses(conn)
        calculation_params = load_calculation_params(conn)
        departure_rules = load_departure_rules(conn)
        complaint_deductions = load_complaint_deductions(conn)
        contract_target_tiers = load_contract_target_tiers(conn)
        staff_targets = load_staff_targets(conn)
        priority_quota_tracker = load_priority_quota_tracker(conn)

    def _show(label: str, data: dict) -> None:
        print(f"{label:30s} {len(data):>4} rows")
        if data:
            sample = next(iter(data.values()))
            print(f"  sample: {sample}")

    _show("Countries:",                  countries)
    _show("Offices:",                    offices)
    _show("Institutions:",               institutions)
    _show("Institution agreements:",     institution_agreements)
    _show("Partners:",                   partners)
    _show("Partner classifications:",    partner_classifications)
    _show("Partner flat rates:",         partner_flat_rates)
    _show("Roles:",                      roles)
    _show("Staff:",                      staff)
    _show("Rates:",                      rates)
    _show("Priority groups:",            priority_groups)
    _show("Priority lists:",             priority_lists)
    _show("Priority list institutions:", priority_list_institutions)
    _show("Priority targets:",           priority_targets)
    _show("Status splits:",              status_splits)
    _show("Service fees:",               service_fees)
    _show("Local enrol bonuses:",        local_enrolment_bonuses)
    _show("Calculation params:",         calculation_params)
    _show("Departure rules:",            departure_rules)
    _show("Complaint deducts:",          complaint_deductions)
    _show("Contract tgt tiers:",         contract_target_tiers)
    _show("Staff targets:",              staff_targets)
    _show("Priority quota tracker:",     priority_quota_tracker)
