import { useEffect, useReducer } from 'react';
import { api } from '../../api';
import type { BulletSource, ProfileBank, ProfileItem, ProfilePoint, ResumeEntry } from '../../types';

export type BankHandle = { status: 'loading' | 'ready' | 'error'; bank: ProfileBank | null; error: string; refresh: () => Promise<ProfileBank | null> };

// The bank is loaded once and shared by every section editor on the page. It is dropped when the last editor unmounts.
type Store = { status: BankHandle['status']; bank: ProfileBank | null; error: string };
let store: Store = { status: 'loading', bank: null, error: '' };
let started = false, generation = 0, mounted = 0, clearTimer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
const publish = (next: Store) => { store = next; listeners.forEach((listener) => listener()); };

async function load(): Promise<ProfileBank | null> {
  const mine = ++generation;
  try {
    const bank = await api.getBank();
    if (mine === generation) publish({ status: 'ready', bank, error: '' });
    return bank;
  } catch (cause) {
    // Keep a bank we already have; only a first load failure disables the profile controls.
    if (mine === generation && !store.bank) publish({ status: 'error', bank: null, error: (cause as Error).message || 'Your profile could not be loaded.' });
    return store.bank;
  }
}
export function resetBankCache() { generation++; started = false; store = { status: 'loading', bank: null, error: '' }; }

export function useProfileBank(override?: BankHandle): BankHandle {
  const [, rerender] = useReducer((count: number) => count + 1, 0);
  useEffect(() => {
    if (override) return;
    listeners.add(rerender); mounted++;
    if (clearTimer) { clearTimeout(clearTimer); clearTimer = undefined; }
    if (!started) { started = true; void load(); } else rerender();
    return () => {
      listeners.delete(rerender); mounted--;
      if (mounted === 0) clearTimer = setTimeout(() => { if (mounted === 0) resetBankCache(); }, 0);
    };
  }, [override]);
  return override ?? { ...store, refresh: load };
}

export const bankItem = (bank: ProfileBank | null, itemId?: string): ProfileItem | undefined => bank?.items.find((item) => item.id === itemId && !item.archived_at);
export const bankPoint = (item: ProfileItem | undefined, pointId?: string): ProfilePoint | undefined => item?.data.bullets.find((point) => point.id === pointId);
/** The profile point behind a resume bullet, or undefined for points written in the resume. */
export function linkedPoint(bank: ProfileBank | null, entry: ResumeEntry, index: number): { item: ProfileItem; point: ProfilePoint; source: BulletSource } | undefined {
  const source = entry.bullet_sources?.[index];
  if (!source || !entry.source) return undefined;
  const item = bankItem(bank, entry.source.item_id), point = bankPoint(item, source.bullet_id);
  return item && point ? { item, point, source } : undefined;
}
/** Version 1 is the main wording; later versions are the alternatives. `id` is null for the main wording. */
export const pointVersions = (point: ProfilePoint): { id: string | null; text: string }[] => [{ id: null, text: point.text }, ...point.alternatives.map((alt) => ({ id: alt.id, text: alt.text }))];
export const clip = (text: string, length = 70) => text.length > length ? `${text.slice(0, length - 1).trimEnd()}…` : text;
