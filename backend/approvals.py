"""
backend/approvals.py

Approval system for the case workflow (Phase 14 Block 3 / B).

When a case is in workflow_state='in_review', specific slots on the case
must be approved before it can advance to 'submitted'. Which slots require
approval is driven by dim_role.requires_case_approval — Counsellor and Case
Officer roles are seeded TRUE; PRESALES/VP/TARGET_OWNER auto-pass.

Approval flavours:
  * Self-approval: the slot's staff member approves their own participation
    and the numbers (set is_override = FALSE, override_reason NULL).
  * Managerial override: a DQO/ADMIN/DIRECTOR/FO approves on behalf with a
    required reason (set is_override = TRUE, override_reason populated).

Approval is durable — once recorded, it doesn't auto-clear on case edits.
The audit_change_log table will record any data changes after approval, so
reviewers can spot situations where an approved case was modified.
"""

from __future__ import annotations

from typing import Any

from backend.data.connection import get_connection


# ---------------------------------------------------------------------------
# Slot registry
# ---------------------------------------------------------------------------
# Each slot is (slot_label, staff_id_column_on_tx_case, role_id_column).
# Only slots in this list are ever considered for approval — even if their
# role's requires_case_approval is TRUE elsewhere.
#
# To extend (e.g. when PRESALES becomes bonusable):
#   1. Add the slot's (label, staff_col, role_col) here
#   2. Toggle the role's requires_case_approval to TRUE in dim_role
SLOTS: list[tuple[str, str, str]] = [
    ("counsellor",   "counsellor_staff_id",   "counsellor_role_id"),
    ("case_officer", "case_officer_staff_id", "case_officer_role_id"),
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CaseNotFoundError(Exception):
    pass


class UserNotOnCaseError(Exception):
    """Raised when a user tries to self-approve a case they aren't assigned to."""


class SlotNotFoundError(Exception):
    """Raised when an override target doesn't match a slot on the case."""


class ApprovalAlreadyRecordedError(Exception):
    """Raised when an override is attempted on an already-approved slot."""


class EmptyOverrideReasonError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_case_approvals(case_id: int) -> dict[str, Any]:
    """Return the approval status of every applicable slot on a case.

    Slots whose staff_id is NULL on the case (not filled) are omitted.
    Slots whose role has requires_case_approval = FALSE are included but
    marked required = False, so the UI can still show who's involved.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tx_case WHERE id = %s", (case_id,))
            if cur.fetchone() is None:
                raise CaseNotFoundError(f"Case {case_id} not found")

            slot_data: list[dict[str, Any]] = []
            for slot_label, staff_col, role_col in SLOTS:
                cur.execute(
                    f"""
                    SELECT
                        c.{staff_col}                       AS staff_id,
                        c.{role_col}                        AS role_id,
                        s.canonical_name                    AS staff_name,
                        r.code                              AS role_code,
                        r.name                              AS role_name,
                        COALESCE(r.requires_case_approval, FALSE) AS required,
                        a.approved,
                        a.approved_at,
                        a.approved_by_user_id,
                        u.display_name                      AS approved_by_display_name,
                        a.is_override,
                        a.override_reason
                    FROM tx_case c
                    LEFT JOIN ref_staff s ON c.{staff_col} = s.id
                    LEFT JOIN dim_role  r ON c.{role_col}  = r.id
                    LEFT JOIN tx_case_approval a
                           ON a.case_id  = c.id
                          AND a.role_id  = c.{role_col}
                          AND a.staff_id = c.{staff_col}
                    LEFT JOIN app_user u ON a.approved_by_user_id = u.id
                    WHERE c.id = %s
                    """,
                    (case_id,),
                )
                row = cur.fetchone()
                if row is None or row["staff_id"] is None:
                    continue

                slot_data.append({
                    "slot_label": slot_label,
                    "staff_id": row["staff_id"],
                    "staff_name": row["staff_name"],
                    "role_id": row["role_id"],
                    "role_code": row["role_code"],
                    "role_name": row["role_name"],
                    "required": bool(row["required"]),
                    "approved": bool(row["approved"]) if row["approved"] is not None else False,
                    "approved_at": (
                        row["approved_at"].isoformat() if row["approved_at"] else None
                    ),
                    "approved_by_user_id": row["approved_by_user_id"],
                    "approved_by_display_name": row["approved_by_display_name"],
                    "is_override": bool(row["is_override"]) if row["is_override"] is not None else False,
                    "override_reason": row["override_reason"],
                })

            missing = [s["slot_label"] for s in slot_data
                       if s["required"] and not s["approved"]]

            return {
                "case_id": case_id,
                "slots": slot_data,
                "all_required_approved": len(missing) == 0,
                "missing_required_slots": missing,
            }


def approve_my_slots(case_id: int, user_id: int, user_staff_id: int | None) -> dict[str, Any]:
    """Self-approve any slot on the case where user.staff_id matches.

    Idempotent: re-approving an already-approved slot is a no-op.
    """
    if user_staff_id is None:
        raise UserNotOnCaseError(
            "Your account has no linked staff record; cannot self-approve."
        )

    approved_now: list[str] = []
    already: list[str] = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tx_case WHERE id = %s", (case_id,))
            if cur.fetchone() is None:
                raise CaseNotFoundError(f"Case {case_id} not found")

            for slot_label, staff_col, role_col in SLOTS:
                cur.execute(
                    f"""
                    SELECT c.{staff_col} AS staff_id, c.{role_col} AS role_id
                    FROM tx_case c
                    WHERE c.id = %s
                      AND c.{staff_col} = %s
                    """,
                    (case_id, user_staff_id),
                )
                slot = cur.fetchone()
                if slot is None:
                    continue
                # role_id may legitimately be NULL on a malformed case; skip.
                if slot["role_id"] is None:
                    continue

                cur.execute(
                    """
                    INSERT INTO tx_case_approval
                        (case_id, role_id, staff_id, approved, approved_at,
                         approved_by_user_id, is_override, override_reason)
                    VALUES (%s, %s, %s, TRUE, NOW(), %s, FALSE, NULL)
                    ON CONFLICT (case_id, role_id, staff_id) DO NOTHING
                    RETURNING id
                    """,
                    (case_id, slot["role_id"], slot["staff_id"], user_id),
                )
                if cur.fetchone():
                    approved_now.append(slot_label)
                else:
                    already.append(slot_label)

            conn.commit()

    if not approved_now and not already:
        raise UserNotOnCaseError(
            f"You are not assigned to any approval-requiring slot on case {case_id}"
        )

    return {
        "case_id": case_id,
        "approved_slots": approved_now,
        "already_approved": already,
    }


def override_approval(
    case_id: int,
    role_id: int,
    staff_id: int,
    user_id: int,
    reason: str,
) -> dict[str, Any]:
    """Manager approves a slot on behalf of the assigned staff member.

    The slot must actually exist on the case (case has these role_id + staff_id
    in one of the SLOTS columns). Idempotency: this raises if the slot is
    already approved — overriding an existing approval is a separate operation
    we haven't designed.
    """
    if not reason or not reason.strip():
        raise EmptyOverrideReasonError("override_reason is required")

    clean_reason = reason.strip()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tx_case WHERE id = %s", (case_id,))
            if cur.fetchone() is None:
                raise CaseNotFoundError(f"Case {case_id} not found")

            # Verify (role_id, staff_id) matches an actual slot on the case
            slot_match = None
            for slot_label, staff_col, role_col in SLOTS:
                cur.execute(
                    f"""
                    SELECT 1 FROM tx_case
                    WHERE id = %s
                      AND {role_col}  = %s
                      AND {staff_col} = %s
                    """,
                    (case_id, role_id, staff_id),
                )
                if cur.fetchone():
                    slot_match = slot_label
                    break

            if slot_match is None:
                raise SlotNotFoundError(
                    f"No slot on case {case_id} with role_id={role_id} "
                    f"and staff_id={staff_id}"
                )

            cur.execute(
                """
                INSERT INTO tx_case_approval
                    (case_id, role_id, staff_id, approved, approved_at,
                     approved_by_user_id, is_override, override_reason)
                VALUES (%s, %s, %s, TRUE, NOW(), %s, TRUE, %s)
                ON CONFLICT (case_id, role_id, staff_id) DO NOTHING
                RETURNING id
                """,
                (case_id, role_id, staff_id, user_id, clean_reason),
            )
            inserted = cur.fetchone()
            if not inserted:
                raise ApprovalAlreadyRecordedError(
                    f"Slot {slot_match!r} on case {case_id} is already approved"
                )

            conn.commit()

    return {
        "case_id": case_id,
        "slot_label": slot_match,
        "approval_id": inserted["id"],
    }


def check_approvals_for_transition(case_ids: list[int]) -> dict[int, list[str]]:
    """For a batch of cases, return {case_id: [missing_slot_labels]} for any
    case missing approvals on its required slots.

    Empty dict means every case is fully approved (or has no required slots).
    Called by the transition endpoint before in_review → submitted.
    """
    if not case_ids:
        return {}

    missing_by_case: dict[int, list[str]] = {}

    with get_connection() as conn:
        with conn.cursor() as cur:
            for slot_label, staff_col, role_col in SLOTS:
                cur.execute(
                    f"""
                    SELECT c.id AS case_id
                    FROM tx_case c
                    JOIN dim_role r ON c.{role_col} = r.id
                    LEFT JOIN tx_case_approval a
                           ON a.case_id  = c.id
                          AND a.role_id  = c.{role_col}
                          AND a.staff_id = c.{staff_col}
                          AND a.approved = TRUE
                    WHERE c.id = ANY(%s)
                      AND r.requires_case_approval = TRUE
                      AND c.{staff_col} IS NOT NULL
                      AND a.id IS NULL
                    """,
                    (case_ids,),
                )
                for row in cur.fetchall():
                    missing_by_case.setdefault(row["case_id"], []).append(slot_label)

    return missing_by_case
