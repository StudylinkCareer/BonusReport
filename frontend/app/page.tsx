"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

/* -------------------------------------------------------------------------
 * Types
 * ----------------------------------------------------------------------- */

type WorkflowState = "uploaded" | "in_review" | "submitted" | "closed";

interface PillarCounts {
  uploaded: number;
  in_review: number;
  submitted: number;
  closed: number;
  total: number;
}

/* -------------------------------------------------------------------------
 * Pillar metadata
 * ----------------------------------------------------------------------- */

interface PillarMeta {
  state: WorkflowState;
  title: string;
  blurb: string;
  href: string;
  accent: string;
  pill: string;
  border: string;
  dot: string;
}

const PILLARS: PillarMeta[] = [
  {
    state: "uploaded",
    title: "Uploaded",
    blurb: "Just imported. Needs to be picked up for review.",
    href: "/import/review?workflow_state=uploaded",
    accent: "bg-slate-50",
    pill: "bg-slate-100 text-slate-700",
    border: "border-slate-300",
    dot: "bg-slate-400",
  },
  {
    state: "in_review",
    title: "In Review",
    blurb: "Under review by case staff, Data Quality, and Finance.",
    href: "/import/review?workflow_state=in_review",
    accent: "bg-amber-50",
    pill: "bg-amber-100 text-amber-800",
    border: "border-amber-300",
    dot: "bg-amber-500",
  },
  {
    state: "submitted",
    title: "Submitted",
    blurb: "All review approvals collected. Ready for engine processing.",
    href: "/import/review?workflow_state=submitted",
    accent: "bg-sky-50",
    pill: "bg-sky-100 text-sky-800",
    border: "border-sky-300",
    dot: "bg-sky-500",
  },
  {
    state: "closed",
    title: "Closed",
    blurb: "Engine complete. Senior Manager review for payment release.",
    href: "/import/review?workflow_state=closed",
    accent: "bg-emerald-50",
    pill: "bg-emerald-100 text-emerald-800",
    border: "border-emerald-300",
    dot: "bg-emerald-500",
  },
];

/* -------------------------------------------------------------------------
 * Page
 * ----------------------------------------------------------------------- */

export default function HomePage() {
  const [counts, setCounts] = useState<PillarCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/pillars/counts")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
        return r.json() as Promise<PillarCounts>;
      })
      .then((d) => setCounts(d))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen bg-white">
      <Header />

      <div className="mx-auto max-w-7xl px-6 py-10">
        <PageIntro total={counts?.total ?? null} />

        {error && (
          <div className="mt-8 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            Failed to load case counts: {error}
          </div>
        )}

        <div className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {PILLARS.map((p) => (
            <PillarCard
              key={p.state}
              meta={p}
              count={counts ? counts[p.state] : null}
              loading={loading}
            />
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

function PageIntro({ total }: { total: number | null }) {
  return (
    <div className="flex items-end justify-between">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
          Case workflow
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          {total === null
            ? "Loading case counts…"
            : `${total.toLocaleString()} case${total === 1 ? "" : "s"} in the system.`}
        </p>
      </div>
    </div>
  );
}

function PillarCard({
  meta,
  count,
  loading,
}: {
  meta: PillarMeta;
  count: number | null;
  loading: boolean;
}) {
  return (
    <Link
      href={meta.href}
      className={`group relative flex flex-col rounded-xl border ${meta.border} ${meta.accent} px-5 py-5 transition hover:shadow-md`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${meta.pill}`}>
            {meta.title}
          </span>
        </div>
        <span className="text-xs text-slate-500 opacity-0 transition group-hover:opacity-100">
          View →
        </span>
      </div>

      <div className="mt-5">
        {loading ? (
          <div className="h-10 w-20 animate-pulse rounded bg-slate-200" />
        ) : (
          <div className="text-4xl font-semibold tracking-tight text-slate-900">
            {(count ?? 0).toLocaleString()}
          </div>
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
        <div className="text-sm font-medium text-slate-900">
          New cases to load?
        </div>
        <div className="text-sm text-slate-600">
          Upload a closed-file Excel report to add new cases to the Uploaded pillar.
        </div>
      </div>
      <Link
        href="/import"
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
      >
        Upload file
      </Link>
    </div>
  );
}
