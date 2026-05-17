'use client';

/**
 * SAVE TO: frontend/app/bonus/[year]/[month]/page.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\bonus\[year]\[month]\page.tsx)
 *
 * Per-staff bao cao view for one (year, month). One report per staff member
 * with cases in the period, switchable via a dropdown at the top.
 *
 * Phase 13e additions (this revision):
 *   - "Reverse this run" button in each staff's sub-header.
 *   - ReverseModal — opens at the page level so the report can be refreshed
 *     after the action completes (reversed cases leave the closed list).
 *   - Modal phases: loading dropdowns → form → submitting → result → error.
 *   - Auth gate: the modal reads useRole() / actingAsKey() and checks the
 *     current key against /api/bonus/reverse/authorised-keys before
 *     enabling the Confirm button. Unauthorised personas see a clear
 *     "switch your Acting As role to ..." message and Confirm is disabled.
 *   - Reason dropdown sourced from /api/bonus/reverse/reasons (excludes
 *     the system-only CASCADE_FROM_PRIORITY_IMPACT code).
 *   - Behaviour (Phase 13e — reverse-only): clicking Reverse flags the
 *     existing tx_bonus_payment rows as reversed (audit) AND moves the
 *     affected tx_case rows back from 'closed' to 'submitted' so QM /
 *     Case Officer can edit them. The engine does NOT re-run — after the
 *     cases are corrected and re-closed, the bonus engine must be run
 *     again manually to produce fresh payments.
 *   - Result panel shows: payments_reversed, total_reversed_amount,
 *     cases_unlocked, next-steps guidance, reversal_id for audit trail.
 *
 * Data: GET /api/bonus/reports/{year}/{month}
 * Action: POST /api/bonus/reverse-only
 */

import { use, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { actingAsKey, useRole } from '@/lib/role';

// ---------------------------------------------------------------------------
// Types — existing
// ---------------------------------------------------------------------------

type Case = {
  no: number;
  case_id: number;
  contract_id: string;
  student_name: string | null;
  student_id: string | null;
  signed_date: string | null;
  client_type: string | null;
  country: string | null;
  refer_source: string;
  system_type: string;
  application_status: string | null;
  visa_date: string | null;
  institution: string | null;
  course_start: string | null;
  course_status: string | null;
  counsellor: string | null;
  co: string | null;
  notes: string | null;
  slot_role: string | null;
  bonus_enrolled: number;
  note_bonus_enrolled: string;
  bonus_priority: number;
  note_bonus_priority: string;
};

type Section = {
  section_name: string;
  cases: Case[];
  subtotal_enrolled: number;
  subtotal_priority: number;
};

type StaffReport = {
  staff_id: number;
  staff_name: string | null;
  role_code: string | null;
  office_code: string | null;
  sections: Section[];
  total_enrolled: number;
  total_priority: number;
  grand_total: number;
};

type ReportData = {
  year: number;
  month: number;
  staff_reports: StaffReport[];
};

// ---------------------------------------------------------------------------
// Types — Phase 13d (reversal modal)
// ---------------------------------------------------------------------------

type AuthorisedKey = {
  acting_as_key: string;
  display_name: string;
};

type ReversalReason = {
  code: string;
  display_name: string;
  notes: string | null;
};

type ReverseOnlyResponse = {
  year: number;
  month: number;
  trigger_staff_id: number;
  reversal_id: number;
  payment_count: number;
  total_reversed_amount: number;
  cases_unlocked: number;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmtVnd = (n: number) => (n ? n.toLocaleString('vi-VN') : '0');
const monthName = (m: number) =>
  ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1] ?? `M${m}`;

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function BaoCaoPage({
  params,
}: {
  params: Promise<{ year: string; month: string }>;
}) {
  const { year: yearStr, month: monthStr } = use(params);
  const year = parseInt(yearStr, 10);
  const month = parseInt(monthStr, 10);

  const [data, setData] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedStaffId, setSelectedStaffId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [showReverseModal, setShowReverseModal] = useState(false);

  // Bump refreshKey to trigger a refetch (used after a successful cascade,
  // which may have touched other staff via priority-quota propagation).
  const refreshReport = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetch(`/api/bonus/reports/${year}/${month}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: ReportData) => {
        if (cancelled) return;
        setData(d);
        // Preserve the user's selected staff if still present after a
        // refetch (e.g. cascade refresh); otherwise fall back to the first.
        setSelectedStaffId((prev) => {
          if (
            prev != null &&
            d.staff_reports.some((s) => s.staff_id === prev)
          ) {
            return prev;
          }
          return d.staff_reports[0]?.staff_id ?? null;
        });
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [year, month, refreshKey]);

  const selectedStaff = useMemo(() => {
    if (!data || selectedStaffId == null) return null;
    return data.staff_reports.find((s) => s.staff_id === selectedStaffId) ?? null;
  }, [data, selectedStaffId]);

  return (
    <main className="mx-auto max-w-[1800px] p-6">
      <nav className="mb-4 flex items-center justify-between text-sm">
        <div className="flex items-center gap-3 text-gray-500">
          <Link href="/" className="hover:text-gray-900 hover:underline">
            ← Case workflow
          </Link>
          <span>·</span>
          <Link href="/bonus" className="hover:text-gray-900 hover:underline">
            All bonus reports
          </Link>
        </div>
        <Link
          href={`/import/review?year=${year}&month=${month}`}
          className="text-blue-600 hover:underline"
        >
          Review imports for this period →
        </Link>
      </nav>

      <header className="mb-4">
        <h1 className="text-2xl font-bold">
          Bonus Report — {monthName(month)} {year}
        </h1>
        {data && (
          <p className="mt-1 text-sm text-gray-600">
            {data.staff_reports.length} staff member
            {data.staff_reports.length === 1 ? '' : 's'} with cases in this period.
          </p>
        )}
      </header>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-4 py-3 text-red-800">
          <strong>Error:</strong> {error}
        </div>
      )}

      {!data && !error && (
        <div className="py-12 text-center text-gray-500">Loading…</div>
      )}

      {data && data.staff_reports.length === 0 && (
        <div className="py-12 text-center text-gray-500">
          No cases for this period.
        </div>
      )}

      {data && data.staff_reports.length > 0 && (
        <>
          <section className="mb-6 flex flex-wrap items-center gap-3">
            <label className="text-sm font-medium text-gray-700">
              Staff:
            </label>
            <select
              value={selectedStaffId ?? ''}
              onChange={(e) =>
                setSelectedStaffId(parseInt(e.target.value, 10))
              }
              className="rounded border px-3 py-1.5 text-sm bg-white min-w-[400px]"
            >
              {data.staff_reports.map((s) => {
                const caseCount = s.sections.reduce(
                  (a, x) => a + x.cases.length,
                  0,
                );
                return (
                  <option key={s.staff_id} value={s.staff_id}>
                    {s.staff_name ?? `#${s.staff_id}`}
                    {s.role_code ? ` (${s.role_code})` : ''}
                    {s.office_code ? ` · ${s.office_code}` : ''}
                    {' — '}
                    {caseCount} case{caseCount === 1 ? '' : 's'}
                    {' · '}
                    {fmtVnd(s.grand_total)} đ
                  </option>
                );
              })}
            </select>
            <span className="text-xs text-gray-500">
              {data.staff_reports.length} staff in this period
            </span>
          </section>

          {selectedStaff && (
            <StaffBaoCao
              staff={selectedStaff}
              year={year}
              month={month}
              onReverseClick={() => setShowReverseModal(true)}
            />
          )}
        </>
      )}

      {showReverseModal && selectedStaff && (
        <ReverseModal
          staff={selectedStaff}
          year={year}
          month={month}
          onClose={() => setShowReverseModal(false)}
          onComplete={() => {
            setShowReverseModal(false);
            refreshReport();
          }}
        />
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// StaffBaoCao — existing, with Reverse button added to sub-header
// ---------------------------------------------------------------------------

function StaffBaoCao({
  staff,
  year,
  month,
  onReverseClick,
}: {
  staff: StaffReport;
  year: number;
  month: number;
  onReverseClick: () => void;
}) {
  return (
    <section className="space-y-5">
      {/* Staff sub-header with Reverse button */}
      <div className="rounded border border-gray-200 bg-gray-50 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">
              Báo cáo {staff.staff_name} — tháng{' '}
              {String(month).padStart(2, '0')}/{year}
            </h2>
            <p className="text-xs text-gray-600">
              {staff.role_code ?? '—'}
              {staff.office_code ? ` · ${staff.office_code}` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onReverseClick}
            className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
            title="Reverse this staff's bonus run and re-calculate"
          >
            Reverse this run
          </button>
        </div>
      </div>

      {staff.sections.map((section) => (
        <BaoCaoSection key={section.section_name} section={section} />
      ))}

      {/* Grand totals */}
      <div className="rounded border border-emerald-200 bg-emerald-50 px-4 py-3">
        <h3 className="text-sm font-semibold mb-2">TỔNG</h3>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              Bonus Enrolled
            </div>
            <div className="text-lg font-semibold">
              {fmtVnd(staff.total_enrolled)} đ
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              Bonus Priority
            </div>
            <div className="text-lg font-semibold">
              {fmtVnd(staff.total_priority)} đ
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-gray-500">
              Grand total
            </div>
            <div className="text-lg font-bold text-emerald-700">
              {fmtVnd(staff.grand_total)} đ
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function BaoCaoSection({ section }: { section: Section }) {
  return (
    <div>
      <h3 className="text-sm font-semibold bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-t">
        {section.section_name}{' '}
        <span className="text-gray-500 font-normal">
          ({section.cases.length})
        </span>
      </h3>
      <div className="overflow-x-auto border border-blue-200 border-t-0 rounded-b">
        <table className="min-w-full text-[11px]">
          <thead className="bg-gray-50">
            <tr>
              <Th>No.</Th>
              <Th>Student Name</Th>
              <Th>Student ID</Th>
              <Th>Contract ID</Th>
              <Th>Signed</Th>
              <Th>Client Type</Th>
              <Th>Country</Th>
              <Th>Refer Source</Th>
              <Th>System</Th>
              <Th>App Status</Th>
              <Th>Visa Date</Th>
              <Th>Institution</Th>
              <Th>Course Start</Th>
              <Th>Course Status</Th>
              <Th>Counsellor</Th>
              <Th>CO</Th>
              <Th>Notes</Th>
              <Th right>BONUS Enrolled</Th>
              <Th>Note Enrolled</Th>
              <Th right>BONUS Priority</Th>
              <Th>Note Priority</Th>
            </tr>
          </thead>
          <tbody>
            {section.cases.map((c) => (
              <tr
                key={`${c.case_id}-${c.slot_role}`}
                className="border-t border-gray-100 hover:bg-yellow-50/40"
              >
                <Td>{c.no}</Td>
                <Td>{c.student_name ?? '—'}</Td>
                <Td className="font-mono">{c.student_id ?? '—'}</Td>
                <Td className="font-mono">{c.contract_id}</Td>
                <Td>{c.signed_date ?? '—'}</Td>
                <Td>{c.client_type ?? '—'}</Td>
                <Td>{c.country ?? '—'}</Td>
                <Td className="max-w-[200px] truncate" title={c.refer_source}>
                  {c.refer_source || '—'}
                </Td>
                <Td>{c.system_type}</Td>
                <Td>{c.application_status ?? '—'}</Td>
                <Td>{c.visa_date ?? '—'}</Td>
                <Td className="max-w-[200px] truncate" title={c.institution ?? ''}>
                  {c.institution ?? '—'}
                </Td>
                <Td>{c.course_start ?? '—'}</Td>
                <Td>{c.course_status ?? '—'}</Td>
                <Td>{c.counsellor ?? '—'}</Td>
                <Td>{c.co ?? '—'}</Td>
                <Td
                  className="max-w-[200px] truncate text-gray-600"
                  title={c.notes ?? ''}
                >
                  {c.notes ?? '—'}
                </Td>
                <Td
                  right
                  className={
                    c.bonus_enrolled > 0 ? 'font-medium' : 'text-gray-400'
                  }
                >
                  {c.bonus_enrolled.toLocaleString('vi-VN')}
                </Td>
                <Td
                  className="max-w-[280px] text-[10px] italic text-gray-600 whitespace-normal"
                  title={c.note_bonus_enrolled}
                >
                  {c.note_bonus_enrolled || '—'}
                </Td>
                <Td
                  right
                  className={
                    c.bonus_priority > 0 ? 'font-medium' : 'text-gray-400'
                  }
                >
                  {c.bonus_priority.toLocaleString('vi-VN')}
                </Td>
                <Td
                  className="max-w-[280px] text-[10px] italic text-gray-600 whitespace-normal"
                  title={c.note_bonus_priority}
                >
                  {c.note_bonus_priority || '—'}
                </Td>
              </tr>
            ))}
            <tr className="border-t-2 border-gray-300 bg-gray-50 font-semibold">
              <Td colSpan={17} className="text-right">
                Subtotal
              </Td>
              <Td right>
                {section.subtotal_enrolled.toLocaleString('vi-VN')}
              </Td>
              <Td></Td>
              <Td right>
                {section.subtotal_priority.toLocaleString('vi-VN')}
              </Td>
              <Td></Td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({
  children,
  right,
}: {
  children: React.ReactNode;
  right?: boolean;
}) {
  return (
    <th
      className={`px-2 py-1.5 text-[11px] font-medium text-gray-700 whitespace-nowrap ${
        right ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  right,
  className,
  colSpan,
  title,
}: {
  children?: React.ReactNode;
  right?: boolean;
  className?: string;
  colSpan?: number;
  title?: string;
}) {
  return (
    <td
      colSpan={colSpan}
      title={title}
      className={`px-2 py-1 whitespace-nowrap align-top ${
        right ? 'text-right' : ''
      } ${className ?? ''}`}
    >
      {children}
    </td>
  );
}

// ===========================================================================
// Phase 13d — ReverseModal
// ===========================================================================

type ModalPhase = 'loading' | 'form' | 'submitting' | 'result' | 'error';

function ReverseModal({
  staff,
  year,
  month,
  onClose,
  onComplete,
}: {
  staff: StaffReport;
  year: number;
  month: number;
  onClose: () => void;
  onComplete: () => void;
}) {
  const [role] = useRole();
  const currentKey = actingAsKey(role);

  const [phase, setPhase] = useState<ModalPhase>('loading');
  const [authorisedKeys, setAuthorisedKeys] = useState<AuthorisedKey[]>([]);
  const [reasons, setReasons] = useState<ReversalReason[]>([]);
  const [selectedReason, setSelectedReason] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [result, setResult] = useState<ReverseOnlyResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>('');

  // Lazy-fetch the two dropdowns when the modal opens
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch('/api/bonus/reverse/authorised-keys').then((r) => {
        if (!r.ok) throw new Error(`authorised-keys HTTP ${r.status}`);
        return r.json();
      }),
      fetch('/api/bonus/reverse/reasons').then((r) => {
        if (!r.ok) throw new Error(`reasons HTTP ${r.status}`);
        return r.json();
      }),
    ])
      .then(([keysResp, reasonsResp]) => {
        if (cancelled) return;
        setAuthorisedKeys(keysResp.authorised_keys ?? []);
        setReasons(reasonsResp.reasons ?? []);
        setPhase('form');
      })
      .catch((e) => {
        if (cancelled) return;
        setErrorMsg(`Failed to load reversal options: ${e}`);
        setPhase('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isAuthorised = authorisedKeys.some(
    (k) => k.acting_as_key === currentKey,
  );

  const submit = async () => {
    if (!selectedReason || !isAuthorised) return;
    setPhase('submitting');
    try {
      const res = await fetch('/api/bonus/reverse-only', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          year,
          month,
          trigger_staff_id: staff.staff_id,
          reversed_by_acting_as: currentKey,
          reason_code: selectedReason,
          notes: notes.trim() || null,
        }),
      });
      if (!res.ok) {
        // FastAPI errors are JSON: {"detail": "..."}.
        // Fall back to text if parse fails.
        const text = await res.text();
        let detail = text;
        try {
          const parsed = JSON.parse(text);
          if (parsed?.detail) detail = parsed.detail;
        } catch {
          /* ignore */
        }
        throw new Error(`HTTP ${res.status} — ${detail}`);
      }
      const data: ReverseOnlyResponse = await res.json();
      setResult(data);
      setPhase('result');
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setPhase('error');
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-start justify-center z-50 p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-lg max-w-3xl w-full my-8"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="text-lg font-semibold">
            Reverse bonus run — {staff.staff_name} · {monthName(month)} {year}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </header>

        <div className="p-5">
          {phase === 'loading' && (
            <div className="py-8 text-center text-sm text-gray-500">
              Loading reversal options…
            </div>
          )}

          {phase === 'form' && (
            <ReverseForm
              currentKey={currentKey}
              isAuthorised={isAuthorised}
              authorisedKeys={authorisedKeys}
              reasons={reasons}
              selectedReason={selectedReason}
              setSelectedReason={setSelectedReason}
              notes={notes}
              setNotes={setNotes}
              onCancel={onClose}
              onSubmit={submit}
            />
          )}

          {phase === 'submitting' && (
            <div className="py-8 text-center">
              <div className="text-sm text-gray-700 mb-1">
                Reversing…
              </div>
              <div className="text-xs text-gray-500">
                Flagging {staff.staff_name}'s payments as reversed and
                moving their cases back to the Submitted pillar for editing.
              </div>
            </div>
          )}

          {phase === 'result' && result && (
            <ResultView
              result={result}
              staffName={staff.staff_name ?? `#${staff.staff_id}`}
              onDone={onComplete}
            />
          )}

          {phase === 'error' && (
            <ErrorView
              errorMsg={errorMsg}
              onRetry={() => setPhase('form')}
              onClose={onClose}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal sub-views
// ---------------------------------------------------------------------------

function ReverseForm({
  currentKey,
  isAuthorised,
  authorisedKeys,
  reasons,
  selectedReason,
  setSelectedReason,
  notes,
  setNotes,
  onCancel,
  onSubmit,
}: {
  currentKey: string;
  isAuthorised: boolean;
  authorisedKeys: AuthorisedKey[];
  reasons: ReversalReason[];
  selectedReason: string;
  setSelectedReason: (s: string) => void;
  notes: string;
  setNotes: (s: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="text-xs font-medium text-gray-600 uppercase tracking-wide mb-1">
          Acting as
        </div>
        <div className="rounded border bg-gray-50 px-3 py-2 font-mono text-xs">
          {currentKey}
        </div>
        {isAuthorised ? (
          <div className="mt-1.5 text-xs text-emerald-700">
            ✓ Authorised to reverse bonus runs.
          </div>
        ) : (
          <div className="mt-1.5 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <div className="font-medium mb-1">
              ✗ Not authorised to reverse bonus runs.
            </div>
            <div>
              Switch your Acting As role using the picker in the top bar to
              one of:{' '}
              <span className="font-medium">
                {authorisedKeys.map((k) => k.display_name).join(', ')}
              </span>
              .
            </div>
          </div>
        )}
      </div>

      <div>
        <label className="text-xs font-medium text-gray-600 uppercase tracking-wide block mb-1">
          Reason <span className="text-red-600">*</span>
        </label>
        <select
          value={selectedReason}
          onChange={(e) => setSelectedReason(e.target.value)}
          disabled={!isAuthorised}
          className="w-full rounded border px-3 py-1.5 text-sm bg-white disabled:bg-gray-100"
        >
          <option value="">— Select a reason —</option>
          {reasons.map((r) => (
            <option key={r.code} value={r.code}>
              {r.display_name}
            </option>
          ))}
        </select>
        {selectedReason &&
          reasons.find((r) => r.code === selectedReason)?.notes && (
            <p className="mt-1 text-xs text-gray-500 italic">
              {reasons.find((r) => r.code === selectedReason)?.notes}
            </p>
          )}
      </div>

      <div>
        <label className="text-xs font-medium text-gray-600 uppercase tracking-wide block mb-1">
          Notes <span className="text-gray-400">(optional)</span>
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={!isAuthorised}
          rows={3}
          maxLength={500}
          placeholder="Optional context for the audit log (max 500 chars)…"
          className="w-full rounded border px-3 py-2 text-sm disabled:bg-gray-100"
        />
        <div className="mt-0.5 text-[11px] text-gray-400 text-right">
          {notes.length}/500
        </div>
      </div>

      <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
        <strong>What happens:</strong> The current bonus payments for this
        staff/period are flagged reversed in the audit log, and their cases
        move from <code className="bg-white px-1 rounded">closed</code> back
        to <code className="bg-white px-1 rounded">submitted</code> so QM /
        Case Officer can edit them. The engine does <em>not</em> re-run —
        after the cases are corrected and re-closed, run the engine again
        manually to produce fresh payments.
      </div>

      <div className="flex items-center justify-end gap-2 pt-2 border-t">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border px-4 py-1.5 text-sm hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={!isAuthorised || !selectedReason}
          className="rounded bg-amber-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          Reverse run
        </button>
      </div>
    </div>
  );
}

function ResultView({
  result,
  staffName,
  onDone,
}: {
  result: ReverseOnlyResponse;
  staffName: string;
  onDone: () => void;
}) {
  return (
    <div className="space-y-4 text-sm">
      <div className="rounded border border-emerald-200 bg-emerald-50 px-4 py-3">
        <div className="font-semibold text-emerald-800">
          ✓ Reversal complete
        </div>
        <div className="text-xs text-emerald-900 mt-0.5">
          {staffName}'s bonus run has been reversed. Affected cases are now
          back in the Submitted pillar and editable by QM / Case Officer.
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded border px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Payments reversed
          </div>
          <div className="text-lg font-semibold mt-0.5">
            {result.payment_count}
          </div>
        </div>
        <div className="rounded border px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Total reversed
          </div>
          <div className="text-lg font-semibold mt-0.5">
            {fmtVnd(result.total_reversed_amount)} đ
          </div>
        </div>
        <div className="rounded border px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">
            Cases unlocked
          </div>
          <div className="text-lg font-semibold mt-0.5">
            {result.cases_unlocked}
          </div>
        </div>
      </div>

      <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
        <strong>Next steps:</strong>
        <ol className="mt-1 ml-4 list-decimal space-y-0.5">
          <li>
            Go to the{' '}
            <Link
              href="/pillars/submitted"
              className="underline font-medium hover:text-blue-700"
            >
              Submitted pillar
            </Link>{' '}
            to find {staffName}'s unlocked cases.
          </li>
          <li>Edit the case data as needed; QM re-closes when satisfied.</li>
          <li>
            Once cases are re-closed, run the bonus engine again for this
            period to produce fresh payments.
          </li>
        </ol>
      </div>

      <div className="text-[11px] text-gray-500">
        Reversal ID: <span className="font-mono">{result.reversal_id}</span> ·
        kept in <code>tx_bonus_reversal</code> for audit.
      </div>

      <div className="flex items-center justify-end pt-2 border-t">
        <button
          type="button"
          onClick={onDone}
          className="rounded bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
        >
          Done — refresh report
        </button>
      </div>
    </div>
  );
}

function ErrorView({
  errorMsg,
  onRetry,
  onClose,
}: {
  errorMsg: string;
  onRetry: () => void;
  onClose: () => void;
}) {
  return (
    <div className="space-y-4 text-sm">
      <div className="rounded border border-red-200 bg-red-50 px-4 py-3">
        <div className="font-semibold text-red-800 mb-1">
          Cascade failed
        </div>
        <div className="text-xs text-red-900 whitespace-pre-wrap break-words">
          {errorMsg}
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Any changes have been rolled back — the engine state is unchanged.
        You can adjust your inputs and retry, or close this dialog.
      </p>
      <div className="flex items-center justify-end gap-2 pt-2 border-t">
        <button
          type="button"
          onClick={onClose}
          className="rounded border px-4 py-1.5 text-sm hover:bg-gray-50"
        >
          Close
        </button>
        <button
          type="button"
          onClick={onRetry}
          className="rounded bg-amber-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-700"
        >
          Back to form
        </button>
      </div>
    </div>
  );
}
