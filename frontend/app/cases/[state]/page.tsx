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
 *
 * --- CHANGES IN THIS VERSION ---
 *  - Adds row-level selection (checkbox column + select-all header).
 *  - Adds a floating action bar shown when ≥1 case is selected.
 *  - Adds a Calculate Bonus action that:
 *      1. Groups selected case IDs by (staff_id, run_year, run_month)
 *         on the client, purely for the confirmation UI.
 *      2. Shows a confirmation modal listing the resulting batches and a
 *         warning that the engine will recalculate the *full* batch
 *         (not just the ticked cases) — see policy locked decision.
 *      3. On confirm, POSTs the selected case_ids to
 *         /api/engine/run, then shows a result modal and refreshes the
 *         data on close.
 *  - No styling changes to existing rows/columns. Period column was
 *    already present; left as-is.
 */

import { useEffect, useMemo, useState } from "react";
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
  /* staff_id is needed to group selected rows into engine batches.
     If your /api/pillars/{state}/cases endpoint doesn't return it
     today, add it server-side (see ENGINE_RUN_API_SPEC.md). */
  staff_id?: number | null;
}

interface ListResponse {
  state: WorkflowState;
  count: number;
  cases: CaseRow[];
}

/* Engine-run API contract — see ENGINE_RUN_API_SPEC.md */
interface RunBatchResult {
  staff_id: number;
  staff_name: string | null;
  year: number;
  month: number;
  cases_processed: number;
  rows_written: number;
  error?: string | null;
}

interface RunResponse {
  success: boolean;
  batches_run: number;
  cases_processed: number;
  rows_written: number;
  duration_seconds: number;
  batches: RunBatchResult[];
  error?: string | null;
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

/* States where running the engine makes sense.
   - uploaded / submitted: yes — fresh data, ready to compute.
   - in_review:           yes — useful for testing while editing.
   - closed:              no — bonus already paid; recalc happens via
                          dedicated re-run/override flow elsewhere. */
const RUNNABLE_STATES: Set<WorkflowState> = new Set([
  "uploaded",
  "in_review",
  "submitted",
]);

/* -------------------------------------------------------------------------
 * Page
 * ----------------------------------------------------------------------- */

export default function PillarCasesPage() {
  const params = useParams<{ state: string }>();
  const stateParam = params?.state ?? "";

  const [data, setData] = useState<ListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /* Selection + run state */
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<RunResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  /* tick a value to force the GET below to re-run (used after engine run) */
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    if (!isValidState(stateParam)) {
      setError(`Unknown pillar: ${stateParam || ""}`);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`/api/pillars/${stateParam}/cases`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
        return r.json() as Promise<ListResponse>;
      })
      .then((d) => setData(d))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
  }, [stateParam, refreshTick]);

  const meta = isValidState(stateParam) ? PILLAR_META[stateParam] : null;
  const showCalculate =
    isValidState(stateParam) && RUNNABLE_STATES.has(stateParam);

  /* Group selected cases by (staff_id, run_year, run_month) for the
     confirmation modal. Cases missing staff_id are bucketed into a
     synthetic 'unknown' batch so the user can see them — backend will
     reject these. */
  const selectedBatches = useMemo(() => {
    if (!data) return [];
    const byKey = new Map<
      string,
      {
        staff_id: number | null;
        year: number;
        month: number;
        case_ids: number[];
      }
    >();
    for (const row of data.cases) {
      if (!selectedIds.has(row.id)) continue;
      const sid = row.staff_id ?? null;
      const key = `${sid ?? "null"}|${row.run_year}|${row.run_month}`;
      const existing = byKey.get(key);
      if (existing) {
        existing.case_ids.push(row.id);
      } else {
        byKey.set(key, {
          staff_id: sid,
          year: row.run_year,
          month: row.run_month,
          case_ids: [row.id],
        });
      }
    }
    return Array.from(byKey.values()).sort((a, b) => {
      if (a.year !== b.year) return a.year - b.year;
      if (a.month !== b.month) return a.month - b.month;
      return (a.staff_id ?? 0) - (b.staff_id ?? 0);
    });
  }, [selectedIds, data]);

  /* Selection helpers */
  function toggleOne(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (!data) return;
    setSelectedIds((prev) => {
      if (prev.size === data.cases.length) return new Set();
      return new Set(data.cases.map((c) => c.id));
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function handleRun() {
    setRunning(true);
    setRunError(null);
    setRunResult(null);
    try {
      const res = await fetch("/api/engine/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_ids: Array.from(selectedIds) }),
      });
      const body = (await res.json().catch(() => ({}))) as
        | RunResponse
        | { detail?: string };
      if (!res.ok || (body as RunResponse).success === false) {
        const msg =
          (body as { detail?: string }).detail ??
          (body as RunResponse).error ??
          `HTTP ${res.status}`;
        throw new Error(msg);
      }
      setRunResult(body as RunResponse);
    } catch (e: unknown) {
      setRunError(String((e as Error).message ?? e));
    } finally {
      setRunning(false);
      setConfirmOpen(false);
    }
  }

  function dismissResult() {
    setRunResult(null);
    setRunError(null);
    clearSelection();
    /* Reload list so any state transitions (e.g. uploaded→closed) reflect */
    setRefreshTick((n) => n + 1);
  }

  /* -- Render -- */

  return (
    <main className="min-h-screen bg-white pb-32">
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
          <CasesTable
            rows={data.cases}
            selectedIds={selectedIds}
            onToggle={toggleOne}
            onToggleAll={toggleAll}
          />
        ) : !error ? (
          <EmptyState meta={meta} />
        ) : null}
      </div>

      {/* Floating action bar */}
      {showCalculate && selectedIds.size > 0 && (
        <FloatingActionBar
          count={selectedIds.size}
          batchCount={selectedBatches.length}
          onClear={clearSelection}
          onCalculate={() => setConfirmOpen(true)}
        />
      )}

      {/* Confirm modal */}
      {confirmOpen && (
        <ConfirmModal
          batches={selectedBatches}
          totalSelected={selectedIds.size}
          running={running}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={handleRun}
        />
      )}

      {/* Result modal */}
      {(runResult || runError) && !confirmOpen && (
        <ResultModal
          result={runResult}
          error={runError}
          onClose={dismissResult}
        />
      )}
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

function CasesTable({
  rows,
  selectedIds,
  onToggle,
  onToggleAll,
}: {
  rows: CaseRow[];
  selectedIds: Set<number>;
  onToggle: (id: number) => void;
  onToggleAll: () => void;
}) {
  const allChecked = rows.length > 0 && selectedIds.size === rows.length;
  const someChecked = selectedIds.size > 0 && !allChecked;

  return (
    <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <th className="w-10 px-3 py-2.5">
              <input
                type="checkbox"
                aria-label="Select all visible rows"
                checked={allChecked}
                ref={(el) => {
                  if (el) el.indeterminate = someChecked;
                }}
                onChange={onToggleAll}
                className="h-4 w-4 cursor-pointer rounded border-slate-300 text-sky-600 focus:ring-sky-500"
              />
            </th>
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
          {rows.map((r) => {
            const checked = selectedIds.has(r.id);
            return (
              <tr
                key={r.id}
                className={`hover:bg-slate-50 ${checked ? "bg-sky-50/40" : ""}`}
              >
                <td className="px-3 py-2.5 align-top">
                  <input
                    type="checkbox"
                    aria-label={`Select case ${r.contract_id}`}
                    checked={checked}
                    onChange={() => onToggle(r.id)}
                    className="h-4 w-4 cursor-pointer rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  />
                </td>
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
            );
          })}
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
 * Floating action bar
 * ----------------------------------------------------------------------- */

function FloatingActionBar({
  count,
  batchCount,
  onClear,
  onCalculate,
}: {
  count: number;
  batchCount: number;
  onClear: () => void;
  onCalculate: () => void;
}) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-6 py-3">
        <div className="text-sm text-slate-700">
          <span className="font-semibold text-slate-900">{count}</span>{" "}
          case{count === 1 ? "" : "s"} selected
          <span className="ml-2 text-slate-500">
            → {batchCount} batch{batchCount === 1 ? "" : "es"} to recalculate
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={onCalculate}
            className="rounded-md bg-sky-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-sky-700"
          >
            Calculate bonus →
          </button>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Confirm modal
 * ----------------------------------------------------------------------- */

function ConfirmModal({
  batches,
  totalSelected,
  running,
  onCancel,
  onConfirm,
}: {
  batches: {
    staff_id: number | null;
    year: number;
    month: number;
    case_ids: number[];
  }[];
  totalSelected: number;
  running: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const hasUnknownStaff = batches.some((b) => b.staff_id == null);

  return (
    <ModalShell onClose={running ? undefined : onCancel}>
      <h2 className="text-lg font-semibold text-slate-900">
        Confirm bonus calculation
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        You selected <span className="font-semibold">{totalSelected}</span>{" "}
        case{totalSelected === 1 ? "" : "s"} spanning{" "}
        <span className="font-semibold">{batches.length}</span> batch
        {batches.length === 1 ? "" : "es"}. The engine will recalculate{" "}
        <span className="font-semibold">every case</span> in each batch — not
        only the ones you ticked.
      </p>

      <div className="mt-4 max-h-64 overflow-y-auto rounded-md border border-slate-200">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Staff</th>
              <th className="px-3 py-2">Year</th>
              <th className="px-3 py-2">Month</th>
              <th className="px-3 py-2 text-right">Selected cases</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {batches.map((b, i) => (
              <tr key={i}>
                <td className="px-3 py-1.5">
                  {b.staff_id == null ? (
                    <span className="text-rose-600">staff_id missing</span>
                  ) : (
                    <span className="font-mono text-slate-700">
                      #{b.staff_id}
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5 font-mono text-slate-700">{b.year}</td>
                <td className="px-3 py-1.5 font-mono text-slate-700">
                  {String(b.month).padStart(2, "0")}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-slate-700">
                  {b.case_ids.length}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hasUnknownStaff && (
        <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
          One or more selected cases have no staff_id and will fail to run.
          Resolve them in import-review first.
        </div>
      )}

      <div className="mt-6 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={running}
          className="rounded-md border border-slate-200 bg-white px-4 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={running || hasUnknownStaff}
          className="rounded-md bg-sky-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-60"
        >
          {running ? "Running engine…" : "Run engine"}
        </button>
      </div>
    </ModalShell>
  );
}

/* -------------------------------------------------------------------------
 * Result modal
 * ----------------------------------------------------------------------- */

function ResultModal({
  result,
  error,
  onClose,
}: {
  result: RunResponse | null;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <ModalShell onClose={onClose}>
      {error ? (
        <>
          <h2 className="text-lg font-semibold text-rose-700">
            Engine run failed
          </h2>
          <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {error}
          </pre>
        </>
      ) : result ? (
        <>
          <h2 className="text-lg font-semibold text-emerald-700">
            Engine run complete
          </h2>
          <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
            <Stat label="Batches" value={result.batches_run} />
            <Stat label="Cases processed" value={result.cases_processed} />
            <Stat label="Rows written" value={result.rows_written} />
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Took {result.duration_seconds.toFixed(1)} s.
          </p>

          {result.batches.some((b) => b.error) && (
            <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Some batches reported errors — see breakdown below.
            </div>
          )}

          <div className="mt-4 max-h-56 overflow-y-auto rounded-md border border-slate-200">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Staff</th>
                  <th className="px-3 py-2">Period</th>
                  <th className="px-3 py-2 text-right">Cases</th>
                  <th className="px-3 py-2 text-right">Rows</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.batches.map((b, i) => (
                  <tr key={i}>
                    <td className="px-3 py-1.5 text-slate-700">
                      {b.staff_name ?? `#${b.staff_id}`}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-slate-700">
                      {b.year}-{String(b.month).padStart(2, "0")}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slate-700">
                      {b.cases_processed}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slate-700">
                      {b.rows_written}
                    </td>
                    <td className="px-3 py-1.5">
                      {b.error ? (
                        <span className="text-rose-700" title={b.error}>
                          error
                        </span>
                      ) : (
                        <span className="text-emerald-700">ok</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <div className="mt-6 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
        >
          Close
        </button>
      </div>
    </ModalShell>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="text-lg font-semibold text-slate-900">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Modal shell
 * ----------------------------------------------------------------------- */

function ModalShell({
  onClose,
  children,
}: {
  onClose?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 px-4"
      onClick={onClose ? () => onClose() : undefined}
    >
      <div
        className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
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
