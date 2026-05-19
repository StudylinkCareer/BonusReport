// frontend/src/app/_components/CaseBonusBreakdownModal.tsx
//
// Click-to-expand bonus breakdown for a single case.
// Opened from any of the four bonus cells (Base / Δ Override / Priority /
// Total) on the Submitted board. Shows one card per staff with the full
// component breakdown, distinguishes draft from published, and (for
// multi-staff direct cases) shows a case-level summary at the bottom.
//
// Receives the case row directly (rather than fetching by id) because
// the page already has it in state — avoids a second API call and keeps
// the modal in sync with whatever the caller already shows in the cells.
//
// Phase 14 Block 5 B3 + reconciliation patches:
//   * Earnings section shows "Priority (computed)" derived from gross_bonus
//     math, so Earnings always reconciles with Gross bonus. (The DB column
//     priority_bonus is the PAID-THIS-RUN value, which can be 0 even when
//     a non-zero priority contributed to gross_bonus — e.g. carry-over
//     data-gap cases. Showing only the paid value hid the discrepancy.)
//   * "Timing" section shows the full picture of where the difference
//     between Gross and Net comes from:
//       - Splittable withheld this run (status is_current_enrolled)
//       - Splittable unlocked from prior month (carry-over release)
//       - Priority paid / withheld / unlocked / deferred
//     The splittable values are derived from (gross, net, priority_unlocked)
//     since they aren't persisted as separate columns on tx_bonus_payment
//     (the carry-over ledger lives in tx_carry_over_balance instead).

import { useEffect, type ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Local types — minimal mirrors of what's in page.tsx. Duplicated here
// (rather than imported from page.tsx) so this component stays
// self-contained and doesn't create a circular dependency.
// ---------------------------------------------------------------------------

export type BonusRow = {
  staff_id: number | null;
  staff_name: string | null;
  role_id: number | null;
  role_code: string | null;
  slot: string | null;
  tier: string | null;
  tier_bonus: number;
  package_bonus: number;
  addon_bonus: number;
  flat_local_enrolment_bonus: number;
  priority_bonus: number;
  priority_withheld_amount: number;
  priority_unlocked_amount: number;
  priority_schedule_type: string;
  presales_share_taken: number;
  advance_offset: number;
  gross_bonus: number;
  net_payable: number;
  mgmt_override_amount: number | null;
  base_bonus: number;
  final_paid: number;
  is_draft: boolean;
  published_at: string | null;
};

// Narrow view of the Case fields this modal actually reads. Lets the
// caller pass any object that satisfies this shape — typically the full
// `Case` from page.tsx will satisfy it implicitly.
export type CaseLike = {
  contract_id: string;
  student_name: string;
  application_status: string;
  run_year: number;
  run_month: number;
  bonus_rows: BonusRow[];
  bonus_rows_total: number;
};

type Props = {
  caseRow: CaseLike | null;   // null = modal closed
  onClose: () => void;
};

// ---------------------------------------------------------------------------
// Formatting helpers (local copies — see fmtVnd in page.tsx)
// ---------------------------------------------------------------------------

function fmtVnd(n: number | null | undefined): string {
  if (n == null) return '–';
  return n.toLocaleString('vi-VN') + ' đ';
}

// Pre-timing priority value, derived from gross_bonus math.
// From calc.py:
//   gross = tier + package + addon + priority + flat_local - presales_share
// Solving for priority:
//   priority = gross - tier - package - addon - flat_local + presales_share
//
// This is the priority value calc_priority.py computed, before
// payment_timing decided how much to pay / withhold / defer.
function priorityComputedPreTiming(r: BonusRow): number {
  return (
    r.gross_bonus
    - r.tier_bonus
    - r.package_bonus
    - r.addon_bonus
    - r.flat_local_enrolment_bonus
    + r.presales_share_taken
  );
}

// Splittable withholding/unlocking this run, derived from gross/net delta.
// These aren't separate columns on tx_bonus_payment (the carry-over ledger
// lives in tx_carry_over_balance), so we reverse-engineer from observable
// values. priority_unlocked_amount adds to net independently of the
// splittable flow, so we factor it out to isolate the splittable delta.
//
// At most one of these can be > 0 per run:
//   - splittableWithheld > 0: status is is_current_enrolled (visa pending);
//     splittable portion held back, releases at visa-receipt month
//   - splittableUnlocked > 0: status is is_carry_over with a matching prior
//     withhold; released this run
function splittableTiming(r: BonusRow): {
  withheld: number;
  unlocked: number;
} {
  const delta = r.gross_bonus - r.net_payable + r.priority_unlocked_amount;
  return {
    withheld: Math.max(0, delta),
    unlocked: Math.max(0, -delta),
  };
}

// ===========================================================================
// Main component
// ===========================================================================

export function CaseBonusBreakdownModal({ caseRow, onClose }: Props) {
  // Esc to close — installed unconditionally; bails out if no case.
  useEffect(() => {
    if (!caseRow) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [caseRow, onClose]);

  if (!caseRow) return null;

  const rows = caseRow.bonus_rows ?? [];
  const totalAll = caseRow.bonus_rows_total ?? rows.length;
  const period = `${caseRow.run_year}-${String(caseRow.run_month).padStart(2, '0')}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 overflow-y-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="bonus-breakdown-title"
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-3xl w-full my-8"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2
                id="bonus-breakdown-title"
                className="text-lg font-semibold text-gray-900"
              >
                Bonus breakdown
              </h2>
              <div className="text-sm text-gray-600 mt-1">
                <span className="font-mono font-medium text-gray-800">
                  {caseRow.contract_id}
                </span>
                <span className="mx-2 text-gray-400">·</span>
                <span>{caseRow.student_name}</span>
                <span className="mx-2 text-gray-400">·</span>
                <span className="text-gray-500">{caseRow.application_status}</span>
                <span className="mx-2 text-gray-400">·</span>
                <span className="text-gray-500">{period}</span>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 text-xl leading-none p-1"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          {rows.length === 0 ? (
            <EmptyState totalAll={totalAll} />
          ) : (
            <div className="space-y-4">
              {rows.map((r, idx) => (
                <BonusRowCard
                  key={`${r.staff_id ?? 'unk'}-${r.slot ?? idx}-${idx}`}
                  row={r}
                />
              ))}

              {rows.length > 1 && <CaseSummary rows={rows} />}
            </div>
          )}

          {totalAll > rows.length && rows.length > 0 && (
            <div className="mt-4 text-xs text-gray-500 italic">
              Showing {rows.length} of {totalAll} bonus row{totalAll === 1 ? '' : 's'} on
              this case — the remaining row(s) belong to other staff and aren't
              visible to you.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 flex justify-end bg-gray-50 rounded-b-lg">
          <button
            onClick={onClose}
            className="rounded bg-gray-200 hover:bg-gray-300 px-4 py-1.5 text-sm font-medium text-gray-800"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Sub-components
// ===========================================================================

function EmptyState({ totalAll }: { totalAll: number }) {
  if (totalAll === 0) {
    return (
      <div className="text-sm text-gray-500 italic py-6 text-center">
        No bonus rows on this case yet. Has Calculate been run for this period?
      </div>
    );
  }
  // The case HAS bonus rows but none are visible to this viewer.
  return (
    <div className="text-sm text-gray-500 italic py-6 text-center">
      {totalAll} bonus row{totalAll === 1 ? '' : 's'} exist on this case but
      none are visible to you. Ask an administrator if you need to see them.
    </div>
  );
}

function BonusRowCard({ row }: { row: BonusRow }) {
  const r = row;

  // Pre-timing priority (the value calc_priority.py computed).
  // This is what contributed to gross_bonus, regardless of how
  // payment_timing later routed it (paid / withheld / unlocked / deferred).
  const priorityComputed = priorityComputedPreTiming(r);

  // Priority "deferred" = computed - (paid + withheld). Non-zero when
  // a carry-over data-gap occurs (priority computed in the original
  // enrolment month but never paid because there's no matching prior
  // withhold to release). This makes that state visible to reviewers.
  const priorityDeferred =
    priorityComputed - r.priority_bonus - r.priority_withheld_amount;

  // Splittable timing — derived. The "missing 350K" in Current-Enrolled
  // cases shows up here as `splittable.withheld`.
  const splittable = splittableTiming(r);

  // Show the timing section only when something interesting happened.
  const hasTimingActivity =
    splittable.withheld > 0 ||
    splittable.unlocked > 0 ||
    priorityComputed > 0 ||
    r.priority_unlocked_amount > 0;

  return (
    <div
      className={`rounded border p-4 ${
        r.is_draft
          ? 'border-amber-200 bg-amber-50/40'
          : 'border-emerald-200 bg-emerald-50/30'
      }`}
    >
      {/* Staff identity header */}
      <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-gray-900">
            {r.staff_name ?? '(unknown staff)'}
          </span>
          {r.role_code && (
            <span className="px-2 py-0.5 text-xs rounded font-mono bg-blue-100 text-blue-800">
              {r.role_code}
            </span>
          )}
          {r.slot && r.slot !== r.role_code && (
            <span className="text-xs text-gray-500">
              slot <span className="font-mono">{r.slot}</span>
            </span>
          )}
        </div>
        <span
          className={`text-xs rounded px-2 py-0.5 font-medium ${
            r.is_draft
              ? 'bg-amber-200 text-amber-900'
              : 'bg-emerald-200 text-emerald-900'
          }`}
        >
          {r.is_draft ? 'DRAFT' : 'PUBLISHED'}
        </span>
      </div>

      {/* Components grid: two columns. Left = labels, right = amounts. */}
      <div className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
        {/*
          EARNINGS — components that contribute to Gross bonus.
          Math: sum of earnings - deductions = Gross.
        */}
        <GroupHeader>Earnings</GroupHeader>
        <ValueRow label="Tier bonus"                  value={r.tier_bonus} muted={!r.tier_bonus} />
        <ValueRow label="Package bonus"               value={r.package_bonus} muted={!r.package_bonus} />
        <ValueRow label="Add-on bonus"                value={r.addon_bonus} muted={!r.addon_bonus} />
        <ValueRow label="Flat-local enrolment bonus"  value={r.flat_local_enrolment_bonus} muted={!r.flat_local_enrolment_bonus} />
        <ValueRow label="Priority (computed)"         value={priorityComputed} muted={!priorityComputed} />

        {/* DEDUCTIONS — subtractions from Earnings before Gross. */}
        {(r.presales_share_taken !== 0 || r.advance_offset !== 0) && (
          <GroupHeader>Deductions</GroupHeader>
        )}
        {r.presales_share_taken !== 0 && (
          <ValueRow label="Pre-sales share taken" value={-r.presales_share_taken} negative />
        )}
        {r.advance_offset !== 0 && (
          <ValueRow label="Advance offset" value={-r.advance_offset} negative />
        )}

        {/*
          TIMING — explains the difference between Gross and Net.
          Splittable: status-driven withholding (current-enrolled holds back
            half of the splittable portion until visa receipt).
          Priority: independent timing rules — passes through at full value
            under STANDARD_50_50, split under SPLIT_25_25_50, or deferred
            in carry-over data-gap cases.
        */}
        {hasTimingActivity && (
          <>
            <GroupHeader>Timing</GroupHeader>
            {splittable.withheld > 0 && (
              <ValueRow
                label="Splittable withheld this run (releases at visa receipt)"
                value={splittable.withheld}
              />
            )}
            {splittable.unlocked > 0 && (
              <ValueRow
                label="Splittable unlocked from prior month"
                value={splittable.unlocked}
              />
            )}
            {(priorityComputed > 0 || r.priority_bonus > 0) && (
              <ValueRow
                label="Priority paid this run"
                value={r.priority_bonus}
                muted={!r.priority_bonus}
              />
            )}
            {r.priority_withheld_amount !== 0 && (
              <ValueRow
                label="Priority withheld this run (releases at visa/year-end)"
                value={r.priority_withheld_amount}
              />
            )}
            {r.priority_unlocked_amount !== 0 && (
              <ValueRow
                label="Priority unlocked from prior month"
                value={r.priority_unlocked_amount}
              />
            )}
            {priorityDeferred !== 0 && (
              <ValueRow
                label="Priority deferred (carry-over data gap)"
                value={priorityDeferred}
                muted
              />
            )}
          </>
        )}

        {/* TOTALS */}
        <GroupHeader>Totals</GroupHeader>
        <ValueRow label="Gross bonus"   value={r.gross_bonus} muted={!r.gross_bonus} />
        <ValueRow label="Net payable"   value={r.net_payable} />
        <ValueRow
          label="Δ Override applied"
          value={r.mgmt_override_amount ?? 0}
          muted={!r.mgmt_override_amount}
        />
        <ValueRow label="Final paid"    value={r.final_paid} bold />
      </div>

      {/* Footnote */}
      {(r.tier || r.priority_schedule_type !== 'STANDARD') && (
        <div className="mt-3 pt-2 border-t border-gray-200/60 text-xs text-gray-500">
          {r.tier && (
            <>
              Tier <span className="font-mono">{r.tier}</span>
            </>
          )}
          {r.priority_schedule_type !== 'STANDARD' && (
            <>
              {r.tier && <span className="mx-2">·</span>}
              Priority schedule{' '}
              <span className="font-mono">{r.priority_schedule_type}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function CaseSummary({ rows }: { rows: BonusRow[] }) {
  const baseSum = rows.reduce((a, r) => a + r.base_bonus, 0);
  const overrideSum = rows.reduce((a, r) => a + (r.mgmt_override_amount ?? 0), 0);
  const prioritySum = rows.reduce((a, r) => a + r.priority_bonus, 0);
  const finalSum = rows.reduce((a, r) => a + r.final_paid, 0);

  return (
    <div className="rounded border-2 border-gray-300 bg-gray-50 p-4">
      <div className="text-sm font-semibold text-gray-900 mb-2">
        Case total · {rows.length} staff
      </div>
      <div className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
        <ValueRow label="Base"      value={baseSum} />
        <ValueRow label="Δ Override" value={overrideSum} muted={!overrideSum} />
        <ValueRow label="Priority"  value={prioritySum} />
        <ValueRow label="Total"     value={finalSum} bold />
      </div>
    </div>
  );
}

function GroupHeader({ children }: { children: ReactNode }) {
  return (
    <div className="col-span-2 text-xs font-semibold uppercase tracking-wide text-gray-500 pt-2 mt-1 border-t border-gray-200/70 first:border-t-0 first:pt-0 first:mt-0">
      {children}
    </div>
  );
}

function ValueRow({
  label,
  value,
  muted,
  bold,
  negative,
}: {
  label: string;
  value: number;
  muted?: boolean;
  bold?: boolean;
  negative?: boolean;
}) {
  const color = muted
    ? 'text-gray-400'
    : negative
      ? 'text-rose-700'
      : bold
        ? 'text-gray-900'
        : 'text-gray-800';
  const weight = bold ? 'font-semibold' : '';

  return (
    <>
      <span className={`${muted ? 'text-gray-400' : 'text-gray-600'} ${weight}`}>
        {label}
      </span>
      <span className={`text-right tabular-nums ${color} ${weight}`}>
        {fmtVnd(value)}
      </span>
    </>
  );
}
