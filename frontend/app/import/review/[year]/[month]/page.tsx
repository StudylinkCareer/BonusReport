'use client';

import { useState, useEffect, FormEvent } from 'react';
import { useRouter } from 'next/navigation';

type Staff = {
  id: number;
  name: string;
  role_code: string;
  office_code: string;
};

type Case = {
  id: number;
  contract_id: string;
  student_id: string | null;
  student_name: string;
  application_status: string;
  course_status: string | null;
  import_status: string;
  contract_signed_date: string | null;
  course_start_date: string | null;
  visa_received_date: string | null;
  client_type_code: string | null;
  handover_flag: boolean;
  case_transition: string | null;
  deferral_code: string | null;
  run_year: number;
  run_month: number;
  institution_name: string | null;
  country_name: string | null;
  counsellor_name: string | null;
  case_officer_name: string | null;
  vp_name: string | null;
};

type EngineResult = {
  total_cases: number;
  adapted: number;
  payment_count: number;
  gross_total: number;
  net_total: number;
  skipped: { contract_id: string; reason: string }[];
  errored: { contract_id: string; error: string; phase: string }[];
};

const ROW_BG: Record<string, string> = {
  OK: 'bg-green-50 hover:bg-green-100',
  FLAGGED: 'bg-amber-50 hover:bg-amber-100',
  UNRESOLVED: 'bg-red-50 hover:bg-red-100',
  SCRAP: 'bg-gray-100 hover:bg-gray-200 opacity-60',
};

const BADGE: Record<string, string> = {
  OK: 'bg-green-200 text-green-900',
  FLAGGED: 'bg-amber-200 text-amber-900',
  UNRESOLVED: 'bg-red-200 text-red-900',
  SCRAP: 'bg-gray-300 text-gray-700',
};

const fmtVnd = (n: number | null | undefined) => {
  if (n == null) return '–';
  return n.toLocaleString('vi-VN') + ' đ';
};

export default function ReviewPage() {
  const router = useRouter();

  const [staff, setStaff] = useState<Staff[]>([]);
  const [staffId, setStaffId] = useState<number | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  // Submit-to-Engine state
  const [submitting, setSubmitting] = useState(false);
  const [engineMessage, setEngineMessage] = useState<
    | { ok: true; result: EngineResult }
    | { ok: false; detail: string }
    | null
  >(null);

  // Load staff list on mount
  useEffect(() => {
    fetch('/api/staff')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setStaff)
      .catch((e) => setError(`Failed to load staff list: ${e}`));
  }, []);

  // Read URL params on mount and auto-load if present
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get('staff_id');
    const y = params.get('year');
    const m = params.get('month');
    if (sid) {
      const sidNum = Number(sid);
      const yNum = y ? Number(y) : new Date().getFullYear();
      const mNum = m ? Number(m) : new Date().getMonth() + 1;
      setStaffId(sidNum);
      setYear(yNum);
      setMonth(mNum);
      loadCases(sidNum, yNum, mNum);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadCases(sid: number, y: number, m: number) {
    setLoading(true);
    setError(null);
    setCases([]);
    setEngineMessage(null);
    try {
      const res = await fetch(
        `/api/cases?staff_id=${sid}&year=${y}&month=${m}`
      );
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`HTTP ${res.status}: ${detail}`);
      }
      setCases(await res.json());
      setHasLoaded(true);
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (staffId === null) {
      setError('Please pick a staff member');
      return;
    }
    // Update URL so the page is shareable/refreshable
    const url = `/import/review?staff_id=${staffId}&year=${year}&month=${month}`;
    window.history.replaceState({}, '', url);
    loadCases(staffId, year, month);
  }

  async function handleSubmitToEngine() {
    const confirmed = window.confirm(
      `Run the engine for ${year}-${String(month).padStart(2, '0')}?\n\n` +
        `Important: this runs the engine for the WHOLE PERIOD (every staff ` +
        `member's cases), not just the staff you're currently viewing.\n\n` +
        `It will:\n` +
        `  • DELETE all existing bonus payments for this period\n` +
        `  • Re-calculate from imported tx_case rows\n` +
        `  • Write fresh tx_bonus_payment rows\n\n` +
        `It is idempotent — you can re-run safely.`
    );
    if (!confirmed) return;

    setSubmitting(true);
    setEngineMessage(null);

    try {
      const r = await fetch('/api/engine/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          year,
          month,
          persist: true,
        }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const detail = (err as { detail?: string }).detail ?? `HTTP ${r.status}`;
        setEngineMessage({ ok: false, detail });
        setSubmitting(false);
        return;
      }

      const result = (await r.json()) as EngineResult;
      setEngineMessage({ ok: true, result });

      // Brief pause so user sees the summary, then navigate
      setTimeout(() => {
        router.push(`/bonus/${year}/${month}`);
      }, 1500);
    } catch (err) {
      setEngineMessage({
        ok: false,
        detail: `Network error: ${String(err)}`,
      });
      setSubmitting(false);
    }
  }

  const counts = {
    OK: cases.filter((c) => c.import_status === 'OK').length,
    FLAGGED: cases.filter((c) => c.import_status === 'FLAGGED').length,
    UNRESOLVED: cases.filter((c) => c.import_status === 'UNRESOLVED').length,
    SCRAP: cases.filter((c) => c.import_status === 'SCRAP').length,
  };

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-[1600px] mx-auto">
        <div className="flex items-baseline justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold">Imported Cases — Review</h1>
            <p className="text-gray-600 mt-1">
              Cases for one staff member in one period, colour-coded by import status.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <a
              href={`/bonus/${year}/${month}`}
              className="text-sm text-blue-600 hover:underline"
            >
              View bonus report →
            </a>
            <a
              href="/import"
              className="text-sm text-blue-600 hover:underline"
            >
              ← Back to Importer
            </a>
          </div>
        </div>

        {/* Filter form */}
        <form
          onSubmit={handleSubmit}
          className="flex flex-wrap gap-3 items-end bg-white p-4 rounded-lg shadow border border-gray-200 mb-6"
        >
          <div className="flex-1 min-w-[260px]">
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              Staff
            </label>
            <select
              value={staffId ?? ''}
              onChange={(e) =>
                setStaffId(e.target.value ? Number(e.target.value) : null)
              }
              className="w-full p-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            >
              <option value="">— pick a staff member —</option>
              {staff.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.role_code}, {s.office_code})
                </option>
              ))}
            </select>
          </div>
          <div className="w-24">
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              Year
            </label>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              min={2020}
              max={2030}
              className="w-full p-2 border border-gray-300 rounded"
              required
            />
          </div>
          <div className="w-20">
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              Month
            </label>
            <input
              type="number"
              value={month}
              onChange={(e) => setMonth(Number(e.target.value))}
              min={1}
              max={12}
              className="w-full p-2 border border-gray-300 rounded"
              required
            />
          </div>
          <button
            type="submit"
            disabled={loading || staffId === null}
            className="bg-blue-600 text-white px-5 py-2 rounded font-medium hover:bg-blue-700 disabled:bg-gray-300"
          >
            {loading ? 'Loading…' : 'Load'}
          </button>
        </form>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded">
            <p className="text-red-800 font-medium">Error</p>
            <p className="text-red-700 text-sm mt-1 font-mono whitespace-pre-wrap">
              {error}
            </p>
          </div>
        )}

        {!loading && !error && hasLoaded && cases.length === 0 && (
          <div className="p-8 text-center text-gray-500 bg-white rounded-lg shadow border border-gray-200">
            No cases found for this period.
          </div>
        )}

        {cases.length > 0 && (
          <div className="bg-white rounded-lg shadow border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-200 flex justify-between items-center flex-wrap gap-2">
              <p className="text-sm text-gray-600">
                <span className="font-semibold">{cases.length}</span> case
                {cases.length === 1 ? '' : 's'}
              </p>
              <div className="flex gap-2 text-xs">
                {(['OK', 'FLAGGED', 'UNRESOLVED', 'SCRAP'] as const).map(
                  (status) =>
                    counts[status] > 0 ? (
                      <span
                        key={status}
                        className={`px-2 py-1 rounded font-medium ${BADGE[status]}`}
                      >
                        {status}: {counts[status]}
                      </span>
                    ) : null
                )}
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200 text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Status
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Contract
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Student
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Application Status
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Institution
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Country
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Signed
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Course
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Visa
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Counsellor
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Case Officer
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr
                      key={c.id}
                      className={`${ROW_BG[c.import_status] ?? ''} border-b border-gray-100`}
                    >
                      <td className="px-3 py-2">
                        <span
                          className={`text-xs px-2 py-0.5 rounded font-medium ${BADGE[c.import_status] ?? 'bg-gray-200'}`}
                        >
                          {c.import_status}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {c.contract_id}
                      </td>
                      <td className="px-3 py-2">{c.student_name}</td>
                      <td className="px-3 py-2 text-xs">
                        {c.application_status}
                      </td>
                      <td className="px-3 py-2">
                        {c.institution_name ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {c.country_name ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs font-mono">
                        {c.contract_signed_date ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs font-mono">
                        {c.course_start_date ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs font-mono">
                        {c.visa_received_date ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {c.counsellor_name ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {c.case_officer_name ?? (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Submit-to-Engine footer */}
            <div className="border-t border-gray-200 bg-gray-50 px-4 py-4 flex flex-col gap-3">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="text-sm text-gray-600">
                  <span className="font-medium">Ready to calculate bonuses?</span>{' '}
                  This runs the engine for{' '}
                  <span className="font-semibold">
                    {year}-{String(month).padStart(2, '0')}
                  </span>{' '}
                  across <em>all</em> staff for this period.
                </div>
                <button
                  type="button"
                  onClick={handleSubmitToEngine}
                  disabled={submitting}
                  className={
                    'px-5 py-2 rounded text-white font-medium ' +
                    (submitting
                      ? 'bg-gray-400 cursor-not-allowed'
                      : 'bg-emerald-600 hover:bg-emerald-700')
                  }
                >
                  {submitting ? 'Running engine…' : 'Submit to Engine →'}
                </button>
              </div>

              {engineMessage && engineMessage.ok && (
                <div className="text-sm px-3 py-2 rounded border bg-emerald-50 border-emerald-200 text-emerald-800">
                  <div className="font-medium">Engine run complete.</div>
                  <div className="mt-1 text-xs">
                    Adapted {engineMessage.result.adapted}/
                    {engineMessage.result.total_cases} case(s),{' '}
                    {engineMessage.result.payment_count} payment row(s) written.
                    Net payable total:{' '}
                    <span className="font-semibold">
                      {fmtVnd(engineMessage.result.net_total)}
                    </span>
                    .
                    {engineMessage.result.skipped.length > 0 && (
                      <> Skipped: {engineMessage.result.skipped.length}.</>
                    )}
                    {engineMessage.result.errored.length > 0 && (
                      <>
                        {' '}
                        <span className="text-red-700 font-medium">
                          Errored: {engineMessage.result.errored.length}.
                        </span>
                      </>
                    )}
                  </div>
                  <div className="mt-1 text-emerald-700 text-xs">
                    Redirecting to the bonus report…
                  </div>
                </div>
              )}

              {engineMessage && !engineMessage.ok && (
                <div className="text-sm px-3 py-2 rounded border bg-red-50 border-red-200 text-red-700">
                  <div className="font-medium">Engine run failed.</div>
                  <div className="mt-1 font-mono text-xs whitespace-pre-wrap">
                    {engineMessage.detail}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
