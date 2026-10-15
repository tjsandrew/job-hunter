import { api, HttpError } from '../../api';
import { itemKindFor, sectionKind } from '../../editor';
import type { BulletSource, ItemData, ProfileItem, ProfilePoint, ResumeEntry, ResumeSection } from '../../types';

/** Result of a profile write. The resume is only changed after `ok`. */
export type SaveResult =
  | { ok: true; item: ProfileItem; source: BulletSource; message: string; keepsLink: boolean; undo: UndoPlan }
  | { ok: false; reason: 'conflict'; currentText: string; itemId: string; pointId: string }
  | { ok: false; reason: 'limit'; message: string; mode: 'update' | 'version'; versions: { id: string; text: string }[]; mainText: string }
  | { ok: false; reason: 'error'; message: string };

/** How to take a profile save back: restore the item's earlier data, or archive an item the save created. */
export type UndoPlan = { itemId: string; expectedRevision: number; restore?: ItemData };
/** Choices made in the version-limit chooser. */
export type SaveOptions = { replaceAlternativeId?: string; keepPrevious?: boolean };

export const LIMIT_MESSAGE = 'A point keeps up to 5 versions';
export const LIMIT_TITLE = 'Your profile keeps 5 versions of a point. Replace which one?';
export const UNDO_CONFLICT_MESSAGE = "Can't undo: this point changed since";
export const CONFLICT_MESSAGE = 'This point changed in your profile since you added it';
export type NewPointTarget = { itemId: string } | { create: true };

const isConflict = (cause: unknown) => cause instanceof HttpError && cause.status === 409;
const isLimit = (cause: unknown) => cause instanceof HttpError && cause.code === 'POINT_VERSION_LIMIT';
/** The limit result lists the other wordings the user may drop. The main wording is never offered. */
const limitFailure = (point: ProfilePoint | undefined, mode: 'update' | 'version', keep?: string | null): SaveResult => ({
  ok: false, reason: 'limit', message: LIMIT_MESSAGE, mode, mainText: point?.text ?? '',
  versions: (point?.alternatives ?? []).filter((version) => version.id !== keep).map(({ id, text }) => ({ id, text })),
});
const failure = (cause: unknown): SaveResult => isConflict(cause) ? { ok: false, reason: 'error', message: 'Your profile changed while saving. Nothing was saved; try again.' }
  : { ok: false, reason: 'error', message: (cause as Error)?.message || 'Could not save to your profile.' };
const versionText = (point: ProfilePoint, alternativeId?: string | null) => alternativeId ? point.alternatives.find((version) => version.id === alternativeId)?.text : point.text;
const newest = (before: ProfilePoint | undefined, after: ProfilePoint | undefined) => {
  const known = new Set(before?.alternatives.map((version) => version.id));
  return after?.alternatives.find((version) => !known.has(version.id)) ?? after?.alternatives.at(-1);
};

/** Update in profile: replaces the version this point came from. Writes with the item's current revision, after checking nobody changed that wording. */
export async function updateInProfile(entry: ResumeEntry, index: number, options: SaveOptions = {}): Promise<SaveResult> {
  const source = entry.bullet_sources?.[index], link = entry.source;
  if (!source || !link) return { ok: false, reason: 'error', message: 'This point is not linked to your profile.' };
  const text = entry.bullets[index];
  const stale = (current: ProfileItem): SaveResult | undefined => {
    const point = current.data.bullets.find((row) => row.id === source.bullet_id);
    if (!point) return { ok: false, reason: 'error', message: 'This point was removed from your profile. Use Save as new point instead.' };
    const live = versionText(point, source.alternative_id);
    return live === source.base_text ? undefined : { ok: false, reason: 'conflict', currentText: live ?? point.text, itemId: current.id, pointId: point.id };
  };
  try {
    const item = await api.getItem(link.item_id);
    const changed = stale(item);
    if (changed) return changed;
    try {
      const saved = await api.updatePoint(item.id, source.bullet_id, { expected_revision: item.revision, text, ...(source.alternative_id ? { alternative_id: source.alternative_id } : {}), ...(options.keepPrevious === false ? { keep_previous: false } : {}), ...(options.replaceAlternativeId ? { replace_alternative_id: options.replaceAlternativeId } : {}) });
      return { ok: true, item: saved, source: { bullet_id: source.bullet_id, alternative_id: source.alternative_id ?? null, base_text: text }, message: 'Updated in your profile.', keepsLink: true, undo: { itemId: item.id, expectedRevision: saved.revision, restore: item.data } };
    } catch (cause) {
      if (isLimit(cause)) return limitFailure(item.data.bullets.find((row) => row.id === source.bullet_id), 'update', source.alternative_id);
      if (!isConflict(cause)) return failure(cause);
      const latest = await api.getItem(link.item_id).catch(() => item);
      const point = latest.data.bullets.find((row) => row.id === source.bullet_id);
      return { ok: false, reason: 'conflict', currentText: (point && versionText(point, source.alternative_id)) ?? point?.text ?? '', itemId: item.id, pointId: source.bullet_id };
    }
  } catch (cause) { return failure(cause); }
}

/** Save as new version: adds this wording as another version of the point it came from. Used directly and after a conflict. */
export async function saveAsNewVersion(entry: ResumeEntry, index: number, options: SaveOptions = {}): Promise<SaveResult> {
  const source = entry.bullet_sources?.[index], link = entry.source;
  if (!source || !link) return { ok: false, reason: 'error', message: 'This point is not linked to your profile.' };
  const text = entry.bullets[index];
  try {
    const item = await api.getItem(link.item_id);
    const before = item.data.bullets.find((row) => row.id === source.bullet_id);
    if (!before) return { ok: false, reason: 'error', message: 'This point was removed from your profile. Use Save as new point instead.' };
    let saved: ProfileItem;
    try {
      saved = await api.addAlternative(item.id, source.bullet_id, { expected_revision: item.revision, text, ...(options.replaceAlternativeId ? { replace_alternative_id: options.replaceAlternativeId } : {}) });
    } catch (cause) {
      if (isLimit(cause)) return limitFailure(before, 'version');
      throw cause;
    }
    const version = newest(before, saved.data.bullets.find((row) => row.id === source.bullet_id));
    return { ok: true, item: saved, source: { bullet_id: source.bullet_id, alternative_id: version?.id ?? null, base_text: text }, message: 'Saved as a new version in your profile.', keepsLink: true, undo: { itemId: item.id, expectedRevision: saved.revision, restore: item.data } };
  } catch (cause) { return failure(cause); }
}

/** Data for a brand-new profile item described by a resume entry. */
export function newItemData(section: ResumeSection, entry: ResumeEntry): ItemData {
  const kind = itemKindFor(sectionKind(section)), range = entry.date_range;
  const dates = range ? { start: range.start, end: range.end, current: range.current } : { dates_text: entry.dates || undefined, current: false };
  const base = { bullets: [], ...dates };
  if (kind === 'education') return { ...base, qualification: entry.heading, institution: entry.subheading };
  if (kind === 'project') return { ...base, name: entry.heading, role: entry.subheading };
  if (kind === 'custom') return { bullets: [], title: entry.heading || section.title };
  return { ...base, title: entry.heading, organisation: entry.subheading };
}

/** Save as new point: adds this wording as a new point on an existing item, or on a new item created from the entry. */
export async function saveAsNewPoint(section: ResumeSection, entry: ResumeEntry, index: number, target: NewPointTarget): Promise<SaveResult> {
  const text = entry.bullets[index], kind = itemKindFor(sectionKind(section));
  try {
    let item: ProfileItem;
    let saved: ProfileItem;
    let point: ProfileItem['data']['bullets'][number] | undefined;
    if ('itemId' in target) {
      item = await api.getItem(target.itemId);
      const known = new Set(item.data.bullets.map((row) => row.id));
      saved = await api.addPoint(item.id, { expected_revision: item.revision, text });
      point = saved.data.bullets.find((row) => !known.has(row.id)) ?? saved.data.bullets.at(-1);
    } else {
      if (!kind) return { ok: false, reason: 'error', message: 'This section cannot be saved to your profile.' };
      // One request creates the item with its point, so a failure can't leave an empty item behind.
      const bulletId = `b_${crypto.randomUUID().replace(/-/g, '')}`;
      item = saved = await api.createItem({ kind, data: { ...newItemData(section, entry), bullets: [{ id: bulletId, text, tags: [], skills: [], alternatives: [] }] } });
      point = saved.data.bullets.find((row) => row.id === bulletId) ?? saved.data.bullets[0];
    }
    return { ok: true, item: saved, source: { bullet_id: point?.id ?? '', alternative_id: null, base_text: text }, message: 'itemId' in target ? 'Saved as a new point in your profile.' : 'Saved to a new item in your profile.', keepsLink: !!point && entry.source?.item_id === item.id, undo: 'itemId' in target ? { itemId: item.id, expectedRevision: saved.revision, restore: item.data } : { itemId: item.id, expectedRevision: saved.revision } };
  } catch (cause) { return failure(cause); }
}

export type UndoResult = { ok: true } | { ok: false; conflict: boolean; message: string };
/** Takes a profile save back. Never overwrites later edits: a changed item answers 409. */
export async function undoSave(plan: UndoPlan): Promise<UndoResult> {
  try {
    if (plan.restore) await api.revertItem(plan.itemId, { expected_revision: plan.expectedRevision, data: plan.restore });
    else await api.archiveItem(plan.itemId, plan.expectedRevision);
    return { ok: true };
  } catch (cause) {
    return isConflict(cause) ? { ok: false, conflict: true, message: UNDO_CONFLICT_MESSAGE } : { ok: false, conflict: false, message: (cause as Error)?.message || 'Could not undo.' };
  }
}
