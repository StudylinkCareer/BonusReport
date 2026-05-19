'use client';

/**
 * SAVE TO: frontend/app/import/review/page.tsx
 *
 * Imported-cases review screen. Two filter modes:
 *   - Period mode (legacy):       /import/review?staff_id=N&year=YYYY&month=M
 *   - Workflow-state mode (P15):  /import/review?workflow_state=uploaded.
 *
 * Every field that maps to a CRM column is inline-editable.
 *
 * Desktop view uses TanStack Table for sort / filter / resize / column reorder.
 * Mobile (<md) falls back to a card layout (unchanged).
 *
 * Edit flow:
 *   - Click a cell -> input/select/datepicker
 *   - Enter or blur saves via PATCH /api/cases/{id}
 *   - Escape cancels
 *   - Errors show inline beneath the cell, value reverts
 *
 * The "Submit to Engine" button (only in period mode) triggers POST /api/engine/run
 * for the WHOLE period and redirects to /bonus/{year}/{month}.
 */

import {
  CSSProperties,
  FormEvent,
  KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ColumnDef,
  ColumnFiltersState,
  ColumnOrderState,
  ColumnPinningState,
  ColumnSizingState,
  Header,
  RowSelectionState,
  SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import {
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  FloatingPortal,
  autoUpdate,
  flip,
  offset,
  shift,
  size,
  useDismiss,
  useFloating,
  useInteractions,
  useListNavigation,
} from '@floating-ui/react';
import {
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  GripVertical,
  Pin,
  PinOff,
} from 'lucide-react';
import { useRole, roleLabel, actingAsKey } from '@/lib/role';
import {
  filtersFromQuery,
  filtersToQuery,
  urlHasFilters,
  type Filters,
} from '@/lib/filters';
import { useRouter } from 'next/navigation';
import { BonusEstimateModal } from '@/app/_components/BonusEstimateModal';
import { CaseApprovalsModal } from '@/app/_components/CaseApprovalsModal';
import { CaseOverridesModal } from '@/app/_components/CaseOverridesModal';

// ===========================================================================
// Types
// ===========================================================================

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
  notes: string | null;
  run_year: number;
  run_month: number;

  institution_id: number | null;
  institution_name: string | null;
  institution_text_raw: string | null;

  country_id: number | null;
  country_name: string | null;

  case_office_id: number | null;
  case_office_code: string | null;

  referring_office_id: number | null;
  referring_office_code: string | null;

  referring_partner_id: number | null;
  referring_partner_name: string | null;
  referring_partner_classification: string | null;

  referring_sub_agent_id: number | null;
  referring_sub_agent_name: string | null;

  referring_agent_text_raw: string | null;
  referring_source_type: string | null;

  counsellor_staff_id: number | null;
  counsellor_name: string | null;
  counsellor_role_id: number | null;
  counsellor_role_code: string | null;

  case_officer_staff_id: number | null;
  case_officer_name: string | null;
  case_officer_role_id: number | null;
  case_officer_role_code: string | null;

  pre_sales_staff_id: number | null;
  pre_sales_name: string | null;

  // Phase 5 + v6.2 — Package (single-select) + new tx_case columns
  package_fee_id: number | null;
  package_code: string | null;
  package_label: string | null;
  package_payment_basis: string | null;
  service_review_pending: boolean;
  system_type: string | null;
  institution_type: string | null;
  targets_name: string | null;

  // Phase 5 — Services (multi-select via tx_case_service junction)
  services: CaseService[];

  // Phase 14 Block 4 / C — Per-slot management overrides
  calculated_at: string | null;          // engine-stamped when payments were written
  overrides: CaseOverrideSummary[];      // 0..3 rows mirroring slot staff

  // Phase 14 Block 5 Piece 5 — Bonus payment rows visible to this viewer.
  // The backend already filters these per viewer (admins see all rows;
  // non-admins see only rows where staff_id matches them). bonus_rows_total
  // is the unfiltered count, useful for "1 of 3 staff" badges without
  // leaking amounts.
  bonus_rows: CaseBonusRow[];
  bonus_rows_total: number;
};

type CaseBonusRow = {
  staff_id: number | null;
  staff_name: string | null;
  role_id: number | null;
  role_code: string | null;
  slot: string | null;
  // Raw engine-output components (all in đồng, as integers)
  tier: string | null;
  tier_bonus: number;
  package_bonus: number;
  addon_bonus: number;
  flat_local_enrolment_bonus: number;
  priority_bonus: number;
  priority_withheld_amount: number;
  priority_unlocked_amount: number;
  priority_schedule_type: string;
  presales_share_taken: number;
  advance_offset: number;
  gross_bonus: number;
  net_payable: number;
  mgmt_override_amount: number | null;
  // Computed convenience fields (backend SQL formula — see main.py)
  //   base_bonus = net_payable - priority_bonus - priority_unlocked_amount
  //   final_paid = net_payable + COALESCE(mgmt_override_amount, 0)
  base_bonus: number;
  final_paid: number;
  // Draft / published status — NULL published_at means the row is still
  // a draft (re-runnable). Set on Publish & Close.
  is_draft: boolean;
  published_at: string | null;
};

type CaseOverrideSummary = {
  id: number;
  staff_id: number;
  staff_name: string | null;
  amount: number;
  reason: string;
  created_at: string | null;
  updated_at: string | null;
};

type CaseService = {
  id: number;            // tx_case_service.id
  service_fee_id: number;
  service_code: string;
  service_label: string; // friendly label (description prefix or service_code)
  category: string;      // SERVICE_FEE | ADDON
  count: number;
  bonus_event: string;
  confirmed: boolean;
  detection_source: string | null;
};

type RefItem = {
  id: number;
  name?: string;
  code?: string;
  classification?: string;
  primary_role_id?: number | null;
  employment_status?: string | null;
  category?: string | null;             // for service_codes (SERVICE_FEE | ADDON)
  counsellor_signing_bonus?: number;    // for service_codes / package_codes
  co_signing_bonus?: number;
  bonus_payment_basis?: string | null;
};

type RefData = {
  institutions: RefItem[];
  sub_agents: RefItem[];
  partners: RefItem[];
  offices: RefItem[];
  countries: RefItem[];
  staff_all: RefItem[];
  statuses: RefItem[];
  source_types: string[];
  import_statuses: string[];
  client_types: string[];
  course_statuses: string[];
  // Phase 5 + v6.2 — new reference lists
  service_codes: RefItem[];      // SERVICE_FEE + ADDON for multi-select
  package_codes: RefItem[];      // PACKAGE for single-select
  deferral_codes: string[];      // v6.2 col 21
  system_types: string[];        // v6.2 col 9
  institution_types: string[];   // v6.2 col 28
  bonus_events: string[];        // tx_case_service.bonus_event
  presales_agents: string[];     // v6.2 col 17 (curated 7-value list incl NONE)
};

const EMPTY_REF: RefData = {
  institutions: [],
  sub_agents: [],
  partners: [],
  offices: [],
  countries: [],
  staff_all: [],
  statuses: [],
  source_types: [],
  import_statuses: [],
  client_types: [],
  course_statuses: [],
  service_codes: [],
  package_codes: [],
  deferral_codes: [],
  system_types: [],
  institution_types: [],
  bonus_events: [],
  presales_agents: [],
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

type SourceType = 'DIRECT' | 'SUB_AGENT' | 'MASTER_AGENT' | 'GROUP' | 'OFFICE';

// ===========================================================================
// Constants & helpers
// ===========================================================================

const ROW_BG: Record<string, string> = {
  OK: 'bg-green-50',
  FLAGGED: 'bg-amber-50',
  UNRESOLVED: 'bg-red-50',
  SCRAP: 'bg-gray-100 opacity-70',
};

const STICKY_BG: Record<string, string> = {
  OK: 'bg-green-50',
  FLAGGED: 'bg-amber-50',
  UNRESOLVED: 'bg-red-50',
  SCRAP: 'bg-gray-100',
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

// ===========================================================================
// Page
// ===========================================================================

export default function ReviewPage() {
  const router = useRouter();

  // --- Filter / data state -------------------------------------------------
  const [staff, setStaff] = useState<Staff[]>([]);
  const [staffId, setStaffId] = useState<number | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [workflowState, setWorkflowState] = useState<string | null>(null);  // Phase 15: pillar-view mode
  const [role] = useRole();
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  // --- Reference data ------------------------------------------------------
  const [refData, setRefData] = useState<RefData>(EMPTY_REF);
  const [refReady, setRefReady] = useState(false);
  const [refError, setRefError] = useState<string | null>(null);

  // --- Submit to Engine state ---------------------------------------------
  const [submitting, setSubmitting] = useState(false);
  const [engineMessage, setEngineMessage] = useState<
    | { ok: true; result: EngineResult }
    | { ok: false; detail: string }
    | null
  >(null);

  // --- Load staff list on mount -------------------------------------------
  useEffect(() => {
    fetch('/api/staff')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setStaff)
      .catch((e) => setError(`Failed to load staff list: ${e}`));
  }, []);

  // --- Load reference data once on mount (parallel) -----------------------
  useEffect(() => {
    let cancelled = false;
    async function loadRef() {
      const lists = [
        'institutions',
        'sub_agents',
        'partners',
        'offices',
        'countries',
        'staff_all',
        'statuses',
        'source_types',
        'import_statuses',
        'client_types',
        'course_statuses',
        // Phase 5 + v6.2
        'service_codes',
        'package_codes',
        'deferral_codes',
        'system_types',
        'institution_types',
        'bonus_events',
        'presales_agents',
      ];
      try {
        const results = await Promise.all(
          lists.map((name) =>
            fetch(`/api/reference/${name}`).then((r) =>
              r.ok ? r.json() : Promise.reject(`${name}: HTTP ${r.status}`),
            ),
          ),
        );
        if (cancelled) return;
        const next: RefData = { ...EMPTY_REF };
        for (let i = 0; i < lists.length; i++) {
          const name = lists[i] as keyof RefData;
          (next as Record<string, unknown>)[name] = results[i].items;
        }
        setRefData(next);
        setRefReady(true);
      } catch (e) {
        if (!cancelled) setRefError(String(e));
      }
    }
    loadRef();
    return () => {
      cancelled = true;
    };
  }, []);

  // --- URL params bootstrap -----------------------------------------------
  // Two filter modes supported:
  //   - workflow_state mode (Phase 15 pillar drill-down): /import/review?workflow_state=uploaded
  //     PLUS optional Case Workload filter bar params (signed_from etc.) which
  //     get passed straight through to /api/cases so the Review Dashboard view
  //     matches the filter that produced the pillar drill-down.
  //   - legacy period mode: /import/review?staff_id=N&year=YYYY&month=M
  const [carriedFilters, setCarriedFilters] = useState<Filters | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const wState = params.get('workflow_state');
    const sid = params.get('staff_id');
    const y = params.get('year');
    const m = params.get('month');
    const yNum = y ? Number(y) : null;
    const mNum = m ? Number(m) : null;
    if (yNum && Number.isFinite(yNum)) setYear(yNum);
    if (mNum && Number.isFinite(mNum)) setMonth(mNum);

    if (wState) {
      setWorkflowState(wState);
      // Parse Case Workload filters from the URL (if any)
      const filters = urlHasFilters(params) ? filtersFromQuery(params) : null;
      setCarriedFilters(filters);
      loadCasesByWorkflowState(wState, filters);
    } else if (sid && yNum && mNum) {
      const sidNum = Number(sid);
      setStaffId(sidNum);
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
      const res = await fetch(`/api/cases?staff_id=${sid}&year=${y}&month=${m}`);
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

  async function loadCasesByWorkflowState(state: string, filters?: Filters | null) {
    setLoading(true);
    setError(null);
    setCases([]);
    setEngineMessage(null);
    try {
      // Compose URL: workflow_state + any carried filters from Case Workload
      const q = filters ? filtersToQuery(filters) : new URLSearchParams();
      q.set('workflow_state', state);
      const res = await fetch(`/api/cases?${q}`);
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
    const url = `/import/review?staff_id=${staffId}&year=${year}&month=${month}`;
    window.history.replaceState({}, '', url);
    loadCases(staffId, year, month);
  }

  // --- Cell save handler --------------------------------------------------
  // PATCHes one or more fields on one case and updates the row in state.
  //
  // Defensive: after a 200 response, verify that every requested field is
  // actually reflected in the returned Case. If not, the backend has
  // silently dropped the update (a known failure mode — certain rows
  // refuse edits without flagging an error). We throw so the cell rolls
  // back its optimistic state and surfaces an error tooltip, rather than
  // letting the cell quietly revert to "—" with no explanation.
  const saveCase = useCallback(
    async (caseId: number, updates: Record<string, unknown>) => {
      const r = await fetch(`/api/cases/${caseId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (!r.ok) {
        let detail: string;
        try {
          const body = await r.json();
          detail = body.detail ?? `HTTP ${r.status}`;
        } catch {
          detail = `HTTP ${r.status}`;
        }
        throw new Error(detail);
      }
      const updated = (await r.json()) as Case;

      // Detect silent rejections — request says X, response says not-X.
      // Only validate scalar fields (string | number | null | boolean). Skip
      // arrays/objects (those are handled by dedicated endpoints anyway).
      const mismatches: string[] = [];
      for (const [key, expected] of Object.entries(updates)) {
        if (
          expected !== null &&
          typeof expected !== 'string' &&
          typeof expected !== 'number' &&
          typeof expected !== 'boolean'
        ) {
          continue;
        }
        const actual = (updated as unknown as Record<string, unknown>)[key];
        if (actual !== expected) {
          mismatches.push(
            `${key}: sent ${JSON.stringify(expected)}, server returned ${JSON.stringify(actual)}`,
          );
        }
      }
      if (mismatches.length > 0) {
        // The backend's PATCH response sometimes returns a stale snapshot of
        // the case — the database is correctly updated, but the response
        // body reflects the pre-update state (a missing db.refresh() after
        // commit on the FastAPI side, or similar). User-visible behaviour:
        // refresh the page and the new value is there. So we don't block
        // the UI; we just leave a diagnostic line in DevTools so this can
        // be tracked down server-side later.
        console.warn(
          '[saveCase] PATCH response did not reflect the request for case',
          caseId,
          '. Patch body:',
          updates,
          'Response body:',
          updated,
          'Mismatches:',
          mismatches,
          '(Optimistic UI will keep the picked value; verify on next page load.)',
        );
      }

      setCases((prev) => prev.map((c) => (c.id === caseId ? updated : c)));
    },
    [],
  );

  // Phase 5 — bulk-replace the services list for a case. The API replaces
  // the full set (idempotent), so we just send what the UI has.
  const saveServices = useCallback(
    async (
      caseId: number,
      newList: Array<{ service_fee_id: number; count: number; bonus_event: string }>,
      clearReview: boolean,
    ) => {
      const r = await fetch(`/api/cases/${caseId}/services`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          services: newList,
          clear_review: clearReview,
        }),
      });
      if (!r.ok) {
        let detail: string;
        try {
          const body = await r.json();
          detail = body.detail ?? `HTTP ${r.status}`;
        } catch {
          detail = `HTTP ${r.status}`;
        }
        throw new Error(detail);
      }
      const result = (await r.json()) as {
        case_id: number;
        services: CaseService[];
        service_review_pending: boolean;
      };
      // Patch the case in place — only services + review flag have changed.
      setCases((prev) =>
        prev.map((c) =>
          c.id === caseId
            ? {
                ...c,
                services: result.services,
                service_review_pending: result.service_review_pending,
              }
            : c,
        ),
      );
    },
    [],
  );

  // --- Submit-to-engine handler ------------------------------------------
  async function handleSubmitToEngine() {
    const confirmed = window.confirm(
      `Run the engine for ${year}-${String(month).padStart(2, '0')}?\n\n` +
        `Important: this runs the engine for the WHOLE PERIOD (every staff ` +
        `member's cases), not just the staff you're currently viewing.\n\n` +
        `It will:\n` +
        `  • DELETE all existing bonus payments for this period\n` +
        `  • Re-calculate from imported tx_case rows\n` +
        `  • Write fresh tx_bonus_payment rows\n\n` +
        `It is idempotent — you can re-run safely.`,
    );
    if (!confirmed) return;

    setSubmitting(true);
    setEngineMessage(null);
    try {
      const r = await fetch('/api/engine/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ year, month, persist: true }),
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
      setTimeout(() => router.push(`/bonus/${year}/${month}`), 1500);
    } catch (err) {
      setEngineMessage({ ok: false, detail: `Network error: ${String(err)}` });
      setSubmitting(false);
    }
  }

  // --- Counts for badges --------------------------------------------------
  const counts = useMemo(
    () => ({
      OK: cases.filter((c) => c.import_status === 'OK').length,
      FLAGGED: cases.filter((c) => c.import_status === 'FLAGGED').length,
      UNRESOLVED: cases.filter((c) => c.import_status === 'UNRESOLVED').length,
      SCRAP: cases.filter((c) => c.import_status === 'SCRAP').length,
    }),
    [cases],
  );

  // --- Pre-selected case IDs based on "acting as" role ---------------------
  // When acting as a Staff member, their own cases (where they're the
  // counsellor, case officer, or pre-sales) are pre-ticked so they only
  // need to confirm. When acting as Admin, nothing is pre-ticked.
  // Only applies in workflow_state pillar mode (not legacy period mode).
  const preselectedIds = useMemo<Set<number>>(() => {
    if (!workflowState || role.kind !== 'staff') return new Set();
    const result = new Set<number>();
    for (const c of cases) {
      if (
        c.counsellor_staff_id === role.staffId ||
        c.case_officer_staff_id === role.staffId ||
        c.pre_sales_staff_id === role.staffId
      ) {
        result.add(c.id);
      }
    }
    return result;
  }, [cases, role, workflowState]);

  // ----------------------------------------------------------------------
  // Title metadata for the workflow_state header banner.
  const PILLAR_TITLES: Record<string, { label: string; chip: string; dot: string }> = {
    uploaded:  { label: 'Uploaded',  chip: 'bg-slate-100 text-slate-700',   dot: 'bg-slate-400' },
    in_review: { label: 'In Review', chip: 'bg-amber-100 text-amber-800',   dot: 'bg-amber-500' },
    submitted: { label: 'Submitted', chip: 'bg-sky-100 text-sky-800',       dot: 'bg-sky-500' },
    closed:    { label: 'Closed',    chip: 'bg-emerald-100 text-emerald-800', dot: 'bg-emerald-500' },
  };
  const pillarMeta = workflowState ? PILLAR_TITLES[workflowState] : null;

  return (
    <main className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-[1800px] mx-auto">
        <div className="flex items-baseline justify-between mb-6 flex-wrap gap-3">
          <div>
            {workflowState ? (
              <>
                <nav className="text-sm text-gray-500 mb-2">
                  <a href="/" className="hover:text-gray-900 hover:underline">Case workflow</a>
                  <span className="mx-2">/</span>
                  <span className="text-gray-900">{pillarMeta?.label ?? workflowState}</span>
                </nav>
                <div className="flex items-center gap-3">
                  {pillarMeta && <span className={`h-2.5 w-2.5 rounded-full ${pillarMeta.dot}`} />}
                  <h1 className="text-2xl md:text-3xl font-bold">
                    {pillarMeta?.label ?? workflowState}
                  </h1>
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${pillarMeta?.chip ?? 'bg-gray-100 text-gray-700'}`}>
                    {loading ? '…' : `${cases.length} case${cases.length === 1 ? '' : 's'}`}
                  </span>
                </div>
                <p className="text-gray-600 mt-1 text-sm">
                  Click any cell to edit. Saves on Enter or blur. Esc cancels.{' '}
                  <span className="ml-1 text-xs text-gray-500">
                    Acting as: <span className="font-medium text-gray-700">{roleLabel(role)}</span>
                    {role.kind === 'staff' && preselectedIds.size > 0 && (
                      <> · {preselectedIds.size} of your case{preselectedIds.size === 1 ? '' : 's'} pre-selected</>
                    )}
                  </span>
                </p>
              </>
            ) : (
              <>
                <h1 className="text-2xl md:text-3xl font-bold">Imported Cases — Review</h1>
                <p className="text-gray-600 mt-1 text-sm">
                  Click any cell to edit. Saves on Enter or blur. Esc cancels.
                </p>
              </>
            )}
          </div>
          <div className="flex items-center gap-4">
            {!workflowState && (
              <a
                href={`/bonus/${year}/${month}`}
                className="text-sm text-blue-600 hover:underline"
              >
                View bonus report →
              </a>
            )}
            {workflowState === 'closed' && (
              <a
                href="/bonus"
                className="text-sm text-blue-600 hover:underline"
              >
                Bonus Reports →
              </a>
            )}
            {workflowState ? (
              <a href="/" className="text-sm text-blue-600 hover:underline">
                ← Back to Case workflow
              </a>
            ) : (
              <a href="/imports" className="text-sm text-blue-600 hover:underline">
                ← Back to Importer
              </a>
            )}
          </div>
        </div>

        {/* Filter form — hidden when in workflow_state mode */}
        {!workflowState && (
        <form
          onSubmit={handleSubmit}
          className="flex flex-wrap gap-3 items-end bg-white p-4 rounded-lg shadow border border-gray-200 mb-4"
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
        )}

        {refError && (
          <div className="mb-4 p-3 bg-amber-50 border border-amber-300 rounded text-sm text-amber-800">
            <strong>Reference data warning:</strong> {refError}
            <br />
            Some dropdowns may not populate; reload the page to retry.
          </div>
        )}

        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded">
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
            {/* Status counts header */}
            <div className="px-4 py-3 border-b border-gray-200 flex justify-between items-center flex-wrap gap-2">
              <p className="text-sm text-gray-600">
                <span className="font-semibold">{cases.length}</span> case
                {cases.length === 1 ? '' : 's'}
                {!refReady && (
                  <span className="ml-2 text-amber-700 text-xs">
                    (loading reference data…)
                  </span>
                )}
              </p>
              <div className="flex gap-2 text-xs">
                {(['OK', 'FLAGGED', 'UNRESOLVED', 'SCRAP'] as const).map((status) =>
                  counts[status] > 0 ? (
                    <span
                      key={status}
                      className={`px-2 py-1 rounded font-medium ${BADGE[status]}`}
                    >
                      {status}: {counts[status]}
                    </span>
                  ) : null,
                )}
              </div>
            </div>

            {/* Desktop table */}
            <div className="hidden md:block">
              <CasesTable
                cases={cases}
                refData={refData}
                onSave={saveCase}
                saveServices={saveServices}
                workflowState={workflowState}
                preselectedIds={preselectedIds}
                onTransitioned={() => {
                  if (workflowState) loadCasesByWorkflowState(workflowState, carriedFilters);
                }}
                actingAs={actingAsKey(role)}
              />
            </div>

            {/* Mobile cards */}
            <div className="md:hidden divide-y divide-gray-200">
              {cases.map((c) => (
                <CaseCard
                  key={c.id}
                  caseRow={c}
                  refData={refData}
                  onSave={saveCase}
                  saveServices={saveServices}
                />
              ))}
            </div>

            {/* Submit-to-Engine footer (period mode only — engine runs are period-scoped) */}
            {!workflowState && (
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
            )}
          </div>
        )}
      </div>
    </main>
  );
}

// ===========================================================================
// Desktop table view
// ===========================================================================

type CommonProps = {
  refData: RefData;
  onSave: (caseId: number, updates: Record<string, unknown>) => Promise<void>;
  // Phase 5 — bulk-replace services (and optionally clear review banner)
  saveServices: (
    caseId: number,
    newList: Array<{ service_fee_id: number; count: number; bonus_event: string }>,
    clearReview: boolean,
  ) => Promise<void>;
};

// Fixed widths (px) for the three sticky columns. Cumulative lefts must
// match the running total so columns butt up perfectly with no gap.
const STICKY_W = { status: 140, contract: 130, student: 220 } as const;
const STICKY_L = {
  status: 0,
  contract: STICKY_W.status,
  student: STICKY_W.status + STICKY_W.contract,
} as const;

// ===========================================================================
// Header cell components — used by <CasesTable />'s <thead>
// ===========================================================================
//
// Two flavours:
//   - SortableHeaderCell: a non-pinned column. Becomes a @dnd-kit sortable
//     item with a GripVertical drag handle. The handle is the only thing
//     that initiates a drag, so clicks elsewhere on the header (e.g. the
//     sort button) still work normally.
//   - PinnedHeaderCell: a pinned column. Renders sticky via
//     `header.column.getStart('left')` — no drag handle, no sortable
//     wrapping. Shows a small Pin icon to indicate pinned state.
//
// Both delegate the right-click menu to a callback supplied by CasesTable.

type HeaderContextMenuState = {
  x: number;
  y: number;
  columnId: string;
} | null;

function SortableHeaderCell({
  header,
  onContextMenu,
}: {
  header: Header<Case, unknown>;
  onContextMenu: (e: ReactMouseEvent, columnId: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: header.column.id });

  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    position: isDragging ? 'relative' : undefined,
    zIndex: isDragging ? 10 : undefined,
    width: header.getSize(),
  };

  return (
    <th
      ref={setNodeRef}
      style={style}
      className="border-b border-r border-gray-200 px-3 py-2 text-left font-semibold text-gray-700 align-bottom relative group"
      onContextMenu={(e) => onContextMenu(e, header.column.id)}
    >
      <div className="flex items-center gap-1">
        {/* Drag handle — only thing that starts a drag */}
        <span
          {...attributes}
          {...listeners}
          className="opacity-0 group-hover:opacity-100 transition cursor-grab active:cursor-grabbing touch-none text-gray-400 hover:text-gray-900 -ml-1"
          title="Drag to reorder column"
          aria-label="Drag to reorder column"
        >
          <GripVertical className="h-3.5 w-3.5" strokeWidth={2} />
        </span>
        {/* Sort button */}
        <button
          type="button"
          onClick={header.column.getToggleSortingHandler()}
          className="flex-1 text-left truncate hover:text-gray-900"
          title="Click to sort. Right-click for pin options."
        >
          {flexRender(header.column.columnDef.header, header.getContext())}
          <SortIndicator dir={header.column.getIsSorted()} />
        </button>
      </div>
      {/* Filter input */}
      <input
        type="text"
        value={(header.column.getFilterValue() as string) ?? ''}
        onChange={(e) => header.column.setFilterValue(e.target.value)}
        placeholder="Filter…"
        className="mt-1 w-full text-xs font-normal normal-case px-1.5 py-0.5 border border-gray-200 rounded focus:outline-none focus:border-blue-400"
      />
      {/* Resize handle */}
      {header.column.getCanResize() && (
        <div
          onMouseDown={header.getResizeHandler()}
          onTouchStart={header.getResizeHandler()}
          className={`absolute top-0 right-0 h-full w-1 cursor-col-resize select-none touch-none ${
            header.column.getIsResizing()
              ? 'bg-blue-500'
              : 'bg-transparent hover:bg-blue-300'
          }`}
        />
      )}
    </th>
  );
}

function PinnedHeaderCell({
  header,
  onContextMenu,
}: {
  header: Header<Case, unknown>;
  onContextMenu: (e: ReactMouseEvent, columnId: string) => void;
}) {
  const pinned = header.column.getIsPinned();
  const leftOffset =
    pinned === 'left' ? header.column.getStart('left') : undefined;
  const rightOffset =
    pinned === 'right' ? header.column.getAfter('right') : undefined;

  const style: CSSProperties = {
    position: 'sticky',
    left: leftOffset,
    right: rightOffset,
    zIndex: 30,
    background: '#F9FAFB', // gray-50
    width: header.getSize(),
  };

  return (
    <th
      style={style}
      className="border-b border-r border-gray-200 px-3 py-2 text-left font-semibold text-gray-700 align-bottom relative group"
      onContextMenu={(e) => onContextMenu(e, header.column.id)}
    >
      <div className="flex items-center gap-1">
        <Pin
          className="h-3 w-3 text-blue-500 shrink-0"
          strokeWidth={2.5}
          aria-label="Pinned column"
        />
        <button
          type="button"
          onClick={header.column.getToggleSortingHandler()}
          className="flex-1 text-left truncate hover:text-gray-900"
          title="Click to sort. Right-click for pin options."
        >
          {flexRender(header.column.columnDef.header, header.getContext())}
          <SortIndicator dir={header.column.getIsSorted()} />
        </button>
      </div>
      {/* Filter input — pinned columns can still filter */}
      {header.column.getCanFilter() && (
        <input
          type="text"
          value={(header.column.getFilterValue() as string) ?? ''}
          onChange={(e) => header.column.setFilterValue(e.target.value)}
          placeholder="Filter…"
          className="mt-1 w-full text-xs font-normal normal-case px-1.5 py-0.5 border border-gray-200 rounded focus:outline-none focus:border-blue-400"
        />
      )}
    </th>
  );
}

// ---- Right-click context menu for column pin operations ------------------
function HeaderPinMenu({
  menu,
  pinnedState,
  onClose,
  onPinLeft,
  onPinRight,
  onUnpin,
  onResetAll,
}: {
  menu: HeaderContextMenuState;
  pinnedState: 'left' | 'right' | false;
  onClose: () => void;
  onPinLeft: () => void;
  onPinRight: () => void;
  onUnpin: () => void;
  onResetAll: () => void;
}) {
  const { refs, floatingStyles, context } = useFloating({
    open: !!menu,
    onOpenChange: (o) => {
      if (!o) onClose();
    },
    placement: 'right-start',
    middleware: [offset(2), flip({ padding: 8 }), shift({ padding: 8 })],
    whileElementsMounted: autoUpdate,
  });

  const dismiss = useDismiss(context, { outsidePress: true, escapeKey: true });
  const { getFloatingProps } = useInteractions([dismiss]);

  useEffect(() => {
    if (menu) {
      refs.setReference({
        getBoundingClientRect: () => ({
          width: 0,
          height: 0,
          x: menu.x,
          y: menu.y,
          left: menu.x,
          top: menu.y,
          right: menu.x,
          bottom: menu.y,
        }),
      });
    }
    // refs is stable; only re-run when the menu coordinates change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu?.x, menu?.y]);

  if (!menu) return null;

  return (
    <FloatingPortal>
      <div
        ref={refs.setFloating}
        style={{ ...floatingStyles, zIndex: 1100 }}
        className="bg-white border border-gray-300 rounded-md shadow-lg py-1 text-sm min-w-[170px]"
        {...getFloatingProps()}
      >
        <PinMenuItem
          icon={<Pin className="h-3.5 w-3.5" />}
          label="Pin to left"
          disabled={pinnedState === 'left'}
          onClick={onPinLeft}
        />
        <PinMenuItem
          icon={<Pin className="h-3.5 w-3.5 rotate-180" />}
          label="Pin to right"
          disabled={pinnedState === 'right'}
          onClick={onPinRight}
        />
        <PinMenuItem
          icon={<PinOff className="h-3.5 w-3.5" />}
          label="Unpin"
          disabled={!pinnedState}
          onClick={onUnpin}
        />
        <div className="border-t border-gray-100 my-1" />
        <PinMenuItem icon={null} label="Reset all pins" onClick={onResetAll} />
      </div>
    </FloatingPortal>
  );
}

function PinMenuItem({
  icon,
  label,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed disabled:hover:bg-transparent"
    >
      <span className="w-4 flex items-center justify-center text-gray-500">
        {icon}
      </span>
      <span>{label}</span>
    </button>
  );
}

// ============================================================================
// VariantSwitcher — Phase 17a UI for saved column layouts
// ============================================================================
//
// A toolbar widget that lets the operator save, recall, and delete named
// layouts of the case table (column order, pinning, sizing, sort). Variants
// are scoped by (acting_as, page_key='import_review'). The one marked
// is_default loads automatically when the page mounts for that role.

type LayoutJson = {
  columnOrder?: ColumnOrderState;
  columnPinning?: { left?: string[]; right?: string[] };
  columnSizing?: ColumnSizingState;
  sorting?: SortingState;
};

type VariantRow = {
  id: number;
  acting_as: string;
  page_key: string;
  variant_name: string;
  is_default: boolean;
  layout_json: LayoutJson;
  created_at: string;
  updated_at: string;
};

function VariantSwitcher({
  actingAs,
  pageKey,
  columnOrder,
  columnPinning,
  columnSizing,
  sorting,
  setColumnOrder,
  setColumnPinning,
  setColumnSizing,
  setSorting,
}: {
  actingAs: string;
  pageKey: string;
  columnOrder: ColumnOrderState;
  columnPinning: ColumnPinningState;
  columnSizing: ColumnSizingState;
  sorting: SortingState;
  setColumnOrder: (next: ColumnOrderState) => void;
  setColumnPinning: (next: ColumnPinningState) => void;
  setColumnSizing: (next: ColumnSizingState) => void;
  setSorting: (next: SortingState) => void;
}) {
  const [variants, setVariants] = useState<VariantRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const initialAppliedRef = useRef(false);

  // Apply a serialized layout to the table state.
  const applyLayout = useCallback(
    (layout: LayoutJson) => {
      if (layout.columnOrder)  setColumnOrder(layout.columnOrder);
      if (layout.columnPinning) {
        setColumnPinning({
          left:  layout.columnPinning.left  ?? [],
          right: layout.columnPinning.right ?? [],
        });
      }
      if (layout.columnSizing) setColumnSizing(layout.columnSizing);
      if (layout.sorting)      setSorting(layout.sorting);
    },
    [setColumnOrder, setColumnPinning, setColumnSizing, setSorting],
  );

  // Snapshot the current table state into a LayoutJson blob.
  const currentLayout = useCallback(
    (): LayoutJson => ({
      columnOrder,
      columnPinning: {
        left:  columnPinning.left  ?? [],
        right: columnPinning.right ?? [],
      },
      columnSizing,
      sorting,
    }),
    [columnOrder, columnPinning, columnSizing, sorting],
  );

  // Fetch variants whenever the acting role or page changes.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    initialAppliedRef.current = false;
    const qs = new URLSearchParams({ acting_as: actingAs, page_key: pageKey });
    fetch(`/api/user_layout?${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: { items: VariantRow[] }) => {
        if (cancelled) return;
        setVariants(data.items);
        if (!initialAppliedRef.current) {
          const def = data.items.find((v) => v.is_default);
          if (def) {
            applyLayout(def.layout_json);
            setSelectedId(def.id);
          } else {
            setSelectedId(null);
          }
          initialAppliedRef.current = true;
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  // applyLayout deliberately omitted — it's stable across renders thanks to
  // useCallback, and including it would cause the layout-state update inside
  // applyLayout to retrigger the fetch in a loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actingAs, pageKey]);

  function onSelectVariant(id: number) {
    const v = variants.find((x) => x.id === id);
    if (!v) return;
    applyLayout(v.layout_json);
    setSelectedId(id);
  }

  async function onSaveCurrent() {
    if (selectedId === null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/user_layout/${selectedId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout_json: currentLayout() }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const updated: VariantRow = await r.json();
      setVariants((vs) => vs.map((v) => (v.id === updated.id ? updated : v)));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveAsNew() {
    const suggested = `Variant ${variants.length + 1}`;
    const name = window.prompt('Name for this layout:', suggested);
    if (!name) return;
    if (variants.some((v) => v.variant_name === name)) {
      setError(`A variant named "${name}" already exists.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await fetch('/api/user_layout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          acting_as:    actingAs,
          page_key:     pageKey,
          variant_name: name,
          is_default:   variants.length === 0, // first variant → auto-default
          layout_json:  currentLayout(),
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const created: VariantRow = await r.json();
      setVariants((vs) => [...vs, created].sort((a, b) =>
        Number(b.is_default) - Number(a.is_default) ||
        a.variant_name.localeCompare(b.variant_name),
      ));
      setSelectedId(created.id);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function onSetDefault() {
    if (selectedId === null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/user_layout/${selectedId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_default: true }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      // Only one default per (acting_as, page_key) — clear the flag on the
      // others locally too so the UI matches.
      setVariants((vs) =>
        vs.map((v) => ({ ...v, is_default: v.id === selectedId })),
      );
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (selectedId === null) return;
    const v = variants.find((x) => x.id === selectedId);
    if (!v) return;
    if (!window.confirm(`Delete variant "${v.variant_name}"?`)) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`/api/user_layout/${selectedId}`, {
        method: 'DELETE',
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      setVariants((vs) => vs.filter((x) => x.id !== selectedId));
      setSelectedId(null);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  const currentVariant =
    selectedId !== null ? variants.find((v) => v.id === selectedId) : null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-500">Layout:</span>
      <select
        value={selectedId ?? ''}
        onChange={(e) => {
          const v = e.target.value;
          if (v === '') {
            setSelectedId(null);
          } else {
            onSelectVariant(Number(v));
          }
        }}
        disabled={busy}
        className="rounded border border-gray-300 bg-white px-2 py-1 text-xs"
        title="Switch to a saved layout variant"
      >
        <option value="">(ad hoc)</option>
        {variants.map((v) => (
          <option key={v.id} value={v.id}>
            {v.variant_name}
            {v.is_default ? ' ★' : ''}
          </option>
        ))}
      </select>
      {currentVariant && (
        <button
          onClick={onSaveCurrent}
          disabled={busy}
          className="rounded border border-gray-300 bg-white px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50"
          title={`Overwrite "${currentVariant.variant_name}" with the current view`}
        >
          Save
        </button>
      )}
      <button
        onClick={onSaveAsNew}
        disabled={busy}
        className="rounded border border-gray-300 bg-white px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50"
        title="Save current view as a new variant"
      >
        Save as…
      </button>
      {currentVariant && !currentVariant.is_default && (
        <button
          onClick={onSetDefault}
          disabled={busy}
          className="rounded border border-gray-300 bg-white px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50"
          title="Load this variant by default for this role"
        >
          Make default
        </button>
      )}
      {currentVariant && (
        <button
          onClick={onDelete}
          disabled={busy}
          className="rounded border border-red-300 bg-white px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
          title="Delete this variant"
        >
          Delete
        </button>
      )}
      {error && (
        <span className="text-xs text-red-700" title={error}>
          {error.length > 60 ? error.slice(0, 57) + '…' : error}
        </span>
      )}
    </div>
  );
}


function CasesTable({
  cases,
  refData,
  onSave,
  saveServices,
  workflowState,
  preselectedIds,
  onTransitioned,
  actingAs,
}: {
  cases: Case[];
  workflowState: string | null;
  preselectedIds: Set<number>;
  onTransitioned: () => void;
  actingAs: string;
} & CommonProps) {
  // ---- column ordering ------------------------------------------------
  // Pinned (sticky) columns always stay leftmost: select (when shown),
  // import_status, contract_id, student_name. Reordering only applies to
  // unpinned columns.
  const showSelect =
    workflowState === 'uploaded' ||
    workflowState === 'in_review' ||
    workflowState === 'submitted';

  // Default left-pinned columns. The user can change this at runtime via
  // the header right-click menu (Pin to left / Unpin). Stored in TanStack's
  // `ColumnPinningState`, so pin offsets are computed natively via
  // `header.column.getStart('left')` rather than a hardcoded lookup table.
  const DEFAULT_PINNED_LEFT = showSelect
    ? ['select', 'import_status', 'contract_id', 'student_name']
    : ['import_status', 'contract_id', 'student_name'];
  const DEFAULT_ORDER = showSelect
    ? [
        'select',
        'import_status',
        'contract_id',
        'student_name',
        'student_id',
        'contract_signed_date',
        'client_type_code',
        'package',         // Phase 5
        'services',        // Phase 5
        'country',
        'system_type',     // v6.2
        'refer_source',
        'application_status',
        'visa_received_date',
        'institution',
        'institution_type', // v6.2
        'course_start_date',
        'course_status',
        'counsellor',
        'case_officer',
        'pre_sales',
        'office',
        'deferral_code',   // v6.2
        'targets_name',    // v6.2
        'notes',
      ]
    : [
        'import_status',
        'contract_id',
        'student_name',
        'student_id',
        'contract_signed_date',
        'client_type_code',
        'package',
        'services',
        'country',
        'system_type',
        'refer_source',
        'application_status',
        'visa_received_date',
        'institution',
        'institution_type',
        'course_start_date',
        'course_status',
        'counsellor',
        'case_officer',
        'pre_sales',
        'office',
        'deferral_code',
        'targets_name',
        'notes',
      ];

  // Persisted view-state — these only affect the local table, never the DB.
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(DEFAULT_ORDER);
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({});
  const [columnPinning, setColumnPinning] = useState<ColumnPinningState>({
    left: DEFAULT_PINNED_LEFT,
    right: [],
  });

  // Row selection (only used in workflow_state / pillar mode).
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [transitioning, setTransitioning] = useState(false);
  // Bonus-estimate modal (P14 Block 3) — open when set to a case id.
  const [estimateModalCaseId, setEstimateModalCaseId] = useState<number | null>(null);
  // Approvals modal (P14 Block 3 / B) — open when set to a case id.
  const [approvalsModalCaseId, setApprovalsModalCaseId] = useState<number | null>(null);
  // Overrides modal (P14 Block 4 / C) — open when set to a case id.
  const [overridesModalCaseId, setOverridesModalCaseId] = useState<number | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  // Calculate flow (only used on workflow_state === 'submitted').
  // bulkCalculate posts case_ids to the engine, then transitions them to
  // 'closed' on success. Result message stays visible until next selection
  // change or another action.
  const [calculating, setCalculating] = useState(false);
  const [calculateError, setCalculateError] = useState<string | null>(null);
  const [calculateMessage, setCalculateMessage] = useState<
    | { ok: true; payment_count: number; net_total: number; skipped: number; errored: number }
    | null
  >(null);

  // Finalize flow (Phase 14 Block 4 / C) — Submitted+Calculated → Closed.
  // Decoupled from Calculate so the user can review overrides between the
  // two steps.
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [finalizeMessage, setFinalizeMessage] = useState<
    | { ok: true; count: number }
    | null
  >(null);

  // When preselectedIds changes (e.g. role switched, or cases reloaded after
  // a transition), reset the selection to the new pre-selected set. This
  // wipes any manual edits the user made — acceptable trade-off.
  // We track the preselected set as a stable key so equal-but-new sets
  // don't trigger spurious resets.
  const preselectKey = useMemo(
    () => Array.from(preselectedIds).sort((a, b) => a - b).join(','),
    [preselectedIds],
  );
  useEffect(() => {
    const next: RowSelectionState = {};
    preselectedIds.forEach((id) => {
      next[String(id)] = true;
    });
    setRowSelection(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectKey]);

  // ---- column definitions --------------------------------------------
  // Each column declares: id, header label, optional accessor for sort/filter,
  // size (px), and the cell renderer (which reuses the existing TextCell / SelectCell
  // / FkCell / StaffCell / DateCell / TextAreaCell / ReferSourceCell components).
  const columns = useMemo<ColumnDef<Case>[]>(
    () => [
      // Select column (only present in workflow_state / pillar mode)
      ...(showSelect
        ? [
            {
              id: 'select',
              size: 44,
              minSize: 44,
              enableSorting: false,
              enableColumnFilter: false,
              enableResizing: false,
              header: ({ table }) => (
                <input
                  type="checkbox"
                  className="cursor-pointer"
                  checked={table.getIsAllRowsSelected()}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate =
                        table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected();
                    }
                  }}
                  onChange={table.getToggleAllRowsSelectedHandler()}
                  aria-label="Select all cases"
                />
              ),
              cell: ({ row }) => (
                <input
                  type="checkbox"
                  className="cursor-pointer"
                  checked={row.getIsSelected()}
                  onChange={row.getToggleSelectedHandler()}
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`Select case ${row.original.contract_id ?? row.original.id}`}
                />
              ),
            } as ColumnDef<Case>,
          ]
        : []),
      // Estimate-bonus column (P14 Block 3) — only on the In Review pillar.
      // Each row gets a small button that opens BonusEstimateModal.
      ...(workflowState === 'in_review'
        ? [
            {
              id: 'estimate',
              size: 90,
              minSize: 90,
              enableSorting: false,
              enableColumnFilter: false,
              enableResizing: false,
              header: () => (
                <span className="text-xs text-gray-600">Bonus</span>
              ),
              cell: ({ row }) => (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setEstimateModalCaseId(row.original.id);
                  }}
                  className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                  title="Preview the bonus this case would generate"
                >
                  💰 Estimate
                </button>
              ),
            } as ColumnDef<Case>,
          ]
        : []),
      // Approvals column (P14 Block 3 / B) — only on the In Review pillar.
      // Click opens CaseApprovalsModal.
      ...(workflowState === 'in_review'
        ? [
            {
              id: 'approvals',
              size: 90,
              minSize: 90,
              enableSorting: false,
              enableColumnFilter: false,
              enableResizing: false,
              header: () => (
                <span className="text-xs text-gray-600">Approvals</span>
              ),
              cell: ({ row }) => (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setApprovalsModalCaseId(row.original.id);
                  }}
                  className="rounded bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
                  title="View approval status for this case"
                >
                  👥 Approvals
                </button>
              ),
            } as ColumnDef<Case>,
          ]
        : []),
      // Overrides column (P14 Block 4 / C) — only on the Submitted pillar.
      // Shows a count + signed total (or "Add" if empty) and opens the
      // CaseOverridesModal on click.
      ...(workflowState === 'submitted'
        ? [
            {
              id: 'overrides',
              size: 130,
              minSize: 110,
              enableSorting: false,
              enableColumnFilter: false,
              enableResizing: false,
              header: () => (
                <span className="text-xs text-gray-600">Overrides</span>
              ),
              cell: ({ row }) => {
                const c = row.original;
                const n = c.overrides?.length ?? 0;
                const total = (c.overrides ?? []).reduce(
                  (a, o) => a + (o.amount ?? 0),
                  0,
                );
                return (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setOverridesModalCaseId(c.id);
                    }}
                    className={`rounded px-2 py-0.5 text-xs font-medium ${
                      n === 0
                        ? 'bg-gray-50 text-gray-600 hover:bg-gray-100'
                        : total < 0
                        ? 'bg-rose-50 text-rose-700 hover:bg-rose-100'
                        : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                    }`}
                    title={
                      n === 0
                        ? 'No overrides set — click to add'
                        : `${n} override(s), total ${fmtVnd(total)}`
                    }
                  >
                    {n === 0 ? '＋ Override' : `⚖ ${n} · ${fmtVnd(total)}`}
                  </button>
                );
              },
            } as ColumnDef<Case>,
          ]
        : []),
      // Bonus columns (P14 Block 5 / B2) — only on the Submitted pillar,
      // populated from the per-viewer-filtered `bonus_rows` array.
      //   - 0 rows visible → "—"
      //   - 1 row visible  → the value
      //   - 2+ rows visible → "N · total" (admin viewing multi-staff case;
      //     click-to-expand modal lands in B3)
      // Drafts vs published are not distinguished visually here; the B3
      // breakdown modal surfaces that. All four columns sum across the
      // viewer's visible rows so each cell answers "what bonus, total,
      // does this case represent for me?"
      ...(workflowState === 'submitted'
        ? (
            // Helper: render one of the four bonus cells. Same logic each
            // time, only the value-extractor differs.
            (() => {
              function makeBonusColumn(
                id: string,
                label: string,
                tooltipNoun: string,
                getValue: (r: CaseBonusRow) => number,
              ): ColumnDef<Case> {
                return {
                  id,
                  size: 110,
                  minSize: 90,
                  enableSorting: false,
                  enableColumnFilter: false,
                  enableResizing: false,
                  header: () => (
                    <span className="text-xs text-gray-600">{label}</span>
                  ),
                  cell: ({ row }) => {
                    const c = row.original;
                    const rows = c.bonus_rows ?? [];
                    const n = rows.length;
                    const total = rows.reduce((a, r) => a + (getValue(r) ?? 0), 0);
                    const totalAll = c.bonus_rows_total ?? n;
                    const anyDraft = rows.some((r) => r.is_draft);

                    if (n === 0) {
                      return <span className="text-xs text-gray-400">—</span>;
                    }
                    if (n === 1) {
                      return (
                        <span
                          className={`text-xs ${
                            anyDraft ? 'text-gray-700 italic' : 'text-gray-900'
                          }`}
                          title={`${tooltipNoun} for ${rows[0].staff_name ?? 'this staff'}${
                            anyDraft ? ' (draft — not yet published)' : ''
                          }`}
                        >
                          {fmtVnd(total)}
                        </span>
                      );
                    }
                    return (
                      <span
                        className={`text-xs ${
                          anyDraft ? 'text-gray-700 italic' : 'text-gray-900'
                        }`}
                        title={
                          `${tooltipNoun} across ${n} staff (of ${totalAll} on case): ` +
                          rows
                            .map(
                              (r) =>
                                `${r.staff_name ?? '?'} ${fmtVnd(getValue(r))}`,
                            )
                            .join(', ') +
                          (anyDraft ? ' — draft, not yet published' : '')
                        }
                      >
                        {n} · {fmtVnd(total)}
                      </span>
                    );
                  },
                } as ColumnDef<Case>;
              }

              return [
                makeBonusColumn(
                  'bonus_base',
                  'Base',
                  'Base bonus (enrolment + package + services, no priority)',
                  (r) => r.base_bonus,
                ),
                makeBonusColumn(
                  'bonus_override',
                  'Δ Override',
                  'Engine-applied management override',
                  (r) => r.mgmt_override_amount ?? 0,
                ),
                makeBonusColumn(
                  'bonus_priority',
                  'Priority',
                  'Priority partner bonus paid this run',
                  (r) => r.priority_bonus,
                ),
                makeBonusColumn(
                  'bonus_total',
                  'Total',
                  'Total bonus (net_payable + applied override)',
                  (r) => r.final_paid,
                ),
              ];
            })()
          )
        : []),
      {
        id: 'import_status',
        header: 'Status',
        accessorFn: (row) => row.import_status ?? '',
        size: STICKY_W.status,
        minSize: 100,
        enableResizing: false, // sticky col — keep fixed width
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.import_status}
              options={refData.import_statuses}
              render={(v) => (
                <span
                  className={`text-xs px-2 py-0.5 rounded font-medium ${
                    BADGE[v ?? ''] ?? 'bg-gray-200'
                  }`}
                >
                  {v}
                </span>
              )}
              onSave={(v) => onSave(c.id, { import_status: v })}
            />
          );
        },
      },
      {
        id: 'contract_id',
        header: 'Contract',
        accessorFn: (row) => row.contract_id ?? '',
        size: STICKY_W.contract,
        minSize: 100,
        enableResizing: false,
        cell: ({ row }) => {
          // Display-only: identity field, never edited inline.
          const c = row.original;
          return (
            <div className="px-1 font-mono text-xs text-gray-800">
              {c.contract_id || <span className="text-gray-300">—</span>}
            </div>
          );
        },
      },
      {
        id: 'student_name',
        header: 'Student',
        accessorFn: (row) => row.student_name ?? '',
        size: STICKY_W.student,
        minSize: 140,
        enableResizing: false,
        cell: ({ row }) => {
          // Display-only.
          const c = row.original;
          return (
            <div className="px-1 text-sm text-gray-900">
              {c.student_name || <span className="text-gray-300">—</span>}
            </div>
          );
        },
      },
      {
        id: 'student_id',
        header: 'Student ID',
        accessorFn: (row) => row.student_id ?? '',
        size: 130,
        cell: ({ row }) => {
          // Display-only.
          const c = row.original;
          return (
            <div className="px-1 font-mono text-xs text-gray-800">
              {c.student_id || <span className="text-gray-300">—</span>}
            </div>
          );
        },
      },
      {
        id: 'contract_signed_date',
        header: 'Signed',
        accessorFn: (row) => row.contract_signed_date ?? '',
        size: 120,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <DateCell
              value={c.contract_signed_date}
              onSave={(v) => onSave(c.id, { contract_signed_date: v })}
            />
          );
        },
      },
      {
        id: 'client_type_code',
        header: 'Client Type',
        accessorFn: (row) => row.client_type_code ?? '',
        size: 200,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.client_type_code}
              options={refData.client_types}
              onSave={(v) => onSave(c.id, { client_type_code: v })}
            />
          );
        },
      },
      // ---- Phase 5: Package (single-select) -----------------------------
      {
        id: 'package',
        header: 'Package',
        accessorFn: (row) => row.package_label ?? '',
        size: 220,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <FkCell
              value={c.package_fee_id}
              label={c.package_label}
              options={refData.package_codes}
              onSave={(id) => onSave(c.id, { package_fee_id: id })}
            />
          );
        },
      },
      // ---- Phase 5: Services (multi-select chips) -----------------------
      {
        id: 'services',
        header: 'Services',
        // Sort/filter by a concatenation of service codes
        accessorFn: (row) =>
          (row.services ?? []).map((s) => `${s.service_code}×${s.count}`).join(' '),
        size: 280,
        enableSorting: false,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <MultiSelectChipCell
              caseId={c.id}
              services={c.services ?? []}
              serviceOptions={refData.service_codes}
              bonusEvents={refData.bonus_events}
              reviewPending={c.service_review_pending ?? false}
              onSave={async (newList, clearReview) => {
                await saveServices(c.id, newList, clearReview);
              }}
            />
          );
        },
      },
      {
        id: 'country',
        header: 'Country',
        accessorFn: (row) => row.country_name ?? '',
        size: 140,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <FkCell
              value={c.country_id}
              label={c.country_name}
              options={refData.countries}
              onSave={(id) => onSave(c.id, { country_id: id })}
            />
          );
        },
      },
      {
        id: 'refer_source',
        header: 'Refer Source',
        accessorFn: (row) =>
          row.referring_partner_name ??
          row.referring_sub_agent_name ??
          row.referring_office_code ??
          row.referring_agent_text_raw ??
          '',
        size: 200,
        cell: ({ row }) => (
          <ReferSourceCell
            caseRow={row.original}
            refData={refData}
            onSave={(updates) => onSave(row.original.id, updates)}
          />
        ),
      },
      {
        id: 'application_status',
        header: 'App Status',
        accessorFn: (row) => row.application_status ?? '',
        size: 160,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.application_status}
              options={refData.statuses.map((s) => s.name ?? '').filter(Boolean)}
              onSave={(v) => onSave(c.id, { application_status: v })}
            />
          );
        },
      },
      {
        id: 'visa_received_date',
        header: 'Visa Date',
        accessorFn: (row) => row.visa_received_date ?? '',
        size: 120,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <DateCell
              value={c.visa_received_date}
              onSave={(v) => onSave(c.id, { visa_received_date: v })}
            />
          );
        },
      },
      {
        id: 'institution',
        header: 'Institution',
        accessorFn: (row) => row.institution_name ?? row.institution_text_raw ?? '',
        size: 220,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <FkCell
              value={c.institution_id}
              label={c.institution_name}
              options={refData.institutions}
              onSave={(id) => onSave(c.id, { institution_id: id })}
            />
          );
        },
      },
      {
        id: 'course_start_date',
        header: 'Course Start',
        accessorFn: (row) => row.course_start_date ?? '',
        size: 130,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <DateCell
              value={c.course_start_date}
              onSave={(v) => onSave(c.id, { course_start_date: v })}
            />
          );
        },
      },
      {
        id: 'course_status',
        header: 'Course Status',
        accessorFn: (row) => row.course_status ?? '',
        size: 140,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.course_status}
              options={refData.course_statuses}
              onSave={(v) => onSave(c.id, { course_status: v })}
            />
          );
        },
      },
      {
        id: 'counsellor',
        header: 'Counsellor',
        accessorFn: (row) => row.counsellor_name ?? '',
        size: 180,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <StaffCell
              staffId={c.counsellor_staff_id}
              staffName={c.counsellor_name}
              options={refData.staff_all}
              onSave={(staffId, roleId) =>
                onSave(c.id, {
                  counsellor_staff_id: staffId,
                  counsellor_role_id: roleId,
                })
              }
            />
          );
        },
      },
      {
        id: 'case_officer',
        header: 'Case Officer',
        accessorFn: (row) => row.case_officer_name ?? '',
        size: 180,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <StaffCell
              staffId={c.case_officer_staff_id}
              staffName={c.case_officer_name}
              options={refData.staff_all}
              onSave={(staffId, roleId) =>
                onSave(c.id, {
                  case_officer_staff_id: staffId,
                  case_officer_role_id: roleId,
                })
              }
            />
          );
        },
      },
      {
        id: 'pre_sales',
        header: 'Pre-sales',
        accessorFn: (row) => row.pre_sales_name ?? '',
        size: 180,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <PresalesCell
              staffId={c.pre_sales_staff_id}
              staffName={c.pre_sales_name}
              presalesAgents={refData.presales_agents}
              staffAll={refData.staff_all}
              onSave={(staffId) => onSave(c.id, { pre_sales_staff_id: staffId })}
            />
          );
        },
      },
      {
        id: 'office',
        header: 'Office',
        accessorFn: (row) => row.case_office_code ?? '',
        size: 120,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <FkCell
              value={c.case_office_id}
              label={c.case_office_code}
              options={refData.offices}
              labelField="code"
              onSave={(id) => onSave(c.id, { case_office_id: id })}
            />
          );
        },
      },
      // ---- v6.2 spec: 4 new dropdown columns ----------------------------
      {
        id: 'system_type',
        header: 'System Type',
        accessorFn: (row) => row.system_type ?? '',
        size: 160,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.system_type}
              options={refData.system_types}
              onSave={(v) => onSave(c.id, { system_type: v })}
            />
          );
        },
      },
      {
        id: 'institution_type',
        header: 'Institution Type',
        accessorFn: (row) => row.institution_type ?? '',
        size: 160,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.institution_type}
              options={refData.institution_types}
              onSave={(v) => onSave(c.id, { institution_type: v })}
            />
          );
        },
      },
      {
        id: 'deferral_code',
        header: 'Deferral',
        accessorFn: (row) => row.deferral_code ?? '',
        size: 160,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <SelectCell
              value={c.deferral_code}
              options={refData.deferral_codes}
              onSave={(v) => onSave(c.id, { deferral_code: v })}
            />
          );
        },
      },
      {
        id: 'targets_name',
        header: 'Targets Name',
        accessorFn: (row) => row.targets_name ?? '',
        size: 180,
        cell: ({ row }) => {
          const c = row.original;
          // Pick from the staff list. Stored as the name string (not a FK),
          // mirroring how the source CRM record carries it. Filter out blank
          // names and dedupe to keep the dropdown clean.
          const staffNames = Array.from(
            new Set(
              refData.staff_all
                .map((s) => s.name ?? '')
                .filter((n) => n.trim().length > 0),
            ),
          ).sort();
          return (
            <SelectCell
              value={c.targets_name}
              options={staffNames}
              onSave={(v) => onSave(c.id, { targets_name: v })}
            />
          );
        },
      },
      // -----------------------------------------------------------------
      // Phase 14 Block 4 — extra metadata columns
      // -----------------------------------------------------------------
      {
        id: 'handover_flag',
        header: 'Handover',
        accessorFn: (row) => (row.handover_flag ? 'Y' : ''),
        size: 90,
        minSize: 80,
        cell: ({ row }) => {
          const c = row.original;
          // Display-only badge. handover_flag is engine-derived from
          // imported data and not user-editable on this screen.
          return c.handover_flag ? (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">
              Handover
            </span>
          ) : (
            <span className="text-xs text-gray-400">—</span>
          );
        },
      },
      {
        id: 'case_transition',
        header: 'Transition',
        accessorFn: (row) => row.case_transition ?? '',
        size: 160,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <TextCell
              value={c.case_transition}
              onSave={(v) => onSave(c.id, { case_transition: v })}
            />
          );
        },
      },
      {
        id: 'period',
        header: 'Period',
        // Composite read-only field: "YYYY-MM" formed from run_year + run_month.
        // Sortable by string since zero-padded months compare correctly.
        accessorFn: (row) =>
          `${row.run_year}-${String(row.run_month).padStart(2, '0')}`,
        size: 100,
        minSize: 90,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <span className="font-mono text-xs text-gray-700">
              {c.run_year}-{String(c.run_month).padStart(2, '0')}
            </span>
          );
        },
      },
      {
        id: 'package_payment_basis',
        header: 'Pay basis',
        accessorFn: (row) => row.package_payment_basis ?? '',
        size: 120,
        minSize: 100,
        cell: ({ row }) => {
          const c = row.original;
          // Display-only — derived from the chosen package.
          return c.package_payment_basis ? (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-700">
              {c.package_payment_basis}
            </span>
          ) : (
            <span className="text-xs text-gray-400">—</span>
          );
        },
      },
      {
        id: 'notes',
        header: 'Notes',
        accessorFn: (row) => row.notes ?? '',
        size: 280,
        cell: ({ row }) => {
          const c = row.original;
          return (
            <TextAreaCell
              value={c.notes}
              onSave={(v) => onSave(c.id, { notes: v })}
            />
          );
        },
      },
    ],
    [refData, onSave, saveServices],
  );

  // ---- table instance -------------------------------------------------
  const table = useReactTable({
    data: cases,
    columns,
    state: { sorting, columnFilters, columnOrder, columnSizing, columnPinning, rowSelection },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnOrderChange: setColumnOrder,
    onColumnSizingChange: setColumnSizing,
    onColumnPinningChange: setColumnPinning,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    columnResizeMode: 'onChange',
    enableColumnResizing: true,
    enableRowSelection: showSelect,
    getRowId: (row) => String(row.id),
    defaultColumn: { minSize: 80 },
  });

  // ---- bulk transition (selected -> next state) ------------------------
  const selectedIds = useMemo(
    () =>
      Object.entries(rowSelection)
        .filter(([, v]) => v)
        .map(([k]) => Number(k))
        .filter((n) => Number.isFinite(n)),
    [rowSelection],
  );

  // Map current pillar to the next state in the workflow.
  const nextState: string | null =
    workflowState === 'uploaded'  ? 'in_review' :
    workflowState === 'in_review' ? 'submitted' :
    workflowState === 'submitted' ? 'closed'    : null;

  const nextStateLabel: string | null =
    nextState === 'in_review' ? 'In Review' :
    nextState === 'submitted' ? 'Submitted' :
    nextState === 'closed'    ? 'Closed'    : null;

  async function bulkTransition() {
    if (!nextState || selectedIds.length === 0) return;
    setTransitioning(true);
    setTransitionError(null);
    try {
      const res = await fetch('/api/cases/transition', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_ids: selectedIds, to_state: nextState }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`HTTP ${res.status}: ${detail}`);
      }
      setRowSelection({});
      onTransitioned();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setTransitionError(msg);
    } finally {
      setTransitioning(false);
    }
  }

  // ---- bulk calculate (selected -> engine, then transition to closed) ----
  // Only used when workflowState === 'submitted'.
  //
  // Calls the existing /api/engine/run endpoint (period-scoped) once per
  // distinct (run_year, run_month) found in the selection. This matches
  // how the engine is designed to operate: monthly batches. Each call
  // recalculates EVERY staff member's cases for that period — not just
  // the ticked ones (and not just the current staff).
  //
  // On success, the selected cases are transitioned to 'closed' so they
  // disappear from the Submitted view.
  async function bulkCalculate() {
    if (selectedIds.length === 0) return;

    // Derive distinct (year, month) periods from the selected cases.
    const selectedSet = new Set(selectedIds);
    const periodMap = new Map<string, { year: number; month: number }>();
    for (const c of cases) {
      if (!selectedSet.has(c.id)) continue;
      const key = `${c.run_year}-${c.run_month}`;
      if (!periodMap.has(key)) {
        periodMap.set(key, { year: c.run_year, month: c.run_month });
      }
    }
    const periods = Array.from(periodMap.values()).sort((a, b) => {
      if (a.year !== b.year) return a.year - b.year;
      return a.month - b.month;
    });

    if (periods.length === 0) return;

    const periodList = periods
      .map((p) => `  • ${p.year}-${String(p.month).padStart(2, '0')}`)
      .join('\n');

    const confirmed = window.confirm(
      `Fire the bonus engine for ${periods.length} period(s)?\n\n` +
        periodList +
        `\n\n` +
        `For each period, the engine will:\n` +
        `  • DELETE all existing bonus payments for that period\n` +
        `  • Re-calculate from imported tx_case rows (ALL staff, not just yours)\n` +
        `  • Write fresh tx_bonus_payment rows\n\n` +
        `Your selected cases will stay on the Submitted board with a\n` +
        `"Calculated" stamp. Use the Finalize button to move them to Closed\n` +
        `once you've reviewed any management overrides.\n\n` +
        `This is idempotent — safe to re-run.`,
    );
    if (!confirmed) return;

    setCalculating(true);
    setCalculateError(null);
    setCalculateMessage(null);

    let totalPayments = 0;
    let totalNet = 0;
    let totalSkipped = 0;
    let totalErrored = 0;

    try {
      // 1. Run engine once per period (sequential — safer for shared state).
      for (const p of periods) {
        const res = await fetch('/api/engine/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ year: p.year, month: p.month, persist: true }),
        });
        if (!res.ok) {
          const detail = await res.text();
          throw new Error(
            `Engine HTTP ${res.status} for ${p.year}-${String(p.month).padStart(
              2,
              '0',
            )}: ${detail}`,
          );
        }
        const result = (await res.json()) as {
          payment_count?: number;
          net_total?: number;
          skipped?: unknown[];
          errored?: unknown[];
        };
        totalPayments += result.payment_count ?? 0;
        totalNet += result.net_total ?? 0;
        totalSkipped += result.skipped?.length ?? 0;
        totalErrored += result.errored?.length ?? 0;
      }

      // 2. (Phase 14 Block 4 / C) DO NOT auto-transition to 'closed' here.
      //    The engine_run endpoint now stamps tx_case.calculated_at for
      //    successful cases server-side. Cases stay on the Submitted board
      //    so the Bonus Admin can review/edit management overrides, then
      //    click Finalize to advance them to Closed.

      setCalculateMessage({
        ok: true,
        payment_count: totalPayments,
        net_total: totalNet,
        skipped: totalSkipped,
        errored: totalErrored,
      });
      // Keep the selection so the user can immediately click "Finalize" on
      // the same cases. (Previously we cleared it because they were about
      // to disappear from the Submitted board.)
      onTransitioned();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setCalculateError(msg);
    } finally {
      setCalculating(false);
    }
  }

  // Phase 14 Block 4 / C — Finalize: move Submitted+Calculated → Closed.
  //
  // The /api/cases/finalize endpoint is all-or-nothing: every selected case
  // must be in 'submitted' state AND have calculated_at IS NOT NULL. If any
  // case fails the precondition, none are transitioned and the backend
  // returns a 400 with detail listing the offending case_ids.
  //
  // Use this AFTER you've run Calculate and reviewed management overrides.
  async function bulkFinalize() {
    if (selectedIds.length === 0) return;

    const confirmed = window.confirm(
      `Move ${selectedIds.length} case(s) to Closed?\n\n` +
        `Preconditions (checked server-side, all-or-nothing):\n` +
        `  • All cases must still be in Submitted state\n` +
        `  • All cases must have been calculated (engine has run for them)\n\n` +
        `Closed cases disappear from this board.`,
    );
    if (!confirmed) return;

    setFinalizing(true);
    setFinalizeError(null);
    setFinalizeMessage(null);

    try {
      const res = await fetch('/api/cases/finalize', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_ids: selectedIds }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const result = (await res.json()) as { finalized: number; ids: number[] };
      setFinalizeMessage({ ok: true, count: result.finalized });
      setRowSelection({});
      onTransitioned();
    } catch (e: unknown) {
      setFinalizeError(e instanceof Error ? e.message : String(e));
    } finally {
      setFinalizing(false);
    }
  }

  // dnd-kit sensors. Mouse needs an 8px activation distance so that clicking
  // a header (e.g. to sort) doesn't accidentally start a drag.
  const dndSensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
    useSensor(KeyboardSensor),
  );

  function handleColumnDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setColumnOrder((order) => {
      const oldIdx = order.indexOf(String(active.id));
      const newIdx = order.indexOf(String(over.id));
      if (oldIdx === -1 || newIdx === -1) return order;
      return arrayMove(order, oldIdx, newIdx);
    });
  }

  const resetView = () => {
    setSorting([]);
    setColumnFilters([]);
    setColumnOrder(DEFAULT_ORDER);
    setColumnSizing({});
    setColumnPinning({ left: DEFAULT_PINNED_LEFT, right: [] });
  };

  // Right-click context menu state for column pin operations.
  const [headerMenu, setHeaderMenu] = useState<HeaderContextMenuState>(null);

  function openHeaderMenu(e: ReactMouseEvent, columnId: string) {
    e.preventDefault();
    setHeaderMenu({ x: e.clientX, y: e.clientY, columnId });
  }

  function closeHeaderMenu() {
    setHeaderMenu(null);
  }

  function pinColumnLeft(columnId: string) {
    setColumnPinning((p) => {
      const left = (p.left ?? []).filter((id) => id !== columnId);
      const right = (p.right ?? []).filter((id) => id !== columnId);
      return { left: [...left, columnId], right };
    });
    closeHeaderMenu();
  }

  function pinColumnRight(columnId: string) {
    setColumnPinning((p) => {
      const left = (p.left ?? []).filter((id) => id !== columnId);
      const right = (p.right ?? []).filter((id) => id !== columnId);
      return { left, right: [columnId, ...right] };
    });
    closeHeaderMenu();
  }

  function unpinColumn(columnId: string) {
    setColumnPinning((p) => ({
      left: (p.left ?? []).filter((id) => id !== columnId),
      right: (p.right ?? []).filter((id) => id !== columnId),
    }));
    closeHeaderMenu();
  }

  function resetPinning() {
    setColumnPinning({ left: DEFAULT_PINNED_LEFT, right: [] });
    closeHeaderMenu();
  }

  const visibleHeaders = table.getHeaderGroups()[0]?.headers ?? [];
  const anyFilterActive = columnFilters.length > 0 || sorting.length > 0;

  // Pinned-state lookup for the open context menu, so the menu can grey out
  // the item matching the column's current pin status.
  const menuColumnPinnedState: 'left' | 'right' | false = headerMenu
    ? table.getColumn(headerMenu.columnId)?.getIsPinned() ?? false
    : false;

  // Items eligible for drag-and-drop reordering: every non-pinned column.
  // Pinned columns stay in their pinned section and aren't draggable.
  const sortableItemIds = visibleHeaders
    .filter((h) => !h.column.getIsPinned())
    .map((h) => h.column.id);

  return (
    <div className="border border-gray-200 rounded">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-3 py-2 text-xs">
        <div className="flex items-center gap-3 text-gray-600">
          <span>
            {table.getRowModel().rows.length === cases.length
              ? `${cases.length} case${cases.length === 1 ? '' : 's'}`
              : `${table.getRowModel().rows.length} of ${cases.length} case${
                  cases.length === 1 ? '' : 's'
                } (filtered)`}
          </span>
          {showSelect && selectedIds.length > 0 && (
            <span className="text-blue-700 font-medium">
              {selectedIds.length} selected
              <button
                onClick={() => setRowSelection({})}
                className="ml-2 text-blue-600 hover:underline"
              >
                clear
              </button>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Submitted-board action buttons.
              Always rendered while on the Submitted pillar; disabled
              (and label simplified) when no rows are selected. Avoids
              the appear/disappear flicker of the previous gated render
              and makes the buttons discoverable before the first click.
              In Batch B these will be joined by a "gate" indicator
              (period must be complete) for Total bonus. */}
          {showSelect && workflowState === 'submitted' && (() => {
            const noneSelected = selectedIds.length === 0;
            const calcDisabled = calculating || finalizing || noneSelected;
            const finalDisabled = finalizing || calculating || noneSelected;
            return (
              <>
                <button
                  onClick={bulkCalculate}
                  disabled={calcDisabled}
                  className={`rounded px-3 py-1 font-medium text-white ${
                    calcDisabled
                      ? 'bg-gray-300 cursor-not-allowed'
                      : 'bg-emerald-600 hover:bg-emerald-700'
                  }`}
                  title={
                    noneSelected
                      ? 'Select one or more cases to calculate.'
                      : 'Run the engine on the period(s) covering the selected cases. Cases stay on this board so you can review overrides afterwards.'
                  }
                >
                  {calculating
                    ? 'Running engine…'
                    : noneSelected
                      ? 'Calculate'
                      : `Calculate ${selectedIds.length}`}
                </button>
                <button
                  onClick={bulkFinalize}
                  disabled={finalDisabled}
                  className={`rounded px-3 py-1 font-medium text-white ${
                    finalDisabled
                      ? 'bg-gray-300 cursor-not-allowed'
                      : 'bg-blue-600 hover:bg-blue-700'
                  }`}
                  title={
                    noneSelected
                      ? 'Select one or more calculated cases to close.'
                      : 'Move calculated cases to Closed. Requires the engine to have run for each selected case.'
                  }
                >
                  {finalizing
                    ? 'Finalizing…'
                    : noneSelected
                      ? 'Finalize → Closed'
                      : `Finalize ${selectedIds.length} → Closed`}
                </button>
              </>
            );
          })()}
          {/* Move-to-next-state button (Uploaded → In Review, In Review →
              Submitted, etc.). Same always-visible / disabled-when-empty
              pattern as above for consistency. */}
          {showSelect && workflowState !== 'submitted' && nextState && (() => {
            const noneSelected = selectedIds.length === 0;
            const moveDisabled = transitioning || noneSelected;
            return (
              <button
                onClick={bulkTransition}
                disabled={moveDisabled}
                className={`rounded px-3 py-1 font-medium text-white ${
                  moveDisabled
                    ? 'bg-gray-300 cursor-not-allowed'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
                title={
                  noneSelected
                    ? `Select one or more cases to move to ${nextStateLabel}.`
                    : `Move the selected cases to ${nextStateLabel}.`
                }
              >
                {transitioning
                  ? 'Moving…'
                  : noneSelected
                    ? `Move to ${nextStateLabel} →`
                    : `Move ${selectedIds.length} to ${nextStateLabel} →`}
              </button>
            );
          })()}
          <VariantSwitcher
            actingAs={actingAs}
            pageKey="import_review"
            columnOrder={columnOrder}
            columnPinning={columnPinning}
            columnSizing={columnSizing}
            sorting={sorting}
            setColumnOrder={setColumnOrder}
            setColumnPinning={setColumnPinning}
            setColumnSizing={setColumnSizing}
            setSorting={setSorting}
          />
          {anyFilterActive && (
            <button
              onClick={resetView}
              className="rounded border border-gray-300 bg-white px-2 py-1 hover:bg-gray-100"
            >
              Reset view
            </button>
          )}
        </div>
      </div>

      {transitionError && (
        <div className="border-b border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          <strong>Move failed:</strong> {transitionError}
        </div>
      )}

      {calculateError && (
        <div className="border-b border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          <strong>Calculate failed:</strong> {calculateError}
        </div>
      )}

      {calculateMessage?.ok && (
        <div className="border-b border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <strong>Engine run complete.</strong>{' '}
          {calculateMessage.payment_count} payment row(s) written. Net total:{' '}
          <span className="font-semibold">
            {fmtVnd(calculateMessage.net_total)}
          </span>
          {calculateMessage.skipped > 0 && (
            <> · skipped {calculateMessage.skipped}</>
          )}
          {calculateMessage.errored > 0 && (
            <> · <span className="font-medium text-red-700">errored {calculateMessage.errored}</span></>
          )}
          . Selected cases are stamped as Calculated and remain on this board —
          review overrides, then click Finalize.
        </div>
      )}

      {finalizeError && (
        <div className="border-b border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          <strong>Finalize failed:</strong> {finalizeError}
        </div>
      )}

      {finalizeMessage?.ok && (
        <div className="border-b border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
          <strong>Finalized {finalizeMessage.count} case(s)</strong> — moved to
          Closed.
        </div>
      )}

      <div className="overflow-auto max-h-[calc(100vh-320px)] relative">
        <DndContext
          sensors={dndSensors}
          collisionDetection={closestCenter}
          onDragEnd={handleColumnDragEnd}
        >
          <table
            className="text-sm border-collapse"
            style={{ width: table.getTotalSize() }}
          >
            <thead className="bg-gray-50 text-xs uppercase tracking-wide sticky top-0 z-20">
              <tr>
                <SortableContext
                  items={sortableItemIds}
                  strategy={horizontalListSortingStrategy}
                >
                  {visibleHeaders.map((header) => {
                    if (header.column.getIsPinned()) {
                      return (
                        <PinnedHeaderCell
                          key={header.id}
                          header={header}
                          onContextMenu={openHeaderMenu}
                        />
                      );
                    }
                    return (
                      <SortableHeaderCell
                        key={header.id}
                        header={header}
                        onContextMenu={openHeaderMenu}
                      />
                    );
                  })}
                </SortableContext>
              </tr>
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row, idx) => {
                const c = row.original;
                const altBg = idx % 2 === 0 ? 'bg-white' : 'bg-slate-50';
                const rowBg =
                  c.import_status === 'OK'
                    ? altBg
                    : ROW_BG[c.import_status] ?? altBg;
                const stickyBg =
                  c.import_status === 'OK'
                    ? idx % 2 === 0
                      ? '#FFFFFF'
                      : '#F8FAFC' /* slate-50 */
                    : STICKY_BG_HEX[c.import_status] ?? '#FFFFFF';

                return (
                  <tr
                    key={row.id}
                    className={`${rowBg} border-b border-gray-100 align-top`}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const pinned = cell.column.getIsPinned();
                      const pinnedStyle: CSSProperties = pinned
                        ? {
                            position: 'sticky',
                            left:
                              pinned === 'left'
                                ? cell.column.getStart('left')
                                : undefined,
                            right:
                              pinned === 'right'
                                ? cell.column.getAfter('right')
                                : undefined,
                            zIndex: 10,
                            background: stickyBg,
                          }
                        : {};
                      return (
                        <td
                          key={cell.id}
                          style={{
                            width: cell.column.getSize(),
                            ...pinnedStyle,
                          }}
                          className="border-r border-gray-100 px-3 py-2"
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              {table.getRowModel().rows.length === 0 && cases.length > 0 && (
                <tr>
                  <td
                    colSpan={visibleHeaders.length}
                    className="px-3 py-8 text-center text-gray-500"
                  >
                    No cases match the current filters.{' '}
                    <button
                      onClick={resetView}
                      className="text-blue-600 underline hover:text-blue-800"
                    >
                      Reset
                    </button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </DndContext>
        {/* Right-click pin menu (portaled to body) */}
        <HeaderPinMenu
          menu={headerMenu}
          pinnedState={menuColumnPinnedState}
          onClose={closeHeaderMenu}
          onPinLeft={() =>
            headerMenu && pinColumnLeft(headerMenu.columnId)
          }
          onPinRight={() =>
            headerMenu && pinColumnRight(headerMenu.columnId)
          }
          onUnpin={() => headerMenu && unpinColumn(headerMenu.columnId)}
          onResetAll={resetPinning}
        />
      </div>
      {/* Bonus-estimate modal (P14 Block 3). Rendered at component root so
          it overlays everything; null caseId keeps it dismissed. */}
      <BonusEstimateModal
        caseId={estimateModalCaseId}
        onClose={() => setEstimateModalCaseId(null)}
      />
      <CaseApprovalsModal
        caseId={approvalsModalCaseId}
        onClose={() => setApprovalsModalCaseId(null)}
      />
      <CaseOverridesModal
        caseId={overridesModalCaseId}
        onClose={() => setOverridesModalCaseId(null)}
        onSaved={onTransitioned}
      />
    </div>
  );
}

function SortIndicator({ dir }: { dir: false | 'asc' | 'desc' }) {
  // Bolder, higher-contrast sort affordance.
  // Unsorted: muted double-chevron at 60% opacity.
  // Sorted: solid chevron in brand blue, slightly larger.
  if (!dir) {
    return (
      <ChevronsUpDown
        aria-hidden
        className="ml-1 inline-block h-3.5 w-3.5 text-gray-400 align-[-2px]"
        strokeWidth={2.5}
      />
    );
  }
  const Icon = dir === 'asc' ? ChevronUp : ChevronDown;
  return (
    <Icon
      aria-hidden
      className="ml-1 inline-block h-4 w-4 text-blue-600 align-[-3px]"
      strokeWidth={3}
    />
  );
}

// STICKY_BG was a Tailwind class map; for inline-style use in sticky cells
// we need explicit hex equivalents.
const STICKY_BG_HEX: Record<string, string> = {
  OK: '#F0FDF4', // green-50
  FLAGGED: '#FFFBEB', // amber-50
  UNRESOLVED: '#FEF2F2', // red-50
  SCRAP: '#F3F4F6', // gray-100
};

// ===========================================================================
// Mobile card view — same cells, vertical layout
// ===========================================================================

function CaseCard({
  caseRow: c,
  refData,
  onSave,
  saveServices,
}: { caseRow: Case } & CommonProps) {
  const save = (updates: Record<string, unknown>) => onSave(c.id, updates);
  const rowBg = ROW_BG[c.import_status] ?? '';

  return (
    <div className={`p-4 ${rowBg}`}>
      <div className="flex justify-between items-start mb-3">
        <div className="font-mono text-xs text-gray-700">{c.contract_id}</div>
        <SelectCell
          value={c.import_status}
          options={refData.import_statuses}
          render={(v) => (
            <span
              className={`text-xs px-2 py-0.5 rounded font-medium ${BADGE[v ?? ''] ?? 'bg-gray-200'}`}
            >
              {v}
            </span>
          )}
          onSave={(v) => save({ import_status: v })}
        />
      </div>
      <div className="space-y-2 text-sm">
        <Field label="Student">
          <TextCell value={c.student_name} onSave={(v) => save({ student_name: v })} />
        </Field>
        <Field label="Student ID">
          <TextCell
            value={c.student_id}
            monospace
            onSave={(v) => save({ student_id: v })}
          />
        </Field>
        <Field label="Signed">
          <DateCell
            value={c.contract_signed_date}
            onSave={(v) => save({ contract_signed_date: v })}
          />
        </Field>
        <Field label="Client Type">
          <SelectCell
            value={c.client_type_code}
            options={refData.client_types}
            onSave={(v) => save({ client_type_code: v })}
          />
        </Field>
        <Field label="Package">
          <FkCell
            value={c.package_fee_id}
            label={c.package_label}
            options={refData.package_codes}
            onSave={(id) => save({ package_fee_id: id })}
          />
        </Field>
        <Field label="Services">
          <MultiSelectChipCell
            caseId={c.id}
            services={c.services ?? []}
            serviceOptions={refData.service_codes}
            bonusEvents={refData.bonus_events}
            reviewPending={c.service_review_pending ?? false}
            onSave={async (newList, clearReview) => {
              await saveServices(c.id, newList, clearReview);
            }}
          />
        </Field>
        <Field label="Country">
          <FkCell
            value={c.country_id}
            label={c.country_name}
            options={refData.countries}
            onSave={(id) => save({ country_id: id })}
          />
        </Field>
        <Field label="System Type">
          <SelectCell
            value={c.system_type}
            options={refData.system_types}
            onSave={(v) => save({ system_type: v })}
          />
        </Field>
        <Field label="Refer Source">
          <ReferSourceCell caseRow={c} refData={refData} onSave={save} />
        </Field>
        <Field label="App Status">
          <SelectCell
            value={c.application_status}
            options={refData.statuses.map((s) => s.name ?? '').filter(Boolean)}
            onSave={(v) => save({ application_status: v })}
          />
        </Field>
        <Field label="Visa Date">
          <DateCell
            value={c.visa_received_date}
            onSave={(v) => save({ visa_received_date: v })}
          />
        </Field>
        <Field label="Institution">
          <FkCell
            value={c.institution_id}
            label={c.institution_name}
            options={refData.institutions}
            onSave={(id) => save({ institution_id: id })}
          />
        </Field>
        <Field label="Course Start">
          <DateCell
            value={c.course_start_date}
            onSave={(v) => save({ course_start_date: v })}
          />
        </Field>
        <Field label="Course Status">
          <SelectCell
            value={c.course_status}
            options={refData.course_statuses}
            onSave={(v) => save({ course_status: v })}
          />
        </Field>
        <Field label="Counsellor">
          <StaffCell
            staffId={c.counsellor_staff_id}
            staffName={c.counsellor_name}
            options={refData.staff_all}
            onSave={(staffId, roleId) =>
              save({
                counsellor_staff_id: staffId,
                counsellor_role_id: roleId,
              })
            }
          />
        </Field>
        <Field label="Case Officer">
          <StaffCell
            staffId={c.case_officer_staff_id}
            staffName={c.case_officer_name}
            options={refData.staff_all}
            onSave={(staffId, roleId) =>
              save({
                case_officer_staff_id: staffId,
                case_officer_role_id: roleId,
              })
            }
          />
        </Field>
        <Field label="Pre-sales">
          <PresalesCell
            staffId={c.pre_sales_staff_id}
            staffName={c.pre_sales_name}
            presalesAgents={refData.presales_agents}
            staffAll={refData.staff_all}
            onSave={(staffId) => save({ pre_sales_staff_id: staffId })}
          />
        </Field>
        <Field label="Office">
          <FkCell
            value={c.case_office_id}
            label={c.case_office_code}
            options={refData.offices}
            labelField="code"
            onSave={(id) => save({ case_office_id: id })}
          />
        </Field>
        <Field label="Institution Type">
          <SelectCell
            value={c.institution_type}
            options={refData.institution_types}
            onSave={(v) => save({ institution_type: v })}
          />
        </Field>
        <Field label="Deferral">
          <SelectCell
            value={c.deferral_code}
            options={refData.deferral_codes}
            onSave={(v) => save({ deferral_code: v })}
          />
        </Field>
        <Field label="Targets Name">
          <SelectCell
            value={c.targets_name}
            options={Array.from(
              new Set(
                refData.staff_all
                  .map((s) => s.name ?? '')
                  .filter((n) => n.trim().length > 0),
              ),
            ).sort()}
            onSave={(v) => save({ targets_name: v })}
          />
        </Field>
        <Field label="Notes">
          <TextAreaCell value={c.notes} onSave={(v) => save({ notes: v })} />
        </Field>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 items-start">
      <div className="text-xs text-gray-500 uppercase tracking-wide pt-1">{label}</div>
      <div>{children}</div>
    </div>
  );
}

// ===========================================================================
// Editable cell primitives
// ===========================================================================

const DASH = <span className="text-gray-400">—</span>;
const EDITABLE_BASE =
  'cursor-pointer hover:bg-blue-50 px-2 py-1 rounded -mx-2 -my-1 min-h-[28px]';
const INPUT_BASE = 'w-full px-2 py-1 border border-blue-500 rounded text-sm';

type CellSavedState = 'idle' | 'saving' | 'error';

function useCellState() {
  const [state, setState] = useState<CellSavedState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  return { state, setState, error, setError, editing, setEditing };
}

function ErrorTooltip({ error }: { error: string | null }) {
  // Anchor for positioning: a zero-size invisible span placed at the top-left
  // of whatever container the consumer renders us in. The tooltip itself
  // renders into a FloatingPortal at the document root so it can break out
  // of any clipping/stacking context (including the open dropdown's
  // z-index 1000 stack, which previously hid this tooltip entirely).
  const anchorRef = useRef<HTMLSpanElement>(null);
  return (
    <>
      <span
        ref={anchorRef}
        className="absolute top-0 left-0 pointer-events-none"
        style={{ width: 0, height: 0 }}
        aria-hidden
      />
      {error ? <ErrorTooltipPortal anchorRef={anchorRef} error={error} /> : null}
    </>
  );
}

function ErrorTooltipPortal({
  anchorRef,
  error,
}: {
  anchorRef: React.RefObject<HTMLSpanElement | null>;
  error: string;
}) {
  const { refs, floatingStyles } = useFloating({
    placement: 'right-start',
    open: true,
    whileElementsMounted: autoUpdate,
    middleware: [offset(8), flip({ padding: 8 }), shift({ padding: 8 })],
  });

  useEffect(() => {
    if (anchorRef.current) {
      refs.setReference(anchorRef.current);
    }
  }, [anchorRef, refs]);

  return (
    <FloatingPortal>
      <div
        ref={refs.setFloating}
        style={{ ...floatingStyles, zIndex: 1100 }}
        className="bg-red-100 text-red-800 text-xs px-2 py-1 rounded shadow max-w-[320px] border border-red-300"
        role="alert"
      >
        {error}
      </div>
    </FloatingPortal>
  );
}

// ---- TextCell -------------------------------------------------------------
function TextCell({
  value,
  monospace,
  onSave,
}: {
  value: string | null;
  monospace?: boolean;
  onSave: (newValue: string | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();
  const [draft, setDraft] = useState(value ?? '');

  useEffect(() => {
    setDraft(value ?? '');
  }, [value]);

  async function commit() {
    const cleaned = draft.trim();
    const newVal = cleaned === '' ? null : cleaned;
    if (newVal === (value ?? null)) {
      setEditing(false);
      return;
    }
    setState('saving');
    setError(null);
    try {
      await onSave(newVal);
      setEditing(false);
      setState('idle');
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setState('error');
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') commit();
    else if (e.key === 'Escape') {
      setEditing(false);
      setError(null);
      setDraft(value ?? '');
    }
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE + (monospace ? ' font-mono text-xs' : '')}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(value ?? '');
        }}
      >
        {value || DASH}
      </div>
    );
  }

  return (
    <div className="relative">
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKey}
        disabled={state === 'saving'}
        className={INPUT_BASE + (monospace ? ' font-mono text-xs' : '')}
      />
      <ErrorTooltip error={error} />
    </div>
  );
}

// ---- TextAreaCell --------------------------------------------------------
function TextAreaCell({
  value,
  onSave,
}: {
  value: string | null;
  onSave: (newValue: string | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();
  const [draft, setDraft] = useState(value ?? '');

  useEffect(() => {
    setDraft(value ?? '');
  }, [value]);

  async function commit() {
    const newVal = draft === '' ? null : draft;
    if (newVal === (value ?? null)) {
      setEditing(false);
      return;
    }
    setState('saving');
    setError(null);
    try {
      await onSave(newVal);
      setEditing(false);
      setState('idle');
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setState('error');
    }
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE + ' text-xs'}
        title={value ?? undefined}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(value ?? '');
        }}
      >
        {value || DASH}
      </div>
    );
  }

  return (
    <div className="relative">
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setEditing(false);
            setError(null);
            setDraft(value ?? '');
          }
        }}
        disabled={state === 'saving'}
        rows={3}
        className={INPUT_BASE + ' min-w-[200px] text-xs'}
      />
      <ErrorTooltip error={error} />
    </div>
  );
}

// ---- DateCell ------------------------------------------------------------
function DateCell({
  value,
  onSave,
}: {
  value: string | null;
  onSave: (newValue: string | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();
  const [draft, setDraft] = useState(value ?? '');

  useEffect(() => {
    setDraft(value ?? '');
  }, [value]);

  async function commit() {
    const newVal = draft === '' ? null : draft;
    if (newVal === (value ?? null)) {
      setEditing(false);
      return;
    }
    setState('saving');
    setError(null);
    try {
      await onSave(newVal);
      setEditing(false);
      setState('idle');
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setState('error');
    }
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE + ' font-mono text-xs whitespace-nowrap'}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(value ?? '');
        }}
      >
        {value || DASH}
      </div>
    );
  }

  return (
    <div className="relative flex items-center gap-1">
      <input
        autoFocus
        type="date"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          else if (e.key === 'Escape') {
            setEditing(false);
            setError(null);
            setDraft(value ?? '');
          }
        }}
        disabled={state === 'saving'}
        className={INPUT_BASE + ' text-xs font-mono'}
      />
      {value && (
        <button
          type="button"
          // onMouseDown so the click registers BEFORE the input's onBlur
          // fires — otherwise the blur commit would close the cell before
          // this handler runs.
          onMouseDown={(e) => {
            e.preventDefault();
            setDraft('');
            // Save null immediately so the user gets a single-click clear.
            setState('saving');
            setError(null);
            onSave(null)
              .then(() => {
                setEditing(false);
                setState('idle');
              })
              .catch((err) => {
                setError(String(err instanceof Error ? err.message : err));
                setState('error');
              });
          }}
          disabled={state === 'saving'}
          className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-600 hover:bg-red-50 hover:text-red-700"
          title="Clear date"
        >
          ×
        </button>
      )}
      <ErrorTooltip error={error} />
    </div>
  );
}

// ===========================================================================
// SearchableDropdown — portal-based, collision-aware, accessible
// ===========================================================================
//
// Replaces the previous inline `position: absolute` dropdown pattern that
// suffered from two bugs:
//   (1) Options below the viewport edge were clipped by ancestor overflow.
//   (2) onMouseDown vs onBlur races caused clicks to fail to commit.
//
// This implementation uses @floating-ui/react. The dropdown is rendered into
// a Portal (`<FloatingPortal>`) so it escapes the table's overflow container,
// is positioned with `position: fixed` based on the input's bounding rect,
// and `flip` middleware automatically opens upward when there's no room
// below. `useDismiss` handles outside-clicks; `useListNavigation` provides
// arrow-key support. Click-to-select goes through the standard `onClick`
// handler — no more racing setTimeouts.
//
// Used by SelectCell, FkCell, and StaffCell.

type SearchableDropdownProps = {
  open: boolean;
  setOpen: (open: boolean) => void;
  options: { key: string; label: string; isCurrent?: boolean }[];
  draft: string;
  setDraft: (s: string) => void;
  onPick: (key: string) => void;
  onCancel: () => void;
  onCommitDraft: () => void; // Called when user presses Enter w/o picking
  placeholder?: string;
  saving?: boolean;
  inputClassName?: string;
  maxShown?: number;
};

function SearchableDropdown({
  open,
  setOpen,
  options,
  draft,
  setDraft,
  onPick,
  onCancel,
  onCommitDraft,
  placeholder,
  saving = false,
  inputClassName,
  maxShown = 200,
}: SearchableDropdownProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const listRef = useRef<Array<HTMLDivElement | null>>([]);

  const { refs, floatingStyles, context } = useFloating({
    open,
    onOpenChange: setOpen,
    placement: 'bottom-start',
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(4),
      flip({ padding: 8 }),
      shift({ padding: 8 }),
      size({
        apply({ rects, availableHeight, elements }) {
          Object.assign(elements.floating.style, {
            minWidth: `${rects.reference.width}px`,
            maxHeight: `${Math.min(availableHeight - 8, 320)}px`,
          });
        },
        padding: 8,
      }),
    ],
  });

  const dismiss = useDismiss(context, { outsidePress: true });
  const listNav = useListNavigation(context, {
    listRef,
    activeIndex,
    onNavigate: setActiveIndex,
    virtual: true,
    loop: true,
  });
  const { getReferenceProps, getFloatingProps, getItemProps } = useInteractions([
    dismiss,
    listNav,
  ]);

  const shown = options.slice(0, maxShown);

  return (
    <>
      <input
        ref={refs.setReference}
        autoFocus
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setOpen(true);
          setActiveIndex(0);
        }}
        onFocus={(e) => {
          e.target.select();
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            // Empty input → always route to onCommitDraft so the parent cell's
            // clear-to-null path runs. Otherwise (with options shown when the
            // input is blank) Enter would pick the highlighted first option
            // and the user could never clear the value.
            if (draft.trim() === '') {
              onCommitDraft();
            } else if (activeIndex != null && shown[activeIndex]) {
              onPick(shown[activeIndex].key);
            } else {
              onCommitDraft();
            }
          } else if (e.key === 'Escape') {
            e.preventDefault();
            onCancel();
          }
        }}
        disabled={saving}
        placeholder={placeholder}
        className={inputClassName ?? INPUT_BASE}
        {...getReferenceProps()}
      />
      {open && (
        <FloatingPortal>
          <div
            ref={refs.setFloating}
            style={{
              ...floatingStyles,
              zIndex: 1000,
            }}
            className="bg-white border border-gray-300 rounded-md shadow-lg overflow-y-auto"
            {...getFloatingProps()}
          >
            {shown.length === 0 ? (
              <div className="px-3 py-2 text-xs text-gray-400">No matches</div>
            ) : (
              shown.map((opt, i) => {
                const isActive = i === activeIndex;
                return (
                  <div
                    key={opt.key}
                    ref={(node) => {
                      listRef.current[i] = node;
                    }}
                    aria-selected={opt.isCurrent}
                    className={`px-3 py-1.5 text-sm cursor-pointer ${
                      isActive ? 'bg-blue-50' : 'bg-white'
                    } ${opt.isCurrent ? 'font-medium' : ''}`}
                    {...getItemProps({
                      // IMPORTANT: pass onClick THROUGH getItemProps so it
                      // composes with Floating UI's internal handlers.
                      // Putting onClick directly on the div AFTER the spread
                      // works; putting it BEFORE the spread (or relying on
                      // spread order) is the canonical gotcha — getItemProps
                      // can return its own onClick and overwrite yours.
                      onClick: () => onPick(opt.key),
                    })}
                  >
                    {opt.label}
                  </div>
                );
              })
            )}
            {options.length > maxShown && (
              <div className="px-3 py-1.5 text-xs text-gray-400 border-t border-gray-100">
                … and {options.length - maxShown} more. Refine the search.
              </div>
            )}
          </div>
        </FloatingPortal>
      )}
    </>
  );
}

// ===========================================================================
// FloatingPopover — generic portaled popover anchored to a trigger element
// ===========================================================================
//
// Used by MultiSelectChipCell (Services) and ReferSourceCell, which both have
// composite popovers (form fields, search lists, buttons) that aren't a
// simple "type-to-search" pattern, so they don't fit SearchableDropdown.
//
// Same overflow-escape and dismiss semantics as SearchableDropdown: rendered
// in a Portal, positioned with collision-aware fixed coords, dismissed on
// outside click and Escape.
//
// Usage:
//   const anchorRef = useRef<HTMLDivElement>(null);
//   <div ref={anchorRef}>...trigger...</div>
//   <FloatingPopover open={isOpen} onClose={...} anchorRef={anchorRef}>
//     ...popover content...
//   </FloatingPopover>

type FloatingPopoverProps = {
  open: boolean;
  onClose: () => void;
  anchorRef: { current: HTMLElement | null };
  children: ReactNode;
  className?: string;
  placement?: 'bottom-start' | 'bottom' | 'bottom-end' | 'top-start' | 'top';
  /** Default true. Set false if outside clicks should not close (e.g. when
   *  the popover contains a confirm-required form and we don't want stray
   *  taps to discard in-progress edits). */
  dismissOnOutsidePress?: boolean;
  /** Default 320 — the maximum height the popover may take. Floating UI's
   *  `size` middleware will clamp this further if the viewport is smaller. */
  maxHeight?: number;
  /** Default false. When true, the popover at least matches the anchor's
   *  width (useful for "type-to-search" style popovers; not needed for
   *  form-style popovers where the content has its own width). */
  matchAnchorWidth?: boolean;
};

function FloatingPopover({
  open,
  onClose,
  anchorRef,
  children,
  className,
  placement = 'bottom-start',
  dismissOnOutsidePress = true,
  maxHeight = 320,
  matchAnchorWidth = false,
}: FloatingPopoverProps) {
  const { refs, floatingStyles, context } = useFloating({
    open,
    onOpenChange: (o) => {
      if (!o) onClose();
    },
    placement,
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(4),
      flip({ padding: 8 }),
      shift({ padding: 8 }),
      size({
        apply({ rects, availableHeight, elements }) {
          const styleUpdates: Record<string, string> = {
            maxHeight: `${Math.min(availableHeight - 8, maxHeight)}px`,
          };
          if (matchAnchorWidth) {
            styleUpdates.minWidth = `${rects.reference.width}px`;
          }
          Object.assign(elements.floating.style, styleUpdates);
        },
        padding: 8,
      }),
    ],
  });

  // Wire the externally-supplied anchor into Floating UI's reference slot.
  useEffect(() => {
    if (anchorRef.current) {
      refs.setReference(anchorRef.current);
    }
    // refs is stable across renders; only re-run when the anchor identity
    // changes (it shouldn't change at runtime — anchorRef stays the same
    // ref across the component's lifetime).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorRef.current]);

  const dismiss = useDismiss(context, {
    outsidePress: dismissOnOutsidePress,
    escapeKey: true,
  });
  const { getFloatingProps } = useInteractions([dismiss]);

  if (!open) return null;

  return (
    <FloatingPortal>
      <div
        ref={refs.setFloating}
        style={{ ...floatingStyles, zIndex: 1000 }}
        className={
          className ??
          'bg-white border border-gray-300 rounded-md shadow-lg overflow-y-auto'
        }
        {...getFloatingProps()}
      >
        {children}
      </div>
    </FloatingPortal>
  );
}

// ---- SelectCell (string options, e.g. import_status, application_status) -
function SelectCell({
  value,
  options,
  render,
  onSave,
}: {
  value: string | null;
  options: string[];
  render?: (v: string | null) => ReactNode;
  onSave: (newValue: string | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();

  // Optimistic local override — same rationale as FkCell. The backend's
  // PATCH response sometimes returns a stale snapshot, so without this,
  // the cell flashes back to the old value after a successful save until
  // the page is reloaded. We hold the picked value locally and use it in
  // place of the prop until the user re-edits, the save errors out, or
  // the page is reloaded.
  const [localValue, setLocalValue] = useState<string | null>(null);
  const displayValue = localValue ?? value;

  const [draft, setDraft] = useState(displayValue ?? '');

  useEffect(() => {
    setDraft(displayValue ?? '');
  }, [displayValue]);

  async function commit(newVal: string | null) {
    if ((newVal ?? null) === (displayValue ?? null)) {
      setEditing(false);
      return;
    }
    setLocalValue(newVal);
    setState('saving');
    setError(null);
    try {
      await onSave(newVal);
      setEditing(false);
      setState('idle');
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setState('error');
      setLocalValue(null);
    }
  }

  function cancel() {
    setEditing(false);
    setError(null);
    setDraft(displayValue ?? '');
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(displayValue ?? '');
        }}
      >
        {render ? render(displayValue) : displayValue || DASH}
      </div>
    );
  }

  const lcDraft = draft.trim().toLowerCase();
  const isUnchanged = lcDraft === (displayValue ?? '').trim().toLowerCase();
  const filtered =
    lcDraft && !isUnchanged
      ? options.filter((o) => o.toLowerCase().includes(lcDraft))
      : options;

  const dropdownOptions = filtered.map((opt) => ({
    key: opt,
    label: opt,
    isCurrent: opt === displayValue,
  }));

  return (
    <div className="relative">
      <SearchableDropdown
        open={editing}
        setOpen={(o) => {
          if (!o) cancel();
        }}
        options={dropdownOptions}
        draft={draft}
        setDraft={setDraft}
        onPick={(key) => commit(key)}
        onCancel={cancel}
        onCommitDraft={() => {
          const trimmed = draft.trim();
          const match = options.find(
            (o) => o.toLowerCase() === trimmed.toLowerCase(),
          );
          if (match) commit(match);
          else if (trimmed === '') commit(null);
          else {
            setError(`No matching option for "${trimmed}"`);
            setState('error');
          }
        }}
        placeholder={`type to search… (${options.length} options)`}
        saving={state === 'saving'}
      />
      <ErrorTooltip error={error} />
    </div>
  );
}

// ---- FkCell (foreign key with searchable datalist) ---------------------
function FkCell({
  value,
  label,
  options,
  labelField = 'name',
  onSave,
}: {
  value: number | null;
  label: string | null;
  options: RefItem[];
  labelField?: 'name' | 'code';
  onSave: (newId: number | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();

  // Optimistic local label override. The backend PATCH endpoint returns the
  // updated Case row with the new FK id but a STALE/NULL label (because the
  // label is a denormalised column populated by a JOIN that the UPDATE path
  // doesn't re-resolve). Without an override, picking a value would leave
  // the cell showing "—" until a full refresh re-joined the lookup. We hold
  // the freshly picked label locally and use it in place of the prop label.
  //
  // We do NOT clear this on subsequent value-prop changes. The backend's
  // PATCH response sometimes returns a stale snapshot of the case (the DB
  // is correctly updated but the response body reflects pre-update state),
  // so if we trusted the prop drift, the cell would flash back to the old
  // value even though the database now holds the new one. The optimistic
  // override stays until either (a) the user explicitly clears the cell,
  // (b) the save errors out, or (c) the page is reloaded and the prop
  // arrives fresh from the database.
  const [localLabel, setLocalLabel] = useState<string | null>(null);

  const displayLabel = localLabel ?? label;

  const [draft, setDraft] = useState(displayLabel ?? '');

  useEffect(() => {
    setDraft(displayLabel ?? '');
  }, [displayLabel]);

  function cancel() {
    setEditing(false);
    setError(null);
    setDraft(displayLabel ?? '');
  }

  function commitDraft() {
    const trimmed = draft.trim();
    if (trimmed === '') {
      if (value === null) {
        setEditing(false);
        return;
      }
      // Clearing — drop the local override so the prop (null) wins.
      setLocalLabel(null);
      setState('saving');
      setError(null);
      onSave(null)
        .then(() => {
          setEditing(false);
          setState('idle');
        })
        .catch((e) => {
          setError(String(e instanceof Error ? e.message : e));
          setState('error');
        });
      return;
    }
    const match = options.find(
      (o) => (labelField === 'code' ? o.code : o.name) === trimmed,
    );
    if (!match) {
      setError(`No matching option for "${trimmed}"`);
      setState('error');
      return;
    }
    pickById(match.id);
  }

  function pickById(newId: number) {
    if (newId === value) {
      setEditing(false);
      return;
    }
    // Stash the picked option's label so the cell can display it immediately,
    // regardless of what the backend returns for the label field.
    const picked = options.find((o) => o.id === newId);
    const pickedLabel = picked
      ? (labelField === 'code' ? picked.code : picked.name) ?? null
      : null;
    setLocalLabel(pickedLabel);

    setState('saving');
    setError(null);
    onSave(newId)
      .then(() => {
        setEditing(false);
        setState('idle');
      })
      .catch((e) => {
        setError(String(e instanceof Error ? e.message : e));
        setState('error');
        // Rollback the optimistic override on real (HTTP) failure.
        setLocalLabel(null);
      });
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(displayLabel ?? ''); // Keep existing value visible until user types
        }}
      >
        {displayLabel || DASH}
      </div>
    );
  }

  const lcDraft = draft.trim().toLowerCase();
  // When the draft still matches the current label exactly, show ALL options
  // (so the user sees the full picker without having to clear the input first).
  const isUnchangedLabel = lcDraft === (displayLabel ?? '').trim().toLowerCase();
  const filtered =
    lcDraft && !isUnchangedLabel
      ? options.filter((o) => {
          const txt = (labelField === 'code' ? o.code : o.name) ?? '';
          return txt.toLowerCase().includes(lcDraft);
        })
      : options;

  const dropdownOptions = filtered.map((o) => ({
    key: String(o.id),
    label: (labelField === 'code' ? o.code : o.name) ?? '',
    isCurrent: o.id === value,
  }));

  return (
    <div className="relative">
      <SearchableDropdown
        open={editing}
        setOpen={(o) => {
          if (!o) cancel();
        }}
        options={dropdownOptions}
        draft={draft}
        setDraft={setDraft}
        onPick={(key) => pickById(Number(key))}
        onCancel={cancel}
        onCommitDraft={commitDraft}
        placeholder={`type to search… (${options.length} options)`}
        saving={state === 'saving'}
      />
      <ErrorTooltip error={error} />
    </div>
  );
}

// ---- StaffCell — picks staff AND auto-sets role_id from primary_role ---
function StaffCell({
  staffId,
  staffName,
  options,
  onSave,
}: {
  staffId: number | null;
  staffName: string | null;
  options: RefItem[];
  onSave: (newStaffId: number | null, newRoleId: number | null) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();

  // Optimistic local name override — same rationale as FkCell. The backend
  // PATCH returns the new staff_id but a stale/null staff_name (derived via
  // join), or sometimes a stale snapshot of the case altogether. Without
  // an optimistic local override, picking a counsellor leaves the cell
  // showing "—" until the page is refreshed. We keep the optimistic name
  // until the user explicitly clears the cell, the save errors out, or the
  // page is reloaded.
  const [localName, setLocalName] = useState<string | null>(null);

  const displayName = localName ?? staffName;

  const [draft, setDraft] = useState(displayName ?? '');

  useEffect(() => {
    setDraft(displayName ?? '');
  }, [displayName]);

  function cancel() {
    setEditing(false);
    setError(null);
    setDraft(displayName ?? '');
  }

  function pickById(newStaffId: number) {
    const o = options.find((opt) => opt.id === newStaffId);
    if (!o) return;
    if (o.id === staffId) {
      setEditing(false);
      return;
    }
    setLocalName(o.name ?? null);

    setState('saving');
    setError(null);
    onSave(o.id, o.primary_role_id ?? null)
      .then(() => {
        setEditing(false);
        setState('idle');
      })
      .catch((e) => {
        setError(String(e instanceof Error ? e.message : e));
        setState('error');
        setLocalName(null);
      });
  }

  function commitDraft() {
    const trimmed = draft.trim();
    if (trimmed === '') {
      if (staffId === null) {
        setEditing(false);
        return;
      }
      setLocalName(null);
      setState('saving');
      setError(null);
      onSave(null, null)
        .then(() => {
          setEditing(false);
          setState('idle');
        })
        .catch((e) => {
          setError(String(e instanceof Error ? e.message : e));
          setState('error');
        });
      return;
    }
    const match = options.find((o) => o.name === trimmed);
    if (!match) {
      setError(`No matching staff for "${trimmed}"`);
      setState('error');
      return;
    }
    pickById(match.id);
  }

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(displayName ?? ''); // Keep existing value visible until user types
        }}
      >
        {displayName || DASH}
      </div>
    );
  }

  const lcDraft = draft.trim().toLowerCase();
  const isUnchangedLabel = lcDraft === (displayName ?? '').trim().toLowerCase();
  const filtered =
    lcDraft && !isUnchangedLabel
      ? options.filter((o) => (o.name ?? '').toLowerCase().includes(lcDraft))
      : options;

  const dropdownOptions = filtered.map((o) => ({
    key: String(o.id),
    label: o.name ?? '',
    isCurrent: o.id === staffId,
  }));

  return (
    <div className="relative">
      <SearchableDropdown
        open={editing}
        setOpen={(o) => {
          if (!o) cancel();
        }}
        options={dropdownOptions}
        draft={draft}
        setDraft={setDraft}
        onPick={(key) => pickById(Number(key))}
        onCancel={cancel}
        onCommitDraft={commitDraft}
        placeholder={`type to search… (${options.length} staff)`}
        saving={state === 'saving'}
      />
      <ErrorTooltip error={error} />
    </div>
  );
}

// ---- MultiSelectChipCell — Services multi-select with per-chip count + event
//
// State machine per cell:
//   - idle: show chips inline + "+ Add" button (compact view, no popover)
//   - adding: "+ Add" was clicked → show search popover to pick a new service
//   - editing <chipId>: a chip label was clicked → show edit popover with
//                       count input + bonus event dropdown + Remove button
//
// Save flow (any of: add, edit, remove):
//   1. Build the full updated services array (the API replaces, not merges)
//   2. Call onSave(serviceList) which PATCHes /api/cases/{id}/services
//   3. Parent updates the Case row in its state with the response
//
// Compact display rules:
//   - Chip text = service_label  (e.g. "AP Gói 2 Standard Plus")
//   - If count > 1, append " ×N"
//   - If review pending, show small "⚠ Review" tag on the cell
function MultiSelectChipCell({
  caseId,
  services: servicesRaw,
  serviceOptions,
  bonusEvents,
  reviewPending,
  onSave,
}: {
  caseId: number;
  services: CaseService[] | undefined;
  serviceOptions: RefItem[];
  bonusEvents: string[];
  reviewPending: boolean;
  onSave: (newList: Array<{ service_fee_id: number; count: number; bonus_event: string }>,
           clearReview: boolean) => Promise<CaseService[] | void>;
}) {
  // Defensive: backend may still be returning rows that pre-date the
  // services-array shape change, in which case it's undefined.
  const services = servicesRaw ?? [];
  type Mode = { kind: 'idle' } | { kind: 'adding' } | { kind: 'editing'; chipId: number };
  const [mode, setMode] = useState<Mode>({ kind: 'idle' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Add-mode state
  const [addQuery, setAddQuery] = useState('');

  // Edit-mode state — pre-fill from the chip when we enter editing
  const [draftCount, setDraftCount] = useState(1);
  const [draftEvent, setDraftEvent] = useState<string>('');

  function startAdd() {
    setMode({ kind: 'adding' });
    setAddQuery('');
    setError(null);
  }

  function startEdit(s: CaseService) {
    setMode({ kind: 'editing', chipId: s.id });
    setDraftCount(s.count);
    setDraftEvent(s.bonus_event);
    setError(null);
  }

  function cancelMode() {
    setMode({ kind: 'idle' });
    setAddQuery('');
    setError(null);
  }

  // Build a "next list" payload for the API by mutating one entry.
  function buildPayload(transform: (list: typeof services) => typeof services) {
    const next = transform(services);
    return next.map((s) => ({
      service_fee_id: s.service_fee_id,
      count: s.count,
      bonus_event: s.bonus_event,
    }));
  }

  async function commit(transform: (list: typeof services) => typeof services, clearReview = true) {
    setSaving(true);
    setError(null);
    try {
      await onSave(buildPayload(transform), clearReview);
      cancelMode();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setSaving(false);
    }
  }

  function addService(opt: RefItem) {
    // Default bonus_event = the option's default basis if available, else
    // 'course_start_date' (sensible fallback that the engine knows)
    const defaultEvent = opt.bonus_payment_basis || 'course_start_date';
    commit((list) => [
      ...list,
      // Cast OK — the row will be replaced after save with the API response
      {
        id: -1,
        service_fee_id: opt.id,
        service_code: opt.code || opt.name || '',
        service_label: opt.name || opt.code || '',
        category: opt.category || 'SERVICE_FEE',
        count: 1,
        bonus_event: defaultEvent,
        confirmed: true,
        detection_source: 'user_manual',
      },
    ]);
  }

  function updateChip(chipId: number) {
    if (draftCount < 1) {
      setError('Count must be at least 1');
      return;
    }
    if (!bonusEvents.includes(draftEvent)) {
      setError(`Invalid bonus event: ${draftEvent}`);
      return;
    }
    commit((list) =>
      list.map((s) => (s.id === chipId ? { ...s, count: draftCount, bonus_event: draftEvent } : s)),
    );
  }

  function removeChip(chipId: number) {
    commit((list) => list.filter((s) => s.id !== chipId));
  }

  // Add-mode option filter (only show services NOT already on this case)
  const usedIds = new Set(services.map((s) => s.service_fee_id));
  const lcQ = addQuery.trim().toLowerCase();
  const addOptions = serviceOptions
    .filter((opt) => !usedIds.has(opt.id))
    .filter((opt) => {
      if (!lcQ) return true;
      const txt = `${opt.name ?? ''} ${opt.code ?? ''}`.toLowerCase();
      return txt.includes(lcQ);
    });

  // Ref to the chip-area container; FloatingPopover anchors its positioning
  // to this so the popovers sit just below the chips and escape the table's
  // overflow container via FloatingPortal.
  const anchorRef = useRef<HTMLDivElement>(null);

  // ---- Render -----------------------------------------------------------
  const editingChip =
    mode.kind === 'editing'
      ? services.find((s) => s.id === mode.chipId) ?? null
      : null;

  return (
    <div className="relative">
      <div ref={anchorRef} className="flex flex-wrap gap-1 items-start">
        {services.length === 0 && mode.kind === 'idle' && (
          <span className="text-gray-300 text-xs italic">—</span>
        )}

        {services.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => startEdit(s)}
            disabled={saving}
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${
              s.confirmed
                ? 'bg-blue-50 border-blue-200 text-blue-900 hover:bg-blue-100'
                : 'bg-yellow-50 border-yellow-300 text-yellow-900 hover:bg-yellow-100'
            } ${saving ? 'opacity-50 cursor-wait' : 'cursor-pointer'}`}
            title={`${s.service_code} (${s.category}) · ${s.bonus_event}${
              s.detection_source ? ` · ${s.detection_source}` : ''
            }`}
          >
            <span className="truncate max-w-[160px]">{s.service_label}</span>
            {s.count > 1 && (
              <span className="font-mono font-semibold">×{s.count}</span>
            )}
          </button>
        ))}

        <button
          type="button"
          onClick={startAdd}
          disabled={saving || mode.kind !== 'idle'}
          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs border border-dashed border-gray-300 text-gray-500 hover:border-gray-500 hover:text-gray-700 disabled:opacity-50"
        >
          + Add
        </button>

        {reviewPending && (
          <span
            className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-900 border border-amber-300"
            title="Importer auto-detected these services. Click any chip to confirm."
          >
            ⚠ Review
          </span>
        )}
      </div>

      {/* Add-mode popover (portaled). Search services not yet on this case. */}
      <FloatingPopover
        open={mode.kind === 'adding'}
        onClose={cancelMode}
        anchorRef={anchorRef}
        className="bg-white border border-gray-300 rounded-md shadow-lg w-72 overflow-hidden"
        maxHeight={380}
      >
        <div className="p-2 border-b border-gray-100">
          <input
            autoFocus
            value={addQuery}
            onChange={(e) => setAddQuery(e.target.value)}
            placeholder={`Search services… (${addOptions.length} available)`}
            className="w-full px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
            onKeyDown={(e) => {
              if (e.key === 'Escape') cancelMode();
            }}
          />
        </div>
        <div className="max-h-64 overflow-y-auto">
          {addOptions.length === 0 ? (
            <div className="px-3 py-2 text-xs text-gray-400">No matches</div>
          ) : (
            addOptions.slice(0, 200).map((opt) => (
              <div
                key={opt.id}
                onClick={() => addService(opt)}
                className="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50"
              >
                <span className="font-medium">{opt.name}</span>
                {opt.category && (
                  <span className="ml-2 text-xs text-gray-400">
                    {opt.category}
                  </span>
                )}
              </div>
            ))
          )}
        </div>
        <div className="px-3 py-1 border-t border-gray-100 flex justify-end">
          <button
            type="button"
            onClick={cancelMode}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
        </div>
      </FloatingPopover>

      {/* Edit-mode popover (portaled). Adjust count + bonus_event, or remove. */}
      <FloatingPopover
        open={mode.kind === 'editing' && editingChip != null}
        onClose={cancelMode}
        anchorRef={anchorRef}
        className="bg-white border border-gray-300 rounded-md shadow-lg w-72"
        // The edit form has unsaved input state — don't dismiss on accidental
        // outside taps; require an explicit Cancel/Save/Remove/Escape.
        dismissOnOutsidePress={false}
      >
        {editingChip && (
          <div className="p-3 space-y-2">
            <div
              className="text-sm font-medium text-gray-900 truncate"
              title={editingChip.service_label}
            >
              {editingChip.service_label}
            </div>
            <div className="text-xs text-gray-500">
              {editingChip.service_code} · {editingChip.category}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <label className="text-xs text-gray-700 w-16">Count:</label>
              <input
                type="number"
                min={1}
                value={draftCount}
                onChange={(e) =>
                  setDraftCount(Math.max(1, Number(e.target.value) || 1))
                }
                onKeyDown={(e) => {
                  if (e.key === 'Escape') cancelMode();
                  if (e.key === 'Enter') updateChip(editingChip.id);
                }}
                className="w-20 px-2 py-0.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-700 w-16">Event:</label>
              <select
                value={draftEvent}
                onChange={(e) => setDraftEvent(e.target.value)}
                className="flex-1 px-2 py-0.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                {bonusEvents.map((ev) => (
                  <option key={ev} value={ev}>
                    {ev}
                  </option>
                ))}
              </select>
            </div>
            {error && <div className="text-xs text-red-600">{error}</div>}
            <div className="flex justify-between pt-2 border-t border-gray-100">
              <button
                type="button"
                onClick={() => removeChip(editingChip.id)}
                disabled={saving}
                className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
              >
                Remove
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={cancelMode}
                  disabled={saving}
                  className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => updateChip(editingChip.id)}
                  disabled={saving}
                  className="text-xs px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}
      </FloatingPopover>

      {error && mode.kind === 'idle' && (
        <div className="absolute top-full mt-0.5 left-0 bg-red-100 text-red-800 text-xs px-2 py-1 rounded shadow z-20 max-w-[300px]">
          {error}
        </div>
      )}
    </div>
  );
}


// ---- PresalesCell — locked dropdown for the curated 7-name list -----------
// v6.2 col 17. The dropdown only shows the 7 names from refData.presales_agents
// (NONE + 6 curated names). When user picks a name, look up the matching
// ref_staff.id from refData.staff_all and PATCH tx_case.pre_sales_staff_id.
// "NONE" → save NULL.
function PresalesCell({
  staffId,
  staffName,
  presalesAgents,
  staffAll,
  onSave,
}: {
  staffId: number | null;
  staffName: string | null;
  presalesAgents: string[];
  staffAll: RefItem[];
  onSave: (newStaffId: number | null) => Promise<void>;
}) {
  // Display label: the saved staffName if present, else "NONE" if explicitly
  // cleared, else "—" if never set.
  const display = staffName ?? (staffId === null ? null : 'NONE');

  // SelectCell handles the dropdown UX. We translate name → staff_id here.
  // The curated presales list uses short or familiar names like "Gia Mẫn"
  // or "Trúc Quỳnh (HCM)" while ref_staff stores canonical full names like
  // "Trần Thanh Gia Mẫn" or "Đoàn Ngọc Trúc Quỳnh". Exact match would fail
  // for almost every name. We strip any parenthetical office suffix and
  // look for a ref_staff entry whose canonical name contains the short
  // name (case-insensitive, accent-sensitive). If multiple ref_staff
  // entries match the same short name, we throw — the curated list needs
  // a more specific entry.
  async function handleSave(name: string | null) {
    if (name === null || name === 'NONE') {
      await onSave(null);
      return;
    }
    const stripped = name.replace(/\s*\([^)]*\)\s*$/, '').trim();
    const lc = stripped.toLowerCase();
    // Try exact match first (strongest signal — handles names that ARE
    // already canonical, like "Lê Thị Trường An").
    const exact = staffAll.find((s) => (s.name ?? '').toLowerCase() === lc);
    if (exact) {
      await onSave(exact.id);
      return;
    }
    const substringMatches = staffAll.filter((s) =>
      (s.name ?? '').toLowerCase().includes(lc),
    );
    if (substringMatches.length === 0) {
      throw new Error(
        `No staff record found matching "${name}". Add them to ref_staff or update the curated presales list.`,
      );
    }
    if (substringMatches.length > 1) {
      const names = substringMatches.map((s) => s.name).join(', ');
      throw new Error(
        `"${name}" matches multiple staff records (${names}). Make the curated presales list entry more specific.`,
      );
    }
    await onSave(substringMatches[0].id);
  }

  return (
    <SelectCell
      value={display}
      options={presalesAgents}
      onSave={handleSave}
    />
  );
}


// ---- ReferSourceCell — composite type + entity picker ------------------
//
// The UI uses 5 source types (DIRECT, SUB_AGENT, MASTER_AGENT, GROUP, OFFICE)
// because MASTER_AGENT and GROUP have separate option lists (filtered by
// partner.classification). The database uses a different 5-value enum
// (PARTNER, SUB_AGENT, OFFICE_ONLY, UNRESOLVED, NONE) enforced by a CHECK
// constraint. MASTER_AGENT and GROUP both collapse to PARTNER at the DB
// level. We translate at the save/load boundary.
const UI_TO_DB_SOURCE_TYPE: Record<SourceType, string> = {
  DIRECT: 'NONE',
  SUB_AGENT: 'SUB_AGENT',
  MASTER_AGENT: 'PARTNER',
  GROUP: 'PARTNER',
  OFFICE: 'OFFICE_ONLY',
};

function dbSourceTypeToUi(
  dbType: string | null | undefined,
  partnerId: number | null,
  partners: RefItem[],
): SourceType {
  switch (dbType) {
    case 'PARTNER': {
      // PARTNER alone doesn't tell us MA vs Group — look up the partner's
      // classification on the joined ref list. Fallback to MASTER_AGENT if
      // partner can't be found (defensive: most partners are MAs).
      const p = partners.find((q) => q.id === partnerId);
      return p?.classification === 'GROUP' ? 'GROUP' : 'MASTER_AGENT';
    }
    case 'SUB_AGENT':
      return 'SUB_AGENT';
    case 'OFFICE_ONLY':
      return 'OFFICE';
    case 'NONE':
      return 'DIRECT';
    case 'UNRESOLVED':
      // System-set state for imports the resolver couldn't classify. We
      // show it as DIRECT in the editor so the user can reclassify; the
      // display label below shows the raw "UNRESOLVED" so the operator
      // knows the row needs attention.
      return 'DIRECT';
    default:
      return 'DIRECT';
  }
}

function ReferSourceCell({
  caseRow: c,
  refData,
  onSave,
}: {
  caseRow: Case;
  refData: RefData;
  onSave: (updates: Record<string, unknown>) => Promise<void>;
}) {
  const { state, setState, error, setError, editing, setEditing } = useCellState();
  const initialType = dbSourceTypeToUi(
    c.referring_source_type,
    c.referring_partner_id,
    refData.partners,
  );
  const [draftType, setDraftType] = useState<SourceType>(initialType);
  const [draftEntityId, setDraftEntityId] = useState<number | null>(
    c.referring_partner_id ?? c.referring_sub_agent_id ?? c.referring_office_id ?? null,
  );

  const displayName =
    c.referring_partner_name ||
    c.referring_sub_agent_name ||
    c.referring_office_code ||
    c.referring_agent_text_raw ||
    null;

  // The bracketed label shown next to the entity name in display mode. Use
  // the UI-side name so it matches the dropdown the user will see when
  // editing — except for UNRESOLVED, which we keep visible verbatim so the
  // operator can see at a glance that the row needs reclassifying.
  const displaySourceLabel =
    c.referring_source_type === 'UNRESOLVED'
      ? 'UNRESOLVED'
      : initialType;

  let entityOptions: RefItem[] = [];
  if (draftType === 'SUB_AGENT') entityOptions = refData.sub_agents;
  else if (draftType === 'MASTER_AGENT')
    entityOptions = refData.partners.filter(
      (p) => p.classification === 'MASTER_AGENT',
    );
  else if (draftType === 'GROUP')
    entityOptions = refData.partners.filter((p) => p.classification === 'GROUP');
  else if (draftType === 'OFFICE') entityOptions = refData.offices;

  async function commit() {
    if (draftType !== 'DIRECT' && draftEntityId === null) {
      setError(`Pick a ${draftType.toLowerCase().replace('_', ' ')}`);
      setState('error');
      return;
    }
    const updates: Record<string, unknown> = {
      // Translate to the DB enum the CHECK constraint requires.
      referring_source_type: UI_TO_DB_SOURCE_TYPE[draftType],
      referring_partner_id: null,
      referring_sub_agent_id: null,
      referring_office_id: null,
    };
    if (draftType === 'SUB_AGENT') updates.referring_sub_agent_id = draftEntityId;
    else if (draftType === 'MASTER_AGENT' || draftType === 'GROUP')
      updates.referring_partner_id = draftEntityId;
    else if (draftType === 'OFFICE') updates.referring_office_id = draftEntityId;

    setState('saving');
    setError(null);
    try {
      await onSave(updates);
      setEditing(false);
      setState('idle');
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setState('error');
    }
  }

  // Anchor for the portaled form popover. We keep the display visible during
  // editing so the user retains spatial context (which cell they're editing).
  const anchorRef = useRef<HTMLDivElement>(null);

  return (
    <>
      <div
        ref={anchorRef}
        className={EDITABLE_BASE + ' min-w-[150px]'}
        onClick={() => {
          if (editing) return;
          setEditing(true);
          setError(null);
          setDraftType(initialType);
          setDraftEntityId(
            c.referring_partner_id ??
              c.referring_sub_agent_id ??
              c.referring_office_id ??
              null,
          );
        }}
      >
        <div className="text-xs">
          <span className="text-gray-500">
            [{displaySourceLabel}]
          </span>{' '}
          {displayName || DASH}
        </div>
      </div>

      <FloatingPopover
        open={editing}
        onClose={() => {
          setEditing(false);
          setError(null);
        }}
        anchorRef={anchorRef}
        className="bg-white border border-blue-500 rounded-md shadow-lg min-w-[260px]"
        // The composite form has in-progress edits — require explicit
        // Cancel/Save/Escape rather than dismissing on outside taps.
        dismissOnOutsidePress={false}
      >
        <div className="p-2 space-y-1.5">
          <label className="block text-xs font-medium text-gray-700">
            Type
          </label>
          <select
            value={draftType}
            onChange={(e) => {
              setDraftType(e.target.value as SourceType);
              setDraftEntityId(null);
            }}
            className="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white"
            disabled={state === 'saving'}
          >
            {refData.source_types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          {draftType !== 'DIRECT' && (
            <>
              <label className="block text-xs font-medium text-gray-700">
                Entity
              </label>
              <select
                value={draftEntityId ?? ''}
                onChange={(e) =>
                  setDraftEntityId(
                    e.target.value ? Number(e.target.value) : null,
                  )
                }
                className="w-full px-2 py-1 border border-gray-300 rounded text-xs bg-white"
                disabled={state === 'saving'}
              >
                <option value="">— pick —</option>
                {entityOptions.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name ?? o.code ?? `#${o.id}`}
                  </option>
                ))}
              </select>
            </>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={commit}
              disabled={state === 'saving'}
              className="px-2 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:bg-gray-400"
            >
              {state === 'saving' ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
              className="px-2 py-1 bg-gray-200 text-gray-700 text-xs rounded hover:bg-gray-300"
            >
              Cancel
            </button>
          </div>
          {error && (
            <div className="bg-red-100 text-red-800 text-xs px-2 py-1 rounded">
              {error}
            </div>
          )}
        </div>
      </FloatingPopover>
    </>
  );
}

// ===========================================================================
// Table primitives
// ===========================================================================

function Th({
  children,
  sticky,
  left,
  width,
}: {
  children: ReactNode;
  sticky?: boolean;
  left?: number;
  width?: number;
}) {
  const stickyCls = sticky
    ? `sticky bg-gray-50 z-10 border-r border-gray-200 shadow-[2px_0_2px_-2px_rgba(0,0,0,0.05)] overflow-hidden`
    : '';
  const style: CSSProperties = {};
  if (sticky && left !== undefined) style.left = left;
  if (width !== undefined) {
    style.width = width;
    style.minWidth = width;
    style.maxWidth = width;
  }
  return (
    <th
      className={`px-3 py-2 text-left font-medium text-gray-600 whitespace-nowrap ${stickyCls}`}
      style={Object.keys(style).length ? style : undefined}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  sticky,
  left,
  bg,
  width,
  wrap,
}: {
  children: ReactNode;
  sticky?: boolean;
  left?: number;
  bg?: string;
  width?: number;
  wrap?: boolean;
}) {
  const stickyCls = sticky
    ? `sticky z-10 border-r border-gray-200 ${bg ?? 'bg-white'} shadow-[2px_0_2px_-2px_rgba(0,0,0,0.05)] overflow-hidden`
    : '';
  const wrapCls = wrap ? '' : 'whitespace-nowrap';
  const style: CSSProperties = {};
  if (sticky && left !== undefined) style.left = left;
  if (width !== undefined) {
    style.width = width;
    style.minWidth = width;
    style.maxWidth = width;
  }
  return (
    <td
      className={`px-3 py-2 ${wrapCls} ${stickyCls}`}
      style={Object.keys(style).length ? style : undefined}
    >
      {children}
    </td>
  );
}
