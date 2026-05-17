'use client';

/**
 * SAVE TO: frontend/app/bonus/[year]/[month]/page.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\bonus\[year]\[month]\page.tsx)
 *
 * REPLACES the prior flat-table viewer. This is the per-staff bao cao
 * view — one report per staff member with cases in the period, switchable
 * via a dropdown at the top.
 *
 * Each staff's report:
 *   - Sub-header: "Báo cáo {name} — tháng {MM}/{YYYY}"
 *   - Sections grouped by application_status (bao cao layout order)
 *   - 21-column table per section, including BONUS Enrolled, Note BONUS
 *     Enrolled, BONUS Priority, Note BONUS Priority
 *   - Subtotal row at the bottom of each section
 *   - TỔNG block at the bottom: Enrolled + Priority + Grand total
 *
 * Data: GET /api/bonus/reports/{year}/{month}
 *
 * NOTE: Vietnamese justification notes are templated/approximate. To be
 * replaced by engine-emitted phrasing in a future phase.
 */

import { use, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';

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

const fmtVnd = (n: number) => (n ? n.toLocaleString('vi-VN') : '0');
const monthName = (m: number) =>
  ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1] ?? `M${m}`;

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

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    setSelectedStaffId(null);
    fetch(`/api/bonus/reports/${year}/${month}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: ReportData) => {
        if (cancelled) return;
        setData(d);
        if (d.staff_reports.length > 0) {
          setSelectedStaffId(d.staff_reports[0].staff_id);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [year, month]);

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
            <StaffBaoCao staff={selectedStaff} year={year} month={month} />
          )}
        </>
      )}
    </main>
  );
}

function StaffBaoCao({
  staff,
  year,
  month,
}: {
  staff: StaffReport;
  year: number;
  month: number;
}) {
  return (
    <section className="space-y-5">
      {/* Staff sub-header */}
      <div className="rounded border border-gray-200 bg-gray-50 px-4 py-3">
        <h2 className="text-lg font-semibold">
          Báo cáo {staff.staff_name} — tháng{' '}
          {String(month).padStart(2, '0')}/{year}
        </h2>
        <p className="text-xs text-gray-600">
          {staff.role_code ?? '—'}
          {staff.office_code ? ` · ${staff.office_code}` : ''}
        </p>
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
