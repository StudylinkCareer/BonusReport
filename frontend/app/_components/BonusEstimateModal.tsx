'use client';

/**
 * SAVE TO: frontend/app/_components/BonusEstimateModal.tsx
 *
 * Modal that previews the bonus the engine would calculate for a single case.
 * Fetches GET /api/cases/{id}/estimate-bonus and renders the result.
 *
 * Used from /import/review when workflow_state === 'in_review'. Closed cases
 * have already been calculated for real, uploaded cases haven't been validated
 * yet — neither case is eligible for an estimate.
 */

import { useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// Types — match the shape returned by the backend simulator
// ---------------------------------------------------------------------------

type Payment = {
  case_id: number;
  staff_id: number | null;
  staff_name: string | null;
  role_id: number | null;
  role_code: string | null;
  role_name: string | null;
  slot_label: string;
  tier_bonus: number;
  package_bonus: number;
  addon_bonus: number;
  priority_bonus: number;
  presales_share_taken: number;
  flat_local_enrolment_bonus: number;
  advance_offset: number;
  gross_bonus: number;
  withheld_amount: number;
  unlocked_amount: number;
  clawback_applied: number;
  bank_transfer_required: boolean;
  net_payable: number;
  calc_notes: string | null;
  audit_json: Record<string, unknown> | null;
  priority_withheld_amount: number;
  priority_unlocked_amount: number;
  priority_schedule_type: string;
};

type EstimateResponse = {
  case: {
    id: number;
    contract_id: string;
    student_name: string;
    year: number;
    month: number;
    workflow_state: string;
  };
  payments: Payment[];
  viewing_mode: 'all_slots' | 'own_slot_only';
  skipped: string[];
  errored: string[];
  disclaimer: string;
};

type Props = {
  caseId: number | null; // null = modal closed
  onClose: () => void;
};

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const VND = new Intl.NumberFormat('en-US');
const fmt = (n: number) => `${VND.format(n)} đ`;

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function BonusEstimateModal({ caseId, onClose }: Props) {
  const [data, setData] = useState<EstimateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Close on Escape
  useEffect(() => {
    if (caseId === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [caseId, onClose]);

  // Fetch when caseId changes
  useEffect(() => {
    if (caseId === null) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setData(null);
    setError(null);

    fetch(`/api/cases/${caseId}/estimate-bonus`, { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(
            (body as { detail?: string }).detail ?? `HTTP ${r.status}`,
          );
        }
        return r.json() as Promise<EstimateResponse>;
      })
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [caseId]);

  if (caseId === null) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Bonus estimate"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ===== Header ====================================================== */}
        <div className="flex items-start justify-between border-b border-gray-200 px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Bonus estimate</h2>
            {data && (
              <div className="mt-1 text-sm text-gray-600">
                <span className="font-mono">{data.case.contract_id}</span>
                <span className="mx-1.5 text-gray-300">·</span>
                {data.case.student_name}
                <span className="mx-1.5 text-gray-300">·</span>
                <span className="font-mono">
                  {data.case.year}-{String(data.case.month).padStart(2, '0')}
                </span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
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

        {/* ===== Body ======================================================== */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {loading && (
            <div className="py-12 text-center text-sm text-gray-500">
              Running engine…
            </div>
          )}

          {error && (
            <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              <div className="font-semibold">Estimate failed</div>
              <div className="mt-0.5">{error}</div>
            </div>
          )}

          {data && (
            <>
              {/* Disclaimer */}
              <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <strong>⚠ Estimate only.</strong> {data.disclaimer.replace(/^.*?— /, '')}
              </div>

              {/* Engine errors */}
              {data.errored.length > 0 && (
                <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                  <div className="mb-1 font-semibold">
                    Engine couldn&apos;t calculate this case:
                  </div>
                  {data.errored.map((e, i) => (
                    <div key={i} className="font-mono text-xs">
                      {e}
                    </div>
                  ))}
                </div>
              )}

              {/* Skipped */}
              {data.skipped.length > 0 && (
                <div className="mb-3 rounded border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-900">
                  <div className="mb-1 font-semibold">Case skipped by the engine:</div>
                  {data.skipped.map((s, i) => (
                    <div key={i}>{s}</div>
                  ))}
                </div>
              )}

              {/* No payments + no errors */}
              {data.payments.length === 0 &&
                data.errored.length === 0 &&
                data.skipped.length === 0 && (
                  <div className="rounded border border-gray-200 bg-gray-50 px-3 py-4 text-center text-sm text-gray-600">
                    {data.viewing_mode === 'own_slot_only'
                      ? "You're not assigned to this case as a paying slot."
                      : 'No bonus payments produced for this case.'}
                  </div>
                )}

              {/* "Filtered to your slot" note */}
              {data.payments.length > 0 &&
                data.viewing_mode === 'own_slot_only' && (
                  <div className="mb-2 text-xs italic text-gray-500">
                    Showing your slot only.
                  </div>
                )}

              {/* Payment cards */}
              {data.payments.map((p, i) => (
                <PaymentCard key={i} payment={p} />
              ))}
            </>
          )}
        </div>

        {/* ===== Footer ====================================================== */}
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
// PaymentCard — one card per slot in the case
// ---------------------------------------------------------------------------

function PaymentCard({ payment: p }: { payment: Payment }) {
  const [showDetails, setShowDetails] = useState(false);

  const hasAdjustments =
    p.withheld_amount !== 0 ||
    p.unlocked_amount !== 0 ||
    p.clawback_applied !== 0;

  return (
    <div className="mb-3 overflow-hidden rounded border border-gray-200 bg-white">
      {/* Card header */}
      <div className="flex items-center justify-between gap-3 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900">
            {p.staff_name ?? `Staff #${p.staff_id ?? '?'}`}
          </span>
          {p.role_name && (
            <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800">
              {p.role_name}
            </span>
          )}
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-500">Net payable</div>
          <div
            className={`text-lg font-bold ${
              p.net_payable > 0 ? 'text-emerald-700' : 'text-gray-500'
            }`}
          >
            {fmt(p.net_payable)}
          </div>
        </div>
      </div>

      {/* Breakdown */}
      <div className="px-3 py-2 text-sm">
        <BreakdownRow label="Tier bonus" value={p.tier_bonus} />
        <BreakdownRow label="Package bonus" value={p.package_bonus} />
        <BreakdownRow label="Add-on bonus" value={p.addon_bonus} />
        <BreakdownRow label="Priority bonus" value={p.priority_bonus} />
        <BreakdownRow label="Presales share" value={p.presales_share_taken} />
        <BreakdownRow
          label="Flat local enrolment"
          value={p.flat_local_enrolment_bonus}
        />
        <BreakdownRow label="Advance offset" value={p.advance_offset} />

        <div className="my-1 border-t border-gray-200" />
        <BreakdownRow label="Gross bonus" value={p.gross_bonus} bold />

        {hasAdjustments && (
          <>
            {p.withheld_amount !== 0 && (
              <BreakdownRow
                label="− Withheld (carry forward)"
                value={-p.withheld_amount}
              />
            )}
            {p.unlocked_amount !== 0 && (
              <BreakdownRow
                label="+ Unlocked from prior month"
                value={p.unlocked_amount}
              />
            )}
            {p.clawback_applied !== 0 && (
              <BreakdownRow
                label="− Clawback applied"
                value={-p.clawback_applied}
              />
            )}
          </>
        )}

        {p.priority_schedule_type === 'SPLIT_25_25_50' && (
          <div className="mt-2 rounded bg-purple-50 px-2 py-1 text-xs text-purple-900">
            <strong>Priority split rule active:</strong> paid 25% now / 25% at
            visa / 50% at year-end. Withheld now: {fmt(p.priority_withheld_amount)}.
          </div>
        )}

        <div className="my-1 border-t border-gray-200" />
        <BreakdownRow label="Net payable" value={p.net_payable} bold />

        {p.bank_transfer_required && (
          <div className="mt-2 rounded bg-blue-50 px-2 py-1 text-xs text-blue-900">
            💳 Bank transfer required (≥ 5,000,000 đ threshold).
          </div>
        )}
      </div>

      {/* Calc notes */}
      {p.calc_notes && (
        <div className="border-t border-gray-100 bg-gray-50/50 px-3 py-2 text-xs italic text-gray-600">
          {p.calc_notes}
        </div>
      )}

      {/* Audit JSON (collapsible) */}
      {p.audit_json && (
        <div className="border-t border-gray-100">
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="w-full px-3 py-1.5 text-left text-xs text-blue-600 hover:bg-blue-50"
          >
            {showDetails ? '▾ Hide audit details' : '▸ Show audit details'}
          </button>
          {showDetails && (
            <pre className="overflow-x-auto bg-gray-50 px-3 py-2 text-xs text-gray-700">
              {JSON.stringify(p.audit_json, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BreakdownRow — one labelled line in the payment breakdown
// ---------------------------------------------------------------------------

function BreakdownRow({
  label,
  value,
  bold,
}: {
  label: string;
  value: number;
  bold?: boolean;
}) {
  // Hide zero rows in the line-item section to reduce noise; always show totals.
  if (value === 0 && !bold) return null;
  return (
    <div className="flex justify-between py-0.5">
      <span className={bold ? 'font-medium text-gray-900' : 'text-gray-600'}>
        {label}
      </span>
      <span
        className={`font-mono ${bold ? 'font-medium' : ''} ${
          value < 0 ? 'text-red-700' : ''
        }`}
      >
        {fmt(value)}
      </span>
    </div>
  );
}
