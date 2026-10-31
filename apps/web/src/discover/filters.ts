import type { Job } from '../types';

/** Job preferences as the API stores them, and as Discover filters send them. */
export type JobPreferences = {
  roles: string[]; locations: string[]; work_modes: string[]; seniority: string;
  salary_min: string | number | null; salary_currency: string; salary_period: string;
};

/** Discover starts from the saved profile preferences ("profile") at every sign-in; "custom" lasts until sign-out. */
export type FilterMode = 'profile' | 'none' | 'custom';
/** ``posted`` is the "Posted" filter in days. It is separate from the preferences: it is never saved to the profile. */
export type FilterChoice = { mode: FilterMode; custom: JobPreferences; posted: number };

/** The "Posted" choices; the server accepts exactly these. A year is the widest, so a list never reaches back further. */
export const POSTED_OPTIONS = [
  { days: 3, label: 'Last 3 days' }, { days: 7, label: 'Last 7 days' }, { days: 14, label: 'Last 14 days' },
  { days: 30, label: 'Last 30 days' }, { days: 365, label: 'Past year' },
];
export const DEFAULT_POSTED = 14;
export const postedLabel = (days: number) => POSTED_OPTIONS.find((option) => option.days === days)?.label || 'Past year';
const postedDays = (value: unknown) => (POSTED_OPTIONS.some((option) => option.days === value) ? Number(value) : DEFAULT_POSTED);
export const defaultChoice = (): FilterChoice => ({ mode: 'profile', custom: emptyPreferences(), posted: DEFAULT_POSTED });

export const WORK_MODES = [{ value: 'remote', label: 'Remote' }, { value: 'hybrid', label: 'Hybrid' }, { value: 'onsite', label: 'On-site' }];

export const emptyPreferences = (): JobPreferences => ({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: '', salary_currency: 'SGD', salary_period: 'year' });

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.map((item) => String(item).trim()).filter(Boolean) : []);

/** Only the fields a filter uses, from whatever the API or storage returned. */
export function cleanPreferences(value: unknown): JobPreferences {
  const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  const salary = raw.salary_min;
  return {
    roles: strings(raw.roles), locations: strings(raw.locations), work_modes: strings(raw.work_modes),
    seniority: typeof raw.seniority === 'string' ? raw.seniority : '',
    salary_min: salary === null || salary === undefined || salary === '' ? '' : String(salary),
    salary_currency: typeof raw.salary_currency === 'string' && raw.salary_currency ? raw.salary_currency : 'SGD',
    salary_period: typeof raw.salary_period === 'string' && raw.salary_period ? raw.salary_period : 'year',
  };
}

export const samePreferences = (a: JobPreferences, b: JobPreferences) => JSON.stringify(cleanPreferences(a)) === JSON.stringify(cleanPreferences(b));

/** How many filters are set, for the "Filters (n)" button on small screens. */
export function activeCount(prefs: JobPreferences): number {
  return [prefs.roles.length, prefs.locations.length, prefs.work_modes.length, prefs.seniority, prefs.salary_min !== '' && prefs.salary_min !== null]
    .filter(Boolean).length;
}

/** Query parameters for a job list. No preferences are sent for the profile defaults, so the server reads the saved ones. */
export function filterQuery(choice: FilterChoice): Record<string, string | string[]> {
  const posted = { posted_within: String(postedDays(choice.posted)) };
  if (choice.mode === 'profile') return posted;
  if (choice.mode === 'none') return { filters: 'none', ...posted };
  const prefs = cleanPreferences(choice.custom);
  const query: Record<string, string | string[]> = { filters: 'custom', role: prefs.roles, location: prefs.locations, work_mode: prefs.work_modes, ...posted };
  if (prefs.seniority) query.seniority = prefs.seniority;
  if (prefs.salary_min !== '' && prefs.salary_min !== null && Number.isFinite(Number(prefs.salary_min))) {
    query.salary_min = String(Number(prefs.salary_min)); query.salary_currency = prefs.salary_currency; query.salary_period = prefs.salary_period;
  }
  return query;
}

/** The preferences a list is filtered by, for the pills and the match tags. */
export function activePreferences(choice: FilterChoice, saved: JobPreferences): JobPreferences {
  return choice.mode === 'profile' ? cleanPreferences(saved) : choice.mode === 'none' ? emptyPreferences() : cleanPreferences(choice.custom);
}

// Remembered per user for this browser session: sign-out clears session storage, so the next sign-in starts from the profile.
const storageKey = (user: string) => `jh-discover-filters:${user}`;

export function loadChoice(user: string): FilterChoice | null {
  try {
    const raw = JSON.parse(sessionStorage.getItem(storageKey(user)) || 'null');
    if (!raw || !['profile', 'none', 'custom'].includes(raw.mode)) return null;
    return { mode: raw.mode, custom: cleanPreferences(raw.custom), posted: postedDays(raw.posted) };
  } catch { return null; }
}

export function storeChoice(user: string, choice: FilterChoice) {
  try { sessionStorage.setItem(storageKey(user), JSON.stringify(choice)); } catch { /* private mode: the choice lasts until reload */ }
}

const periodFactor: Record<string, number> = { year: 1, month: 12, hour: 2080 };   // 40-hour weeks, as the server's salary filter assumes
const yearly = (amount: number, period: string | null | undefined) => {
  const key = (period || '').toLowerCase();
  const found = Object.keys(periodFactor).find((name) => key.includes(name));
  return found ? amount * periodFactor[found] : null;
};

/** Short "why this fits your filters" tags for a job card: work mode, location and salary that match. */
export function preferenceMatches(job: Job, prefs: JobPreferences): string[] {
  const tags: string[] = [];
  const mode = (job.work_mode || '').toLowerCase().replace(/[-_\s]/g, '');
  const wanted = prefs.work_modes.map((value) => value.toLowerCase().replace(/[-_\s]/g, ''));
  if (mode && wanted.includes(mode)) tags.push(WORK_MODES.find((item) => item.value === mode)?.label || job.work_mode!);
  const location = (job.location || '').toLowerCase();
  const place = prefs.locations.find((value) => location && location.includes(value.toLowerCase()));
  if (place) tags.push(place);
  const minimum = Number(prefs.salary_min);
  const offered = job.salary_max ?? job.salary_min;
  if (prefs.salary_min !== '' && prefs.salary_min !== null && Number.isFinite(minimum) && offered != null
      && (!job.salary_currency || job.salary_currency.toUpperCase() === prefs.salary_currency.toUpperCase())) {
    const offeredYear = yearly(Number(offered), job.salary_period), wantedYear = yearly(minimum, prefs.salary_period);
    if (offeredYear !== null && wantedYear !== null && offeredYear >= wantedYear) tags.push('Meets your salary');
  }
  return tags;
}
