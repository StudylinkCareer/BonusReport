"""
backend/tools/seed_asterisk_aliases.py

Seeds ref_institution_alias with the 94 asterisk-decorated institution
strings observed in historical CRM data, mapping each to its canonical
institution by stripping asterisks/suffix and looking up the cleaned form.

Algorithm
---------
For each raw asterisk-decorated string from CRM data:

  1. Normalize: strip leading/trailing whitespace, collapse internal whitespace
  2. Strip the asterisk decoration:
       "X **"            -> "X"
       "X * - Navitas"   -> "X"
       "X *"             -> "X"
       "X*"              -> "X"
  3. Look up the cleaned form in ref_institution_alias / ref_institution
     (case-insensitive). Follow merged_into_id if necessary.
  4. If resolved → INSERT the raw string as an alias of the canonical institution
     (skip if already exists).
  5. If unresolved → log to a TODO file for human attention.

This is a one-time data backfill. Idempotent — re-running won't create duplicates.

Usage:
    python -m backend.tools.seed_asterisk_aliases [--dry-run]

By default it commits. --dry-run reports what would be done without committing.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

# Add project root so 'backend.*' imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.data.connection import get_connection


# The 94 distinct asterisk-bearing strings extracted from /mnt/project/ reports.
# Format: list of (raw_string, total_occurrences) tuples for logging.
ASTERISK_STRINGS = [
    # populated below from the analysis we already did
]


# Pattern: capture name (greedy non-empty) before any combination of
# asterisks, optional " - <suffix>", optional whitespace.
_DECORATION_RE = re.compile(
    r"^(?P<name>.+?)\s*\*+\s*(?:[-/]\s*.+?)?\s*$"
)


def strip_decoration(raw: str) -> Optional[str]:
    """Return the cleaned form (asterisks + suffix removed), or None if
    the string doesn't have asterisk decoration we recognise."""
    m = _DECORATION_RE.match(raw)
    if not m:
        return None
    cleaned = m.group("name").strip()
    return cleaned if cleaned else None


def lookup_institution(cursor, cleaned_name: str) -> Optional[int]:
    """Look up institution_id by cleaned name. Try aliases first, then
    canonical names. Follow merged_into_id."""
    # alias table
    cursor.execute(
        """SELECT i.id, i.merged_into_id
             FROM ref_institution_alias a
             JOIN ref_institution       i ON i.id = a.institution_id
            WHERE LOWER(a.alias) = LOWER(%s)""",
        (cleaned_name,),
    )
    row = cursor.fetchone()
    if row:
        return row["merged_into_id"] or row["id"]

    # canonical name
    cursor.execute(
        """SELECT id, merged_into_id FROM ref_institution
            WHERE LOWER(canonical_name) = LOWER(%s)""",
        (cleaned_name,),
    )
    row = cursor.fetchone()
    if row:
        return row["merged_into_id"] or row["id"]

    return None


def insert_alias(cursor, institution_id: int, alias: str) -> bool:
    """Insert alias if not already present. Returns True if a new row was
    inserted, False if it already existed."""
    cursor.execute(
        """SELECT 1 FROM ref_institution_alias
            WHERE LOWER(alias) = LOWER(%s)""",
        (alias,),
    )
    if cursor.fetchone():
        return False
    cursor.execute(
        """INSERT INTO ref_institution_alias (institution_id, alias)
           VALUES (%s, %s)""",
        (institution_id, alias),
    )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Seed asterisk-decorated institution aliases."
    )
    parser.add_argument("--input", type=Path,
        default=Path("backend/tools/asterisk_institution_strings.txt"),
        help="Path to the file listing asterisk-decorated raw strings, "
             "one per line, in the format '[NNNx] <string>'.")
    parser.add_argument("--dry-run", action="store_true",
        help="Print what would be done; do not commit.")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2

    raw_strings: list[tuple[str, int]] = []
    line_re = re.compile(r"^\[\s*(\d+)x\]\s+(.+)$")
    for line in args.input.read_text(encoding="utf-8").splitlines():
        m = line_re.match(line)
        if m:
            raw_strings.append((m.group(2).strip(), int(m.group(1))))

    print(f"Loaded {len(raw_strings)} asterisk-decorated strings from {args.input}")

    inserted = 0
    already_present = 0
    unresolved: list[tuple[str, int, Optional[str]]] = []
    no_decoration: list[str] = []

    with get_connection() as conn, conn.cursor() as cur:
        for raw, count in raw_strings:
            cleaned = strip_decoration(raw)
            if cleaned is None:
                no_decoration.append(raw)
                continue

            inst_id = lookup_institution(cur, cleaned)
            if inst_id is None:
                unresolved.append((raw, count, cleaned))
                continue

            if insert_alias(cur, inst_id, raw):
                inserted += 1
                print(f"  + alias added: {raw!r} -> institution_id={inst_id} (cleaned={cleaned!r})")
            else:
                already_present += 1

        if args.dry_run:
            conn.rollback()
            print("\n[DRY RUN] All changes rolled back.")
        else:
            conn.commit()
            print("\nChanges committed.")

    print()
    print(f"Summary:")
    print(f"  Inserted (new aliases):      {inserted}")
    print(f"  Already present (no-op):     {already_present}")
    print(f"  Unresolved (cleaned form not in DB): {len(unresolved)}")
    print(f"  No decoration recognised:    {len(no_decoration)}")

    if unresolved:
        todo_path = Path("backend/tools/asterisk_aliases_TODO.txt")
        with todo_path.open("w", encoding="utf-8") as f:
            f.write("# Asterisk-decorated CRM strings that did not auto-resolve.\n")
            f.write("# Cleaned form (stripped of asterisks + suffix) was not found\n")
            f.write("# in ref_institution_alias or ref_institution.canonical_name.\n")
            f.write("#\n")
            f.write("# Format: <count>x  <raw>  ->  cleaned: <cleaned>\n")
            f.write("#\n")
            f.write("# Action: either add the cleaned form as a canonical institution,\n")
            f.write("# or add it as an alias to an existing institution. Then re-run\n")
            f.write("# this script to seed the asterisk-decorated aliases.\n\n")
            for raw, count, cleaned in unresolved:
                f.write(f"{count:>3}x  {raw}  ->  cleaned: {cleaned}\n")
        print(f"\nUnresolved strings written to: {todo_path}")

    if no_decoration:
        print(f"\nNo-decoration strings (regex failed; check manually):")
        for s in no_decoration:
            print(f"  {s!r}")

    return 0 if not unresolved else 1


if __name__ == "__main__":
    sys.exit(main())
