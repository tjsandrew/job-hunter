// The first page of each Discover list, kept in browser memory only (nothing is written to storage and it is gone
// on reload or sign-out). Switching between For you, All, Saved and Passed shows the last answer at once.
// The key carries everything that changes what a list contains (user, tab, search, the refresh counter that every
// save, pass, preference or profile change bumps), so a stale list can only be shown for an unchanged view.
const FRESH_MS = 60_000;       // younger than this: show it and do not ask the server again
const USABLE_MS = 10 * 60_000; // older than FRESH: show it, then fetch a newer one; older than this: ignore it
const MAX_ENTRIES = 40;

const entries = new Map<string, { value: unknown; at: number }>();

export const listKey = (...parts: Array<string | number | boolean>) => JSON.stringify(parts);

export function readList<T>(key: string, now = Date.now()): { value: T; fresh: boolean } | undefined {
  const hit = entries.get(key);
  if (!hit) return undefined;
  const age = now - hit.at;
  if (age > USABLE_MS) { entries.delete(key); return undefined; }
  return { value: hit.value as T, fresh: age <= FRESH_MS };
}

export function writeList(key: string, value: unknown, now = Date.now()) {
  entries.delete(key);
  entries.set(key, { value, at: now });
  while (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value as string);
}

export const dropList = (key: string) => { entries.delete(key); };

export const clearLists = () => entries.clear();

/** The user's resume defaults: read for every new resume, so they are kept for a minute and dropped when they are saved. */
export const SETTINGS_KEY = listKey('settings');
