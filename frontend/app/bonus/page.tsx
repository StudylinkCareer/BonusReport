'use client';

/**
 * SAVE TO: frontend/app/bonus/page.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\bonus\page.tsx)
 *
 * Bonus Reports index — lists every (year, month) period present in
 * tx_case, most-recent-first. Each row carries case/staff counts and
 * (when the engine has run) the total net payable.
 *
 * Click any row to open /bonus/{year}/{month} for the per-staff bao cao
 * view.
 *
 * Data: GET /api/bonus/periods
 */

import { useEffect, useState } from 'react';
import Link from 'next/link';

type Period = {
  run_year: number;
  run_month: number;
  case_count: number;
  staff_count: number;
  total_net_payable: number;
  has_engine_output: boolean;
};

const fmtVnd = (n: number) =>
  n > 0 ? n.toLocaleString('vi-VN') + ' đ' : '—';

const monthName = (m: number) =>
  ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1] ?? `M${m}`;

export default function BonusIndexPage() {
  const [periods, setPeriods] = useState<Period[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/bonus/periods')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Period[]) => setPeriods(data))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="mx-auto max-w-5xl p-6">
      <nav className="mb-4 text-sm text-gray-500">
        <Link href="/" className="hover:text-gray-900 hover:underline">
          ← Back to Case workflow
        </Link>
      </nav>

      <header className="mb-6">
        <h1 className="text-2xl font-bold">Bonus Reports</h1>
        <p className="mt-1 text-sm text-gray-600">
          Each period contains one bao cao per staff member with cases in
          that month. Click a row to open the per-staff view.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-red-800">
          <strong>Error:</strong> {error}
        </div>
      )}

      {!periods && !error && (
        <div className="py-12 text-center text-gray-500">Loading…</div>
      )}

      {periods && periods.length === 0 && (
        <div className="py-12 text-center text-gray-500">
          No periods yet. Upload some cases from{' '}
          <Link href="/import" className="text-blue-600 hover:underline">
            /import
          </Link>{' '}
          first.
        </div>
      )}

      {periods && periods.length > 0 && (
        <div className="overflow-hidden rounded border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="border-b border-gray-200 text-left">
                <th className="px-4 py-2 font-semibold">Period</th>
                <th className="px-4 py-2 font-semibold text-right">Cases</th>
                <th className="px-4 py-2 font-semibold text-right">Staff</th>
                <th className="px-4 py-2 font-semibold text-right">
                  Total net payable
                </th>
                <th className="px-4 py-2 font-semibold">Engine</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => (
                <tr
                  key={`${p.run_year}-${p.run_month}`}
                  className="border-b border-gray-100 hover:bg-blue-50"
                >
                  <td className="px-4 py-2">
                    <Link
                      href={`/bonus/${p.run_year}/${p.run_month}`}
                      className="font-medium text-blue-700 hover:underline"
                    >
                      {monthName(p.run_month)} {p.run_year}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right">{p.case_count}</td>
                  <td className="px-4 py-2 text-right">{p.staff_count}</td>
                  <td className="px-4 py-2 text-right">
                    {p.total_net_payable > 0 ? (
                      <span className="font-medium">{fmtVnd(p.total_net_payable)}</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {p.has_engine_output ? (
                      <span className="inline-block rounded border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-medium text-green-800">
                        run
                      </span>
                    ) : (
                      <span className="inline-block rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                        not yet
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link
                      href={`/bonus/${p.run_year}/${p.run_month}`}
                      className="text-blue-600 hover:underline text-xs"
                    >
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
