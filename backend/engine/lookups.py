"""
Lookup helpers for the BonusReport calculation engine.

Pure functions that read from a ReferenceData snapshot to resolve
calculation inputs (rates today; splits, partner data, etc. later).
They never touch the database — ReferenceData is the only source.

Design rules:
  - O(1) where the data layer pre-indexes; O(N) linear scan otherwise.
    With ~113 rate rows, linear scan is microseconds — we'll add an
    index in the data layer if/when it matters.
  - Missing data raises an explicit error rather than returning a
    default. Silent defaults hide data-integrity bugs.
  - Returns full row dicts so callers can record the matched row in
    audit_json.

CHANGES IN THIS REVISION (item 3 — sub-agent CO scheme):
  - resolve_co_sub_subscheme(): new helper that looks up the
    subscheme for a given (staff, role, office, year, month) tuple.
    Used by calc_tier when slot.role_id is CO_SUB.
  - CoSubSubschemeNotFoundError: raised when the lookup finds no
    matching ref_staff_target row.
"""

from __future__ import annotations

from datetime import date

from .models import CaseInput, ReferenceData


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RateNotFoundError(LookupError):
    """No ref_rate row matches the given lookup keys + as_of_date."""


class AmbiguousRateError(LookupError):
    """
    More than one ref_rate row matches.

    The UNIQUE constraint in the schema should prevent this, but we
    check defensively so any future schema change that breaks
    uniqueness fails loudly here instead of producing wrong bonuses.
    """


class CoSubSubschemeNotFoundError(LookupError):
    """
    A CO_SUB slot has no resolvable subscheme.

    Either:
      - case.co_sub_subscheme_override is unset (or None), AND
      - no ref_staff_target row exists for the given
        (staff_id, role_id, office_id, year, month) tuple.

    Fix: insert the missing ref_staff_target row, or set
    case.co_sub_subscheme_override on the CaseInput.
    """


# ---------------------------------------------------------------------------
# Rate lookup
# ---------------------------------------------------------------------------

def lookup_rate(
    ref: ReferenceData,
    *,
    office_id: int,
    role_id: int,
    co_sub_subscheme: str | None,
    country_bucket: str,
    tier: str,
    as_of_date: date,
) -> dict:
    """
    Find the single ref_rate row matching all five lookup keys whose
    effective date range covers as_of_date.

    Effective date filter:
        effective_from <= as_of_date AND
        (effective_to IS NULL OR effective_to >= as_of_date)

    Args:
        ref:               ReferenceData snapshot (engine input).
        office_id:         dim_office.id
        role_id:           dim_role.id
        co_sub_subscheme:  'ENROL_ONLY_VISA_ONLY', 'ENROL_PLUS_VISA',
                           or None for non-sub-agent rows.
        country_bucket:    'TARGET' | 'FLAT' | 'VN_RMIT' | 'VN_BUV'
                           | 'VN_OTHER' | 'SUMMER'.
        tier:              'OUT_SYSTEM' | 'VISA_ONLY' | 'UNDER'
                           | 'MEET_HIGH' | 'MEET_LOW' | 'MEET'
                           | 'OVER' | 'FLAT'.
        as_of_date:        Used for effective-date filter. Per policy,
                           callers pass the contract_signed_date.

    Returns:
        The full row dict (caller pulls 'amount' and records the row
        in audit_json).

    Raises:
        RateNotFoundError:   no row matches.
        AmbiguousRateError:  more than one row matches.
    """
    matches: list[dict] = []

    for row in ref.rates.values():
        if row['office_id'] != office_id:
            continue
        if row['role_id'] != role_id:
            continue
        if row['co_sub_subscheme'] != co_sub_subscheme:
            continue
        if row['country_bucket'] != country_bucket:
            continue
        if row['tier'] != tier:
            continue

        # Effective date filter
        if row['effective_from'] > as_of_date:
            continue
        if row['effective_to'] is not None and row['effective_to'] < as_of_date:
            continue

        matches.append(row)

    if not matches:
        raise RateNotFoundError(
            f"No ref_rate row for office_id={office_id}, "
            f"role_id={role_id}, "
            f"co_sub_subscheme={co_sub_subscheme!r}, "
            f"country_bucket={country_bucket!r}, "
            f"tier={tier!r}, "
            f"as_of_date={as_of_date}"
        )

    if len(matches) > 1:
        raise AmbiguousRateError(
            f"{len(matches)} ref_rate rows match for "
            f"office_id={office_id}, role_id={role_id}, "
            f"co_sub_subscheme={co_sub_subscheme!r}, "
            f"country_bucket={country_bucket!r}, tier={tier!r}, "
            f"as_of_date={as_of_date}. "
            f"UNIQUE constraint should prevent this — schema bug."
        )

    return matches[0]


# ---------------------------------------------------------------------------
# CO_SUB subscheme resolution (item 3)
# ---------------------------------------------------------------------------

def resolve_co_sub_subscheme(
    case: CaseInput,
    *,
    staff_id: int,
    role_id: int,
    office_id: int,
    year: int,
    month: int,
    ref: ReferenceData,
) -> str:
    """
    Resolve the CO_SUB subscheme for a given slot in a given run-month.

    Resolution order (Pattern Y):
      1. If case.co_sub_subscheme_override is set, use it directly.
         This is the per-case override hatch — operator asserts the
         subscheme on the input CSV/form when the database doesn't
         reflect reality for this specific case.
      2. Otherwise scan ref.staff_targets for a row matching
         (staff_id, role_id, office_id, year, month) and read the
         co_sub_subscheme column.
      3. If neither yields a value, raise CoSubSubschemeNotFoundError.

    Args:
        case:       CaseInput (only co_sub_subscheme_override is read).
        staff_id:   The CO_SUB staff member.
        role_id:    Should be the CO_SUB role id. Pass it explicitly
                    rather than assume — keeps the helper composable.
        office_id:  Case office (where the work was done).
        year:       Run year.
        month:      Run month.
        ref:        ReferenceData snapshot (reads staff_targets).

    Returns:
        'ENROL_ONLY_VISA_ONLY' or 'ENROL_PLUS_VISA'.

    Raises:
        CoSubSubschemeNotFoundError: no override and no matching row.
    """
    # 1. Per-case override wins.
    if case.co_sub_subscheme_override is not None:
        return case.co_sub_subscheme_override

    # 2. Look up ref_staff_target.
    for row in ref.staff_targets.values():
        if row.get('staff_id') != staff_id:
            continue
        if row.get('role_id') != role_id:
            continue
        if row.get('office_id') != office_id:
            continue
        if row.get('year') != year:
            continue
        if row.get('month') != month:
            continue
        subscheme = row.get('co_sub_subscheme')
        if subscheme is not None:
            return subscheme
        # Found the row but the column is null — treat same as not found.
        # CO_SUB rows in ref_staff_target should always have a subscheme.
        break

    # 3. Hard fail.
    raise CoSubSubschemeNotFoundError(
        f"No CO_SUB subscheme resolvable for "
        f"staff_id={staff_id}, role_id={role_id}, "
        f"office_id={office_id}, year={year}, month={month}, "
        f"and case.co_sub_subscheme_override is None. "
        f"Fix: insert ref_staff_target row, or set "
        f"case.co_sub_subscheme_override."
    )
