"""
backend/engine_runner/simulator.py

Single-case dry-run bonus estimator. Used by the
/api/cases/{id}/estimate-bonus endpoint to preview the bonus before
the case is calculated for real.

Key characteristics:
  * Runs the engine on ONE case (looked up via case_id → contract_id)
  * Never writes to the DB (persist is always False)
  * Returns the BonusPayment objects converted to dicts so they're
    JSON-serialisable
  * Loads the same context as run_engine_api (priority quota tracker,
    YTD aggregates, prior withholdings, etc.) so the estimate reflects
    the real state of the period at the moment it's requested

Does NOT modify the priority_quota_tracker or any other shared state.
The in-memory ctx is built fresh per call and discarded.

Mirrors the engine flow from api_runner._run_engine_within_connection
but skips the persist/snapshot/warning paths — those are only relevant
for the real run.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from psycopg.rows import dict_row

from backend.data.connection import get_connection
from backend.data.ref_loaders import load_priority_quota_tracker
from backend.data.reference_data import load_reference_data
from backend.engine.calc import calculate_case
from backend.engine_runner.adapter import (
    CaseNotAdaptableError,
    adapt_case,
)
from backend.engine_runner.cli import (
    build_run_context,
    load_cases,
    load_enrolments_by_staff_office,
    load_open_carry_overs,
    load_prior_priority_withholdings,
)
from backend.engine_runner.ytd_aggregator import aggregate_ytd


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CaseNotFoundError(Exception):
    """tx_case.id didn't match anything."""


class CasePeriodMissingError(Exception):
    """The case has no bonus_year_month set, so we can't pick a period
    to run the engine for. Set bonus_year_month during upload."""


class CaseNotInReviewError(Exception):
    """The case is not in workflow_state 'in_review'. Per business rules,
    estimates are only available while the case is being reviewed
    (uploaded cases haven't been validated yet; submitted/closed cases
    have already been calculated for real)."""

    def __init__(self, current_state: str) -> None:
        self.current_state = current_state
        super().__init__(
            f"Estimates are only available for cases in 'in_review'. "
            f"This case is currently '{current_state}'."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_bonus_for_case(case_id: int) -> dict:
    """Run the engine on a single case in dry-run mode. No DB writes.

    Returns:
        {
            "case": {
                "id": int,
                "contract_id": str,
                "student_name": str,
                "year": int,
                "month": int,
                "workflow_state": str,
            },
            "payments": [
                {
                    "staff_id": int | None,
                    "staff_name": str | None,
                    "role_id": int | None,
                    "role_code": str | None,
                    "role_name": str | None,
                    "gross_bonus": int,
                    "net_payable": int,
                    "priority_bonus": int,
                    "priority_withheld_amount": int,
                    "priority_unlocked_amount": int,
                    "priority_schedule_type": str,
                    ...all other BonusPayment fields...
                },
                ...
            ],
            "skipped": list[str],   # if the case couldn't be adapted
            "errored": list[str],   # if the engine raised
        }

    Raises:
        CaseNotFoundError      — case_id not in tx_case
        CasePeriodMissingError — case has no bonus_year_month
        CaseNotInReviewError   — case isn't in 'in_review' state
    """
    skipped: list[str] = []
    errored: list[str] = []
    payment_dicts: list[dict] = []
    case_info: dict[str, Any] = {}

    with get_connection() as conn:
        # ---- 1. Look up the case to get its period + state ---------------
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.contract_id,
                    c.student_name,
                    c.bonus_year_month,
                    c.workflow_state
                FROM tx_case c
                WHERE c.id = %s
                """,
                (case_id,),
            )
            case = cur.fetchone()

        if not case:
            raise CaseNotFoundError(f"Case {case_id} not found")

        if case["workflow_state"] != "in_review":
            raise CaseNotInReviewError(case["workflow_state"])

        if not case["bonus_year_month"]:
            raise CasePeriodMissingError(
                f"Case {case_id} ({case['contract_id']}) has no "
                "bonus_year_month set"
            )

        # Parse YYYY-MM
        try:
            year_str, month_str = case["bonus_year_month"].split("-")
            year = int(year_str)
            month = int(month_str)
            if not (1 <= month <= 12):
                raise ValueError
        except (ValueError, AttributeError):
            raise CasePeriodMissingError(
                f"Case {case_id} has invalid bonus_year_month "
                f"{case['bonus_year_month']!r}"
            )

        case_info = {
            "id": case["id"],
            "contract_id": case["contract_id"],
            "student_name": case["student_name"],
            "year": year,
            "month": month,
            "workflow_state": case["workflow_state"],
        }

        # ---- 2. Load staff + role name maps (for display labels) ---------
        with conn.cursor() as cur:
            cur.execute("SELECT id, canonical_name FROM ref_staff")
            staff_id_to_name = {
                r["id"]: r["canonical_name"] for r in cur.fetchall()
            }

            cur.execute("SELECT id, code, name FROM dim_role")
            role_id_to_info = {
                r["id"]: {"code": r["code"], "name": r["name"]}
                for r in cur.fetchall()
            }

        # ---- 3. Build engine context (same as the real engine) -----------
        ref = load_reference_data(conn)
        priority_quota_tracker = load_priority_quota_tracker(conn)

        with conn.cursor(row_factory=dict_row) as cursor:
            priority_ytd = aggregate_ytd(cursor, year=year, month=month)
            prior_withholdings = load_open_carry_overs(cursor)
            prior_priority_withholdings = load_prior_priority_withholdings(cursor)
            enrolments = load_enrolments_by_staff_office(
                cursor, year=year, month=month,
            )

            ctx = build_run_context(
                priority_ytd, prior_withholdings, enrolments, ref,
                year=year, month=month,
                priority_quota_tracker=priority_quota_tracker,
                prior_priority_withholdings=prior_priority_withholdings,
            )

            # ---- 4. Load only THIS case ----------------------------------
            case_rows = load_cases(
                cursor,
                year=year,
                month=month,
                contract_id=case["contract_id"],
                limit=1,
            )

            if not case_rows:
                skipped.append(
                    "Case is not loadable by the engine (likely a missing "
                    "reference or import_status != OK)."
                )
                return {
                    "case": case_info,
                    "payments": payment_dicts,
                    "skipped": skipped,
                    "errored": errored,
                }

            case_row = case_rows[0]

            # ---- 5. Adapt + calculate ------------------------------------
            try:
                case_input = adapt_case(case_row, ref)
            except CaseNotAdaptableError as e:
                skipped.append(f"Not adaptable: {e.reason}")
                return {
                    "case": case_info,
                    "payments": payment_dicts,
                    "skipped": skipped,
                    "errored": errored,
                }
            except Exception as e:  # noqa: BLE001
                errored.append(f"adapt failed: {type(e).__name__}: {e}")
                return {
                    "case": case_info,
                    "payments": payment_dicts,
                    "skipped": skipped,
                    "errored": errored,
                }

            try:
                case_payments = calculate_case(case_input, ctx, ref)
            except Exception as e:  # noqa: BLE001
                errored.append(f"calc failed: {type(e).__name__}: {e}")
                return {
                    "case": case_info,
                    "payments": payment_dicts,
                    "skipped": skipped,
                    "errored": errored,
                }

            # ---- 6. Convert BonusPayment objects to dicts ----------------
            for p in case_payments or []:
                d = _payment_to_dict(p, staff_id_to_name, role_id_to_info)
                payment_dicts.append(d)

    # ctx.priority_quota_state was mutated in-memory but never persisted.
    # GC will free it when we return — no side effect on the real DB.

    return {
        "case": case_info,
        "payments": payment_dicts,
        "skipped": skipped,
        "errored": errored,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payment_to_dict(
    payment: Any,
    staff_id_to_name: dict[int, str],
    role_id_to_info: dict[int, dict[str, str]],
) -> dict:
    """Convert a BonusPayment dataclass to a JSON-friendly dict, with
    staff_name and role_code/role_name resolved for display."""
    if is_dataclass(payment):
        d = asdict(payment)
    elif isinstance(payment, dict):
        d = dict(payment)
    else:
        # Last-resort fallback: try to read public attributes
        d = {
            k: getattr(payment, k)
            for k in dir(payment)
            if not k.startswith("_") and not callable(getattr(payment, k))
        }

    staff_id = d.get("staff_id")
    if isinstance(staff_id, int):
        d["staff_name"] = staff_id_to_name.get(staff_id)
    else:
        d["staff_name"] = None

    # role might be 'role_id' (int FK) or 'role' (string code) depending on
    # BonusPayment shape. Try both.
    role_id = d.get("role_id")
    if isinstance(role_id, int):
        info = role_id_to_info.get(role_id, {})
        d["role_code"] = info.get("code")
        d["role_name"] = info.get("name")
    else:
        d.setdefault("role_code", d.get("role"))
        d.setdefault("role_name", None)

    return d
