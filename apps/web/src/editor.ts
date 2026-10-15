import type { BulletSource, ItemData, ItemKind, ProfileItem, ProfilePoint, Resume, ResumeContent, ResumeEntry, ResumeSection, SectionKind } from './types';

export const blankContent = (): ResumeContent => ({ name: '', email: '', phone: '', location: '', summary: '', sections: [
  { id: crypto.randomUUID(), title: 'Experience', entries: [] },
  { id: crypto.randomUUID(), title: 'Education', entries: [] },
  { id: crypto.randomUUID(), title: 'Projects', entries: [] },
  { id: crypto.randomUUID(), title: 'Skills', entries: [] },
] });
export function moveItem<T>(items: T[], index: number, delta: -1 | 1): T[] {
  const next = [...items], target = index + delta;
  if (target < 0 || target >= next.length) return next;
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
export function addSection(content: ResumeContent, title = 'New section'): ResumeContent {
  return { ...content, sections: [...content.sections, { id: crypto.randomUUID(), title, entries: [] }] };
}
export function addEntry(section: ResumeSection): ResumeSection {
  const entry: ResumeEntry = { id: crypto.randomUUID(), heading: '', subheading: '', dates: '', bullets: [''] };
  return { ...section, entries: [...section.entries, entry] };
}
export function updateEntry(content: ResumeContent, sectionId: string, entryId: string, patch: Partial<ResumeEntry>): ResumeContent {
  return updateEntryWith(content, sectionId, entryId, (entry) => patchEntryFields(entry, patch));
}
/** Hand-editing the dates text drops the structured date_range, so a later date-format change can't bring the old dates back. */
export function patchEntryFields(entry: ResumeEntry, patch: Partial<ResumeEntry>): ResumeEntry {
  const next = { ...entry, ...patch };
  if ('dates' in patch && patch.dates !== entry.dates && !('date_range' in patch)) delete next.date_range;
  return next;
}
export function updateEntryWith(content: ResumeContent, sectionId: string, entryId: string, change: (entry: ResumeEntry) => ResumeEntry): ResumeContent {
  return { ...content, sections: content.sections.map((section) => section.id !== sectionId ? section : { ...section, entries: section.entries.map((entry) => entry.id === entryId ? change(entry) : entry) }) };
}

// Point (bullet) helpers. `bullets` and `bullet_sources` stay the same length whenever bullet_sources is present.
const sourcesOf = (entry: ResumeEntry): (BulletSource | null)[] | undefined => entry.bullet_sources && entry.bullets.map((_, i) => entry.bullet_sources?.[i] ?? null);
export function addBullet(entry: ResumeEntry, text = '', source: BulletSource | null = null): ResumeEntry {
  const sources = sourcesOf(entry);
  const next: ResumeEntry = { ...entry, bullets: [...entry.bullets, text] };
  if (sources || source) next.bullet_sources = [...(sources ?? entry.bullets.map(() => null)), source];
  return next;
}
export function removeBullet(entry: ResumeEntry, index: number): ResumeEntry {
  if (index < 0 || index >= entry.bullets.length) return entry;
  const sources = sourcesOf(entry);
  const next: ResumeEntry = { ...entry, bullets: entry.bullets.filter((_, i) => i !== index) };
  if (sources) next.bullet_sources = sources.filter((_, i) => i !== index);
  return next;
}
export function setBullet(entry: ResumeEntry, index: number, text: string): ResumeEntry {
  if (index < 0 || index >= entry.bullets.length) return entry;
  const bullets = [...entry.bullets]; bullets[index] = text;
  return { ...entry, bullets };
}
export function moveBullet(entry: ResumeEntry, index: number, delta: -1 | 1): ResumeEntry {
  const target = index + delta;
  if (index < 0 || index >= entry.bullets.length || target < 0 || target >= entry.bullets.length) return entry;
  const sources = sourcesOf(entry);
  const next: ResumeEntry = { ...entry, bullets: moveItem(entry.bullets, index, delta) };
  if (sources) next.bullet_sources = moveItem(sources, index, delta);
  return next;
}
/** Swap a point to another version of the same profile point; the chosen wording becomes its base text. */
export function replaceWithVersion(entry: ResumeEntry, index: number, text: string, alternativeId: string | null): ResumeEntry {
  const sources = sourcesOf(entry), current = sources?.[index];
  if (!sources || !current) return setBullet(entry, index, text);
  sources[index] = { bullet_id: current.bullet_id, alternative_id: alternativeId, base_text: text };
  return { ...setBullet(entry, index, text), bullet_sources: sources };
}
/** After a successful profile write: record the saved point as this bullet's source and the item's new revision. */
export function markSaved(entry: ResumeEntry, index: number, source: BulletSource, itemRevision?: number): ResumeEntry {
  if (index < 0 || index >= entry.bullets.length) return entry;
  const sources = sourcesOf(entry) ?? entry.bullets.map(() => null);
  sources[index] = source;
  const next: ResumeEntry = { ...entry, bullet_sources: sources };
  if (itemRevision !== undefined && entry.source) next.source = { ...entry.source, item_revision: itemRevision };
  return next;
}
export function isEdited(entry: ResumeEntry, index: number): boolean {
  const source = entry.bullet_sources?.[index];
  return !!source && entry.bullets[index] !== source.base_text;
}
export function updateBullet(content: ResumeContent, sectionId: string, entryId: string, bulletIndex: number, value: string): ResumeContent {
  return updateEntryWith(content, sectionId, entryId, (entry) => setBullet(entry, bulletIndex, value));
}

/** The section's kind: the saved one, otherwise inferred from its title so old resumes need no migration. */
export function sectionKind(section: Pick<ResumeSection, 'title' | 'kind'>): SectionKind {
  if (section.kind) return section.kind;
  const title = section.title.trim().toLowerCase().replace(/\s+/g, ' ');
  if (/^((professional|work|relevant) )?(experience|employment)$/.test(title) || /^(work|employment|career|professional) history$/.test(title)) return 'experience';
  if (/^(education|education and training|academic background)$/.test(title)) return 'education';
  if (/^((selected|personal|key|side) )?projects?$/.test(title)) return 'projects';
  if (/^((technical|key|core) )?skills$/.test(title)) return 'skills';
  if (/^((professional|relevant) )?(certifications?|licen[cs]es?)( (and|&) (certifications?|licen[cs]es?))?$/.test(title) || /^(licen[cs]es?|certifications?) (and|&) (certifications?|licen[cs]es?)$/.test(title)) return 'certifications';
  if (/^(awards?|honou?rs?|(awards?|honou?rs?) (and|&) (awards?|honou?rs?|achievements?|scholarships?)|honou?rs? (and|&) awards?)$/.test(title)) return 'awards';
  if (/^(volunteering|volunteer|volunteer experience|volunteering experience)$/.test(title)) return 'volunteering';
  return 'custom';
}
export function removeSection(content: ResumeContent, sectionId: string): ResumeContent { return { ...content, sections: content.sections.filter((section) => section.id !== sectionId) }; }
export function removeEntry(section: ResumeSection, entryId: string): ResumeSection { return { ...section, entries: section.entries.filter((entry) => entry.id !== entryId) }; }
export function patchResume(resume: Resume, changes: Partial<Resume>): Resume { return { ...resume, ...changes }; }

// Profile bank -> resume entries
export const itemKindFor = (kind: SectionKind): ItemKind | null => ({ experience: 'experience', education: 'education', projects: 'project', custom: 'custom', skills: null, certifications: 'certification', awards: 'award', volunteering: 'volunteering' } as const)[kind];
const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function formatMonth(value?: string | null) {
  const match = /^(\d{4})(?:-(\d{2}))?/.exec(value || '');
  if (!match) return value || '';
  const month = match[2] ? months[Number(match[2]) - 1] : '';
  return month ? `${month} ${match[1]}` : match[1];
}
export function formatItemDates(data: ItemData): string {
  if (data.dates_text) return data.dates_text;
  const start = formatMonth(data.start), end = data.current ? 'Present' : formatMonth(data.end);
  return start && end ? `${start} – ${end}` : start || end;
}
export function itemHeadings(item: ProfileItem): { heading: string; subheading: string } {
  const data = item.data, join = (...parts: (string | undefined)[]) => parts.filter(Boolean).join(' · ');
  if (item.kind === 'education') return { heading: data.qualification || data.title || '', subheading: join(data.institution, data.grade) };
  if (item.kind === 'project') return { heading: data.name || data.title || '', subheading: data.role || '' };
  if (item.kind === 'custom') return { heading: data.title || data.heading || '', subheading: '' };
  if (item.kind === 'certification') return { heading: data.name || data.title || '', subheading: data.issuer || '' };
  if (item.kind === 'award') return { heading: data.title || data.name || '', subheading: data.awarder || '' };
  if (item.kind === 'volunteering') return { heading: data.title || data.name || '', subheading: data.organisation || '' };
  return { heading: data.title || data.name || '', subheading: join(data.organisation, data.location) };
}
export const itemLabel = (item: ProfileItem) => { const { heading, subheading } = itemHeadings(item); return [heading, subheading.split(' · ')[0]].filter(Boolean).join(' · ') || 'Untitled'; };
/** A resume entry for a profile item: structured dates plus the chosen points (and which version of each), all linked back to the item. */
export function entryFromItem(item: ProfileItem, picks: { point: ProfilePoint; alternativeId?: string | null }[]): ResumeEntry {
  const { heading, subheading } = itemHeadings(item), data = item.data;
  const bullets = picks.map(({ point, alternativeId }) => alternativeId ? point.alternatives.find((version) => version.id === alternativeId)?.text ?? point.text : point.text);
  const entry: ResumeEntry = {
    id: crypto.randomUUID(), heading, subheading, dates: formatItemDates(data), bullets,
    source: { item_id: item.id, item_revision: item.revision },
    bullet_sources: picks.map(({ point, alternativeId }, i) => ({ bullet_id: point.id, alternative_id: alternativeId ?? null, base_text: bullets[i] })),
  };
  if ((data.start || data.end || data.current)) entry.date_range = { start: data.start ?? null, end: data.end ?? null, current: !!data.current };
  return entry;
}
export function addEntryToSection(section: ResumeSection, entry: ResumeEntry): ResumeSection { return { ...section, entries: [...section.entries, entry] }; }
