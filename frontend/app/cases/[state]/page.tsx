"use client";

/**
 * frontend/app/cases/[state]/page.tsx
 *
 * Pillar drill-down list view. Renders a list of cases at one workflow_state.
 * Reachable via the 4 pillar tiles on the home page.
 *
 * Routes:
 *   /cases/uploaded
 *   /cases/in_review
 *   /cases/submitted
 *   /cases/closed
 *
 * Data: GET /api/pillars/{state}/cases
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

/* -------------------------------------------------------------------------
 * Types
 * ----------------------------------------------------------------------- */

type WorkflowState = "uploaded" | "in_review" | "submitted" | "closed";

interface CaseRow {
  id: number;
  contract_id: string;
  student_name: string;
  application_status: string | null;
  import_status: string | null;
  workflow_state: WorkflowState;
  run_year: number;
  run_month: number;
  updated_at: string;
  institution_name: string | null;
  country_name: string | null;
  counsellor_name: string | null;
  case_officer_name: string | null;
  pre_sales_name: string | null;
}

interface ListResponse {
  state: WorkflowState;
  count: number;
  cases: CaseRow[];
}

/* -------------------------------------------------------------------------
 * Pillar metadata (must match home page colors)
 * ----------------------------------------------------------------------- */

const PILLAR_META: Record<
  WorkflowState,
  { title: string; chip: string; dot: string; bar: string }
> = {
  uploaded:   { title: "Uploaded",   chip: "bg-slate-100 text-slate-700",   dot: "bg-slate-400",   bar: "border-slate-300" },
  in_review:  { title: "In Review",  chip: "bg-amber-100 text-amber-800",   dot: "bg-amber-500",   bar: "border-amber-300" },
  submitted:  { title: "Submitted",  chip: "bg-sky-100 text-sky-800",       dot: "bg-sky-500",     bar: "border-sky-300" },
  closed:     { title: "Closed",     chip: "bg-emerald-100 text-emerald-800", dot: "bg-emerald-500", bar: "border-emerald-300" },
};

const VALID_STATES: WorkflowState[] = ["uploaded", "in_review", "submitted", "closed"];

function isValidState(s: string): s is WorkflowState {
  return (VALID_STATES as string[]).includes(s);
}

/* -------------------------------------------------------------------------
 * Page
 * ----------------------------------------------------------------------- */

export default function PillarCasesPage() {
  const params = useParams<{ state: string }>();
  const stateParam = params?.state ?? "";

  const [data, setData] = useState<ListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isValidState(stateParam)) {
      setError(`Unknown pillar: ${stateParam || ""}`);
      setLoading(false);
      return;
    }
    fetch(`/api/pillars/${stateParam}/cases`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
        return r.json() as Promise<ListResponse>;
      })
      .then((d) => setData(d))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
  }, [stateParam]);

  const meta = isValidState(stateParam) ? PILLAR_META[stateParam] : null;

  return (
    <main className="min-h-screen bg-white">
      <Header meta={meta} />

      <div className="mx-auto max-w-7xl px-6 py-8">
        <Breadcrumb stateLabel={meta?.title ?? stateParam} />

        <PageHeading meta={meta} count={data?.count ?? null} loading={loading} />

        {error && (
          <div className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </div>
        )}

        {loading ? (
          <SkeletonTable />
        ) : data && data.cases.length > 0 ? (
          <CasesTable rows={data.cases} />
        ) : !error ? (
          <EmptyState meta={meta} />
        ) : null}
      </div>
    </main>
  );
}

/* -------------------------------------------------------------------------
 * Header
 * ----------------------------------------------------------------------- */

function Header({ meta }: { meta: { bar: string } | null }) {
  return (
    <header className={`border-b ${meta?.bar ?? "border-slate-200"} bg-white`}>
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-md bg-slate-900" />
          <div>
            <div className="text-sm font-semibold tracking-tight text-slate-900">
              StudyLink Bonus
            </div>
            <div className="text-xs text-slate-500">Case workflow</div>
          </div>
        </div>
        <button
          className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          disabled
          title="Role switching not yet wired up"
        >
          Acting as: <span className="font-medium">Admin</span>
        </button>
      </div>
    </header>
  );
}

function Breadcrumb({ stateLabel }: { stateLabel: string }) {
  return (
    <nav className="text-sm text-slate-500">
      <Link href="/" className="hover:text-slate-900 hover:underline">Case workflow</Link>
      <span className="mx-2">/</span>
      <span className="text-slate-900">{stateLabel}</span>
    </nav>
  );
}

function PageHeading({
  meta,
  count,
  loading,
}: {
  meta: { title: string; chip: string; dot: string } | null;
  count: number | null;
  loading: boolean;
}) {
  return (
    <div className="mt-3 flex items-end justify-between">
      <div className="flex items-center gap-3">
        {meta && (
          <>
            <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} />
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
              {meta.title}
            </h1>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.chip}`}>
              {loading ? "…" : count === null ? "—" : `${count.toLocaleString()} case${count === 1 ? "" : "s"}`}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Cases table
 * ----------------------------------------------------------------------- */

function CasesTable({ rows }: { rows: CaseRow[] }) {
  return (
    <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <Th>Contract</Th>
            <Th>Student</Th>
            <Th>Application status</Th>
            <Th>Institution</Th>
            <Th>Country</Th>
            <Th>Staff</Th>
            <Th>Import</Th>
            <Th>Period</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-slate-50">
              <Td>
                <span className="font-mono text-xs font-medium text-slate-900">
                  {r.contract_id}
                </span>
              </Td>
              <Td>
                <span className="text-slate-900">{r.student_name}</span>
              </Td>
              <Td>
                <span className="text-slate-700">{r.application_status ?? "—"}</span>
              </Td>
              <Td>
                <span className="text-slate-700">{r.institution_name ?? "—"}</span>
              </Td>
              <Td>
                <span className="text-slate-700">{r.country_name ?? "—"}</span>
              </Td>
              <Td>
                <StaffPills
                  counsellor={r.counsellor_name}
                  caseOfficer={r.case_officer_name}
                  preSales={r.pre_sales_name}
                />
              </Td>
              <Td>
                <ImportStatusBadge status={r.import_status} />
              </Td>
              <Td>
                <span className="font-mono text-xs text-slate-500">
                  {r.run_year}-{String(r.run_month).padStart(2, "0")}
                </span>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2.5">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2.5 align-top">{children}</td>;
}

function StaffPills({
  counsellor,
  caseOfficer,
  preSales,
}: {
  counsellor: string | null;
  caseOfficer: string | null;
  preSales: string | null;
}) {
  const items: { letter: string; name: string; title: string }[] = [];
  if (counsellor) items.push({ letter: "C",  name: counsellor,  title: "Counsellor" });
  if (caseOfficer) items.push({ letter: "CO", name: caseOfficer, title: "Case Officer" });
  if (preSales) items.push({ letter: "PS", name: preSales,    title: "Pre-sales" });

  if (items.length === 0) return <span className="text-slate-400">—</span>;

  return (
    <div className="flex flex-col gap-1">
      {items.map((it, i) => (
        <div key={i} className="flex items-center gap-1.5" title={it.title}>
          <span className="inline-flex h-4 min-w-[1rem] items-center justify-center rounded bg-slate-200 px-1 text-[10px] font-semibold text-slate-700">
            {it.letter}
          </span>
          <span className="text-xs text-slate-700">{it.name}</span>
        </div>
      ))}
    </div>
  );
}

function ImportStatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-400">—</span>;
  const styles: Record<string, string> = {
    OK:          "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    UNRESOLVED:  "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    "WARN-MISMATCH": "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    SCRAP:       "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
    FLAGGED:     "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  };
  const cls = styles[status] ?? "bg-slate-50 text-slate-600 ring-1 ring-slate-200";
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>
      {status}
    </span>
  );
}

/* -------------------------------------------------------------------------
 * Loading / empty states
 * ----------------------------------------------------------------------- */

function SkeletonTable() {
  return (
    <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
      <div className="divide-y divide-slate-100">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 p-3">
            <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
            <div className="h-3 w-32 animate-pulse rounded bg-slate-200" />
            <div className="h-3 w-24 animate-pulse rounded bg-slate-200" />
            <div className="h-3 w-40 animate-pulse rounded bg-slate-200" />
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ meta }: { meta: { title: string } | null }) {
  return (
    <div className="mt-8 flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center">
      <div className="text-sm font-medium text-slate-900">
        No cases in {meta?.title ?? "this pillar"}.
      </div>
      <div className="mt-1 text-sm text-slate-600">
        When cases move to this stage, they&apos;ll appear here.
      </div>
      <Link
        href="/"
        className="mt-4 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
      >
        ← Back to case workflow
      </Link>
    </div>
  );
}
