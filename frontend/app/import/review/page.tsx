'use client';

/**
 * frontend/app/import/review/[year]/[month]/page.tsx
 *
 * Imported-cases review screen. Displays one staff member's cases for one
 * (year, month). Every field that maps to a CRM column is inline-editable.
 *
 * Layout:
 *   - md+ : wide horizontal-scroll table with sticky Status/Contract/Student
 *   - <md : card-per-case layout for mobile
 *
 * Edit flow:
 *   - Click a cell -> input/select/datepicker
 *   - Enter or blur saves via PATCH /api/cases/{id}
 *   - Escape cancels
 *   - Errors show inline beneath the cell, value reverts
 *
 * URL query string drives filter state:
 *   /import/review?staff_id=N&year=YYYY&month=M
 *
 * The "Submit to Engine" button at the bottom triggers POST /api/engine/run
 * for the WHOLE period (every staff for that year+month, not just the
 * staff being reviewed) and redirects to /bonus/{year}/{month}.
 */

import {
  FormEvent,
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useRouter } from 'next/navigation';

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
};

type RefItem = {
  id: number;
  name?: string;
  code?: string;
  classification?: string;
  primary_role_id?: number | null;
  employment_status?: string | null;
};

type RefData = {
  institutions: RefItem[];
  sub_agents: RefItem[];
  partners: RefItem[];
  offices: RefItem[];
  countries: RefItem[];
  staff_active: RefItem[];
  statuses: RefItem[];
  source_types: string[];
  import_statuses: string[];
};

const EMPTY_REF: RefData = {
  institutions: [],
  sub_agents: [],
  partners: [],
  offices: [],
  countries: [],
  staff_active: [],
  statuses: [],
  source_types: [],
  import_statuses: [],
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
        'staff_active',
        'statuses',
        'source_types',
        'import_statuses',
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
  // Pre-fills year/month from URL whether or not staff_id is present.
  // Auto-loads only when all three are present.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get('staff_id');
    const y = params.get('year');
    const m = params.get('month');
    const yNum = y ? Number(y) : null;
    const mNum = m ? Number(m) : null;
    if (yNum && Number.isFinite(yNum)) setYear(yNum);
    if (mNum && Number.isFinite(mNum)) setMonth(mNum);
    if (sid && yNum && mNum) {
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
      setCases((prev) => prev.map((c) => (c.id === caseId ? updated : c)));
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

  // ----------------------------------------------------------------------
  return (
    <main className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-[1800px] mx-auto">
        <div className="flex items-baseline justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl md:text-3xl font-bold">Imported Cases — Review</h1>
            <p className="text-gray-600 mt-1 text-sm">
              Click any cell to edit. Saves on Enter or blur. Esc cancels.
            </p>
          </div>
          <div className="flex items-center gap-4">
            <a
              href={`/bonus/${year}/${month}`}
              className="text-sm text-blue-600 hover:underline"
            >
              View bonus report →
            </a>
            <a href="/imports" className="text-sm text-blue-600 hover:underline">
              ← Back to Importer
            </a>
          </div>
        </div>

        {/* Filter form */}
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
              <CasesTable cases={cases} refData={refData} onSave={saveCase} />
            </div>

            {/* Mobile cards */}
            <div className="md:hidden divide-y divide-gray-200">
              {cases.map((c) => (
                <CaseCard
                  key={c.id}
                  caseRow={c}
                  refData={refData}
                  onSave={saveCase}
                />
              ))}
            </div>

            {/* Submit-to-Engine footer */}
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
};

function CasesTable({ cases, refData, onSave }: { cases: Case[] } & CommonProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200 text-xs uppercase tracking-wide">
          <tr>
            <Th sticky left={0}>Status</Th>
            <Th sticky left={110}>Contract</Th>
            <Th sticky left={230}>Student</Th>
            <Th>Student ID</Th>
            <Th>Signed</Th>
            <Th>Client Type</Th>
            <Th>Country</Th>
            <Th>Refer Source</Th>
            <Th>App Status</Th>
            <Th>Visa Date</Th>
            <Th>Institution</Th>
            <Th>Course Start</Th>
            <Th>Course Status</Th>
            <Th>Counsellor</Th>
            <Th>Case Officer</Th>
            <Th>Office</Th>
            <Th>Notes</Th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <CaseRow key={c.id} caseRow={c} refData={refData} onSave={onSave} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CaseRow({
  caseRow: c,
  refData,
  onSave,
}: { caseRow: Case } & CommonProps) {
  const rowBg = ROW_BG[c.import_status] ?? '';
  const stickyBg = STICKY_BG[c.import_status] ?? 'bg-white';

  const save = (updates: Record<string, unknown>) => onSave(c.id, updates);

  return (
    <tr className={`${rowBg} border-b border-gray-100 align-top`}>
      <Td sticky left={0} bg={stickyBg}>
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
      </Td>
      <Td sticky left={110} bg={stickyBg}>
        <TextCell
          value={c.contract_id}
          monospace
          onSave={(v) => save({ contract_id: v })}
        />
      </Td>
      <Td sticky left={230} bg={stickyBg}>
        <TextCell value={c.student_name} onSave={(v) => save({ student_name: v })} />
      </Td>
      <Td>
        <TextCell
          value={c.student_id}
          monospace
          onSave={(v) => save({ student_id: v })}
        />
      </Td>
      <Td>
        <DateCell
          value={c.contract_signed_date}
          onSave={(v) => save({ contract_signed_date: v })}
        />
      </Td>
      <Td>
        <TextCell
          value={c.client_type_code}
          onSave={(v) => save({ client_type_code: v })}
        />
      </Td>
      <Td>
        <FkCell
          value={c.country_id}
          label={c.country_name}
          options={refData.countries}
          onSave={(id) => save({ country_id: id })}
        />
      </Td>
      <Td>
        <ReferSourceCell caseRow={c} refData={refData} onSave={save} />
      </Td>
      <Td>
        <SelectCell
          value={c.application_status}
          options={refData.statuses.map((s) => s.name ?? '').filter(Boolean)}
          onSave={(v) => save({ application_status: v })}
        />
      </Td>
      <Td>
        <DateCell
          value={c.visa_received_date}
          onSave={(v) => save({ visa_received_date: v })}
        />
      </Td>
      <Td>
        <FkCell
          value={c.institution_id}
          label={c.institution_name}
          options={refData.institutions}
          onSave={(id) => save({ institution_id: id })}
        />
      </Td>
      <Td>
        <DateCell
          value={c.course_start_date}
          onSave={(v) => save({ course_start_date: v })}
        />
      </Td>
      <Td>
        <TextCell
          value={c.course_status}
          onSave={(v) => save({ course_status: v })}
        />
      </Td>
      <Td>
        <StaffCell
          staffId={c.counsellor_staff_id}
          staffName={c.counsellor_name}
          options={refData.staff_active}
          onSave={(staffId, roleId) =>
            save({
              counsellor_staff_id: staffId,
              counsellor_role_id: roleId,
            })
          }
        />
      </Td>
      <Td>
        <StaffCell
          staffId={c.case_officer_staff_id}
          staffName={c.case_officer_name}
          options={refData.staff_active}
          onSave={(staffId, roleId) =>
            save({
              case_officer_staff_id: staffId,
              case_officer_role_id: roleId,
            })
          }
        />
      </Td>
      <Td>
        <FkCell
          value={c.case_office_id}
          label={c.case_office_code}
          options={refData.offices}
          labelField="code"
          onSave={(id) => save({ case_office_id: id })}
        />
      </Td>
      <Td>
        <TextAreaCell value={c.notes} onSave={(v) => save({ notes: v })} />
      </Td>
    </tr>
  );
}

// ===========================================================================
// Mobile card view — same cells, vertical layout
// ===========================================================================

function CaseCard({
  caseRow: c,
  refData,
  onSave,
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
          <TextCell
            value={c.client_type_code}
            onSave={(v) => save({ client_type_code: v })}
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
          <TextCell
            value={c.course_status}
            onSave={(v) => save({ course_status: v })}
          />
        </Field>
        <Field label="Counsellor">
          <StaffCell
            staffId={c.counsellor_staff_id}
            staffName={c.counsellor_name}
            options={refData.staff_active}
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
            options={refData.staff_active}
            onSave={(staffId, roleId) =>
              save({
                case_officer_staff_id: staffId,
                case_officer_role_id: roleId,
              })
            }
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
  if (!error) return null;
  return (
    <div className="absolute top-full left-0 mt-0.5 bg-red-100 text-red-800 text-xs px-2 py-1 rounded shadow z-20 max-w-[300px]">
      {error}
    </div>
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
        className={EDITABLE_BASE + ' whitespace-pre-wrap text-xs max-w-[300px]'}
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
    <div className="relative">
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
      <ErrorTooltip error={error} />
    </div>
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

  async function commit(newVal: string | null) {
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
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
        }}
      >
        {render ? render(value) : value || DASH}
      </div>
    );
  }

  return (
    <div className="relative">
      <select
        autoFocus
        defaultValue={value ?? ''}
        onChange={(e) => commit(e.target.value || null)}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setEditing(false);
            setError(null);
          }
        }}
        disabled={state === 'saving'}
        className={INPUT_BASE}
      >
        <option value="">—</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
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
  const [draft, setDraft] = useState(label ?? '');
  const datalistId = useMemo(
    () => `dl-${Math.random().toString(36).slice(2, 10)}`,
    [],
  );

  useEffect(() => {
    setDraft(label ?? '');
  }, [label]);

  async function commit() {
    const trimmed = draft.trim();
    if (trimmed === '') {
      if (value === null) {
        setEditing(false);
        return;
      }
      setState('saving');
      setError(null);
      try {
        await onSave(null);
        setEditing(false);
        setState('idle');
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
        setState('error');
      }
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
    if (match.id === value) {
      setEditing(false);
      return;
    }
    setState('saving');
    setError(null);
    try {
      await onSave(match.id);
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
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(label ?? '');
        }}
      >
        {label || DASH}
      </div>
    );
  }

  return (
    <div className="relative">
      <input
        autoFocus
        list={datalistId}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          else if (e.key === 'Escape') {
            setEditing(false);
            setError(null);
            setDraft(label ?? '');
          }
        }}
        disabled={state === 'saving'}
        className={INPUT_BASE}
        placeholder={`type to search… (${options.length})`}
      />
      <datalist id={datalistId}>
        {options.map((o) => (
          <option key={o.id} value={(labelField === 'code' ? o.code : o.name) ?? ''} />
        ))}
      </datalist>
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
  const [draft, setDraft] = useState(staffName ?? '');
  const datalistId = useMemo(
    () => `dl-${Math.random().toString(36).slice(2, 10)}`,
    [],
  );

  useEffect(() => {
    setDraft(staffName ?? '');
  }, [staffName]);

  async function commit() {
    const trimmed = draft.trim();
    if (trimmed === '') {
      if (staffId === null) {
        setEditing(false);
        return;
      }
      setState('saving');
      setError(null);
      try {
        await onSave(null, null);
        setEditing(false);
        setState('idle');
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
        setState('error');
      }
      return;
    }
    const match = options.find((o) => o.name === trimmed);
    if (!match) {
      setError(`No matching staff for "${trimmed}"`);
      setState('error');
      return;
    }
    if (match.id === staffId) {
      setEditing(false);
      return;
    }
    setState('saving');
    setError(null);
    try {
      await onSave(match.id, match.primary_role_id ?? null);
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
        className={EDITABLE_BASE}
        onClick={() => {
          setEditing(true);
          setError(null);
          setDraft(staffName ?? '');
        }}
      >
        {staffName || DASH}
      </div>
    );
  }

  return (
    <div className="relative">
      <input
        autoFocus
        list={datalistId}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          else if (e.key === 'Escape') {
            setEditing(false);
            setError(null);
            setDraft(staffName ?? '');
          }
        }}
        disabled={state === 'saving'}
        className={INPUT_BASE}
        placeholder={`type to search… (${options.length} staff)`}
      />
      <datalist id={datalistId}>
        {options.map((o) => (
          <option key={o.id} value={o.name ?? ''} />
        ))}
      </datalist>
      <ErrorTooltip error={error} />
    </div>
  );
}

// ---- ReferSourceCell — composite type + entity picker ------------------
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
  const initialType = (c.referring_source_type ?? 'DIRECT') as SourceType;
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

  let entityOptions: RefItem[] = [];
  if (draftType === 'SUB_AGENT') entityOptions = refData.sub_agents;
  else if (draftType === 'MASTER_AGENT')
    entityOptions = refData.partners.filter(
      (p) => p.classification === 'Master agent',
    );
  else if (draftType === 'GROUP')
    entityOptions = refData.partners.filter((p) => p.classification === 'Group');
  else if (draftType === 'OFFICE') entityOptions = refData.offices;

  async function commit() {
    if (draftType !== 'DIRECT' && draftEntityId === null) {
      setError(`Pick a ${draftType.toLowerCase().replace('_', ' ')}`);
      setState('error');
      return;
    }
    const updates: Record<string, unknown> = {
      referring_source_type: draftType,
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

  if (!editing) {
    return (
      <div
        className={EDITABLE_BASE + ' min-w-[150px]'}
        onClick={() => {
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
          <span className="text-gray-500">[{c.referring_source_type ?? 'DIRECT'}]</span>{' '}
          {displayName || DASH}
        </div>
      </div>
    );
  }

  return (
    <div className="relative bg-white p-2 border border-blue-500 rounded shadow-sm min-w-[260px] z-20">
      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-gray-700">Type</label>
        <select
          value={draftType}
          onChange={(e) => {
            setDraftType(e.target.value as SourceType);
            setDraftEntityId(null);
          }}
          className="w-full px-2 py-1 border border-gray-300 rounded text-xs"
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
            <label className="block text-xs font-medium text-gray-700">Entity</label>
            <select
              value={draftEntityId ?? ''}
              onChange={(e) =>
                setDraftEntityId(e.target.value ? Number(e.target.value) : null)
              }
              className="w-full px-2 py-1 border border-gray-300 rounded text-xs"
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
    </div>
  );
}

// ===========================================================================
// Table primitives
// ===========================================================================

function Th({
  children,
  sticky,
  left,
}: {
  children: ReactNode;
  sticky?: boolean;
  left?: number;
}) {
  const stickyCls = sticky
    ? `sticky bg-gray-50 z-10 border-r border-gray-200 shadow-[2px_0_2px_-2px_rgba(0,0,0,0.05)]`
    : '';
  const style = sticky && left !== undefined ? { left } : undefined;
  return (
    <th
      className={`px-3 py-2 text-left font-medium text-gray-600 whitespace-nowrap ${stickyCls}`}
      style={style}
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
}: {
  children: ReactNode;
  sticky?: boolean;
  left?: number;
  bg?: string;
}) {
  const stickyCls = sticky
    ? `sticky z-10 border-r border-gray-200 ${bg ?? 'bg-white'} shadow-[2px_0_2px_-2px_rgba(0,0,0,0.05)]`
    : '';
  const style = sticky && left !== undefined ? { left } : undefined;
  return (
    <td className={`px-3 py-2 ${stickyCls}`} style={style}>
      {children}
    </td>
  );
}
