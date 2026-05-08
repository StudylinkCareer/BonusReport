'use client';

import { useEffect, useState } from 'react';

const API_BASE = 'http://localhost:8000';

type Staff = {
  id: number;
  name: string;
  role_code: string;
  role_name: string;
  office_code: string;
  office_name: string;
};

type Payment = {
  payment_id: number;
  contract_id: string;
  student_name: string;
  application_status: string;
  institution_name: string | null;
  country_name: string | null;
  slot: string;
  tier: string;
  tier_bonus: number;
  priority_bonus: number;
  package_bonus: number;
  gross_bonus: number;
  net_payable: number;
  staff_name: string;
};

type PaymentResponse = {
  staff_id: number;
  year: number;
  month: number;
  payments: Payment[];
  totals: { gross: number; net: number };
};

export default function Home() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [staffId, setStaffId] = useState<number | ''>('');
  const [year, setYear] = useState(2025);
  const [month, setMonth] = useState(9);
  const [data, setData] = useState<PaymentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load staff list on mount
  useEffect(() => {
    fetch(`${API_BASE}/staff`)
      .then((r) => r.json())
      .then(setStaff)
      .catch((e) => setError(`Failed to load staff: ${e.message}`));
  }, []);

  async function load() {
    if (!staffId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `${API_BASE}/payments?staff_id=${staffId}&year=${year}&month=${month}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setData(d);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'unknown';
      setError(`Failed to load payments: ${msg}`);
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  const fmt = (n: number) => n.toLocaleString('en-US');

  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold mb-6 text-gray-900">
          StudyLink Bonus Report
        </h1>

        {/* Form */}
        <div className="bg-white rounded-lg shadow p-4 mb-6 flex gap-4 items-end flex-wrap">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Staff
            </label>
            <select
              value={staffId}
              onChange={(e) =>
                setStaffId(e.target.value ? Number(e.target.value) : '')
              }
              className="border border-gray-300 rounded px-3 py-2 min-w-[280px] bg-white text-gray-900"
            >
              <option value="">-- pick a staff member --</option>
              {staff.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.role_code} / {s.office_code})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Year
            </label>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              className="border border-gray-300 rounded px-3 py-2 w-24 bg-white text-gray-900"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Month
            </label>
            <input
              type="number"
              min={1}
              max={12}
              value={month}
              onChange={(e) => setMonth(Number(e.target.value))}
              className="border border-gray-300 rounded px-3 py-2 w-20 bg-white text-gray-900"
            />
          </div>
          <button
            onClick={load}
            disabled={!staffId || loading}
            className="bg-blue-600 text-white px-4 py-2 rounded font-medium hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
          >
            {loading ? 'Loading...' : 'Load'}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded mb-6">
            {error}
          </div>
        )}

        {/* Results */}
        {data && (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <div className="px-4 py-3 border-b bg-gray-50 flex justify-between text-sm text-gray-700">
              <span className="font-medium">
                {data.payments.length} payment rows
              </span>
              <span>
                Gross:{' '}
                <span className="font-mono font-medium">
                  {fmt(data.totals.gross)}
                </span>
                {' • '}
                Net:{' '}
                <span className="font-mono font-medium">
                  {fmt(data.totals.net)}
                </span>
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-100 text-left text-xs uppercase tracking-wider text-gray-600">
                  <tr>
                    <th className="px-3 py-2">Contract</th>
                    <th className="px-3 py-2">Student</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Institution</th>
                    <th className="px-3 py-2">Country</th>
                    <th className="px-3 py-2">Slot</th>
                    <th className="px-3 py-2">Tier</th>
                    <th className="px-3 py-2 text-right">Tier $</th>
                    <th className="px-3 py-2 text-right">Priority $</th>
                    <th className="px-3 py-2 text-right">Net $</th>
                  </tr>
                </thead>
                <tbody className="divide-y text-gray-900">
                  {data.payments.map((p) => (
                    <tr
                      key={p.payment_id}
                      className={p.net_payable === 0 ? 'text-gray-400' : ''}
                    >
                      <td className="px-3 py-2 font-mono">{p.contract_id}</td>
                      <td className="px-3 py-2">{p.student_name}</td>
                      <td className="px-3 py-2">{p.application_status}</td>
                      <td className="px-3 py-2">{p.institution_name ?? '—'}</td>
                      <td className="px-3 py-2">{p.country_name ?? '—'}</td>
                      <td className="px-3 py-2 text-xs">{p.slot}</td>
                      <td className="px-3 py-2 text-xs">{p.tier}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        {fmt(p.tier_bonus)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {fmt(p.priority_bonus)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-medium">
                        {fmt(p.net_payable)}
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
