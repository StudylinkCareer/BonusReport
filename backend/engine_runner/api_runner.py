"""
backend/engine_runner/api_runner.py

API-friendly wrapper around the engine runner. Mirrors the orchestration
in cli.main() but returns a structured dict instead of printing, so it
can be called from a FastAPI endpoint.

Reuses the same loader / persist primitives as cli.py — single source
of truth for the engine flow.

Transaction policy:
  Same as cli.py with --persist: opens a connection, runs the engine
  in dry-run, then if persist=True calls persist_payments +
  persist_priority_quota_tracker and commits at the end. Any exception
  before commit means the connection's `with` block rolls back, leaving
  the DB untouched.

Returns a JSON-serialisable result dict suitable for FastAPI's automatic
response encoding.
"""

from __future__ import annotations

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
    persist_payments,
    persist_priority_quota_tracker,
)
from backend.engine_runner.ytd_aggregator import aggregate_ytd


def run_engine_api(
    *,
    year: int,
    month: int,
    persist: bool = True,
    limit: int | None = None,
    contract_id: str | None = None,
) -> dict:
    """
    Run the engine for one (year, month) period. No stdout writes.

    Args:
        year, month: run period (month 1-12).
        persist: if True, write results to tx_bonus_payment + manage
            tx_carry_over_balance + tx_priority_quota_tracker. If False,
            performs a dry run with no DB writes.
        limit: optional cap on tx_case rows processed (for spot-checks).
        contract_id: optional contract filter (debug a single case).

    Returns:
        {
          "year": int,
          "month": int,
          "persist": bool,
          "total_cases": int,
          "adapted": int,
          "skipped": [{"contract_id": str, "reason": str}],
          "errored": [{"contract_id": str, "error": str, "phase": str}],
          "payment_count": int,
          "gross_total": int,
          "net_total": int,
        }

    Raises:
        ValueError if month is out of range.
        Any exception from the engine itself (caught at the API layer
        and turned into a 500).
    """
    if not (1 <= month <= 12):
        raise ValueError("month must be between 1 and 12")

    skipped: list[dict] = []
    errored: list[dict] = []
    payments: list[Any] = []
    adapted_count = 0
    total_cases = 0
    gross_total = 0
    net_total = 0

    with get_connection() as conn:
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

            case_rows = load_cases(
                cursor,
                year=year, month=month,
                contract_id=contract_id,
                limit=limit,
            )
            total_cases = len(case_rows)

            case_office_id_map = {r["id"]: r["case_office_id"] for r in case_rows}
            case_contract_id_map = {r["id"]: r["contract_id"] for r in case_rows}

            # Adapt + run engine per case
            for case_row in case_rows:
                cid = case_row.get("contract_id") or "<no-id>"

                try:
                    case_input = adapt_case(case_row, ref)
                except CaseNotAdaptableError as e:
                    skipped.append({"contract_id": cid, "reason": e.reason})
                    continue
                except Exception as e:
                    errored.append({
                        "contract_id": cid,
                        "error": f"{type(e).__name__}: {e}",
                        "phase": "adapt",
                    })
                    continue

                adapted_count += 1

                try:
                    case_payments = calculate_case(case_input, ctx, ref)
                except Exception as e:
                    errored.append({
                        "contract_id": cid,
                        "error": f"{type(e).__name__}: {e}",
                        "phase": "calc",
                    })
                    continue

                if case_payments:
                    payments.extend(case_payments)
                    for p in case_payments:
                        gross_total += int(p.gross_bonus or 0)
                        net_total += int(p.net_payable or 0)

            # Persist if requested
            if persist:
                persist_payments(
                    cursor,
                    year=year, month=month,
                    payments=payments,
                    case_office_id_map=case_office_id_map,
                    case_contract_id_map=case_contract_id_map,
                )
                persist_priority_quota_tracker(
                    cursor,
                    year=year, month=month,
                    priority_quota_state=ctx.priority_quota_state,
                )
                conn.commit()

    return {
        "year": year,
        "month": month,
        "persist": persist,
        "total_cases": total_cases,
        "adapted": adapted_count,
        "skipped": skipped,
        "errored": errored,
        "payment_count": len(payments),
        "gross_total": gross_total,
        "net_total": net_total,
    }
