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
"""

from __future__ import annotations

from datetime import date

from .models import ReferenceData


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
