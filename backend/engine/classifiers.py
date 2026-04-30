"""
Pure classification functions for the BonusReport calculation engine.

These take a CaseInput (and sometimes ReferenceData / RunContext) and
return a canonical string indicating which lookup bucket/tier the case
falls into. They do not return amounts — only the strings used as
keys into ref_rate.

Per architecture.md §6.
"""

from __future__ import annotations

from .models import CaseInput, ReferenceData, RunContext, Slot


# ---------------------------------------------------------------------------
# Bucket constants (must match the CHECK constraint on ref_rate.country_bucket)
# ---------------------------------------------------------------------------

BUCKET_TARGET = 'TARGET'      # 14 countries with enrolment targets (D1.R2)
BUCKET_FLAT = 'FLAT'          # TH/PH/MY/KR — 2-out-target = 1-target
BUCKET_VN_RMIT = 'VN_RMIT'    # VN-domestic, RMIT
BUCKET_VN_BUV = 'VN_BUV'      # VN-domestic, BUV (British University Vietnam)
BUCKET_VN_OTHER = 'VN_OTHER'  # VN-domestic, all other institutions
BUCKET_SUMMER = 'SUMMER'      # Summer camps (du học hè) — flat bonus


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CountryNotFoundError(LookupError):
    """case.country_id has no matching row in ref.countries."""


class InstitutionNotFoundError(LookupError):
    """case.institution_id has no matching row in ref.institutions."""


class UnclassifiedCountryError(ValueError):
    """
    Country has neither is_target_country nor is_flat_country set,
    and isn't a domestic VN case. Means the data layer loaded a
    country that the bucket logic doesn't know how to handle.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_vn_domestic(country: dict) -> bool:
    """
    A country is the VN-domestic row when is_domestic_for is set
    (points to a VN office). This is the only row in dim_country
    where is_domestic_for is non-NULL today.
    """
    return country.get('is_domestic_for') is not None


def _vn_subbucket(institution: dict) -> str:
    """
    For a VN-domestic case, decide RMIT / BUV / OTHER.

    We match on canonical_name because Phase 5 schema doesn't carry a
    dedicated vn_subbucket column. If a future schema revision adds
    one, replace this with a column read.
    """
    name = institution.get('canonical_name', '').upper()
    if 'RMIT' in name:
        return BUCKET_VN_RMIT
    if 'BRITISH UNIVERSITY VIETNAM' in name or name.startswith('BUV'):
        return BUCKET_VN_BUV
    return BUCKET_VN_OTHER


# ---------------------------------------------------------------------------
# Country bucket classifier
# ---------------------------------------------------------------------------

def classify_country_bucket(case: CaseInput, ref: ReferenceData) -> str:
    """
    Determine which ref_rate.country_bucket applies to this case.

    Decision order:
      1. Summer programs override country → BUCKET_SUMMER. (TODO: hook
         this up once ref_service_fee carries a summer flag.)
      2. VN-domestic case → split by institution name into VN_RMIT /
         VN_BUV / VN_OTHER.
      3. Country has is_target_country = TRUE → BUCKET_TARGET.
      4. Country has is_flat_country = TRUE → BUCKET_FLAT.
      5. Otherwise raise UnclassifiedCountryError.

    Args:
        case: CaseInput.
        ref:  ReferenceData snapshot. Required shapes:
                ref.countries[id]    = {'code': str, 'name': str,
                                         'is_target_country': bool,
                                         'is_flat_country': bool,
                                         'is_domestic_for': int | None}
                ref.institutions[id] = {'canonical_name': str,
                                         'country_id': int, ...}

    Returns:
        One of the BUCKET_* constants.

    Raises:
        CountryNotFoundError, InstitutionNotFoundError,
        UnclassifiedCountryError.
    """
    institution = ref.institutions.get(case.institution_id)
    if institution is None:
        raise InstitutionNotFoundError(
            f"institution_id={case.institution_id} not in ref.institutions"
        )

    # 1. SUMMER — TODO once ref_service_fee carries a summer flag.
    # Today there's no field on CaseInput or ref tables that reliably
    # marks a summer program; we'll add one in a later phase. Until
    # then this branch is dormant.
    # Example future logic:
    #   if case.package_service_fee_id is not None:
    #       fee = ref.service_fees.get(case.package_service_fee_id)
    #       if fee and fee.get('is_summer'):
    #           return BUCKET_SUMMER

    country = ref.countries.get(case.country_id)
    if country is None:
        raise CountryNotFoundError(
            f"country_id={case.country_id} not in ref.countries"
        )

    # 2. VN-domestic
    if _is_vn_domestic(country):
        return _vn_subbucket(institution)

    # 3 & 4. Foreign country: target or flat
    if country.get('is_target_country'):
        return BUCKET_TARGET
    if country.get('is_flat_country'):
        return BUCKET_FLAT

    # 5. Defensive
    raise UnclassifiedCountryError(
        f"country_id={case.country_id} ({country.get('code')!r}) is "
        f"neither target nor flat and not VN-domestic — bucket logic "
        f"can't classify it. Check dim_country flags."
    )


# ---------------------------------------------------------------------------
# Tier constants (must match the CHECK constraint on ref_rate.tier)
# ---------------------------------------------------------------------------

TIER_UNDER = 'UNDER'            # enrolments < target
TIER_MEET_LOW = 'MEET_LOW'      # met target, low-band target size (TODO: threshold)
TIER_MEET_HIGH = 'MEET_HIGH'    # met target, high-band target size (TODO: threshold)
TIER_MEET = 'MEET'              # met target, no sub-band (default if low/high not used)
TIER_OVER = 'OVER'              # enrolments > target
TIER_OUT_SYSTEM = 'OUT_SYSTEM'  # case via master agent (overrides performance)
TIER_VISA_ONLY = 'VISA_ONLY'    # visa-only contract (overrides performance)
TIER_FLAT = 'FLAT'              # paired with non-TARGET buckets — no performance tier


# Target-size threshold separating MEET_LOW from MEET_HIGH.
# Per policy: bonus uplift is 100k/enrol when 2 ≤ target < 4, 200k/enrol
# when target ≥ 4. So the boundary is 4. Refine if business rules
# disagree.
# TODO: confirm this is the right threshold and where it's applied.
MEET_HIGH_TARGET_THRESHOLD = 4


# ---------------------------------------------------------------------------
# Tier exceptions
# ---------------------------------------------------------------------------

class TargetNotFoundError(LookupError):
    """
    No ref_staff_target row matches (staff_id, office_id, year, month).
    Raised only when the case actually needs a performance tier; OUT_SYSTEM
    and FLAT cases short-circuit before this lookup.
    """


# ---------------------------------------------------------------------------
# Tier classifier
# ---------------------------------------------------------------------------

def classify_tier(
    case: CaseInput,
    slot: Slot,
    country_bucket: str,
    ctx: RunContext,
    ref: ReferenceData,
) -> str:
    """
    Determine which ref_rate.tier applies for one slot on one case.

    Decision order (each step short-circuits):
      1. Master Agent route → TIER_OUT_SYSTEM.
      2. VISA_ONLY case → TIER_VISA_ONLY. (TODO: confirm trigger.)
      3. Non-TARGET bucket (FLAT, VN_*, SUMMER) → TIER_FLAT.
      4. Performance comparison vs ref_staff_target:
           enrolments < target → UNDER
           enrolments == target → MEET_LOW (target < threshold)
                                  MEET_HIGH (target ≥ threshold)
           enrolments > target → OVER

    Args:
        case:            CaseInput.
        slot:            The Slot we're computing tier for. Must be a
                         filled slot (staff_id is not None).
        country_bucket:  Pre-classified bucket — pass the result of
                         classify_country_bucket(). Avoids duplicate
                         lookups.
        ctx:             RunContext with enrolments_by_staff_office.
        ref:             ReferenceData. Tier classifier reads
                         ref.staff_targets (TODO: data layer must
                         load this).

    Returns:
        One of the TIER_* constants.

    Raises:
        TargetNotFoundError: no target row for this (staff, office,
        year, month) — shouldn't happen for an active staff member,
        but we surface it loudly if it does.
    """
    # Defensive: caller must pass a filled slot.
    assert slot.staff_id is not None, "classify_tier called with empty slot"

    # 1. Master Agent route overrides everything.
    if case.referring_partner_id is not None:
        return TIER_OUT_SYSTEM

    # 2. Visa-only — TODO: confirm what triggers this. Likely a status
    # code or a flag on the service-fee package. Leaving dormant for
    # now; revisit when implementing visa-only test cases.
    # Example future logic:
    #   if case.status_code == 'VISA_ONLY':
    #       return TIER_VISA_ONLY

    # 3. Non-TARGET buckets all use the FLAT tier.
    if country_bucket != BUCKET_TARGET:
        return TIER_FLAT

    # 4. Performance comparison
    key = (slot.staff_id, case.office_id)
    enrolments = ctx.enrolments_by_staff_office.get(key, 0)
    target = ctx.targets_by_staff_office.get(key)
    if target is None:
        raise TargetNotFoundError(
            f"No target found for staff_id={slot.staff_id}, "
            f"office_id={case.office_id}, year={ctx.year}, month={ctx.month}. "
            f"Cannot compute performance tier."
        )

    if enrolments < target:
        return TIER_UNDER
    if enrolments > target:
        return TIER_OVER

    # enrolments == target: split into LOW vs HIGH based on target size.
    if target < MEET_HIGH_TARGET_THRESHOLD:
        return TIER_MEET_LOW
    return TIER_MEET_HIGH
