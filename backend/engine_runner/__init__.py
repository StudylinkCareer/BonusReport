"""
backend/engine_runner/

The engine runner is the glue layer between the database and the engine.

The engine itself (backend/engine/) is purely functional — it takes a
CaseInput + RunContext + ReferenceData and returns BonusPayments. The
runner:

  * Loads tx_case rows from Postgres for a given (year, month)
  * Adapts them to CaseInput dataclasses (adapter.py)
  * Builds the RunContext (YTD aggregator)
  * Calls the engine
  * Persists BonusPayments to tx_bonus_payment
  * Updates tx_clawback_balance

Modules:
  * adapter.py — tx_case row → CaseInput conversion
  * cli.py     — orchestrates a full run (next)
"""

from backend.engine_runner.adapter import (
    adapt_case,
    is_adaptable,
    CaseNotAdaptableError,
    NON_ADAPTABLE_STATUSES,
)

__all__ = [
    "adapt_case",
    "is_adaptable",
    "CaseNotAdaptableError",
    "NON_ADAPTABLE_STATUSES",
]
