import type { ItemKind, ProfileBank, ProfileItem } from '../../types';
import { formatDateRange } from './dates';
import type { BuildPlan, BuildSummary, PlanKind, PlanSection, Suggestion } from './buildApi';

export type DraftVersion = { id: string; text: string };
export type DraftPoint = { id: string; text: string; tags: string[]; skills: string[]; on: boolean; alt: string | null; versions: DraftVersion[] };
export type DraftItem = { id: string; kind: PlanKind; parentId: string | null; title: string; sub: string; dates: string; tags: string[]; on: boolean; points: DraftPoint[] };
export type DraftSkill = { id: string; name: string; category: string; tags: string[]; on: boolean };
export type Draft = { items: DraftItem[]; skills: DraftSkill[] };

export const planKinds: PlanKind[] = ['experience', 'education', 'projects', 'certifications', 'volunteering', 'awards', 'custom'];
export const kindLabels: Record<PlanKind, string> = { experience: 'Experience', education: 'Education', projects: 'Projects', certifications: 'Certifications', volunteering: 'Volunteering', awards: 'Awards', custom: 'Other sections' };
const defaultSectionOrder = ['experience', 'education', 'projects', 'skills', 'certifications', 'volunteering', 'awards', 'custom'];
/** Awards and volunteering are never ticked by a free build unless the focus asks for them. */
const optInKinds: PlanKind[] = ['awards', 'volunteering'];

const kindOfItem: Partial<Record<ItemKind, PlanKind>> = { experience: 'experience', education: 'education', custom: 'custom', project: 'projects', certification: 'certifications', award: 'awards', volunteering: 'volunteering' };
export const planKind = (kind: ItemKind): PlanKind | null => kindOfItem[kind] ?? null;

export const itemTitle = (item: ProfileItem) => item.data.title || item.data.qualification || item.data.name || item.data.heading || 'Untitled';
export const itemSub = (item: ProfileItem) => item.data.organisation || item.data.institution || item.data.role || item.data.issuer || item.data.awarder || '';
export const itemDates = (item: ProfileItem) => item.data.dates_text || formatDateRange({ start: item.data.start, end: item.data.end, current: item.data.current });

// Newest first: current roles lead, then by end date, then by start date. ISO-like strings compare correctly.
const recency = (item: ProfileItem) => item.data.current ? '9999-99' : (item.data.end || item.data.start || '');
function newestFirst(a: ProfileItem, b: ProfileItem) {
  const byEnd = recency(b).localeCompare(recency(a));
  return byEnd || (b.data.start || '').localeCompare(a.data.start || '') || a.position - b.position;
}

export function bankToDraft(bank: ProfileBank): Draft {
  const active = bank.items.filter((item) => !item.archived_at);
  const items: DraftItem[] = [];
  for (const kind of planKinds) {
    for (const item of active.filter((row) => planKind(row.kind) === kind).sort(newestFirst)) {
      items.push({ id: item.id, kind, parentId: item.parent_id || null, title: itemTitle(item), sub: itemSub(item), dates: itemDates(item), tags: item.tags || [], on: false,
        points: (item.data.bullets || []).map((point) => ({ id: point.id, text: point.text, tags: point.tags || [], skills: point.skills || [], on: false, alt: null, versions: (point.alternatives || []).map((version) => ({ id: version.id, text: version.text })) })) });
    }
  }
  const skills = active.filter((item) => item.kind === 'skill').sort((a, b) => a.position - b.position)
    .map((item) => ({ id: item.id, name: item.data.name || item.data.title || 'Skill', category: item.data.category || 'tool', tags: item.tags || [], on: false }));
  return { items, skills };
}

/** Point types and tags the user can focus a free build on. */
export function focusOptions(draft: Draft): string[] {
  const tags = new Set<string>();
  for (const item of draft.items) { item.tags.forEach((tag) => tags.add(tag)); item.points.forEach((point) => point.tags.forEach((tag) => tags.add(tag))); }
  return [...tags].sort((a, b) => a.localeCompare(b));
}

const overlaps = (tags: string[], focus: string[]) => tags.some((tag) => focus.includes(tag));

/** Free build: tick everything matching the focus (all if none), newest first, at most `cap` points per item. */
export function applyFocus(draft: Draft, focus: string[], cap: number): Draft {
  const limit = Math.max(1, cap);
  const items = draft.items.map((item) => {
    const matching = !focus.length || overlaps(item.tags, focus) ? item.points : item.points.filter((point) => overlaps(point.tags, focus));
    const on = optInKinds.includes(item.kind) ? !!focus.length && (matching.length > 0 || overlaps(item.tags, focus))
      : !focus.length || matching.length > 0 || item.kind === 'education' || overlaps(item.tags, focus);
    const eligible = matching.length ? matching : item.points; // education with no matching point falls back to all of its points
    const chosen = new Set(eligible.slice(0, limit).map((point) => point.id));
    return { ...item, on, points: item.points.map((point) => ({ ...point, on: on && chosen.has(point.id), alt: null })) };
  });
  const used = new Set(items.flatMap((item) => item.points.filter((point) => point.on).flatMap((point) => point.skills.map((skill) => skill.toLowerCase()))));
  let skills = draft.skills.map((skill) => ({ ...skill, on: !focus.length || overlaps(skill.tags, focus) || used.has(skill.name.toLowerCase()) }));
  if (!skills.some((skill) => skill.on)) skills = skills.map((skill) => ({ ...skill, on: true }));
  return { items, skills };
}

/** Build for a job: tick what the suggested plan picked, in its order, and leave the rest of the bank unticked after it. */
export function applySuggestion(draft: Draft, suggestion: Suggestion): Draft {
  const items: DraftItem[] = [];
  const planned = new Map<string, { kind: PlanKind; picks: { bullet_id: string; alternative_id?: string }[] }>();
  const order: string[] = [];
  for (const section of suggestion.plan.sections) {
    if (section.kind === 'skills') continue;
    for (const entry of section.items) { planned.set(entry.item_id, { kind: section.kind, picks: entry.picks || [] }); order.push(entry.item_id); }
  }
  for (const kind of planKinds) {
    const ofKind = draft.items.filter((item) => item.kind === kind);
    const first = order.map((id) => ofKind.find((item) => item.id === id)).filter((item): item is DraftItem => !!item);
    for (const item of [...first, ...ofKind.filter((row) => !planned.has(row.id))]) {
      const plan = planned.get(item.id);
      if (!plan) { items.push({ ...item, on: false, points: item.points.map((point) => ({ ...point, on: false, alt: null })) }); continue; }
      const picked = plan.picks.map((pick) => ({ pick, point: item.points.find((point) => point.id === pick.bullet_id) })).filter((row): row is { pick: typeof row.pick; point: DraftPoint } => !!row.point);
      const pickedIds = new Set(picked.map((row) => row.point.id));
      items.push({ ...item, on: true, points: [
        ...picked.map(({ pick, point }) => ({ ...point, on: true, alt: pick.alternative_id && point.versions.some((version) => version.id === pick.alternative_id) ? pick.alternative_id : null })),
        ...item.points.filter((point) => !pickedIds.has(point.id)).map((point) => ({ ...point, on: false, alt: null })),
      ] });
    }
  }
  const skillSection = suggestion.plan.sections.find((section): section is Extract<PlanSection, { kind: 'skills' }> => section.kind === 'skills');
  const chosenSkills = new Set(skillSection?.skill_ids || []);
  return { items, skills: draft.skills.map((skill) => ({ ...skill, on: chosenSkills.has(skill.id) })) };
}

export function draftToPlan(draft: Draft, meta: { title: string; template: BuildPlan['template']; job_id: string | null; summary: BuildSummary; sectionOrder?: string[] }): BuildPlan {
  const sections: PlanSection[] = [];
  for (const kind of planKinds) {
    const items = draft.items.filter((item) => item.kind === kind && item.on).map((item) => ({ item_id: item.id,
      picks: item.points.filter((point) => point.on).map((point) => point.alt ? { bullet_id: point.id, alternative_id: point.alt } : { bullet_id: point.id }) }));
    if (items.length) sections.push({ kind, items });
  }
  const skillIds = draft.skills.filter((skill) => skill.on).map((skill) => skill.id);
  if (skillIds.length) sections.push({ kind: 'skills', skill_ids: skillIds });
  const order = [...(meta.sectionOrder || []).filter((kind, index, all) => all.indexOf(kind) === index), ...defaultSectionOrder];
  const rank = (kind: string) => order.indexOf(kind);
  sections.sort((a, b) => rank(a.kind) - rank(b.kind));
  return { title: meta.title, template: meta.template, job_id: meta.job_id, summary: meta.summary, sections };
}

export function countSelected(draft: Draft) {
  const items = draft.items.filter((item) => item.on);
  return { items: items.length, points: items.reduce((total, item) => total + item.points.filter((point) => point.on).length, 0), skills: draft.skills.filter((skill) => skill.on).length };
}

// Immutable edits used by the pickers.
const mapItem = (draft: Draft, id: string, change: (item: DraftItem) => DraftItem): Draft => ({ ...draft, items: draft.items.map((item) => item.id === id ? change(item) : item) });
/** Ticking an item with nothing ticked picks its first `cap` points, so it never lands on the resume empty. */
export function toggleItem(draft: Draft, id: string, on: boolean, cap = 4): Draft {
  return mapItem(draft, id, (item) => ({ ...item, on, points: on && !item.points.some((point) => point.on) ? item.points.map((point, index) => ({ ...point, on: index < cap })) : item.points }));
}
export function togglePoint(draft: Draft, itemId: string, pointId: string, on: boolean): Draft {
  return mapItem(draft, itemId, (item) => ({ ...item, on: on ? true : item.on, points: item.points.map((point) => point.id === pointId ? { ...point, on } : point) }));
}
export function setVersion(draft: Draft, itemId: string, pointId: string, alt: string | null): Draft {
  return mapItem(draft, itemId, (item) => ({ ...item, points: item.points.map((point) => point.id === pointId ? { ...point, alt } : point) }));
}
export function toggleSkill(draft: Draft, id: string, on: boolean): Draft { return { ...draft, skills: draft.skills.map((skill) => skill.id === id ? { ...skill, on } : skill) }; }
function swap<T>(rows: T[], from: number, to: number): T[] { if (to < 0 || to >= rows.length) return rows; const next = [...rows]; [next[from], next[to]] = [next[to], next[from]]; return next; }
export function movePoint(draft: Draft, itemId: string, pointId: string, delta: -1 | 1): Draft {
  return mapItem(draft, itemId, (item) => { const index = item.points.findIndex((point) => point.id === pointId); return { ...item, points: swap(item.points, index, index + delta) }; });
}
/** The experience a project is shown under in the pickers, or null. The resume itself stays flat. */
export function nestedUnder(draft: Draft, item: DraftItem): string | null {
  return item.kind === 'projects' && item.parentId && draft.items.some((row) => row.id === item.parentId && row.kind === 'experience') ? item.parentId : null;
}
/** Moves an item among the items of its own kind (and, for a nested project, of its own job). */
export function moveDraftItem(draft: Draft, id: string, delta: -1 | 1): Draft {
  const item = draft.items.find((row) => row.id === id);
  if (!item) return draft;
  const sameKind = draft.items.filter((row) => row.kind === item.kind && nestedUnder(draft, row) === nestedUnder(draft, item));
  const target = sameKind[sameKind.indexOf(item) + delta];
  if (!target) return draft;
  const from = draft.items.indexOf(item), to = draft.items.indexOf(target);
  return { ...draft, items: swap(draft.items, from, to) };
}

// Manual choices survive a refreshed suggestion or a new focus: every edit in the pickers is recorded, then laid over the new defaults.
export type Overrides = { items: Record<string, boolean>; points: Record<string, boolean>; versions: Record<string, string | null>; skills: Record<string, boolean>; itemOrder: Partial<Record<PlanKind, string[]>>; pointOrder: Record<string, string[]> };
export const noOverrides = (): Overrides => ({ items: {}, points: {}, versions: {}, skills: {}, itemOrder: {}, pointOrder: {} });
const pointKey = (itemId: string, pointId: string) => `${itemId}:${pointId}`;
const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((value, index) => value === b[index]);

/** Adds what changed between `before` and `after` (one edit by the user) to the recorded manual choices. */
export function recordOverrides(before: Draft, after: Draft, recorded: Overrides): Overrides {
  const next: Overrides = { items: { ...recorded.items }, points: { ...recorded.points }, versions: { ...recorded.versions }, skills: { ...recorded.skills }, itemOrder: { ...recorded.itemOrder }, pointOrder: { ...recorded.pointOrder } };
  for (const item of after.items) {
    const was = before.items.find((row) => row.id === item.id);
    if (!was) continue;
    if (was.on !== item.on) next.items[item.id] = item.on;
    for (const point of item.points) {
      const wasPoint = was.points.find((row) => row.id === point.id);
      if (!wasPoint) continue;
      if (wasPoint.on !== point.on) next.points[pointKey(item.id, point.id)] = point.on;
      if (wasPoint.alt !== point.alt) next.versions[pointKey(item.id, point.id)] = point.alt;
    }
    const ids = item.points.map((point) => point.id);
    if (!sameList(ids, was.points.map((point) => point.id))) next.pointOrder[item.id] = ids;
  }
  for (const kind of planKinds) {
    const ids = after.items.filter((item) => item.kind === kind).map((item) => item.id);
    if (!sameList(ids, before.items.filter((item) => item.kind === kind).map((item) => item.id))) next.itemOrder[kind] = ids;
  }
  for (const skill of after.skills) {
    const was = before.skills.find((row) => row.id === skill.id);
    if (was && was.on !== skill.on) next.skills[skill.id] = skill.on;
  }
  return next;
}

/** Orders `rows` by `wanted` where the ids exist; rows not named keep their place after the named ones. */
function reorder<T extends { id: string }>(rows: T[], wanted: string[] | undefined): T[] {
  if (!wanted) return rows;
  const named = wanted.map((id) => rows.find((row) => row.id === id)).filter((row): row is T => !!row);
  return [...named, ...rows.filter((row) => !wanted.includes(row.id))];
}

/** The new defaults with the user's earlier choices put back for everything still present; other items keep the defaults. */
export function applyOverrides(draft: Draft, overrides: Overrides): Draft {
  const items: DraftItem[] = [];
  for (const kind of planKinds) {
    for (const item of reorder(draft.items.filter((row) => row.kind === kind), overrides.itemOrder[kind])) {
      const points = reorder(item.points, overrides.pointOrder[item.id]).map((point) => {
        const key = pointKey(item.id, point.id);
        const alt = key in overrides.versions && (overrides.versions[key] === null || point.versions.some((version) => version.id === overrides.versions[key])) ? overrides.versions[key] : point.alt;
        return { ...point, on: key in overrides.points ? overrides.points[key] : point.on, alt };
      });
      items.push({ ...item, on: item.id in overrides.items ? overrides.items[item.id] : item.on, points });
    }
  }
  return { items, skills: draft.skills.map((skill) => skill.id in overrides.skills ? { ...skill, on: overrides.skills[skill.id] } : skill) };
}
