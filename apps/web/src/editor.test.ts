import { describe, expect, it } from 'vitest';
import { itemKindFor, itemHeadings, addBullet, addEntry, addSection, blankContent, entryFromItem, formatItemDates, isEdited, markSaved, moveBullet, moveItem, removeBullet, removeEntry, removeSection, replaceWithVersion, sectionKind, setBullet, updateBullet, updateEntry } from './editor';
import type { ProfileItem, ResumeEntry } from './types';

describe('resume editing operations', () => {
  it('adds and removes sections without changing their content', () => {
    const original = blankContent();
    const withCustom = addSection(original, 'Volunteer work');
    expect(withCustom.sections.at(-1)?.title).toBe('Volunteer work');
    expect(original.sections).toHaveLength(4);
    expect(removeSection(withCustom, withCustom.sections.at(-1)!.id).sections).toHaveLength(4);
  });

  it('adds entries and updates/removes individual bullets', () => {
    const section = addEntry({ id: 'experience', title: 'Experience', entries: [] });
    const entry = section.entries[0];
    const content = { ...blankContent(), sections: [section] };
    const edited = updateBullet(content, section.id, entry.id, 0, 'Improved onboarding conversion by 18%.');
    expect(edited.sections[0].entries[0].bullets).toEqual(['Improved onboarding conversion by 18%.']);
    expect(removeEntry(section, entry.id).entries).toHaveLength(0);
  });

  it('reorders items within bounds and preserves input arrays', () => {
    const input = ['Experience', 'Education', 'Projects'];
    expect(moveItem(input, 2, -1)).toEqual(['Experience', 'Projects', 'Education']);
    expect(moveItem(input, 0, -1)).toEqual(input);
    expect(input).toEqual(['Experience', 'Education', 'Projects']);
  });
});

const linked = (): ResumeEntry => ({
  id: 'e1', heading: 'Engineer', subheading: 'Acme', dates: 'Jul 2023 – Present', bullets: ['one', 'two', 'three'],
  source: { item_id: 'item-1', item_revision: 4 }, date_range: { start: '2023-07', end: null, current: true },
  bullet_sources: [{ bullet_id: 'b1', base_text: 'one' }, null, { bullet_id: 'b3', alternative_id: 'v1', base_text: 'three' }],
});
const aligned = (entry: ResumeEntry) => expect(entry.bullet_sources).toHaveLength(entry.bullets.length);

describe('point helpers keep bullets and bullet_sources aligned', () => {
  it('adds a point with or without a source', () => {
    const withSource = addBullet(linked(), 'four', { bullet_id: 'b4', base_text: 'four' });
    expect(withSource.bullets).toEqual(['one', 'two', 'three', 'four']);
    expect(withSource.bullet_sources?.[3]).toEqual({ bullet_id: 'b4', base_text: 'four' });
    const typed = addBullet(linked());
    expect(typed.bullets.at(-1)).toBe(''); expect(typed.bullet_sources?.at(-1)).toBeNull(); aligned(typed);
  });
  it('does not invent bullet_sources for hand-written entries, but creates them when a sourced point arrives', () => {
    const plain: ResumeEntry = { id: 'p', heading: '', subheading: '', dates: '', bullets: ['a'] };
    expect(addBullet(plain, 'b').bullet_sources).toBeUndefined();
    expect(addBullet(plain, 'b', { bullet_id: 'x', base_text: 'b' }).bullet_sources).toEqual([null, { bullet_id: 'x', base_text: 'b' }]);
  });
  it('removes a point and its source together', () => {
    const next = removeBullet(linked(), 0);
    expect(next.bullets).toEqual(['two', 'three']); expect(next.bullet_sources).toEqual([null, { bullet_id: 'b3', alternative_id: 'v1', base_text: 'three' }]); aligned(next);
    expect(removeBullet(linked(), 9)).toEqual(linked());
  });
  it('moves a point with its source, and ignores moves past either end', () => {
    const down = moveBullet(linked(), 0, 1);
    expect(down.bullets).toEqual(['two', 'one', 'three']);
    expect(down.bullet_sources?.map((source) => source?.bullet_id ?? null)).toEqual([null, 'b1', 'b3']); aligned(down);
    const up = moveBullet(linked(), 2, -1);
    expect(up.bullets).toEqual(['one', 'three', 'two']);
    expect(up.bullet_sources?.map((source) => source?.bullet_id ?? null)).toEqual(['b1', 'b3', null]);
    expect(moveBullet(linked(), 0, -1)).toEqual(linked()); expect(moveBullet(linked(), 2, 1)).toEqual(linked());
  });
  it('moves hand-written entries without creating bullet_sources', () => {
    const plain: ResumeEntry = { id: 'p', heading: '', subheading: '', dates: '', bullets: ['a', 'b'] };
    expect(moveBullet(plain, 0, 1)).toEqual({ ...plain, bullets: ['b', 'a'] });
  });
  it('swaps in another version and records it as the new base text', () => {
    const next = replaceWithVersion(linked(), 2, 'three, reworded', 'v2');
    expect(next.bullets[2]).toBe('three, reworded');
    expect(next.bullet_sources?.[2]).toEqual({ bullet_id: 'b3', alternative_id: 'v2', base_text: 'three, reworded' });
    expect(isEdited(next, 2)).toBe(false);
    expect(replaceWithVersion(linked(), 0, 'main wording', null).bullet_sources?.[0]).toEqual({ bullet_id: 'b1', alternative_id: null, base_text: 'main wording' });
  });
  it('markSaved records the saved wording and the item revision, leaving other points alone', () => {
    const edited = setBullet(linked(), 0, 'one, better');
    expect(isEdited(edited, 0)).toBe(true);
    const saved = markSaved(edited, 0, { bullet_id: 'b1', alternative_id: null, base_text: 'one, better' }, 5);
    expect(isEdited(saved, 0)).toBe(false); expect(saved.source?.item_revision).toBe(5); expect(saved.bullet_sources?.[2]).toEqual(linked().bullet_sources?.[2]);
  });
  it('does not mutate the input entry', () => {
    const entry = linked(); const copy = structuredClone(entry);
    moveBullet(entry, 0, 1); removeBullet(entry, 1); addBullet(entry, 'x'); replaceWithVersion(entry, 2, 'y', null); markSaved(entry, 0, { bullet_id: 'q', base_text: 'q' }, 9);
    expect(entry).toEqual(copy);
  });
});

describe('isEdited', () => {
  it('compares text with the base text and ignores points written in the resume', () => {
    const entry = setBullet(linked(), 0, 'one!');
    expect(isEdited(entry, 0)).toBe(true);
    expect(isEdited(entry, 1)).toBe(false);
    expect(isEdited(entry, 2)).toBe(false);
    expect(isEdited({ id: 'p', heading: '', subheading: '', dates: '', bullets: ['x'] }, 0)).toBe(false);
  });
});

describe('sectionKind', () => {
  it('uses a saved kind first', () => expect(sectionKind({ title: 'Experience', kind: 'custom' })).toBe('custom'));
  it.each([
    ['Experience', 'experience'], ['Work history', 'experience'], ['Professional experience', 'experience'], ['  WORK EXPERIENCE ', 'experience'],
    ['Education', 'education'], ['Projects', 'projects'], ['Selected projects', 'projects'], ['Skills', 'skills'], ['Technical skills', 'skills'],
    ['Fun facts', 'custom'], ['Experience with dogs', 'custom'], ['Volunteer work', 'custom'],
    ['Certifications', 'certifications'], ['Licenses', 'certifications'], ['Licences & Certifications', 'certifications'], ['Professional certifications', 'certifications'],
    ['Awards', 'awards'], ['Honours', 'awards'], ['Honors & Awards', 'awards'], ['Volunteering', 'volunteering'], ['Volunteer experience', 'volunteering'],
  ])('infers %s as %s', (title, kind) => expect(sectionKind({ title })).toBe(kind));
});

describe('dates and structured ranges', () => {
  it('hand-editing dates removes date_range; other edits keep it', () => {
    const content = { ...blankContent(), sections: [{ id: 's', title: 'Experience', entries: [linked()] }] };
    expect(updateEntry(content, 's', 'e1', { dates: '2023 to now' }).sections[0].entries[0].date_range).toBeUndefined();
    expect(updateEntry(content, 's', 'e1', { heading: 'Lead' }).sections[0].entries[0].date_range).toEqual({ start: '2023-07', end: null, current: true });
    expect(updateEntry(content, 's', 'e1', { dates: linked().dates }).sections[0].entries[0].date_range).toBeDefined();
  });
  it('formats profile dates', () => {
    expect(formatItemDates({ bullets: [], start: '2023-07', current: true })).toBe('Jul 2023 – Present');
    expect(formatItemDates({ bullets: [], start: '2019', end: '2021-05' })).toBe('2019 – May 2021');
    expect(formatItemDates({ bullets: [], dates_text: 'Summer 2020', start: '2020' })).toBe('Summer 2020');
    expect(formatItemDates({ bullets: [] })).toBe('');
  });
});

describe('entryFromItem', () => {
  const item: ProfileItem = { id: 'item-9', kind: 'experience', position: 0, revision: 6, archived_at: null, origin: 'manual', import_id: null, parent_id: null, tags: [], data: { title: 'Backend Engineer', organisation: 'Harbour', location: 'Singapore', start: '2023-07', current: true, bullets: [
    { id: 'p1', text: 'Built APIs', alternatives: [{ id: 'a1', text: 'Shipped APIs' }] }, { id: 'p2', text: 'Cut latency', alternatives: [] }] } };
  it('builds a linked entry with the chosen versions', () => {
    const entry = entryFromItem(item, [{ point: item.data.bullets[0], alternativeId: 'a1' }, { point: item.data.bullets[1] }]);
    expect(entry).toMatchObject({ heading: 'Backend Engineer', subheading: 'Harbour · Singapore', dates: 'Jul 2023 – Present', bullets: ['Shipped APIs', 'Cut latency'], source: { item_id: 'item-9', item_revision: 6 }, date_range: { start: '2023-07', end: null, current: true } });
    expect(entry.bullet_sources).toEqual([{ bullet_id: 'p1', alternative_id: 'a1', base_text: 'Shipped APIs' }, { bullet_id: 'p2', alternative_id: null, base_text: 'Cut latency' }]);
  });
});

describe('certifications, awards and volunteering', () => {
  const item = (kind: ProfileItem['kind'], data: ProfileItem['data']): ProfileItem => ({ id: `${kind}-1`, kind, data, tags: [], parent_id: null, revision: 2, position: 0, archived_at: null, origin: 'manual', import_id: null });
  it('maps each section kind to its profile item kind', () => {
    expect([itemKindFor('certifications'), itemKindFor('awards'), itemKindFor('volunteering'), itemKindFor('skills')]).toEqual(['certification', 'award', 'volunteering', null]);
  });
  it('builds entries: certification name and issuer, award title and awarder, volunteering title and organisation with points', () => {
    const cert = entryFromItem(item('certification', { name: 'AWS Developer', issuer: 'Amazon', start: '2024-03', bullets: [] }), []);
    expect([cert.heading, cert.subheading, cert.dates, cert.source]).toEqual(['AWS Developer', 'Amazon', 'Mar 2024', { item_id: 'certification-1', item_revision: 2 }]);
    const award = entryFromItem(item('award', { title: 'Hackathon winner', awarder: 'City Council', start: '2021', bullets: [] }), []);
    expect([award.heading, award.subheading, award.dates]).toEqual(['Hackathon winner', 'City Council', '2021']);
    const point = { id: 'p1', text: 'Taught Python.', alternatives: [] };
    const volunteering = item('volunteering', { title: 'Mentor', organisation: 'Code Club', location: 'Singapore', start: '2020', end: '2021', bullets: [point] });
    const entry = entryFromItem(volunteering, [{ point }]);
    expect([entry.heading, entry.subheading, entry.dates, entry.bullets]).toEqual(['Mentor', 'Code Club', '2020 – 2021', ['Taught Python.']]);
    expect(itemHeadings(volunteering).subheading).toBe('Code Club');
  });
});
