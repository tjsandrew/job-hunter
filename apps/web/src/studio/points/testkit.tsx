import { useState } from 'react';
import { vi } from 'vitest';
import type { ProfileBank, ProfileItem, ResumeContent, ResumeEntry } from '../../types';
import { SectionEditor } from '../SectionEditor';
import type { BankHandle } from './bank';

export const experienceItem = (): ProfileItem => ({ id: 'item-1', kind: 'experience', position: 0, revision: 4, archived_at: null, origin: 'manual', import_id: null, parent_id: null, tags: [], data: {
  title: 'Backend Engineer', organisation: 'Harbour Metrics', location: 'Singapore', start: '2023-07', current: true, bullets: [
    { id: 'b1', text: 'Built FastAPI services', alternatives: [{ id: 'v1', text: 'Designed FastAPI services at scale' }] },
    { id: 'b2', text: 'Made dashboards 4x faster', alternatives: [] },
    { id: 'b3', text: 'Mentored two interns', alternatives: [] },
  ] } });
export const otherItem = (): ProfileItem => ({ ...experienceItem(), id: 'item-2', position: 1, revision: 1, data: { title: 'Data Analyst', organisation: 'Fictional Co', start: '2020', end: '2022-06', bullets: [{ id: 'c1', text: 'Cleaned the warehouse', alternatives: [] }] } });
export const educationItem = (): ProfileItem => ({ ...experienceItem(), id: 'edu-1', kind: 'education', data: { qualification: 'BSc Computing', institution: 'Fictional University', start: '2016', end: '2020', bullets: [] } });

export const makeBank = (items: ProfileItem[] = [experienceItem(), otherItem(), educationItem()]): ProfileBank => ({ basics: {}, items, grouped: { experience: [], project: [], education: [], skill: [], certification: [], award: [], volunteering: [], custom: [] }, bank_revision: 1, confirmed_revision: null, profile_epoch: 0 });
export const readyBank = (items?: ProfileItem[]): BankHandle => ({ status: 'ready', bank: makeBank(items), error: '', refresh: vi.fn(async () => makeBank(items)) });
export const failedBank = (): BankHandle => ({ status: 'error', bank: null, error: 'down', refresh: vi.fn(async () => null) });

export const linkedEntry = (): ResumeEntry => ({
  id: 'e1', heading: 'Backend Engineer', subheading: 'Harbour Metrics', dates: 'Jul 2023 – Present', bullets: ['Built FastAPI services', 'Wrote a new thing here', 'Mentored two interns'],
  source: { item_id: 'item-1', item_revision: 4 }, date_range: { start: '2023-07', end: null, current: true },
  bullet_sources: [{ bullet_id: 'b1', alternative_id: null, base_text: 'Built FastAPI services' }, null, { bullet_id: 'b3', alternative_id: null, base_text: 'Mentored two interns' }],
});
export const content = (entries: ResumeEntry[] = [linkedEntry()], title = 'Experience', extra: Record<string, unknown> = {}): ResumeContent => ({ name: '', email: '', phone: '', location: '', summary: '', sections: [{ id: 's1', title, entries, ...extra }] });

/** Holds the content in state like the Studio does, and prints it so tests can inspect what the editor produced. */
export function Harness({ initial, bank }: { initial: ResumeContent; bank?: BankHandle }) {
  const [value, setValue] = useState(initial);
  return <div>
    {value.sections.map((section, index) => <SectionEditor key={section.id} section={section} index={index} count={value.sections.length} content={value} onContent={setValue} bank={bank} />)}
    <pre data-testid="content" hidden>{JSON.stringify(value)}</pre>
  </div>;
}
export const current = (screen: { getByTestId: (id: string) => HTMLElement }): ResumeContent => JSON.parse(screen.getByTestId('content').textContent || '{}');
