import type { Resume, ResumeContent, ResumeEntry, ResumeSection } from './types';

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
  return { ...content, sections: content.sections.map((section) => section.id !== sectionId ? section : { ...section, entries: section.entries.map((entry) => entry.id === entryId ? { ...entry, ...patch } : entry) }) };
}
export function updateBullet(content: ResumeContent, sectionId: string, entryId: string, bulletIndex: number, value: string): ResumeContent {
  const section = content.sections.find((item) => item.id === sectionId), entry = section?.entries.find((item) => item.id === entryId);
  if (!entry) return content;
  const bullets = [...entry.bullets]; bullets[bulletIndex] = value;
  return updateEntry(content, sectionId, entryId, { bullets });
}
export function removeSection(content: ResumeContent, sectionId: string): ResumeContent { return { ...content, sections: content.sections.filter((section) => section.id !== sectionId) }; }
export function removeEntry(section: ResumeSection, entryId: string): ResumeSection { return { ...section, entries: section.entries.filter((entry) => entry.id !== entryId) }; }
export function patchResume(resume: Resume, changes: Partial<Resume>): Resume { return { ...resume, ...changes }; }
