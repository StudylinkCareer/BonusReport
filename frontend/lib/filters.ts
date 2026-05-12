'use client';

/**
 * SAVE TO: frontend/lib/filters.ts
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\lib\filters.ts)
 *
 * Shared Case Workload filter state — types, URL serialization, localStorage
 * persistence. Used by both the home page (FilterBar above the pillars) and
 * the review page (passes the same filter through to /api/cases).
 *
 * State flow:
 *   1. On page load: read filters from URL ?staff_id=...&signed_from=...
 *      If URL has any filter keys, use them.
 *      Else fall back to localStorage (last-saved filter from this browser).
 *   2. On Apply: write to URL AND localStorage.
 *   3. Pillar tile hrefs include the same query params so drilling carries
 *      the filter forward into the Review Dashboard.
 */

export type Filters = {
  staffId: number | null;        // null = no staff filter (review team)
  signedFrom: string;            // 'YYYY-MM-DD' or ''
  signedTo:   string;
  courseFrom: string;
  courseTo:   string;
  visaFrom:   string;
  visaTo:     string;
  bonusMonth: string;            // 'YYYY-MM' or ''
  qStudent:   string;            // wildcard
  qContract:  string;            // wildcard
  appStatus:  string;            // exact match
  clientType: string;            // exact match
  institutionId: number | null;
  officeId:      number | null;
};

export const EMPTY_FILTERS: Filters = {
  staffId: null,
  signedFrom: '', signedTo: '',
  courseFrom: '', courseTo: '',
  visaFrom: '',   visaTo: '',
  bonusMonth: '',
  qStudent: '', qContract: '',
  appStatus: '', clientType: '',
  institutionId: null, officeId: null,
};

const STORAGE_KEY = 'bonusreport.filters';

/**
 * Map a Filters object to URL query params (camelCase -> snake_case).
 * Empty / null values are omitted so the URL stays short.
 */
export function filtersToQuery(f: Filters): URLSearchParams {
  const q = new URLSearchParams();
  if (f.staffId !== null) q.set('staff_id', String(f.staffId));
  if (f.signedFrom) q.set('signed_from', f.signedFrom);
  if (f.signedTo)   q.set('signed_to',   f.signedTo);
  if (f.courseFrom) q.set('course_from', f.courseFrom);
  if (f.courseTo)   q.set('course_to',   f.courseTo);
  if (f.visaFrom)   q.set('visa_from',   f.visaFrom);
  if (f.visaTo)     q.set('visa_to',     f.visaTo);
  if (f.bonusMonth) q.set('bonus_month', f.bonusMonth);
  if (f.qStudent)   q.set('q_student',   f.qStudent);
  if (f.qContract)  q.set('q_contract',  f.qContract);
  if (f.appStatus)  q.set('app_status',  f.appStatus);
  if (f.clientType) q.set('client_type', f.clientType);
  if (f.institutionId !== null) q.set('institution_id', String(f.institutionId));
  if (f.officeId      !== null) q.set('office_id',      String(f.officeId));
  return q;
}

/** Inverse of filtersToQuery. Bad / missing values fall back to empty. */
export function filtersFromQuery(params: URLSearchParams): Filters {
  const num = (k: string): number | null => {
    const v = params.get(k);
    if (!v) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const str = (k: string): string => params.get(k) ?? '';
  return {
    staffId:       num('staff_id'),
    signedFrom:    str('signed_from'),
    signedTo:      str('signed_to'),
    courseFrom:    str('course_from'),
    courseTo:      str('course_to'),
    visaFrom:      str('visa_from'),
    visaTo:        str('visa_to'),
    bonusMonth:    str('bonus_month'),
    qStudent:      str('q_student'),
    qContract:     str('q_contract'),
    appStatus:     str('app_status'),
    clientType:    str('client_type'),
    institutionId: num('institution_id'),
    officeId:      num('office_id'),
  };
}

/** True if the URL contains at least one filter param (so URL takes priority over storage). */
export function urlHasFilters(params: URLSearchParams): boolean {
  for (const k of [
    'staff_id', 'signed_from', 'signed_to', 'course_from', 'course_to',
    'visa_from', 'visa_to', 'bonus_month', 'q_student', 'q_contract',
    'app_status', 'client_type', 'institution_id', 'office_id',
  ]) {
    if (params.has(k)) return true;
  }
  return false;
}

export function loadFiltersFromStorage(): Filters {
  if (typeof window === 'undefined') return EMPTY_FILTERS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_FILTERS;
    const parsed = JSON.parse(raw);
    return { ...EMPTY_FILTERS, ...parsed };
  } catch {
    return EMPTY_FILTERS;
  }
}

export function saveFiltersToStorage(f: Filters): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(f));
  } catch {
    // quota / privacy — ignore
  }
}

/** True iff any filter is set (used to decide whether to show Clear button). */
export function hasAnyFilter(f: Filters): boolean {
  return (
    f.staffId !== null ||
    !!f.signedFrom || !!f.signedTo ||
    !!f.courseFrom || !!f.courseTo ||
    !!f.visaFrom   || !!f.visaTo   ||
    !!f.bonusMonth ||
    !!f.qStudent   || !!f.qContract ||
    !!f.appStatus  || !!f.clientType ||
    f.institutionId !== null || f.officeId !== null
  );
}

/** Count of active filter fields (for the "N filters" badge). */
export function filterCount(f: Filters): number {
  let n = 0;
  if (f.staffId !== null) n++;
  if (f.signedFrom || f.signedTo) n++;
  if (f.courseFrom || f.courseTo) n++;
  if (f.visaFrom   || f.visaTo)   n++;
  if (f.bonusMonth) n++;
  if (f.qStudent)  n++;
  if (f.qContract) n++;
  if (f.appStatus) n++;
  if (f.clientType) n++;
  if (f.institutionId !== null) n++;
  if (f.officeId      !== null) n++;
  return n;
}
