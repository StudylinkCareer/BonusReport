"""
backend/importer/cached_resolvers.py

In-memory cache for the importer's reference-data lookups.

Why this exists
---------------
The per-row CRM importer (transformer + resolvers) makes ~5 DB SELECTs
per row. Against Railway-hosted Postgres each round-trip is ~100ms+,
so a 2440-row import takes ~3.5 hours of round-trip latency.

This module pre-loads every ref_* table that resolvers.py + transformer.py
read from, exposes the same function/method shapes as the originals,
and patches the modules so the existing transformer code calls cached
versions instead. Result: ~5-10 minute imports (DB INSERTs are still
per-row, but the SELECTs are gone).

Usage
-----
    with active_conn.cursor() as cursor:
        with ResolverCache(cursor):
            # resolvers.* and transformer.* are patched in this block.
            run_my_import(...)
        # patches restored on exit, even on exception.

Trade-offs
----------
- Cache is built once at construction. Concurrent INSERTs into ref_*
  during the run are NOT visible. Acceptable for single-process import.
- Cache misses return None — same contract as the underlying resolvers.
  If ref data is incomplete you get the same UNRESOLVED rows you'd get
  without the cache.
- Memory: ~few thousand strings + ints. Trivial.

Caveats
-------
- We patch transformer.py's two private helpers (_get_staff_office and
  _has_active_agreement) because they also do per-row DB lookups. This
  is by name on the transformer module — slight smell but contained,
  and reverted on exit.
- _has_active_agreement's date-range check is replicated in Python.
  Spot-checked against the SQL semantics in transformer.py.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (must match resolvers._normalize)
# ---------------------------------------------------------------------------

def _normalize(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    cleaned = " ".join(str(s).split())
    return cleaned if cleaned else None


def _key(s: Optional[str]) -> Optional[str]:
    n = _normalize(s)
    return n.lower() if n else None


# Names patched into the resolvers module
_RESOLVER_NAMES = (
    "resolve_country",
    "resolve_office",
    "resolve_sub_agent",
    "resolve_partner",
    "resolve_institution",
    "resolve_staff",
    "resolve_status",
    "resolve_staff_role",
    "resolve_staff_employment",
)

# Names patched into the transformer module. Includes resolver names
# (transformer did `from .resolvers import resolve_X` so the binding
# lives in transformer.__dict__) plus transformer's own private helpers
# that hit the DB.
_TRANSFORMER_PATCHABLE_NAMES = _RESOLVER_NAMES + (
    "_get_staff_office",
    "_has_active_agreement",
)


# ---------------------------------------------------------------------------
# Cache class
# ---------------------------------------------------------------------------

class ResolverCache:
    """Pre-loads reference data and exposes resolver-shaped methods.

    Construction eagerly loads from the cursor (a few seconds). Using
    the instance as a context manager patches the resolvers + transformer
    modules so all lookup calls hit the cache. __exit__ restores
    originals.
    """

    def __init__(self, cursor):
        # entity-text-lower -> id
        self.countries: dict[str, int] = {}
        self.offices: dict[str, int] = {}
        self.sub_agents: dict[str, int] = {}
        self.partners: dict[str, int] = {}
        self.institutions: dict[str, int] = {}
        self.staff: dict[str, int] = {}
        self.statuses: dict[str, int] = {}
        # staff_id -> ...
        self.staff_role: dict[int, Optional[int]] = {}
        self.staff_employment: dict[int, Optional[str]] = {}
        self.staff_office: dict[int, Optional[int]] = {}
        # institution_id -> [(effective_from, effective_to), ...]
        self.agreements: dict[int, list[tuple[Optional[date], Optional[date]]]] = {}

        self._original_resolver_bindings: dict[str, Any] = {}
        self._original_transformer_bindings: dict[str, Any] = {}

        self._load(cursor)

    # ------------------------------------------------------------------
    # Bulk load
    # ------------------------------------------------------------------

    def _load(self, cursor) -> None:
        log.info("Loading resolver cache from DB...")

        # Countries: name OR code, plus alias overlay (Tier 1B addition)
        cursor.execute("SELECT id, name, code FROM dim_country")
        for r in cursor.fetchall():
            if r.get("name"):
                self.countries[r["name"].strip().lower()] = r["id"]
            if r.get("code"):
                self.countries[r["code"].strip().lower()] = r["id"]
        cursor.execute("SELECT alias, country_id FROM ref_country_alias")
        for r in cursor.fetchall():
            self.countries[r["alias"].strip().lower()] = r["country_id"]

        # Offices: dim_office first, aliases override on conflict
        # (resolver checks alias first, so aliases must "win" in the dict)
        cursor.execute("SELECT id, name, code FROM dim_office")
        for r in cursor.fetchall():
            if r.get("name"):
                self.offices[r["name"].strip().lower()] = r["id"]
            if r.get("code"):
                self.offices[r["code"].strip().lower()] = r["id"]
        cursor.execute("SELECT alias, office_id FROM ref_office_alias")
        for r in cursor.fetchall():
            self.offices[r["alias"].strip().lower()] = r["office_id"]

        # Sub-agents (with merged_into_id)
        cursor.execute(
            "SELECT id, canonical_name, merged_into_id FROM ref_sub_agent"
        )
        sa_rows = cursor.fetchall()
        sa_final: dict[int, int] = {
            r["id"]: r["merged_into_id"] or r["id"] for r in sa_rows
        }
        for r in sa_rows:
            if r.get("canonical_name"):
                self.sub_agents[r["canonical_name"].strip().lower()] = sa_final[r["id"]]
        cursor.execute("SELECT alias, sub_agent_id FROM ref_sub_agent_alias")
        for r in cursor.fetchall():
            sa_id = r["sub_agent_id"]
            self.sub_agents[r["alias"].strip().lower()] = sa_final.get(sa_id, sa_id)

        # Partners (no merged_into)
        cursor.execute("SELECT id, name FROM ref_partner")
        for r in cursor.fetchall():
            if r.get("name"):
                self.partners[r["name"].strip().lower()] = r["id"]
        cursor.execute("SELECT alias, partner_id FROM ref_partner_alias")
        for r in cursor.fetchall():
            self.partners[r["alias"].strip().lower()] = r["partner_id"]

        # Institutions (with merged_into_id)
        cursor.execute(
            "SELECT id, canonical_name, merged_into_id FROM ref_institution"
        )
        inst_rows = cursor.fetchall()
        inst_final: dict[int, int] = {
            r["id"]: r["merged_into_id"] or r["id"] for r in inst_rows
        }
        for r in inst_rows:
            if r.get("canonical_name"):
                self.institutions[r["canonical_name"].strip().lower()] = inst_final[r["id"]]
        cursor.execute("SELECT alias, institution_id FROM ref_institution_alias")
        for r in cursor.fetchall():
            i_id = r["institution_id"]
            self.institutions[r["alias"].strip().lower()] = inst_final.get(i_id, i_id)

        # Staff (canonical, role, employment, home office in one query)
        cursor.execute(
            "SELECT id, canonical_name, primary_role_id, "
            "employment_status, home_office_id FROM ref_staff"
        )
        for r in cursor.fetchall():
            if r.get("canonical_name"):
                self.staff[r["canonical_name"].strip().lower()] = r["id"]
            self.staff_role[r["id"]] = r.get("primary_role_id")
            self.staff_employment[r["id"]] = r.get("employment_status")
            self.staff_office[r["id"]] = r.get("home_office_id")
        cursor.execute("SELECT alias, staff_id FROM ref_staff_alias")
        for r in cursor.fetchall():
            self.staff[r["alias"].strip().lower()] = r["staff_id"]

        # Statuses (alias-only — no canonical fallback in resolver)
        cursor.execute("SELECT alias, status_id FROM ref_status_split_alias")
        for r in cursor.fetchall():
            self.statuses[r["alias"].strip().lower()] = r["status_id"]

        # Institution agreements: keyed by institution_id, list of
        # (effective_from, effective_to) for the date-range checks.
        cursor.execute(
            "SELECT institution_id, effective_from, effective_to "
            "FROM ref_institution_agreement"
        )
        for r in cursor.fetchall():
            self.agreements.setdefault(r["institution_id"], []).append(
                (r.get("effective_from"), r.get("effective_to"))
            )

        log.info(
            "Resolver cache loaded: %d country keys, %d office keys, %d sub-agent keys, "
            "%d partner keys, %d institution keys, %d staff keys, %d status keys, "
            "%d agreements across %d institutions.",
            len(self.countries), len(self.offices), len(self.sub_agents),
            len(self.partners), len(self.institutions), len(self.staff),
            len(self.statuses),
            sum(len(v) for v in self.agreements.values()),
            len(self.agreements),
        )

    # ------------------------------------------------------------------
    # Resolver-shaped methods (signatures match backend.importer.resolvers).
    # `cursor` is accepted for compatibility but ignored.
    # ------------------------------------------------------------------

    def resolve_country(self, cursor, raw):
        k = _key(raw)
        return self.countries.get(k) if k else None

    def resolve_office(self, cursor, raw):
        k = _key(raw)
        return self.offices.get(k) if k else None

    def resolve_sub_agent(self, cursor, raw):
        k = _key(raw)
        return self.sub_agents.get(k) if k else None

    def resolve_partner(self, cursor, raw):
        k = _key(raw)
        return self.partners.get(k) if k else None

    def resolve_institution(self, cursor, raw):
        k = _key(raw)
        return self.institutions.get(k) if k else None

    def resolve_staff(self, cursor, raw):
        k = _key(raw)
        return self.staff.get(k) if k else None

    def resolve_status(self, cursor, raw):
        k = _key(raw)
        return self.statuses.get(k) if k else None

    def resolve_staff_role(self, cursor, staff_id):
        if staff_id is None:
            return None
        return self.staff_role.get(staff_id)

    def resolve_staff_employment(self, cursor, staff_id):
        if staff_id is None:
            return None
        return self.staff_employment.get(staff_id)

    # ------------------------------------------------------------------
    # Transformer private helpers (re-implemented against cache)
    # ------------------------------------------------------------------

    def _get_staff_office(self, cursor, staff_id):
        if staff_id is None:
            return None
        return self.staff_office.get(staff_id)

    def _has_active_agreement(self, cursor, institution_id, case_date) -> bool:
        """Replicates transformer._has_active_agreement against cached data.

        Mirrors the original SQL semantics:
        - institution_id is None     -> False
        - case_date is None          -> 'currently active': effective_to
                                        is NULL or >= today
        - case_date is provided      -> effective_from <= case_date AND
                                        (effective_to NULL or >= case_date)
        """
        if institution_id is None:
            return False
        agreements = self.agreements.get(institution_id)
        if not agreements:
            return False

        # Original SQL uses CURRENT_DATE when case_date is None. Match that.
        if case_date is None:
            check_date = date.today()
        elif isinstance(case_date, datetime):
            check_date = case_date.date()
        else:
            check_date = case_date

        for eff_from, eff_to in agreements:
            # Original only applies the effective_from filter when case_date
            # is provided; replicate that.
            if case_date is not None:
                if eff_from is not None and eff_from > check_date:
                    continue
            if eff_to is not None and eff_to < check_date:
                continue
            return True
        return False

    # ------------------------------------------------------------------
    # Patch / unpatch
    # ------------------------------------------------------------------

    def install(self) -> None:
        """Patch resolvers + transformer module bindings to use this cache.

        Imports happen here (not at module top) so cached_resolvers.py
        has no module-level dependency on resolvers/transformer — keeps
        import order clean.
        """
        from backend.importer import resolvers as _resolvers
        from backend.importer import transformer as _transformer

        self._original_resolver_bindings = {}
        for name in _RESOLVER_NAMES:
            if hasattr(_resolvers, name):
                self._original_resolver_bindings[name] = getattr(_resolvers, name)
                setattr(_resolvers, name, getattr(self, name))

        self._original_transformer_bindings = {}
        for name in _TRANSFORMER_PATCHABLE_NAMES:
            if hasattr(_transformer, name):
                self._original_transformer_bindings[name] = getattr(_transformer, name)
                setattr(_transformer, name, getattr(self, name))

        log.info(
            "ResolverCache installed: patched %d names on resolvers, %d on transformer.",
            len(self._original_resolver_bindings),
            len(self._original_transformer_bindings),
        )

    def uninstall(self) -> None:
        """Restore the original module bindings."""
        from backend.importer import resolvers as _resolvers
        from backend.importer import transformer as _transformer

        for name, fn in self._original_resolver_bindings.items():
            setattr(_resolvers, name, fn)
        self._original_resolver_bindings = {}

        for name, fn in self._original_transformer_bindings.items():
            setattr(_transformer, name, fn)
        self._original_transformer_bindings = {}

        log.info("ResolverCache uninstalled: original bindings restored.")

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.uninstall()
        return False  # don't suppress exceptions
