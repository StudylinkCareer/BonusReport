"""
backend/overrides.py

Per-slot case overrides (Phase 14 Block 4 / C).

The Bonus Admin reviews calculated payments on the Submitted board (after
approvals have completed and the engine has run) and may decide that one
or more staff members on a case need their bonus adjusted — a signed
delta with a mandatory reason. The engine reads these rows at calc time
and copies each row's amount + reason onto the matching tx_bonus_payment
row's mgmt_override_amount / mgmt_override_reason columns.

Pattern mirrors backend/approvals.py: explicit exception classes, public
API functions, all DB access via get_connection() with explicit commits.

Constraints enforced by this module:
  * Case must exist
  * Case must be in workflow_state = 'submitted' for any writes
  * staff_id must match one of the case's slot assignments
    (counsellor_staff_id, case_officer_staff_id, pre_sales_staff_id)
  * amount cannot be 0 (no-op override has no purpose)
  * reason cannot be empty/whitespace
  * No duplicate staff_ids in a single PUT payload
"""

from __future__ import annotations

from typing import Any

from backend.data.connection import get_connection


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CaseNotFoundError(Exception):
    pass


class WorkflowStateError(Exception):
    """Override writes are only allowed when case is in 'submitted' state."""


class StaffNotOnCaseError(Exception):
    """staff_id is not assigned to any slot on the case."""


class EmptyReasonError(Exception):
    pass


class InvalidAmountError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _case_slot_staff_ids(cur, case_id: int) -> set[int]:
    """Return the set of staff_ids currently assigned to slot columns on
    the case. Raises CaseNotFoundError if the case doesn't exist.
    """
    cur.execute(
        """
        SELECT counsellor_staff_id, case_officer_staff_id, pre_sales_staff_id
        FROM tx_case WHERE id = %s
        """,
        (case_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise CaseNotFoundError(f"Case {case_id} not found")
    return {
        sid for sid in (
            row["counsellor_staff_id"],
            row["case_officer_staff_id"],
            row["pre_sales_staff_id"],
        )
        if sid is not None
    }


def _case_workflow_state(cur, case_id: int) -> str:
    cur.execute("SELECT workflow_state FROM tx_case WHERE id = %s", (case_id,))
    row = cur.fetchone()
    if row is None:
        raise CaseNotFoundError(f"Case {case_id} not found")
    return row["workflow_state"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_case_overrides(case_id: int) -> dict[str, Any]:
    """Return all overrides for a case, plus the case's slot staff so the
    UI can populate the "add" dropdown.

    Response:
        {
            "case_id": int,
            "workflow_state": str,
            "calculated_at": str | None,  # ISO format
            "available_staff": [           # all slot staff on the case
                {"staff_id": int, "staff_name": str, "slot": str},
                ...
            ],
            "overrides": [                 # rows currently set
                {
                    "id": int,
                    "staff_id": int,
                    "staff_name": str,
                    "amount": int,
                    "reason": str,
                    "created_at": str, "updated_at": str,
                    "created_by_user_id": int, "created_by_display_name": str,
                    "updated_by_user_id": int, "updated_by_display_name": str,
                },
                ...
            ],
        }
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Case header (state + calc timestamp + slot fillings)
            cur.execute(
                """
                SELECT
                    c.id, c.workflow_state, c.calculated_at,
                    c.counsellor_staff_id,  cs.canonical_name AS counsellor_name,
                    c.case_officer_staff_id, os.canonical_name AS case_officer_name,
                    c.pre_sales_staff_id,    ps.canonical_name AS pre_sales_name
                FROM tx_case c
                LEFT JOIN ref_staff cs ON cs.id = c.counsellor_staff_id
                LEFT JOIN ref_staff os ON os.id = c.case_officer_staff_id
                LEFT JOIN ref_staff ps ON ps.id = c.pre_sales_staff_id
                WHERE c.id = %s
                """,
                (case_id,),
            )
            case_row = cur.fetchone()
            if case_row is None:
                raise CaseNotFoundError(f"Case {case_id} not found")

            available_staff: list[dict[str, Any]] = []
            for slot_label, sid_key, name_key in [
                ("counsellor",   "counsellor_staff_id",   "counsellor_name"),
                ("case_officer", "case_officer_staff_id", "case_officer_name"),
                ("pre_sales",    "pre_sales_staff_id",    "pre_sales_name"),
            ]:
                sid = case_row[sid_key]
                if sid is not None:
                    available_staff.append({
                        "staff_id": sid,
                        "staff_name": case_row[name_key],
                        "slot": slot_label,
                    })

            # Current override rows
            cur.execute(
                """
                SELECT
                    o.id, o.staff_id, s.canonical_name AS staff_name,
                    o.amount, o.reason,
                    o.created_at, o.updated_at,
                    o.created_by_user_id,
                    cu.display_name AS created_by_display_name,
                    o.updated_by_user_id,
                    uu.display_name AS updated_by_display_name
                FROM tx_case_override o
                LEFT JOIN ref_staff s ON s.id = o.staff_id
                LEFT JOIN app_user  cu ON cu.id = o.created_by_user_id
                LEFT JOIN app_user  uu ON uu.id = o.updated_by_user_id
                WHERE o.case_id = %s
                ORDER BY s.canonical_name
                """,
                (case_id,),
            )
            overrides = []
            for row in cur.fetchall():
                overrides.append({
                    "id": row["id"],
                    "staff_id": row["staff_id"],
                    "staff_name": row["staff_name"],
                    "amount": row["amount"],
                    "reason": row["reason"],
                    "created_at": (
                        row["created_at"].isoformat() if row["created_at"] else None
                    ),
                    "updated_at": (
                        row["updated_at"].isoformat() if row["updated_at"] else None
                    ),
                    "created_by_user_id": row["created_by_user_id"],
                    "created_by_display_name": row["created_by_display_name"],
                    "updated_by_user_id": row["updated_by_user_id"],
                    "updated_by_display_name": row["updated_by_display_name"],
                })

            return {
                "case_id": case_id,
                "workflow_state": case_row["workflow_state"],
                "calculated_at": (
                    case_row["calculated_at"].isoformat()
                    if case_row["calculated_at"] else None
                ),
                "available_staff": available_staff,
                "overrides": overrides,
            }


def replace_case_overrides(
    case_id: int,
    overrides: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    """Replace the entire list of overrides for a case (PUT semantics).

    overrides: list of dicts shaped {"staff_id": int, "amount": int, "reason": str}

    Validates the whole payload BEFORE touching the DB:
      - Every staff_id is on the case
      - Every amount is a non-zero int
      - Every reason is a non-empty string after trimming
      - No duplicate staff_ids

    Then atomically (in one transaction):
      - DELETEs all existing override rows for the case
      - INSERTs the new ones

    On any validation failure, raises an explicit exception and the DB
    is untouched.

    Returns the fresh list_case_overrides() output.
    """
    # --- payload validation (pre-DB) ---------------------------------------
    seen_staff_ids: set[int] = set()
    cleaned: list[dict[str, Any]] = []

    for ov in overrides:
        if not isinstance(ov, dict):
            raise InvalidAmountError(f"override entry must be an object, got {type(ov).__name__}")

        staff_id = ov.get("staff_id")
        amount = ov.get("amount")
        reason = ov.get("reason", "")

        if not isinstance(staff_id, int):
            raise StaffNotOnCaseError(
                f"staff_id must be int, got {staff_id!r} (type {type(staff_id).__name__})"
            )
        if not isinstance(amount, int) or isinstance(amount, bool):
            # bool is a subclass of int in Python — explicitly reject
            raise InvalidAmountError(f"amount must be int, got {amount!r}")
        if amount == 0:
            raise InvalidAmountError(
                f"amount cannot be zero for staff_id={staff_id} "
                "(no-op override has no purpose; remove the row instead)"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise EmptyReasonError(
                f"reason is required for staff_id={staff_id} (got {reason!r})"
            )
        if staff_id in seen_staff_ids:
            raise StaffNotOnCaseError(
                f"Duplicate staff_id={staff_id} in overrides payload"
            )
        seen_staff_ids.add(staff_id)
        cleaned.append({
            "staff_id": staff_id,
            "amount": amount,
            "reason": reason.strip(),
        })

    # --- DB transaction ----------------------------------------------------
    with get_connection() as conn:
        with conn.cursor() as cur:
            # State gate
            state = _case_workflow_state(cur, case_id)
            if state != "submitted":
                raise WorkflowStateError(
                    f"Case {case_id} is in '{state}' state; overrides are "
                    f"only editable when workflow_state='submitted'"
                )

            # Membership gate
            on_case = _case_slot_staff_ids(cur, case_id)
            for staff_id in seen_staff_ids:
                if staff_id not in on_case:
                    raise StaffNotOnCaseError(
                        f"staff_id={staff_id} is not assigned to any slot on "
                        f"case {case_id}. Allowed staff_ids: {sorted(on_case)}"
                    )

            # Replace-whole-list: delete then insert. Atomic via the
            # surrounding transaction — either both succeed or both roll back.
            cur.execute(
                "DELETE FROM tx_case_override WHERE case_id = %s",
                (case_id,),
            )
            for ov in cleaned:
                cur.execute(
                    """
                    INSERT INTO tx_case_override
                        (case_id, staff_id, amount, reason,
                         created_by_user_id, updated_by_user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        case_id, ov["staff_id"], ov["amount"], ov["reason"],
                        user_id, user_id,
                    ),
                )

            conn.commit()

    # Re-read with all the joined display names for the response
    return list_case_overrides(case_id)
