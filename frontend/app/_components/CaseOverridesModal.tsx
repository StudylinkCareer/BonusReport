'use client';

/**
 * SAVE TO: frontend/app/_components/CaseOverridesModal.tsx
 *
 * Per-slot management overrides for a single case (Phase 14 Block 4 / C).
 *
 * Shows the case's slot-assigned staff and allows DQO/ADMIN/DIRECTOR/FO to
 * add/edit/remove signed bonus override deltas with mandatory reasons.
 *
 * Used from /import/review on the Submitted pillar. PUT semantics: a single
 * save replaces the entire override list for the case atomically — the
 * backend deletes all existing rows for the case and inserts the new ones
 * inside one transaction.
 *
 * The engine reads tx_case_override rows at calc time and copies each row's
 * amount + reason onto the matching tx_bonus_payment row's mgmt_override_*
 * columns. (Engine integration ships in Phase 4 of Block 4.)
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// Types — match backend overrides.list_case_overrides shape
// ---------------------------------------------------------------------------

type AvailableStaff = {
  staff_id: number;
  staff_name: string;
  slot: string;
};

type ServerOverride = {
  id: number;
  staff_id: number;
  staff_name: string | null;
  amount: number;
  reason: string;
  created_at: string | null;
  updated_at: string | null;
  created_by_user_id: number;
  created_by_display_name: string | null;
  updated_by_user_id: number;
  updated_by_display_name: string | null;
};

type OverridesResponse = {
  case_id: number;
  workflow_state: string;
  calculated_at: string | null;
  available_staff: AvailableStaff[];
  overrides: ServerOverride[];
};

type CurrentUser = {
  id: number;
  staff_id: number | null;
  roles: string[];
};

// Local-only draft type. We never trust client row ids — the server is
// authoritative and rebuilds the list on every PUT.
type DraftOverride = {
  staff_id: number | null; // null = "not yet chosen" for a freshly added row
  amount: string; // string for editing — parsed to int on save
  reason: string;
};

type Props = {
  caseId: number | null;
  onClose: () => void;
  onSaved?: () => void; // parent should refresh case list to pick up new overrides
};

// ---------------------------------------------------------------------------
// Helpers
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

function fmtVnd(n: number): string {
  return n.toLocaleString('vi-VN') + ' đ';
}

// Display labels for slot codes, mirrors backend.
const SLOT_LABELS: Record<string, string> = {
  counsellor: 'Counsellor',
  case_officer: 'Case Officer',
  pre_sales: 'Pre-Sales',
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CaseOverridesModal({ caseId, onClose, onSaved }: Props) {
  const [data, setData] = useState<OverridesResponse | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [drafts, setDrafts] = useState<DraftOverride[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // --- Dirty check (used by Esc handler, backdrop click, Close button) ----
  const isDirty = useCallback((): boolean => {
    if (!data) return false;
    if (drafts.length !== data.overrides.length) return true;
    for (let i = 0; i < drafts.length; i++) {
      const d = drafts[i];
      const s = data.overrides[i];
      if (d.staff_id !== s.staff_id) return true;
      if (Number(d.amount) !== s.amount) return true;
      if (d.reason !== s.reason) return true;
    }
    return false;
  }, [drafts, data]);

  const tryClose = useCallback(() => {
    if (isDirty()) {
      const ok = window.confirm('You have unsaved changes. Discard and close?');
      if (!ok) return;
    }
    onClose();
  }, [isDirty, onClose]);

  // Keep an up-to-date ref so the Esc keydown handler (bound once per modal
  // open) always calls the latest tryClose without re-binding on every
  // keystroke.
  const tryCloseRef = useRef(tryClose);
  tryCloseRef.current = tryClose;

  useEffect(() => {
    if (caseId === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') tryCloseRef.current();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [caseId]);

  // --- Fetch overrides + current user -------------------------------------
  const fetchAll = useCallback(async () => {
    if (caseId === null) return;
    setLoading(true);
    setError(null);
    try {
      const [overridesRes, meRes] = await Promise.all([
        fetch(`/api/cases/${caseId}/overrides`, { credentials: 'include' }),
        fetch('/api/auth/me', { credentials: 'include' }),
      ]);
      if (!overridesRes.ok) {
        const body = await overridesRes.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${overridesRes.status}`);
      }
      if (!meRes.ok) throw new Error('Failed to load current user');
      const d: OverridesResponse = await overridesRes.json();
      setData(d);
      setUser(await meRes.json());
      // Seed drafts from server. Server orders by canonical_name.
      setDrafts(
        d.overrides.map((o) => ({
          staff_id: o.staff_id,
          amount: String(o.amount),
          reason: o.reason,
        })),
      );
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
      setDrafts([]);
      setError(null);
      return;
    }
    void fetchAll();
  }, [caseId, fetchAll]);

  // ---- Local edits -------------------------------------------------------

  function updateDraft(idx: number, patch: Partial<DraftOverride>) {
    setDrafts((prev) => prev.map((d, i) => (i === idx ? { ...d, ...patch } : d)));
  }

  function removeDraft(idx: number) {
    setDrafts((prev) => prev.filter((_, i) => i !== idx));
  }

  function addDraft() {
    setDrafts((prev) => [...prev, { staff_id: null, amount: '', reason: '' }]);
  }

  // ---- Save (PUT whole list) --------------------------------------------

  async function handleSave() {
    if (caseId === null || data === null) return;

    // Local validation mirrors the server. Catch issues before the network
    // round trip — gives faster feedback than parsing a 400 reply.
    const payload: { staff_id: number; amount: number; reason: string }[] = [];
    const seen = new Set<number>();
    const knownStaffIds = new Set(data.available_staff.map((s) => s.staff_id));

    for (let i = 0; i < drafts.length; i++) {
      const d = drafts[i];
      const rowNum = i + 1;
      if (d.staff_id === null) {
        setError(`Row ${rowNum}: please pick a staff member.`);
        return;
      }
      if (!knownStaffIds.has(d.staff_id)) {
        setError(`Row ${rowNum}: staff_id ${d.staff_id} is not on this case.`);
        return;
      }
      if (seen.has(d.staff_id)) {
        setError(`Row ${rowNum}: duplicate staff selection.`);
        return;
      }
      seen.add(d.staff_id);

      const amt = Number(d.amount);
      if (!Number.isFinite(amt) || !Number.isInteger(amt)) {
        setError(`Row ${rowNum}: amount must be a whole number.`);
        return;
      }
      if (amt === 0) {
        setError(`Row ${rowNum}: amount cannot be zero (remove the row instead).`);
        return;
      }
      if (!d.reason.trim()) {
        setError(`Row ${rowNum}: reason is required.`);
        return;
      }
      payload.push({
        staff_id: d.staff_id,
        amount: amt,
        reason: d.reason.trim(),
      });
    }

    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/cases/${caseId}/overrides`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides: payload }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${r.status}`);
      }
      await fetchAll(); // re-seed drafts from server
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (caseId === null) return null;

  // --- Permission + state gates ------------------------------------------
  const canEditRole =
    !!user && user.roles.some((r) => ['DQO', 'ADMIN', 'DIRECTOR', 'FO'].includes(r));
  const inSubmitted = data?.workflow_state === 'submitted';
  const writable = canEditRole && inSubmitted;

  // Staff ids currently used across all drafts — used to disable conflicting
  // dropdown options.
  const draftStaffIds = new Set(
    drafts.map((d) => d.staff_id).filter((id): id is number => id !== null),
  );
  const allOptions = data?.available_staff ?? [];
  const canAddMore = draftStaffIds.size < allOptions.length;

  // Running total — finite int rows only.
  const totalDelta = drafts
    .map((d) => Number(d.amount))
    .filter((n) => Number.isFinite(n) && Number.isInteger(n))
    .reduce((a, b) => a + b, 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={tryClose}
      role="dialog"
      aria-modal="true"
      aria-label="Case overrides"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ===== Header =================================================== */}
        <div className="flex items-start justify-between border-b border-gray-200 px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Management overrides
            </h2>
            {data && (
              <div className="mt-1 text-sm text-gray-600">
                <span className="font-mono">case_id={data.case_id}</span>
                <span className="mx-1.5 text-gray-300">·</span>
                {inSubmitted ? (
                  <span className="font-medium text-emerald-700">
                    Submitted (editable)
                  </span>
                ) : (
                  <span className="text-gray-500">
                    State:{' '}
                    <span className="font-medium">{data.workflow_state}</span>{' '}
                    — read-only
                  </span>
                )}
                {data.calculated_at && (
                  <>
                    <span className="mx-1.5 text-gray-300">·</span>
                    <span>Calculated {fmtDate(data.calculated_at)}</span>
                  </>
                )}
              </div>
            )}
          </div>
          <button
            onClick={tryClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* ===== Body ===================================================== */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {loading && (
            <div className="py-8 text-center text-sm text-gray-500">Loading…</div>
          )}

          {error && (
            <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              <strong>Error:</strong> {error}
            </div>
          )}

          {data && !canEditRole && (
            <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              You need DQO, ADMIN, DIRECTOR, or FO role to edit overrides. This
              view is read-only.
            </div>
          )}

          {data && canEditRole && !inSubmitted && (
            <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              This case is in <strong>{data.workflow_state}</strong> state.
              Overrides can only be edited while the case is in{' '}
              <strong>submitted</strong>.
            </div>
          )}

          {data && allOptions.length === 0 && (
            <div className="rounded border border-gray-200 bg-gray-50 px-3 py-4 text-center text-sm text-gray-600">
              This case has no slot-assigned staff to override.
            </div>
          )}

          {data && drafts.length === 0 && allOptions.length > 0 && (
            <div className="mb-3 rounded border border-gray-200 bg-gray-50 px-3 py-3 text-center text-sm text-gray-600">
              No overrides set for this case.
            </div>
          )}

          {drafts.map((d, idx) => (
            <OverrideRow
              key={idx}
              index={idx}
              draft={d}
              allOptions={allOptions}
              draftStaffIds={draftStaffIds}
              writable={writable}
              onChange={(patch) => updateDraft(idx, patch)}
              onRemove={() => removeDraft(idx)}
              original={data?.overrides[idx]}
            />
          ))}

          {writable && (
            <button
              onClick={addDraft}
              disabled={!canAddMore || busy}
              className="mt-2 rounded border border-dashed border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
              title={
                canAddMore
                  ? 'Add a new override row'
                  : 'All slot-assigned staff already have an override'
              }
            >
              + Add override
            </button>
          )}
        </div>

        {/* ===== Footer =================================================== */}
        <div className="flex items-center justify-between gap-3 border-t border-gray-200 bg-gray-50 px-4 py-2">
          <div className="text-xs text-gray-600">
            {drafts.length > 0 && (
              <>
                {drafts.length} override{drafts.length !== 1 ? 's' : ''} · Total
                delta: <span className="font-semibold">{fmtVnd(totalDelta)}</span>
              </>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={tryClose}
              disabled={busy}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              {writable && isDirty() ? 'Cancel' : 'Close'}
            </button>
            {writable && (
              <button
                onClick={handleSave}
                disabled={busy || !isDirty()}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
              >
                {busy ? 'Saving…' : 'Save changes'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OverrideRow — one editable row card
// ---------------------------------------------------------------------------

function OverrideRow({
  index,
  draft,
  allOptions,
  draftStaffIds,
  writable,
  onChange,
  onRemove,
  original,
}: {
  index: number;
  draft: DraftOverride;
  allOptions: AvailableStaff[];
  draftStaffIds: Set<number>;
  writable: boolean;
  onChange: (patch: Partial<DraftOverride>) => void;
  onRemove: () => void;
  original: ServerOverride | undefined;
}) {
  return (
    <div className="mb-3 overflow-hidden rounded border border-gray-200 bg-white">
      <div className="flex items-center justify-between gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-500">
            Override #{index + 1}
          </span>
          {original ? (
            <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-700">
              Saved
            </span>
          ) : (
            <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-800">
              New
            </span>
          )}
        </div>
        {writable && (
          <button
            onClick={onRemove}
            className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
            title="Remove this override"
            aria-label={`Remove override ${index + 1}`}
          >
            <svg
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 px-3 py-2 sm:grid-cols-2">
        {/* Staff selector */}
        <label className="block text-xs">
          <span className="text-gray-600">Staff member</span>
          <select
            value={draft.staff_id ?? ''}
            disabled={!writable}
            onChange={(e) =>
              onChange({
                staff_id: e.target.value === '' ? null : Number(e.target.value),
              })
            }
            className="mt-1 block w-full rounded border border-gray-300 bg-white px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-500"
          >
            <option value="">— pick a staff member —</option>
            {allOptions.map((s) => {
              const usedElsewhere =
                draftStaffIds.has(s.staff_id) && draft.staff_id !== s.staff_id;
              return (
                <option
                  key={`${s.staff_id}-${s.slot}`}
                  value={s.staff_id}
                  disabled={usedElsewhere}
                >
                  {s.staff_name} ({SLOT_LABELS[s.slot] ?? s.slot})
                  {usedElsewhere ? ' — already used' : ''}
                </option>
              );
            })}
          </select>
        </label>

        {/* Amount input */}
        <label className="block text-xs">
          <span className="text-gray-600">
            Amount (đ — negative reduces, positive adds)
          </span>
          <input
            type="text"
            inputMode="numeric"
            value={draft.amount}
            disabled={!writable}
            onChange={(e) => onChange({ amount: e.target.value })}
            placeholder="e.g. -500000 or 250000"
            className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 font-mono text-sm disabled:bg-gray-100 disabled:text-gray-500"
          />
        </label>

        {/* Reason textarea — full width */}
        <label className="col-span-1 block text-xs sm:col-span-2">
          <span className="text-gray-600">Reason (required)</span>
          <textarea
            value={draft.reason}
            disabled={!writable}
            onChange={(e) => onChange({ reason: e.target.value })}
            rows={2}
            placeholder="Why is this override needed?"
            className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100 disabled:text-gray-500"
          />
        </label>
      </div>

      {/* Audit footer for saved rows */}
      {original && (
        <div className="border-t border-gray-100 bg-gray-50/50 px-3 py-1.5 text-[11px] text-gray-500">
          Created by{' '}
          {original.created_by_display_name ??
            `user #${original.created_by_user_id}`}{' '}
          on {fmtDate(original.created_at)}
          {original.updated_at && original.updated_at !== original.created_at && (
            <>
              {' '}
              · Updated by{' '}
              {original.updated_by_display_name ??
                `user #${original.updated_by_user_id}`}{' '}
              on {fmtDate(original.updated_at)}
            </>
          )}
        </div>
      )}
    </div>
  );
}
