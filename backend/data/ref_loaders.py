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

This file will grow. We start with three loaders today and add the
rest in subsequent batches:
  Batch 1 (done): institutions, countries, offices
  Batch 2 (done): roles, staff, rates
  Batch 3 (done): priority_partners, priority_targets, status_splits
  Batch 4 (done): service_fees, local_enrolment_bonuses,
                  calculation_params, departure_rules,
                  complaint_deductions, contract_target_tiers,
                  staff_targets
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
#   - calc_priority reads priority_partner_id and aggregate_priority_partner_id
#     to decide whether the case earns a priority bonus uplift.
#   - calc_tier reads classification (e.g. 'OUT_SYSTEM_MASTER_AGENT') for
#     the Phase 6c fees_paid_non_enrolled override.
#   - audit/display: canonical_name, country_id
INSTITUTION_COLUMNS = (
    "id",
    "canonical_name",
    "country_id",
    "classification",
    "priority_partner_id",
    "aggregate_priority_partner_id",
)


def load_institutions(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_institution into {institution_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(INSTITUTION_COLUMNS)} FROM ref_institution"
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
# ref_priority_partner
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority reads name (display) and is_aggregate (resolution
#     path: institutions point to either a 1:1 priority_partner_id or
#     to an aggregate via aggregate_priority_partner_id).
PRIORITY_PARTNER_COLUMNS = (
    "id",
    "name",
    "country_id",
    "is_aggregate",
)


def load_priority_partners(conn: psycopg.Connection) -> dict[int, dict]:
    """Load ref_priority_partner into {priority_partner_id: {col: val, ...}}."""
    sql = f"SELECT {', '.join(PRIORITY_PARTNER_COLUMNS)} FROM ref_priority_partner"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_id(cur)


# ---------------------------------------------------------------------------
# ref_priority_target
# ---------------------------------------------------------------------------

# Engine consumers:
#   - calc_priority reads bonus_pct (uplift % applied to tier_bonus) and
#     total_target / direct_target / sub_target (used to compute the
#     achievement factor against ctx.enrolments_by_priority_partner_ytd).
#   - prior_year_owing affects target calculation in some scenarios.
PRIORITY_TARGET_COLUMNS = (
    "id",
    "priority_partner_id",
    "year",
    "total_target",
    "direct_target",
    "sub_target",
    "bonus_pct",
    "prior_year_owing",
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
#   - calc_tier reads is_carry_over and fees_paid_non_enrolled to
#     decide special-case rate behavior.
# Schema-to-engine column rename:
#   status → status_code (the engine refers to it as case.status_code,
#   so the row's own copy of that value is also called status_code)
# Keyed by the status string, not the row id, because that's how the
# engine looks it up: ref.status_splits[case.status_code].
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
    is_visa_granted,
    deduplication_rank
"""


def load_status_splits(conn: psycopg.Connection) -> dict[str, dict]:
    """Load ref_status_split into {status_code: {col: val, ...}}."""
    sql = f"SELECT {STATUS_SPLIT_SELECT} FROM ref_status_split"
    with conn.cursor() as cur:
        cur.execute(sql)
        return _rows_by_column(cur, 'status_code')


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
# Smoke test — `python -m data.ref_loaders` runs this.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .connection import get_connection

    with get_connection() as conn:
        countries = load_countries(conn)
        offices = load_offices(conn)
        institutions = load_institutions(conn)
        roles = load_roles(conn)
        staff = load_staff(conn)
        rates = load_rates(conn)
        priority_partners = load_priority_partners(conn)
        priority_targets = load_priority_targets(conn)
        status_splits = load_status_splits(conn)
        service_fees = load_service_fees(conn)
        local_enrolment_bonuses = load_local_enrolment_bonuses(conn)
        calculation_params = load_calculation_params(conn)
        departure_rules = load_departure_rules(conn)
        complaint_deductions = load_complaint_deductions(conn)
        contract_target_tiers = load_contract_target_tiers(conn)
        staff_targets = load_staff_targets(conn)

    def _show(label: str, data: dict) -> None:
        print(f"{label:24s} {len(data):>4} rows")
        if data:
            sample = next(iter(data.values()))
            print(f"  sample:     {sample}")

    _show("Countries:",           countries)
    _show("Offices:",             offices)
    _show("Institutions:",        institutions)
    _show("Roles:",               roles)
    _show("Staff:",               staff)
    _show("Rates:",               rates)
    _show("Priority partners:",   priority_partners)
    _show("Priority targets:",    priority_targets)
    _show("Status splits:",       status_splits)
    _show("Service fees:",        service_fees)
    _show("Local enrol bonuses:", local_enrolment_bonuses)
    _show("Calculation params:",  calculation_params)
    _show("Departure rules:",     departure_rules)
    _show("Complaint deducts:",   complaint_deductions)
    _show("Contract tgt tiers:",  contract_target_tiers)
    _show("Staff targets:",       staff_targets)
