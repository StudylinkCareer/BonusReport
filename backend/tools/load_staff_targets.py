"""
load_staff_targets.py — Load staff_targets.csv into ref_staff_target.

Reads the CSV produced by parse_targets.py and:
  1. Resolves staff_name_short → canonical full name via staff_alias_map.json
  2. Looks up staff_id (and role/office) from ref_staff
  3. Splits the special "Ngọc Hà/Phạm Lợi" shared row into two inserts
  4. Skips ENROL_SUMMER rows (no schema slot — by design per policy doc §I.2)
  5. Detects same-key collisions (e.g. Phạm Thị Lợi appearing in both sub-agent
     and monthly-office files for the same month/type) and keeps the first
     occurrence with a warning
  6. UPSERTs into ref_staff_target keyed on (staff_id, role_id, year, month, target_type)

Usage:
    python load_staff_targets.py
    python load_staff_targets.py --dry-run        # validate, no commit
    python load_staff_targets.py --csv path.csv   # override input

Defaults:
    --csv:        backend/tools/staff_targets.csv
    --alias-map:  backend/tools/staff_alias_map.json
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Resolve paths relative to this script: backend/tools/load_staff_targets.py → backend/
THIS_FILE = Path(__file__).resolve()
BACKEND_DIR = THIS_FILE.parent.parent
load_dotenv(BACKEND_DIR / '.env')

DEFAULT_CSV   = BACKEND_DIR / 'tools' / 'staff_targets.csv'
DEFAULT_ALIAS = BACKEND_DIR / 'tools' / 'staff_alias_map.json'

# CHECK constraint on ref_staff_target.target_type
ALLOWED_TYPES = {'CONTRACT', 'ENROLMENT', 'CANCELLED', 'TELESALES'}


def main():
    p = argparse.ArgumentParser(description='Load staff_targets.csv into ref_staff_target')
    p.add_argument('--csv', type=Path, default=DEFAULT_CSV,
                   help='Path to staff_targets.csv from parse_targets.py')
    p.add_argument('--alias-map', type=Path, default=DEFAULT_ALIAS,
                   help='Path to staff_alias_map.json')
    p.add_argument('--dry-run', action='store_true',
                   help='Validate and report; do not insert')
    args = p.parse_args()

    if not args.csv.exists():
        sys.exit(f'CSV not found: {args.csv}')
    if not args.alias_map.exists():
        sys.exit(f'Alias map not found: {args.alias_map}')
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        sys.exit('DATABASE_URL not set (expected in backend/.env)')

    alias_map = json.loads(args.alias_map.read_text(encoding='utf-8'))
    print(f'Loaded alias map: {len(alias_map)} short → canonical mappings')

    csv_rows = list(csv.DictReader(args.csv.open(encoding='utf-8-sig')))
    print(f'Read CSV:         {len(csv_rows)} target rows from {args.csv.name}')

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        # Build name → staff record lookup
        with conn.cursor() as cur:
            cur.execute('''
                SELECT id, canonical_name, primary_role_id, secondary_role_id,
                       home_office_id, employment_status
                FROM ref_staff
            ''')
            staff_by_name = {r['canonical_name']: r for r in cur.fetchall()}
        print(f'Loaded ref_staff: {len(staff_by_name)} staff records\n')

        # Build the upsert payload, deduping collisions
        bucket: dict[tuple, dict] = {}  # (staff_id, year, month, ttype) → row
        stats: dict[str, int] = defaultdict(int)
        unresolved_short: set[str] = set()
        collisions: list[tuple[dict, dict]] = []

        for r in csv_rows:
            short = r['staff_name_short']
            ttype = r['target_type']

            if ttype == 'ENROL_SUMMER':
                stats['skipped_summer'] += 1
                continue
            if ttype not in ALLOWED_TYPES:
                stats['skipped_unknown_type'] += 1
                continue

            canonical = alias_map.get(short)
            if not canonical:
                unresolved_short.add(short)
                stats['skipped_unresolved_alias'] += 1
                continue

            # Shared row → split into per-staff inserts
            if canonical.startswith('__SHARED:'):
                inner = canonical[len('__SHARED:'):-len('__')]
                names = inner.split('|')
                stats['split_shared_rows'] += 1
            else:
                names = [canonical]

            try:
                year = int(r['year'])
                month = int(r['month'])
                tval = float(r['target_value'])
            except (ValueError, KeyError):
                stats['skipped_bad_data'] += 1
                continue

            for cname in names:
                staff = staff_by_name.get(cname)
                if not staff:
                    print(f'  WARN: canonical {cname!r} not in ref_staff (skipping)')
                    stats['skipped_no_staff'] += 1
                    continue

                # Phạm Thị Lợi special: monthly-office file → CO_DIR (secondary role)
                role_id = staff['primary_role_id']
                if (cname == 'Phạm Thị Lợi'
                    and short == 'Phạm Lợi'
                    and staff['secondary_role_id']):
                    role_id = staff['secondary_role_id']

                key = (staff['id'], role_id, year, month, ttype)
                row = {
                    'staff_id':    staff['id'],
                    'role_id':     role_id,
                    'office_id':   staff['home_office_id'],
                    'year':        year,
                    'month':       month,
                    'target':      tval,
                    'target_type': ttype,
                    'target_unit': r.get('target_unit') or 'COUNT',
                    'notes':       (r.get('notes') or '')[:500],
                    '_source_short': short,
                    '_source_file':  r.get('source_file', ''),
                }
                if key in bucket:
                    other = bucket[key]
                    if abs(other['target'] - row['target']) > 1e-6:
                        collisions.append((other, row))
                    stats['collisions_kept_first'] += 1
                    continue
                bucket[key] = row
                stats['queued'] += 1

        print('Resolution summary:')
        print(f'  Queued for insert:           {stats["queued"]}')
        print(f'  Split shared rows:           {stats["split_shared_rows"]}')
        print(f'  Collisions (kept first):     {stats["collisions_kept_first"]}')
        print(f'  Skipped ENROL_SUMMER:        {stats["skipped_summer"]}')
        print(f'  Skipped unknown target_type: {stats["skipped_unknown_type"]}')
        print(f'  Skipped unresolved alias:    {stats["skipped_unresolved_alias"]}')
        print(f'  Skipped no staff in DB:      {stats["skipped_no_staff"]}')
        print(f'  Skipped bad data:            {stats["skipped_bad_data"]}')

        if unresolved_short:
            print(f'\n*** {len(unresolved_short)} short names with NO alias-map entry ***')
            for s in sorted(unresolved_short):
                print(f'    {s!r}')

        if collisions:
            print(f'\n*** {len(collisions)} value collisions (same key, different value) ***')
            print('    First occurrence kept; alternates listed below.')
            for first, alt in collisions[:15]:
                print(f"    staff_id={first['staff_id']} {first['year']}-{first['month']:02d} "
                      f"{first['target_type']}: kept {first['target']} from "
                      f"{first['_source_short']!r} ({first['_source_file']}), "
                      f"dropped {alt['target']} from "
                      f"{alt['_source_short']!r} ({alt['_source_file']})")
            if len(collisions) > 15:
                print(f'    ... and {len(collisions) - 15} more')

        if args.dry_run:
            print('\n--dry-run: not committing.')
            return

        if not bucket:
            print('\nNothing to insert.')
            return

        # Strip helper fields
        rows_for_db = [
            {k: v for k, v in row.items() if not k.startswith('_')}
            for row in bucket.values()
        ]

        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS cnt FROM ref_staff_target')
            before = cur.fetchone()['cnt']

            cur.executemany(
                '''
                INSERT INTO ref_staff_target (
                    staff_id, role_id, office_id,
                    year, month,
                    target, target_type, target_unit, notes
                )
                VALUES (
                    %(staff_id)s, %(role_id)s, %(office_id)s,
                    %(year)s, %(month)s,
                    %(target)s, %(target_type)s, %(target_unit)s, %(notes)s
                )
                ON CONFLICT (staff_id, role_id, year, month, target_type) DO UPDATE
                SET target      = EXCLUDED.target,
                    target_unit = EXCLUDED.target_unit,
                    office_id   = EXCLUDED.office_id,
                    notes       = EXCLUDED.notes,
                    updated_at  = NOW()
                ''',
                rows_for_db,
            )

            cur.execute('SELECT COUNT(*) AS cnt FROM ref_staff_target')
            after = cur.fetchone()['cnt']

        conn.commit()
        print(f'\nLoaded successfully.')
        print(f'  Before: {before:5d} rows')
        print(f'  After:  {after:5d} rows')
        print(f'  Net:   +{after - before:5d} new (others upserted)')


if __name__ == '__main__':
    main()
