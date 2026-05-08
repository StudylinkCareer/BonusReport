"""
regression_parking.py
---------------------
Helper for the regression tool to skip cases that have been escalated
externally and are not expected to MATCH/GAP/BC-only-classify.

Usage in regression_compare.py:

    from regression_parking import load_parking_list, is_parked

    PARKED = load_parking_list()  # call once near the top of main()

    for each (year, month, contract_id) being compared:
        if is_parked(PARKED, year, month, contract_id):
            parked_count += 1
            continue   # skip this case entirely
        # ...existing comparison logic...

    # at the end of the run, print parked_count alongside MATCH/GAP/BC-only.
"""
import csv
from pathlib import Path

DEFAULT_PARKING_PATH = Path(__file__).parent / "regression_parking_lot.csv"


def load_parking_list(path: Path | str | None = None) -> set[tuple[int, int, str]]:
    """Load the parking lot CSV. Returns a set of (year, month, contract_id)."""
    p = Path(path) if path else DEFAULT_PARKING_PATH
    if not p.exists():
        return set()

    parked: set[tuple[int, int, str]] = set()
    with p.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                key = (int(row["year"]), int(row["month"]), row["contract_id"].strip())
                parked.add(key)
            except (KeyError, ValueError):
                continue
    return parked


def is_parked(parked_set: set[tuple[int, int, str]], year: int, month: int, contract_id: str) -> bool:
    """Check whether (year, month, contract_id) is in the parking list."""
    return (year, month, contract_id.strip()) in parked_set


if __name__ == "__main__":
    parked = load_parking_list()
    print(f"Loaded {len(parked)} parked cases:")
    for y, m, cid in sorted(parked):
        print(f"  {y}-{m:02d}  {cid}")
