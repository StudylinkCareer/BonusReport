"""
backend/engine_runner/ytd_aggregator.py

Builds year-to-date enrolment counts that feed RunContext for the
priority-bonus engine.

# What this counts

Each enrolled case contributes 1 to YTD, indexed three ways:

  * by_list[(priority_list_id, channel)]
        For non-carve-out institutions (junction has no
        institution_target_*). These enrolments roll up to the List's
        list-level targets.

  * by_list_institution[(priority_list_id, institution_id, channel)]
        For carve-out institutions (junction has institution_target_direct
        or institution_target_sub set). These enrolments DO NOT roll up
        to the List's totals; they accumulate against the per-institution
        target (e.g. Griffith College's target of 2 within the Navitas
        priority list).

`channel` is one of:
  * 'direct' — case has no sub-agent referrer (referring_sub_agent_id IS NULL)
  * 'sub'    — case has a sub-agent referrer
  * 'total'  — synthetic: direct + sub

# Why three channels

Per the StudyLink priority-bonus rule (confirmed 2026-05-07): priority
unlocks for a slot only when BOTH the slot's channel target AND the
list's total target are met YTD.

CO_SUB slots gate on sub_target; COUNS_DIR/CO_DIR slots gate on
direct_target. So the engine needs the YTD count broken down by channel,
not just the totals the prior stub returned.

# De-duplication

A single contract can appear in multiple monthly tx_case rows as its
application status evolves. We use COUNT(DISTINCT contract_id) so each
contract counts once, regardless of how many monthly rows it has.

# Effectivity

Junction membership is filtered to rows active at the start of the run
period being processed. A junction that ended in (e.g.) Mar 2024 will
not contribute to YTD counts for Apr 2024 onwards, even if there are
historical enrolments.

# Caller contract

`aggregate_ytd(cursor, year=Y, month=M)` returns YTD counts for runs
where `c.run_month < M` — i.e. counts as of end of month (M-1).

To get YTD counts as of end of month M (for the post-month retroactive
finalizer), call `aggregate_ytd(cursor, year=Y, month=M+1)`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriorityYtdSnapshot:
    """
    YTD enrolment counts indexed by (list, channel) and (list, institution, channel).

    by_list:
        Keyed by (priority_list_id, channel). Counts non-carve-out
        enrolments per list per channel.

    by_list_institution:
        Keyed by (priority_list_id, institution_id, channel). Counts
        carve-out enrolments per institution per channel.

    `channel` is 'direct', 'sub', or 'total'. The 'total' entry is
    synthesized as direct + sub at construction time.

    Both dicts default to 0 for missing keys via the helper accessors
    `list_count` and `institution_count`.
    """
    by_list: dict[tuple[int, str], int] = field(default_factory=dict)
    by_list_institution: dict[tuple[int, int, str], int] = field(default_factory=dict)

    def list_count(self, priority_list_id: int, channel: str) -> int:
        """Convenience accessor — returns 0 when the key is absent."""
        return self.by_list.get((priority_list_id, channel), 0)

    def institution_count(
        self,
        priority_list_id: int,
        institution_id: int,
        channel: str,
    ) -> int:
        """Convenience accessor — returns 0 when the key is absent."""
        return self.by_list_institution.get(
            (priority_list_id, institution_id, channel), 0
        )


def aggregate_ytd(
    cursor: Any,
    *,
    year: int,
    month: int,
) -> PriorityYtdSnapshot:
    """
    Build a YTD snapshot for `year` from rows with `run_month < month`.

    Args:
        cursor: psycopg cursor with read access to tx_case,
                ref_priority_list_institution, ref_status_split.
        year:   the run year being aggregated.
        month:  exclusive upper bound for run_month. So passing month=4
                returns YTD as of end of March; passing month=13 returns
                full-year YTD.

    Returns:
        PriorityYtdSnapshot with counts split by channel.
    """
    cursor.execute(
        """
        SELECT
            pli.priority_list_id,
            pli.institution_id,
            (pli.institution_target_direct IS NOT NULL
             OR pli.institution_target_sub IS NOT NULL) AS is_carveout,
            CASE
                WHEN c.referring_sub_agent_id IS NULL THEN 'direct'
                ELSE 'sub'
            END AS channel,
            COUNT(DISTINCT c.contract_id) AS cnt
        FROM tx_case c
        JOIN ref_priority_list_institution pli
            ON pli.institution_id = c.institution_id
        JOIN ref_status_split ss
            ON ss.status = c.application_status
        WHERE c.run_year = %s
          AND c.run_month < %s
          AND ss.counts_as_enrolled = TRUE
          AND (pli.effective_from IS NULL
               OR pli.effective_from <= make_date(%s, %s, 1))
          AND (pli.effective_to IS NULL
               OR pli.effective_to >= make_date(%s, %s, 1))
        GROUP BY pli.priority_list_id, pli.institution_id, is_carveout, channel
        """,
        (year, month, year, month, year, month),
    )

    by_list: dict[tuple[int, str], int] = {}
    by_list_institution: dict[tuple[int, int, str], int] = {}

    for row in cursor.fetchall():
        # Handle both tuple and dict cursors
        if isinstance(row, dict):
            list_id = row['priority_list_id']
            inst_id = row['institution_id']
            is_carveout = row['is_carveout']
            channel = row['channel']
            cnt = row['cnt']
        else:
            list_id, inst_id, is_carveout, channel, cnt = row

        if is_carveout:
            key_inst = (list_id, inst_id, channel)
            # Same (list, inst, channel) won't repeat in GROUP BY so set is fine
            by_list_institution[key_inst] = cnt
        else:
            key_list = (list_id, channel)
            # An institution can have multiple junction rows under the same
            # list (rare, but legal). Sum them.
            by_list[key_list] = by_list.get(key_list, 0) + cnt

    # Synthesize 'total' channel = direct + sub
    list_ids_seen = {k[0] for k in by_list.keys()}
    for list_id in list_ids_seen:
        d = by_list.get((list_id, 'direct'), 0)
        s = by_list.get((list_id, 'sub'), 0)
        by_list[(list_id, 'total')] = d + s

    inst_keys_seen = {(k[0], k[1]) for k in by_list_institution.keys()}
    for list_id, inst_id in inst_keys_seen:
        d = by_list_institution.get((list_id, inst_id, 'direct'), 0)
        s = by_list_institution.get((list_id, inst_id, 'sub'), 0)
        by_list_institution[(list_id, inst_id, 'total')] = d + s

    snapshot = PriorityYtdSnapshot(
        by_list=by_list,
        by_list_institution=by_list_institution,
    )

    logger.info(
        "ytd_aggregator: built snapshot for year=%d month<%d — "
        "%d list-level rows, %d institution-level rows",
        year,
        month,
        len(by_list),
        len(by_list_institution),
    )

    return snapshot
