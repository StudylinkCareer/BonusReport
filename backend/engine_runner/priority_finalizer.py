"""
backend/engine_runner/priority_finalizer.py

Post-month retroactive catch-up for priority bonus.

# What it does

After all cases in run-month M have been processed by the main engine
flow, this finalizer:

  1. Builds a YTD snapshot inclusive of M (i.e. aggregate_ytd up to
     month=M+1 exclusive).
  2. Walks every (case_id, slot) that:
       - had a payment row written this year,
       - has zero priority_bonus YTD on that (case, slot),
       - is at an institution on a priority list,
       - has an enrolled status,
       - has a priority-eligible role (COUNS_DIR / CO_DIR / CO_SUB).
  3. For each such (case, slot), checks whether the threshold for the
     slot's role-channel and the list's total is now met based on the
     post-M snapshot.
  4. Where it is, INSERTs a new tx_bonus_payment row with:
        run_year=Y, run_month=M (the month the threshold was crossed
        or the case was processed in a post-crossing month),
        priority_bonus = tier_bonus × bonus_pct,
        all other gross columns = 0,
        gross_bonus = priority_bonus,
        net_payable = priority_bonus,
        audit_json carrying retroactive_priority=true plus the YTD
          snapshot values that drove the decision.

# Why it lives outside calculate_case

The forward calc (calc_priority_bonus) only sees the per-case picture
at processing time — it can't know that a threshold will be crossed
later in the same month. The finalizer runs once per month, after all
cases in that month are persisted, and uses the full end-of-month YTD
to make the call.

The two layers don't double-pay because the finalizer skips any
(case, slot) that already has a non-zero priority_bonus row.

# Idempotency

If the finalizer is run twice for the same (year, month), the second
run finds no eligible (case, slot) pairs (because the first run
populated priority_bonus on them) and inserts nothing.

# Integration

Engine runner pseudo-code:

    for year, month in months_to_process:
        process_cases_for_month(year, month, ...)   # writes tx_bonus_payment
        priority_finalizer.run(cursor, year=year, month=month, ref=ref)
        conn.commit()
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg.types.json import Json

from .ytd_aggregator import aggregate_ytd, PriorityYtdSnapshot

logger = logging.getLogger(__name__)


# Role codes that are priority-eligible. Keep in sync with calc_priority.py.
_PRIORITY_ELIGIBLE_ROLE_CODES = ('COUNS_DIR', 'CO_DIR', 'CO_SUB')
_DIRECT_ROLE_CODES = frozenset({'COUNS_DIR', 'CO_DIR'})


# Per StudyLink policy (Priority_2024_final_v2.pdf):
#   "Individual bonus paid 50% at enrolment, 50% after KPI reached for each partner"
# When the finalizer pays a retroactive priority bonus, it pays only the
# "50% at enrolment" portion. The other 50% is held back for a future
# trigger (year-end true-up — not yet modelled). Keep this in sync with
# calc_priority._AT_ENROLMENT_FRACTION.
_AT_ENROLMENT_FRACTION = Decimal('0.5')


def _channel_for(role_code: str) -> str:
    return 'direct' if role_code in _DIRECT_ROLE_CODES else 'sub'


def _active_at(row: dict, as_of: date) -> bool:
    if row.get('effective_from') is not None and row['effective_from'] > as_of:
        return False
    if row.get('effective_to') is not None and row['effective_to'] < as_of:
        return False
    return True


def _has_carveout_target(jct: dict) -> bool:
    return (
        jct.get('institution_target_direct') is not None
        or jct.get('institution_target_sub') is not None
    )


def _lookup_active_target(ref: Any, priority_list_id: int, as_of: date) -> dict | None:
    matches = [
        row for row in ref.priority_targets.values()
        if row['priority_list_id'] == priority_list_id
        and _active_at(row, as_of)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        matches.sort(key=lambda r: r['effective_from'], reverse=True)
    return matches[0]


# ---------------------------------------------------------------------------
# Query: find unpaid priority slots
# ---------------------------------------------------------------------------

_FIND_UNPAID_SQL = """
WITH unpaid AS (
    SELECT
        bp.case_id,
        bp.slot,
        MIN(bp.run_month)              AS first_run_month,
        MAX(bp.tier_bonus)             AS tier_bonus,
        MAX(bp.staff_id)               AS staff_id,
        MAX(bp.role_id)                AS role_id,
        MAX(bp.office_id)              AS office_id
    FROM tx_bonus_payment bp
    WHERE bp.run_year = %s
      AND bp.run_month <= %s
    GROUP BY bp.case_id, bp.slot
    HAVING SUM(bp.priority_bonus) = 0
       AND MAX(bp.tier_bonus) > 0
)
SELECT
    u.case_id,
    u.slot,
    u.first_run_month,
    u.tier_bonus,
    u.staff_id,
    u.role_id,
    u.office_id,
    c.contract_id,
    c.institution_id,
    c.referring_sub_agent_id,
    pli.id                              AS junction_id,
    pli.priority_list_id,
    pli.institution_target_direct,
    pli.institution_target_sub,
    pli.bonus_pct_override,
    pli.effective_from                  AS junction_effective_from,
    pli.effective_to                    AS junction_effective_to,
    r.code                              AS role_code,
    pl.canonical_name                   AS list_name,
    pl.is_aggregate                     AS list_is_aggregate
FROM unpaid u
JOIN tx_case c
    ON c.id = u.case_id
JOIN ref_status_split ss
    ON ss.status = c.application_status
JOIN dim_role r
    ON r.id = u.role_id
JOIN ref_priority_list_institution pli
    ON pli.institution_id = c.institution_id
JOIN ref_priority_list pl
    ON pl.id = pli.priority_list_id
WHERE ss.counts_as_enrolled = TRUE
  AND r.code = ANY(%s)
  AND (pli.effective_from IS NULL
       OR pli.effective_from <= make_date(%s, %s, 1))
  AND (pli.effective_to IS NULL
       OR pli.effective_to >= make_date(%s, %s, 1))
ORDER BY u.case_id, u.slot
"""


_INSERT_PAYMENT_SQL = """
INSERT INTO tx_bonus_payment (
    case_id, slot, staff_id, role_id, office_id,
    tier, target, actual_enrolled, base_rate, split_pct,
    tier_bonus, package_bonus, addon_bonus, priority_bonus,
    presales_share_taken, flat_local_enrolment_bonus, advance_offset,
    gross_bonus, net_payable,
    calc_notes, audit_json,
    run_id, run_year, run_month,
    calculated_at, created_at
)
VALUES (
    %(case_id)s, %(slot)s, %(staff_id)s, %(role_id)s, %(office_id)s,
    NULL, NULL, NULL, 0, 0,
    0, 0, 0, %(priority_bonus)s,
    0, 0, 0,
    %(priority_bonus)s, %(priority_bonus)s,
    %(calc_notes)s, %(audit_json)s,
    %(run_id)s, %(run_year)s, %(run_month)s,
    NOW(), NOW()
)
"""


# UPDATE existing row when threshold is crossed in the same month the
# case was processed. The original row had priority_bonus=0; we set it,
# bump gross_bonus and net_payable, append a finalizer note, and merge
# audit_json with a 'priority_retroactive' key.
_UPDATE_PAYMENT_SQL = """
UPDATE tx_bonus_payment
   SET priority_bonus = %(priority_bonus)s,
       gross_bonus    = gross_bonus + %(priority_bonus)s,
       net_payable    = net_payable + %(priority_bonus)s,
       calc_notes     = COALESCE(calc_notes, '') || E'\n' || %(calc_notes)s,
       audit_json     = COALESCE(audit_json, '{}'::jsonb)
                        || jsonb_build_object('priority_retroactive', %(audit_json)s::jsonb)
 WHERE case_id   = %(case_id)s
   AND slot      = %(slot)s
   AND run_year  = %(run_year)s
   AND run_month = %(run_month)s
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    cursor: Any,
    *,
    year: int,
    month: int,
    ref: Any,
    run_id: int | None = None,
) -> dict:
    """
    Execute retroactive priority catch-up for (year, month).

    Args:
        cursor: psycopg cursor (caller manages transaction)
        year:   the run year being finalized
        month:  the run month just processed (catch-up rows will be
                stamped with run_month=month)
        ref:    ReferenceData snapshot (for priority_targets lookup)
        run_id: optional run identifier to attach to inserted rows

    Returns:
        Summary dict:
          {
            'rows_examined':     int,
            'rows_paid':         int,
            'amount_paid_total': int (đồng),
            'skipped_threshold_not_met': int,
            'skipped_no_target_row':     int,
            'skipped_no_bonus_pct':      int,
          }
    """
    summary = {
        'rows_examined': 0,
        'rows_paid': 0,
        'amount_paid_total': 0,
        'skipped_threshold_not_met': 0,
        'skipped_no_target_row': 0,
        'skipped_no_bonus_pct': 0,
    }

    # Snapshot inclusive of month M: pass month+1 (exclusive bound)
    snapshot: PriorityYtdSnapshot = aggregate_ytd(
        cursor, year=year, month=month + 1,
    )

    cursor.execute(
        _FIND_UNPAID_SQL,
        (
            year, month,
            list(_PRIORITY_ELIGIBLE_ROLE_CODES),
            year, month,
            year, month,
        ),
    )
    candidates = cursor.fetchall()
    summary['rows_examined'] = len(candidates)

    if not candidates:
        logger.info(
            "priority_finalizer: year=%d month=%d — no unpaid priority "
            "candidates found.",
            year, month,
        )
        return summary

    case_date = date(year, month, 1)

    for row in candidates:
        # Tuple/dict cursor handling
        if isinstance(row, dict):
            r = row
        else:
            (
                case_id, slot, first_run_month, tier_bonus, staff_id,
                role_id, office_id, contract_id, institution_id,
                referring_sub_agent_id, junction_id, priority_list_id,
                inst_target_direct, inst_target_sub, bonus_pct_override,
                jct_eff_from, jct_eff_to, role_code, list_name,
                list_is_aggregate,
            ) = row
            r = {
                'case_id': case_id, 'slot': slot,
                'first_run_month': first_run_month,
                'tier_bonus': tier_bonus, 'staff_id': staff_id,
                'role_id': role_id, 'office_id': office_id,
                'contract_id': contract_id, 'institution_id': institution_id,
                'referring_sub_agent_id': referring_sub_agent_id,
                'junction_id': junction_id,
                'priority_list_id': priority_list_id,
                'institution_target_direct': inst_target_direct,
                'institution_target_sub': inst_target_sub,
                'bonus_pct_override': bonus_pct_override,
                'role_code': role_code, 'list_name': list_name,
                'list_is_aggregate': list_is_aggregate,
            }

        channel = _channel_for(r['role_code'])

        # Resolve effective bonus_pct
        target_row = _lookup_active_target(ref, r['priority_list_id'], case_date)

        if r['bonus_pct_override'] is not None:
            bonus_pct = Decimal(str(r['bonus_pct_override']))
            bonus_pct_source = 'junction_override'
        elif target_row is not None:
            bonus_pct = Decimal(str(target_row['bonus_pct']))
            bonus_pct_source = 'list_target'
        else:
            summary['skipped_no_target_row'] += 1
            logger.warning(
                "priority_finalizer: skipping case_id=%d slot=%s — no active "
                "ref_priority_target for list_id=%d at %s and no junction override",
                r['case_id'], r['slot'], r['priority_list_id'],
                case_date.isoformat(),
            )
            continue

        if bonus_pct == 0:
            summary['skipped_no_bonus_pct'] += 1
            continue

        # Resolve effective targets and YTD counts
        is_carveout = _has_carveout_target({
            'institution_target_direct': r['institution_target_direct'],
            'institution_target_sub': r['institution_target_sub'],
        })

        if is_carveout:
            if channel == 'direct':
                role_target = r['institution_target_direct'] or 0
            else:
                role_target = r['institution_target_sub'] or 0
            total_target = (
                (r['institution_target_direct'] or 0)
                + (r['institution_target_sub'] or 0)
            )
            role_ytd = snapshot.institution_count(
                r['priority_list_id'], r['institution_id'], channel,
            )
            total_ytd = snapshot.institution_count(
                r['priority_list_id'], r['institution_id'], 'total',
            )
            target_source = 'junction_carveout'
        else:
            if target_row is None:
                summary['skipped_no_target_row'] += 1
                continue
            role_target = (
                target_row.get('direct_target') if channel == 'direct'
                else target_row.get('sub_target')
            ) or 0
            total_target = target_row.get('total_target') or 0
            role_ytd = snapshot.list_count(r['priority_list_id'], channel)
            total_ytd = snapshot.list_count(r['priority_list_id'], 'total')
            target_source = 'list_target'

        role_ok = role_target > 0 and role_ytd >= role_target
        total_ok = total_target > 0 and total_ytd >= total_target
        threshold_met = role_ok and total_ok

        if not threshold_met:
            summary['skipped_threshold_not_met'] += 1
            continue

        # Threshold met → write retroactive priority payment
        priority_amount = int(
            Decimal(r['tier_bonus']) * bonus_pct * _AT_ENROLMENT_FRACTION
        )

        audit = {
            'retroactive_priority': True,
            'original_run_month': r['first_run_month'],
            'threshold_hit_month': month,
            'list_id': r['priority_list_id'],
            'list_name': r['list_name'],
            'list_is_aggregate': r['list_is_aggregate'],
            'junction_id': r['junction_id'],
            'role_code': r['role_code'],
            'channel': channel,
            'role_target': role_target,
            'role_ytd': role_ytd,
            'total_target': total_target,
            'total_ytd': total_ytd,
            'bonus_pct': str(bonus_pct),
            'bonus_pct_source': bonus_pct_source,
            'at_enrolment_fraction': str(_AT_ENROLMENT_FRACTION),
            'target_source': target_source,
            'tier_bonus_input': r['tier_bonus'],
            'case_date': case_date.isoformat(),
        }

        notes = (
            f"Retroactive priority bonus (threshold crossed). "
            f"List='{r['list_name']}' channel={channel} "
            f"role_ytd={role_ytd}/{role_target} "
            f"total_ytd={total_ytd}/{total_target}; "
            f"original case month={r['first_run_month']}, paid in month={month}."
        )

        params = {
            'case_id': r['case_id'],
            'slot': r['slot'],
            'staff_id': r['staff_id'],
            'role_id': r['role_id'],
            'office_id': r['office_id'],
            'priority_bonus': priority_amount,
            'calc_notes': notes,
            'audit_json': Json(audit),
            'run_id': run_id,
            'run_year': year,
            'run_month': month,
        }

        # Same-month threshold-crossing: UPDATE the existing row (the
        # original forward calc wrote it with priority_bonus=0). Prior-
        # month case: INSERT a new row dated to the threshold-hit month.
        if r['first_run_month'] == month:
            cursor.execute(_UPDATE_PAYMENT_SQL, params)
            update_or_insert = 'UPDATE'
        else:
            cursor.execute(_INSERT_PAYMENT_SQL, params)
            update_or_insert = 'INSERT'

        summary['rows_paid'] += 1
        summary['amount_paid_total'] += priority_amount

        logger.info(
            "priority_finalizer: %s retroactive priority case_id=%d slot=%s "
            "list='%s' channel=%s amount=%d (role %d/%d, total %d/%d)",
            update_or_insert,
            r['case_id'], r['slot'], r['list_name'], channel,
            priority_amount, role_ytd, role_target, total_ytd, total_target,
        )

    logger.info(
        "priority_finalizer: year=%d month=%d done — examined=%d paid=%d "
        "amount_total=%d skipped_threshold=%d skipped_no_target=%d "
        "skipped_no_bonus_pct=%d",
        year, month,
        summary['rows_examined'], summary['rows_paid'],
        summary['amount_paid_total'],
        summary['skipped_threshold_not_met'],
        summary['skipped_no_target_row'],
        summary['skipped_no_bonus_pct'],
    )

    return summary
