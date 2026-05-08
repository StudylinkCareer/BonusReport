'use client';

import { useState, useEffect, FormEvent } from 'react';

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

export default function ReviewPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [staffId, setStaffId] = useState<number | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

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
          <a
            href="/import"
            className="text-sm text-blue-600 hover:underline"
          >
            ← Back to Importer
          </a>
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
          </div>
        )}
      </div>
    </main>
  );
}