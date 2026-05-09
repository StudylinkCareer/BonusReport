'use client';

/**
 * frontend/app/bonus/[year]/[month]/page.tsx
 *
 * Bonus Report view — reads tx_bonus_payment rows for a (year, month)
 * via /api/bonus and renders a sortable/filterable table with summary
 * tiles. Single-page client component for now (no server-side fetch).
 *
 * URL: /bonus/2024/11
 */

import { use, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';

type Payment = {
  id: number;
  case_id: number;
  slot: string;
  staff_id: number | null;
  staff_name: string | null;
  role_id: number | null;
  role_code: string | null;
  role_name: string | null;
  office_id: number | null;
  office_code: string | null;
  office_name: string | null;
  contract_id: string;
  student_name: string | null;
  application_status: string | null;
  course_status: string | null;
  institution_name: string | null;
  country_name: string | null;
  tier: string | null;
  target: number | null;
  actual_enrolled: number | null;
  base_rate: number;
  split_pct: string | null;
  tier_bonus: number;
  package_bonus: number;
  addon_bonus: number;
  priority_bonus: number;
  presales_share_taken: number;
  flat_local_enrolment_bonus: number;
  advance_offset: number;
  gross_bonus: number;
  net_payable: number;
  priority_withheld_amount: number;
  priority_unlocked_amount: number;
  priority_schedule_type: string;
  calc_notes: string | null;
};

const fmtVnd = (n: number | null | undefined) => {
  if (n == null) return '–';
  return n.toLocaleString('vi-VN') + ' đ';
};

const monthName = (m: number) =>
  ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1] ?? `M${m}`;

export default function BonusReportPage({
  params,
}: {
  params: Promise<{ year: string; month: string }>;
}) {
  const { year: yearStr, month: monthStr } = use(params);
  const year = parseInt(yearStr, 10);
  const month = parseInt(monthStr, 10);

  const [payments, setPayments] = useState<Payment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [staffFilter, setStaffFilter] = useState<string>('all');

  useEffect(() => {
    let cancelled = false;
    setPayments(null);
    setLoadError(null);
    fetch(`/api/bonus?year=${year}&month=${month}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Payment[]) => {
        if (!cancelled) setPayments(data);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [year, month]);

  // Distinct staff for filter (memoised so selecting doesn't re-sort)
  const staffOptions = useMemo(() => {
    if (!payments) return [];
    const map = new Map<number, string>();
    for (const p of payments) {
      if (p.staff_id != null) {
        map.set(p.staff_id, p.staff_name ?? `Staff ${p.staff_id}`);
      }
    }
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [payments]);

  if (loadError) {
    return (
      <main className="p-6 max-w-3xl">
        <Link href="/imports" className="text-sm text-blue-600 hover:underline">
          ← All imports
        </Link>
        <h1 className="text-xl font-semibold mt-2">Bonus Report — error</h1>
        <p className="text-red-600 mt-2">{loadError}</p>
        <p className="text-sm text-gray-600 mt-2">
          Make sure the engine has been run for this period (Submit to Engine
          on the import review page).
        </p>
      </main>
    );
  }

  if (!payments) {
    return (
      <main className="p-6">
        <p className="text-gray-600">Loading bonus report…</p>
      </main>
    );
  }

  // Apply filters
  const lowerFilter = filter.toLowerCase().trim();
  const filtered = payments.filter((p) => {
    if (staffFilter !== 'all' && String(p.staff_id) !== staffFilter) return false;
    if (lowerFilter) {
      const hay = [
        p.staff_name,
        p.contract_id,
        p.student_name,
        p.institution_name,
        p.role_code,
        p.slot,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (!hay.includes(lowerFilter)) return false;
    }
    return true;
  });

  const totalGross = filtered.reduce((a, p) => a + (p.gross_bonus ?? 0), 0);
  const totalNet = filtered.reduce((a, p) => a + (p.net_payable ?? 0), 0);
  const totalPriorityWithheld = filtered.reduce(
    (a, p) => a + (p.priority_withheld_amount ?? 0),
    0,
  );
  const distinctStaff = new Set(filtered.map((p) => p.staff_id)).size;
  const distinctContracts = new Set(filtered.map((p) => p.contract_id)).size;

  return (
    <main className="p-6 max-w-[1600px] mx-auto">
      <header className="flex items-center justify-between mb-4">
        <div>
          <Link href="/imports" className="text-sm text-blue-600 hover:underline">
            ← All imports
          </Link>
          <h1 className="text-2xl font-semibold mt-1">
            Bonus Report — {monthName(month)} {year}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={`/import/review?year=${year}&month=${month}`}
            className="text-sm text-blue-600 hover:underline"
          >
            ← Review imports
          </Link>
          <span className="text-sm text-gray-500">
            · {payments.length} row(s) total
          </span>
        </div>
      </header>

      {/* Summary tiles */}
      <section className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        <Stat label="Payments" value={filtered.length} />
        <Stat label="Staff" value={distinctStaff} />
        <Stat label="Contracts" value={distinctContracts} />
        <Stat label="Gross" value={fmtVnd(totalGross)} />
        <Stat label="Net payable" value={fmtVnd(totalNet)} highlight />
      </section>

      {/* Filters */}
      <section className="flex flex-wrap gap-3 mb-3 items-center">
        <input
          type="text"
          placeholder="Filter (staff, contract, student, institution…)"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm flex-1 min-w-[280px]"
        />
        <select
          value={staffFilter}
          onChange={(e) => setStaffFilter(e.target.value)}
          className="border rounded px-3 py-1.5 text-sm"
        >
          <option value="all">All staff ({staffOptions.length})</option>
          {staffOptions.map(([id, name]) => (
            <option key={id} value={String(id)}>
              {name}
            </option>
          ))}
        </select>
        {totalPriorityWithheld > 0 && (
          <span className="text-xs text-amber-700">
            Priority withheld in view: {fmtVnd(totalPriorityWithheld)}
          </span>
        )}
      </section>

      {/* Table */}
      <div className="overflow-x-auto border rounded">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50">
            <tr>
              <Th>Staff</Th>
              <Th>Contract</Th>
              <Th>Student</Th>
              <Th>Slot</Th>
              <Th>Role</Th>
              <Th>Institution</Th>
              <Th>Tier</Th>
              <Th right>Tgt / Act</Th>
              <Th right>Base</Th>
              <Th right>Split</Th>
              <Th right>Tier bonus</Th>
              <Th right>Priority</Th>
              <Th right>Package</Th>
              <Th right>Addon</Th>
              <Th right>Withheld</Th>
              <Th>Schedule</Th>
              <Th right>Gross</Th>
              <Th right>Net</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr key={p.id} className="border-t hover:bg-yellow-50/40">
                <Td>{p.staff_name ?? `#${p.staff_id}`}</Td>
                <Td className="font-mono">{p.contract_id}</Td>
                <Td>{p.student_name ?? '–'}</Td>
                <Td className="text-gray-600 lowercase">{p.slot}</Td>
                <Td>{p.role_code ?? '–'}</Td>
                <Td>{p.institution_name ?? '–'}</Td>
                <Td>{p.tier && <TierBadge tier={p.tier} />}</Td>
                <Td right className="text-gray-600">
                  {p.target ?? '–'} / {p.actual_enrolled ?? '–'}
                </Td>
                <Td right className="text-gray-600">{fmtVnd(p.base_rate)}</Td>
                <Td right className="text-gray-600">{p.split_pct ?? '–'}</Td>
                <Td right>{fmtVnd(p.tier_bonus)}</Td>
                <Td right>{p.priority_bonus ? fmtVnd(p.priority_bonus) : '–'}</Td>
                <Td right>{p.package_bonus ? fmtVnd(p.package_bonus) : '–'}</Td>
                <Td right>{p.addon_bonus ? fmtVnd(p.addon_bonus) : '–'}</Td>
                <Td right>
                  {p.priority_withheld_amount ? (
                    <span className="text-amber-700">
                      {fmtVnd(p.priority_withheld_amount)}
                    </span>
                  ) : (
                    '–'
                  )}
                </Td>
                <Td>
                  {p.priority_schedule_type !== 'STANDARD' && (
                    <span className="text-amber-700 text-[10px] font-medium">
                      {p.priority_schedule_type}
                    </span>
                  )}
                </Td>
                <Td right className="font-medium">{fmtVnd(p.gross_bonus)}</Td>
                <Td right className="font-semibold">{fmtVnd(p.net_payable)}</Td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={18} className="p-6 text-center text-gray-500">
                  No payment rows match the filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}

// ---------- helpers ---------------------------------------------------------

function Stat({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div
      className={`border rounded px-3 py-2 ${
        highlight ? 'bg-emerald-50 border-emerald-200' : 'bg-white'
      }`}
    >
      <div className="text-[11px] uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className={`text-lg font-semibold ${highlight ? 'text-emerald-700' : ''}`}>
        {value}
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
      className={`px-2 py-1.5 text-xs font-medium text-gray-700 whitespace-nowrap ${
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
}: {
  children: React.ReactNode;
  right?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`px-2 py-1 whitespace-nowrap ${right ? 'text-right' : ''} ${
        className ?? ''
      }`}
    >
      {children}
    </td>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const styles: Record<string, string> = {
    UNDER: 'bg-gray-100 text-gray-700',
    TARGET: 'bg-blue-100 text-blue-700',
    OVER: 'bg-emerald-100 text-emerald-700',
  };
  const cls = styles[tier] ?? 'bg-gray-100 text-gray-700';
  return (
    <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded ${cls}`}>
      {tier}
    </span>
  );
}
