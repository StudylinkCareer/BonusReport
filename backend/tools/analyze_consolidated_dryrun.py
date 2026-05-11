"""
backend/tools/analyze_consolidated_dryrun.py

Post-dry-run forensic tool. Answers two questions from the consolidated
import dry-run summary:

  Q1: dry-run reported N updates but the source file has M multi-row
      contracts. What are the M-N that didn't follow the pair-collapse
      pattern, and why?

  Q2: which rows had unresolvable run periods? Output them with full
      content so the business team can investigate the missing dates.

Approach
--------
Reads the consolidated CRM file directly and applies the orchestrator's
period derivation to each row. No DB connection needed. Groups by
Contract ID, classifies each multi-row contract, and emits two CSVs.

A multi-row contract is classified as:
  SAME_PERIOD     - all rows resolve to the same (year, month). The
                    UPSERT collapses them to 1 tx_case row (1 INSERT
                    + N-1 UPDATE log lines).
  DIFF_PERIOD     - rows resolve to different periods. Each produces
                    its own tx_case row (N INSERTs, 0 UPDATEs).
  ONE_UNRESOLVED  - at least one row's period couldn't be derived but
                    not all of them. The OK rows produce records; the
                    unresolved row(s) produce orphan notes only.
  ALL_UNRESOLVED  - all rows in this contract are period-unresolved.
                    The contract produces 0 tx_case rows.

The "Statuses match?" column on multi_row_contracts.csv flags whether all
rows in the contract share the same Application Report Status. When they
don't, the rows are also dumped to differing_status_rows.csv with full
source data — useful for handing to the business team when status
progression patterns warrant discussion (e.g., a SAME_PERIOD pair where
status went from "Current - Enrolled" to "Closed - Enrolled, then Visa
granted" within the same month).

Note this analysis does NOT account for the transformer-level skips
(SCRAP, MISSING_CONTRACT_ID, DEPARTED_STAFF, etc.) which require DB
access to detect. So a contract classified here as SAME_PERIOD might
still produce 0 updates if one of its rows is transformer-skipped at
import time.

Usage
-----
    python -m backend.tools.analyze_consolidated_dryrun PATH_TO_XLSX
    python -m backend.tools.analyze_consolidated_dryrun PATH_TO_XLSX --out-dir backend/logs

Outputs (default in backend/logs/)
----------------------------------
    multi_row_contracts.csv     - one row per multi-row contract, classified
    differing_status_rows.csv   - per-row dump for contracts where statuses
                                   differ between rows (full source data)
    period_unresolved.csv       - per-row dump for the period-unresolved rows
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from backend.importer.consolidated_orchestrator import derive_run_period
from backend.importer.consolidated_reader import iter_filtered_rows


CLASSIFICATIONS = {
    "SAME_PERIOD":    "All rows resolve to the same (year, month). UPSERT collapses to 1 tx_case row.",
    "DIFF_PERIOD":    "Rows resolve to different (year, month) tuples. Produces N rows, 0 UPDATEs.",
    "ONE_UNRESOLVED": "At least one row's period couldn't be derived (others may insert OK).",
    "ALL_UNRESOLVED": "Every row in the contract is period-unresolved. Produces 0 records.",
}


def _classify(periods: list[tuple[Optional[int], Optional[int]]]) -> str:
    n_unresolved = sum(1 for y, _ in periods if y is None)
    if n_unresolved == len(periods):
        return "ALL_UNRESOLVED"
    if n_unresolved > 0:
        return "ONE_UNRESOLVED"
    distinct = {p for p in periods}
    return "SAME_PERIOD" if len(distinct) == 1 else "DIFF_PERIOD"


def _fmt_value(v) -> str:
    """Format a cell value for CSV output."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def run(path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group rows by Contract ID; collect period-unresolved separately
    by_contract: dict[str, list[dict]] = defaultdict(list)
    unresolved: list[tuple[int, dict, str]] = []

    print(f"Reading {path.name}...")
    total_rows = 0
    for raw in iter_filtered_rows(path):
        total_rows += 1
        contract_id = str(raw.data.get("Contract ID") or "").strip()
        period = derive_run_period(raw.data)

        if contract_id:
            by_contract[contract_id].append({
                "row_number": raw.row_number,
                "data":       raw.data,
                "period":     (period.year, period.month),
                "status":     str(raw.data.get("Application Report Status") or "").strip(),
                "failure":    period.failure_reason,
            })

        if period.year is None:
            unresolved.append((raw.row_number, raw.data, period.failure_reason or ""))

    print(f"  rows: {total_rows}")
    print(f"  unique Contract IDs: {len(by_contract)}")
    print(f"  period-unresolved rows: {len(unresolved)}")

    # ---- Multi-row classification --------------------------------------
    multi = {cid: rows for cid, rows in by_contract.items() if len(rows) >= 2}
    print(f"  multi-row contracts: {len(multi)}")

    summary: dict[str, int] = defaultdict(int)
    detail_rows = []
    differing_status_contracts: list[tuple[str, list[dict]]] = []
    for cid, rows in sorted(multi.items()):
        periods = [r["period"] for r in rows]
        cls = _classify(periods)
        summary[cls] += 1

        period_strs = [
            f"{y}-{m:02d}" if y is not None else "UNRESOLVED"
            for y, m in periods
        ]
        statuses = [r["status"] for r in rows]
        statuses_match = len(set(statuses)) == 1
        if not statuses_match:
            differing_status_contracts.append((cid, rows))

        detail_rows.append({
            "Contract ID":      cid,
            "Row count":        len(rows),
            "Classification":   cls,
            "Statuses match?":  "Yes" if statuses_match else "No",
            "Periods":          " | ".join(period_strs),
            "Statuses":         " | ".join(statuses),
            "Row numbers":      " | ".join(str(r["row_number"]) for r in rows),
        })

    print("\nMulti-row contract classification:")
    for cls in ["SAME_PERIOD", "DIFF_PERIOD", "ONE_UNRESOLVED", "ALL_UNRESOLVED"]:
        n = summary.get(cls, 0)
        print(f"  {cls:18s}  {n:5d}   {CLASSIFICATIONS[cls]}")

    print(f"\nMulti-row contracts where statuses DIFFER between rows: {len(differing_status_contracts)}")
    print("  (these are dumped to differing_status_rows.csv for business review)")

    expected_updates = summary.get("SAME_PERIOD", 0)
    expected_extra_inserts = sum(
        len([p for p in [r["period"] for r in multi[cid]] if p[0] is not None])
        for cid in multi
        if _classify([r["period"] for r in multi[cid]]) == "DIFF_PERIOD"
    )
    print(f"\nExpected dry-run UPDATEs from this analysis: {expected_updates}")
    print(f"  (compare against dry-run summary's 'tx_case updated' count)")

    # ---- Multi-row CSV --------------------------------------------------
    multi_path = out_dir / "multi_row_contracts.csv"
    with open(multi_path, "w", newline="", encoding="utf-8") as f:
        cols = ["Contract ID", "Row count", "Classification", "Statuses match?",
                "Periods", "Statuses", "Row numbers"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(detail_rows)
    print(f"\nWrote {multi_path} ({len(detail_rows)} rows)")

    # ---- Differing-status full-row dump --------------------------------
    if differing_status_contracts:
        diff_path = out_dir / "differing_status_rows.csv"
        # Find a row to read column ordering from
        sample_data = differing_status_contracts[0][1][0]["data"]
        first_keys = list(sample_data.keys())
        cols = ["Contract ID", "Source row number"] + first_keys
        n_rows_written = 0
        with open(diff_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for cid, rows in differing_status_contracts:
                for r in rows:
                    data = r["data"]
                    w.writerow(
                        [cid, r["row_number"]]
                        + [_fmt_value(data.get(k)) for k in first_keys]
                    )
                    n_rows_written += 1
        print(f"Wrote {diff_path} ({n_rows_written} rows from "
              f"{len(differing_status_contracts)} contracts)")

    # ---- Period-unresolved CSV -----------------------------------------
    if unresolved:
        unresolved_path = out_dir / "period_unresolved.csv"
        # Use the first row's keys for column ordering; all rows have same shape.
        first_keys = list(unresolved[0][1].keys())
        cols = ["Source row number", "Failure reason"] + first_keys
        with open(unresolved_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row_num, data, reason in unresolved:
                w.writerow([row_num, reason] + [_fmt_value(data.get(k)) for k in first_keys])
        print(f"Wrote {unresolved_path} ({len(unresolved)} rows)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("path", type=Path, help="Path to consolidated CRM .xlsx")
    p.add_argument("--out-dir", type=Path, default=Path("backend/logs"),
                   help="Output directory (default: backend/logs)")
    args = p.parse_args()

    if not args.path.exists():
        print(f"File not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    run(args.path, args.out_dir)


if __name__ == "__main__":
    main()
