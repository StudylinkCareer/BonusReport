'use client';

/**
 * SAVE TO: frontend/app/_components/CaseApprovalsModal.tsx
 *
 * Shows per-slot approval status for a single case and lets the user:
 *   - Self-approve their own slot (visible if user.staff_id matches a slot)
 *   - Override a slot's approval (visible if user is DQO/ADMIN/DIRECTOR/FO)
 *
 * Used from /import/review when workflow_state === 'in_review'. Cases must
 * have all required slots approved before they can advance to 'submitted'.
 */

import { useEffect, useState, useCallback } from 'react';

// ---------------------------------------------------------------------------
// Types — match backend approvals.get_case_approvals shape
// ---------------------------------------------------------------------------

type Slot = {
  slot_label: string;
  staff_id: number;
  staff_name: string | null;
  role_id: number;
  role_code: string | null;
  role_name: string | null;
  required: boolean;
  approved: boolean;
  approved_at: string | null;
  approved_by_user_id: number | null;
  approved_by_display_name: string | null;
  is_override: boolean;
  override_reason: string | null;
};

type ApprovalsResponse = {
  case_id: number;
  slots: Slot[];
  all_required_approved: boolean;
  missing_required_slots: string[];
};

type CurrentUser = {
  id: number;
  staff_id: number | null;
  roles: string[];
};

type Props = {
  caseId: number | null; // null = closed
  onClose: () => void;
  onApprovalChanged?: () => void; // optional: parent refreshes table
};

// ---------------------------------------------------------------------------
// Date formatting — show "Jan 2, 2024 14:23"
// ---------------------------------------------------------------------------

function fmtDate(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CaseApprovalsModal({ caseId, onClose, onApprovalChanged }: Props) {
  const [data, setData] = useState<ApprovalsResponse | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Esc to close
  useEffect(() => {
    if (caseId === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [caseId, onClose]);

  // Fetch approvals + current user
  const fetchAll = useCallback(async () => {
    if (caseId === null) return;
    setLoading(true);
    setError(null);
    try {
      const [approvalsRes, meRes] = await Promise.all([
        fetch(`/api/cases/${caseId}/approvals`, { credentials: 'include' }),
        fetch('/api/auth/me', { credentials: 'include' }),
      ]);
      if (!approvalsRes.ok) {
        const body = await approvalsRes.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${approvalsRes.status}`);
      }
      if (!meRes.ok) throw new Error('Failed to load current user');
      setData(await approvalsRes.json());
      setUser(await meRes.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    if (caseId === null) {
      setData(null);
      setUser(null);
      setError(null);
      return;
    }
    void fetchAll();
  }, [caseId, fetchAll]);

  // ---- Actions -----------------------------------------------------------

  async function handleSelfApprove() {
    if (caseId === null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/cases/${caseId}/approve`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${r.status}`);
      }
      await fetchAll();
      onApprovalChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleOverride(slot: Slot) {
    if (caseId === null) return;
    const reason = window.prompt(
      `Override approval for ${slot.staff_name} (${slot.role_name})?\n\n` +
        'Enter a reason (required):',
    );
    if (reason === null) return; // cancelled
    if (!reason.trim()) {
      setError('Override reason cannot be empty');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/cases/${caseId}/override-approval`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role_id: slot.role_id,
          staff_id: slot.staff_id,
          reason: reason.trim(),
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${r.status}`);
      }
      await fetchAll();
      onApprovalChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (caseId === null) return null;

  const isManager =
    user && user.roles.some((r) => ['DQO', 'ADMIN', 'DIRECTOR', 'FO'].includes(r));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Case approvals"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ===== Header ===================================================== */}
        <div className="flex items-start justify-between border-b border-gray-200 px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Case approvals</h2>
            {data && (
              <div className="mt-1 text-sm text-gray-600">
                <span className="font-mono">case_id={data.case_id}</span>
                <span className="mx-1.5 text-gray-300">·</span>
                {data.all_required_approved ? (
                  <span className="text-emerald-700 font-medium">
                    ✓ All required slots approved
                  </span>
                ) : (
                  <span className="text-amber-700 font-medium">
                    Pending: {data.missing_required_slots.join(', ')}
                  </span>
                )}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* ===== Body ======================================================= */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {loading && (
            <div className="py-8 text-center text-sm text-gray-500">Loading…</div>
          )}

          {error && (
            <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              <strong>Error:</strong> {error}
            </div>
          )}

          {data && data.slots.length === 0 && (
            <div className="rounded border border-gray-200 bg-gray-50 px-3 py-4 text-center text-sm text-gray-600">
              No approval slots configured on this case.
            </div>
          )}

          {data &&
            data.slots.map((slot) => (
              <SlotCard
                key={`${slot.role_id}-${slot.staff_id}`}
                slot={slot}
                isCurrentUser={user?.staff_id === slot.staff_id}
                isManager={!!isManager}
                busy={busy}
                onSelfApprove={handleSelfApprove}
                onOverride={() => handleOverride(slot)}
              />
            ))}
        </div>

        {/* ===== Footer ===================================================== */}
        <div className="border-t border-gray-200 bg-gray-50 px-4 py-2 text-right">
          <button
            onClick={onClose}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SlotCard — one card per slot
// ---------------------------------------------------------------------------

function SlotCard({
  slot,
  isCurrentUser,
  isManager,
  busy,
  onSelfApprove,
  onOverride,
}: {
  slot: Slot;
  isCurrentUser: boolean;
  isManager: boolean;
  busy: boolean;
  onSelfApprove: () => void;
  onOverride: () => void;
}) {
  const statusColor = !slot.required
    ? 'bg-gray-100 text-gray-700'
    : slot.approved
    ? 'bg-emerald-100 text-emerald-800'
    : 'bg-amber-100 text-amber-800';

  const statusLabel = !slot.required
    ? 'Not required'
    : slot.approved
    ? slot.is_override
      ? 'Override approved'
      : 'Approved'
    : 'Pending';

  return (
    <div className="mb-3 overflow-hidden rounded border border-gray-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900">
            {slot.staff_name ?? `Staff #${slot.staff_id}`}
          </span>
          {slot.role_name && (
            <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800">
              {slot.role_name}
            </span>
          )}
          <span className="text-xs text-gray-500">({slot.slot_label})</span>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusColor}`}>
          {statusLabel}
        </span>
      </div>

      <div className="px-3 py-2 text-sm">
        {slot.approved ? (
          <>
            <div className="text-gray-700">
              <strong>Approved by:</strong>{' '}
              {slot.approved_by_display_name ?? `user #${slot.approved_by_user_id}`}
            </div>
            <div className="text-gray-600">
              <strong>At:</strong> {fmtDate(slot.approved_at)}
            </div>
            {slot.is_override && slot.override_reason && (
              <div className="mt-1 rounded bg-purple-50 px-2 py-1 text-xs text-purple-900">
                <strong>Override reason:</strong> {slot.override_reason}
              </div>
            )}
          </>
        ) : !slot.required ? (
          <div className="text-xs text-gray-500 italic">
            This role doesn&apos;t require approval.
          </div>
        ) : (
          <div className="text-gray-700">Waiting for {slot.staff_name} to approve.</div>
        )}
      </div>

      {/* Action buttons */}
      {slot.required && !slot.approved && (
        <div className="flex gap-2 border-t border-gray-100 bg-gray-50/50 px-3 py-2">
          {isCurrentUser && (
            <button
              onClick={onSelfApprove}
              disabled={busy}
              className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-400"
            >
              ✓ Approve my slot
            </button>
          )}
          {isManager && !isCurrentUser && (
            <button
              onClick={onOverride}
              disabled={busy}
              className="rounded border border-purple-300 bg-white px-3 py-1 text-xs font-medium text-purple-700 hover:bg-purple-50 disabled:cursor-not-allowed disabled:bg-gray-100"
            >
              Override approval…
            </button>
          )}
        </div>
      )}
    </div>
  );
}
