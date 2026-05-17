"use client";

/**
 * SAVE TO: frontend/app/page.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\page.tsx)
 *
 * Case Workload — four-pillar home page with a filter bar above the tiles.
 *
 * Filter bar (Phase 4):
 *   - Staff: dropdown for review team; greyed-out current staff for staff role
 *   - Bonus Month: convenience picker (YYYY-MM expands to contract_signed_date range)
 *   - 3 date ranges: signed / course start / visa received
 *   - Wildcards: student (name OR id), contract id
 *   - Dropdowns: application status, client type, institution, office
 *   - Apply / Clear buttons
 *   - Filter state persists in URL (first) and localStorage (fallback)
 *
 * Pillar tile hrefs carry the active filter through to /import/review so the
 * Review Dashboard view matches the filter that produced the pillar count.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRole, PERSONAS } from "@/lib/role";
import {
  EMPTY_FILTERS,
  type Filters,
  filtersFromQuery,
  filtersToQuery,
  hasAnyFilter,
  loadFiltersFromStorage,
  saveFiltersToStorage,
  urlHasFilters,
} from "@/lib/filters";

type WorkflowState = "uploaded" | "in_review" | "submitted" | "closed";

interface PillarCounts {
  uploaded: number;
  in_review: number;
  submitted: number;
  closed: number;
  total: number;
}

type StaffOption = { id: number; name: string; employment_status?: string };
type RefList = { items: (string | { id: number; name?: string; code?: string })[] };

interface PillarMeta {
  state: WorkflowState;
  title: string;
  blurb: string;
  accent: string;
  pill: string;
  border: string;
  dot: string;
}

const PILLARS: PillarMeta[] = [
  { state: "uploaded",  title: "Uploaded",  blurb: "Just imported. Needs to be picked up for review.",
    accent: "bg-slate-50",   pill: "bg-slate-100 text-slate-700",   border: "border-slate-300",   dot: "bg-slate-400" },
  { state: "in_review", title: "In Review", blurb: "Under review by case staff, Data Quality, and Finance.",
    accent: "bg-amber-50",   pill: "bg-amber-100 text-amber-800",   border: "border-amber-300",   dot: "bg-amber-500" },
  { state: "submitted", title: "Submitted", blurb: "All review approvals collected. Engine has calculated bonus.",
    accent: "bg-sky-50",     pill: "bg-sky-100 text-sky-800",       border: "border-sky-300",     dot: "bg-sky-500" },
  { state: "closed",    title: "Closed",    blurb: "Engine complete. Senior Manager review for payment release.",
    accent: "bg-emerald-50", pill: "bg-emerald-100 text-emerald-800", border: "border-emerald-300", dot: "bg-emerald-500" },
];

export default function HomePage() {
  const [role] = useRole();

  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filtersReady, setFiltersReady] = useState(false);

  // First-load: URL wins; else localStorage; else empty. Role lock applies.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let next: Filters = urlHasFilters(params)
      ? filtersFromQuery(params)
      : loadFiltersFromStorage();
    if (role.kind === "staff") {
      next = { ...next, staffId: role.staffId };
    }
    setFilters(next);
    setFiltersReady(true);
  }, [role]);

  const [counts, setCounts] = useState<PillarCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!filtersReady) return;
    setLoading(true);
    const q = filtersToQuery(filters);
    const url = q.toString() ? `/api/pillars/counts?${q}` : `/api/pillars/counts`;
    fetch(url)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
        return r.json() as Promise<PillarCounts>;
      })
      .then((d) => { setCounts(d); setError(null); })
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
  }, [filters, filtersReady]);

  function applyFilters(next: Filters) {
    if (role.kind === "staff") next = { ...next, staffId: role.staffId };
    setFilters(next);
    saveFiltersToStorage(next);
    const q = filtersToQuery(next);
    const newUrl = q.toString() ? `?${q}` : window.location.pathname;
    window.history.replaceState(null, "", newUrl);
  }

  function clearFilters() {
    let cleared = EMPTY_FILTERS;
    if (role.kind === "staff") cleared = { ...cleared, staffId: role.staffId };
    applyFilters(cleared);
  }

  return (
    <main className="min-h-screen bg-white">
      <Header />
      <div className="mx-auto max-w-7xl px-6 py-8">
        <PageIntro total={counts?.total ?? null} loading={loading} />
        <FilterBar filters={filters} role={role} onApply={applyFilters} onClear={clearFilters} />
        {error && (
          <div className="mt-6 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            Failed to load case counts: {error}
          </div>
        )}
        <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {PILLARS.map((p) => (
            <PillarCard key={p.state} meta={p} count={counts ? counts[p.state] : null} loading={loading} filters={filters} />
          ))}
        </div>
        <UploadCallToAction />
      </div>
    </main>
  );
}

function Header() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-md bg-slate-900" />
          <div>
            <div className="text-sm font-semibold tracking-tight text-slate-900">StudyLink Bonus</div>
            <div className="text-xs text-slate-500">Case workflow</div>
          </div>
        </div>
        <nav className="flex items-center gap-2">
          <Link href="/import"  className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">Import Board</Link>
          <Link href="/imports" className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">Upload history</Link>
          <RoleSwitcher />
        </nav>
      </div>
    </header>
  );
}

function RoleSwitcher() {
  const [role, setRole] = useRole();
  const [staff, setStaff] = useState<StaffOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/reference/staff_all")
      .then((r) => r.json())
      .then((d) => {
        const items: StaffOption[] = d.items ?? [];
        setStaff(items.filter((s) => s.employment_status === "ACTIVE"));
      })
      .catch(() => setStaff([]))
      .finally(() => setLoading(false));
  }, []);

  // Encode the active role into a single string for the <select>:
  //   admin                → "admin"
  //   persona:director     → "p:director"
  //   staff (id=42)        → "s:42"
  const value =
    role.kind === "admin"
      ? "admin"
      : role.kind === "persona"
      ? `p:${role.personaCode}`
      : `s:${role.staffId}`;

  const onChange = (v: string) => {
    if (v === "admin") return setRole({ kind: "admin" });
    if (v.startsWith("p:")) {
      const code = v.slice(2);
      const p = PERSONAS.find((x) => x.code === code);
      if (p) setRole({ kind: "persona", personaCode: p.code, personaName: p.label });
      return;
    }
    if (v.startsWith("s:")) {
      const id = Number(v.slice(2));
      const found = staff.find((s) => s.id === id);
      if (found) setRole({ kind: "staff", staffId: found.id, staffName: found.name });
    }
  };

  return (
    <label className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700">
      <span className="text-slate-500">Acting as:</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={loading}
        className="border-none bg-transparent text-slate-900 font-medium focus:outline-none cursor-pointer">
        <option value="admin">Admin</option>
        <optgroup label="Roles">
          {PERSONAS.map((p) => (
            <option key={p.code} value={`p:${p.code}`}>{p.label}</option>
          ))}
        </optgroup>
        {staff.length > 0 && (
          <optgroup label="Staff">
            {staff.map((s) => <option key={s.id} value={`s:${s.id}`}>{s.name}</option>)}
          </optgroup>
        )}
      </select>
    </label>
  );
}

function PageIntro({ total, loading }: { total: number | null; loading: boolean }) {
  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Case Workload</h1>
      <p className="mt-1 text-sm text-slate-600">
        {loading ? "Loading case counts…" : total === null ? "—" :
          `${total.toLocaleString()} case${total === 1 ? "" : "s"} matching your filter.`}
      </p>
    </div>
  );
}

function FilterBar({
  filters, role, onApply, onClear,
}: {
  filters: Filters;
  role: ReturnType<typeof useRole>[0];
  onApply: (f: Filters) => void;
  onClear: () => void;
}) {
  const [draft, setDraft] = useState<Filters>(filters);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => { setDraft(filters); }, [filters]);

  const [staffList, setStaffList] = useState<StaffOption[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [clientTypes, setClientTypes] = useState<string[]>([]);
  const [institutions, setInstitutions] = useState<{ id: number; name: string }[]>([]);
  const [offices, setOffices] = useState<{ id: number; code: string }[]>([]);

  useEffect(() => {
    const pull = async (url: string) => {
      try {
        const r = await fetch(url);
        if (!r.ok) return null;
        return (await r.json()) as RefList;
      } catch { return null; }
    };
    pull("/api/reference/staff_all").then((d) => {
      if (!d) return;
      const items = (d.items ?? []) as StaffOption[];
      setStaffList(items.filter((s) => s.employment_status === "ACTIVE"));
    });
    pull("/api/reference/statuses").then((d) => {
      if (!d) return;
      setStatuses((d.items ?? []).map((x) => (typeof x === "string" ? x : x.name ?? "")).filter(Boolean));
    });
    pull("/api/reference/client_types").then((d) => {
      if (!d) return;
      setClientTypes((d.items ?? []).map((x) => (typeof x === "string" ? x : x.name ?? "")).filter(Boolean));
    });
    pull("/api/reference/institutions").then((d) => {
      if (!d) return;
      setInstitutions((d.items ?? []) as { id: number; name: string }[]);
    });
    pull("/api/reference/offices").then((d) => {
      if (!d) return;
      setOffices((d.items ?? []) as { id: number; code: string }[]);
    });
  }, []);

  const staffLocked = role.kind === "staff";

  const activeCount = useMemo(() => {
    let n = 0;
    if (filters.staffId !== null && !staffLocked) n++;
    if (filters.signedFrom || filters.signedTo) n++;
    if (filters.courseFrom || filters.courseTo) n++;
    if (filters.visaFrom   || filters.visaTo)   n++;
    if (filters.bonusMonth) n++;
    if (filters.qStudent)   n++;
    if (filters.qContract)  n++;
    if (filters.appStatus)  n++;
    if (filters.clientType) n++;
    if (filters.institutionId !== null) n++;
    if (filters.officeId      !== null) n++;
    return n;
  }, [filters, staffLocked]);

  return (
    <section className="mt-6 rounded-lg border border-slate-200 bg-slate-50/60">
      <header
        className="flex items-center justify-between px-4 py-3 cursor-pointer select-none"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="text-sm font-medium text-slate-900">
          Filter cases
          {activeCount > 0 && (
            <span className="ml-2 rounded-full bg-blue-100 text-blue-700 text-xs font-semibold px-2 py-0.5">
              {activeCount} active
            </span>
          )}
        </div>
        <button type="button" className="text-xs text-slate-500 hover:text-slate-900">
          {expanded ? "Collapse ▴" : "Expand ▾"}
        </button>
      </header>

      {expanded && (
        <div className="border-t border-slate-200 p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <Field label="Staff">
            <select
              value={draft.staffId === null ? "" : String(draft.staffId)}
              disabled={staffLocked}
              onChange={(e) => setDraft({ ...draft, staffId: e.target.value ? Number(e.target.value) : null })}
              className={`w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm ${staffLocked ? "bg-slate-100 text-slate-500 cursor-not-allowed" : ""}`}
            >
              <option value="">— Any staff —</option>
              {staffList.map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
            </select>
            {staffLocked && <p className="text-xs text-slate-500 mt-1">Locked to your account.</p>}
          </Field>

          <Field label="Bonus month (contract signed)">
            <input type="month" value={draft.bonusMonth}
              onChange={(e) => setDraft({ ...draft, bonusMonth: e.target.value })}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm" />
            <p className="text-xs text-slate-500 mt-1">Convenience: expands to that whole month.</p>
          </Field>

          <Field label="Student name or ID (wildcard)">
            <input type="text" value={draft.qStudent}
              onChange={(e) => setDraft({ ...draft, qStudent: e.target.value })}
              placeholder="e.g. Nguyen or SLC-1234"
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm" />
          </Field>

          <Field label="Contract ID (wildcard)">
            <input type="text" value={draft.qContract}
              onChange={(e) => setDraft({ ...draft, qContract: e.target.value })}
              placeholder="e.g. SLC-13"
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm" />
          </Field>

          <DateRange label="Contract signed"
            from={draft.signedFrom} to={draft.signedTo}
            onFrom={(v) => setDraft({ ...draft, signedFrom: v })}
            onTo={(v) => setDraft({ ...draft, signedTo: v })} />

          <DateRange label="Course start"
            from={draft.courseFrom} to={draft.courseTo}
            onFrom={(v) => setDraft({ ...draft, courseFrom: v })}
            onTo={(v) => setDraft({ ...draft, courseTo: v })} />

          <DateRange label="Visa received"
            from={draft.visaFrom} to={draft.visaTo}
            onFrom={(v) => setDraft({ ...draft, visaFrom: v })}
            onTo={(v) => setDraft({ ...draft, visaTo: v })} />

          <Field label="Application status">
            <select value={draft.appStatus}
              onChange={(e) => setDraft({ ...draft, appStatus: e.target.value })}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm">
              <option value="">— Any —</option>
              {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>

          <Field label="Client type">
            <select value={draft.clientType}
              onChange={(e) => setDraft({ ...draft, clientType: e.target.value })}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm">
              <option value="">— Any —</option>
              {clientTypes.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>

          <Field label="Institution">
            <select value={draft.institutionId === null ? "" : String(draft.institutionId)}
              onChange={(e) => setDraft({ ...draft, institutionId: e.target.value ? Number(e.target.value) : null })}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm">
              <option value="">— Any —</option>
              {institutions.map((i) => <option key={i.id} value={String(i.id)}>{i.name}</option>)}
            </select>
          </Field>

          <Field label="Office">
            <select value={draft.officeId === null ? "" : String(draft.officeId)}
              onChange={(e) => setDraft({ ...draft, officeId: e.target.value ? Number(e.target.value) : null })}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm">
              <option value="">— Any —</option>
              {offices.map((o) => <option key={o.id} value={String(o.id)}>{o.code}</option>)}
            </select>
          </Field>

          <div className="col-span-full flex items-center justify-end gap-2 mt-2">
            {hasAnyFilter(filters) && (
              <button onClick={onClear}
                className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-100">
                {staffLocked ? "Clear (keep my staff lock)" : "Clear all"}
              </button>
            )}
            <button onClick={() => onApply(draft)}
              className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
              Apply
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">{label}</label>
      {children}
    </div>
  );
}

function DateRange({
  label, from, to, onFrom, onTo,
}: { label: string; from: string; to: string; onFrom: (v: string) => void; onTo: (v: string) => void; }) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-1">
        <input type="date" value={from} onChange={(e) => onFrom(e.target.value)}
          className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm" />
        <span className="text-slate-400 text-xs">to</span>
        <input type="date" value={to} onChange={(e) => onTo(e.target.value)}
          className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm" />
      </div>
    </Field>
  );
}

function PillarCard({
  meta, count, loading, filters,
}: { meta: PillarMeta; count: number | null; loading: boolean; filters: Filters; }) {
  const q = filtersToQuery(filters);
  q.set("workflow_state", meta.state);
  const href = `/import/review?${q}`;

  return (
    <Link href={href}
      className={`group relative flex flex-col rounded-xl border ${meta.border} ${meta.accent} px-5 py-5 transition hover:shadow-md`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${meta.pill}`}>{meta.title}</span>
        </div>
        <span className="text-xs text-slate-500 opacity-0 transition group-hover:opacity-100">View →</span>
      </div>
      <div className="mt-5">
        {loading ? (
          <div className="h-10 w-20 animate-pulse rounded bg-slate-200" />
        ) : (
          <div className="text-4xl font-semibold tracking-tight text-slate-900">{(count ?? 0).toLocaleString()}</div>
        )}
        <div className="mt-2 text-sm text-slate-600">{meta.blurb}</div>
      </div>
    </Link>
  );
}

function UploadCallToAction() {
  return (
    <div className="mt-10 flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-6 py-5">
      <div>
        <div className="text-sm font-medium text-slate-900">New cases to load?</div>
        <div className="text-sm text-slate-600">Use the Import Board to upload Input sheets or Mass Upload files.</div>
      </div>
      <Link href="/import" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">
        Open Import Board
      </Link>
    </div>
  );
}
