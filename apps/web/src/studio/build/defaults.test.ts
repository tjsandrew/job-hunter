import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../api';
import { applyDefaults, buildOptionsFrom, resumeToDefaults, saveAsDefault, sectionKind } from './defaults';
import { resume } from './testData';

vi.mock('../../api', async (importOriginal) => ({ ...await importOriginal<typeof import('../../api')>(), api: { getSettings: vi.fn(), putSettings: vi.fn() } }));
const mockApi = vi.mocked(api);
beforeEach(() => vi.resetAllMocks());

describe('buildOptionsFrom', () => {
  it('falls back to 4 points, the profile summary and the classic template', () => {
    expect(buildOptionsFrom(undefined)).toEqual({ pointsPerItem: 4, includeSummary: true, template: 'classic', sectionOrder: [] });
    expect(buildOptionsFrom({ template: 'modern', build: { points_per_item: 2, include_profile_summary: false }, sections: [{ kind: 'skills' }, { kind: 'experience' }] }))
      .toEqual({ pointsPerItem: 2, includeSummary: false, template: 'modern', sectionOrder: ['skills', 'experience'] });
  });
});

describe('sectionKind', () => {
  it('uses the saved kind, otherwise infers it from the title', () => {
    expect(sectionKind({ id: 'a', title: 'Whatever', entries: [], kind: 'projects' })).toBe('projects');
    expect(['Work history', 'Professional experience', 'Education', 'Projects', 'Technical Skills', 'Fun facts'].map((title) => sectionKind({ id: 'a', title, entries: [] })))
      .toEqual(['experience', 'experience', 'education', 'projects', 'skills', 'custom']);
  });
});

describe('save and apply defaults', () => {
  it('stores template, layout and section order, titles and hidden flags, keeping other settings', () => {
    const doc = resume({ template: 'modern', layout: { font_size: 10, margin: 15, heading_style: 'bold' } });
    doc.content.sections[2].hidden = true;
    expect(resumeToDefaults(doc, { build: { points_per_item: 3 }, header_fields: ['email'] })).toEqual({
      build: { points_per_item: 3 }, header_fields: ['email'], template: 'modern', layout: { font_size: 10, margin: 15, heading_style: 'bold' },
      sections: [{ kind: 'experience', title: 'Experience' }, { kind: 'skills', title: 'Skills' }, { kind: 'custom', title: 'Fun facts', hidden: true }] });
  });
  it('sends the revision it read', async () => {
    mockApi.getSettings.mockResolvedValue({ revision: 6, resume_defaults: { build: { points_per_item: 3 } } });
    mockApi.putSettings.mockResolvedValue({ revision: 7, resume_defaults: {} });
    await saveAsDefault(resume());
    expect(mockApi.putSettings).toHaveBeenCalledWith(expect.objectContaining({ expected_revision: 6, resume_defaults: expect.objectContaining({ template: 'classic', build: { points_per_item: 3 } }) }));
  });
  it('applies layout and reorders, retitles and hides sections without touching entries', () => {
    const doc = resume();
    const result = applyDefaults(doc, { template: 'modern', layout: { heading_style: 'small-caps', font_size: 12 }, sections: [{ kind: 'skills', title: 'Technical skills' }, { kind: 'experience' }, { kind: 'custom', title: 'Fun facts', hidden: true }] });
    expect(result.template).toBe('modern');
    expect(result.layout).toMatchObject({ margin: 18, font_size: 12, heading_style: 'small-caps' });
    expect(result.content.sections.map((section) => [section.title, section.hidden])).toEqual([['Technical skills', undefined], ['Experience', undefined], ['Fun facts', true]]);
    expect(result.content.sections[1].entries).toBe(doc.content.sections[0].entries);
  });
  it('keeps sections the defaults do not mention, after the ordered ones, and leaves content alone without section rules', () => {
    const doc = resume();
    expect(applyDefaults(doc, { sections: [{ kind: 'custom', title: 'Fun facts' }] }).content.sections.map((section) => section.title)).toEqual(['Fun facts', 'Experience', 'Skills']);
    expect(applyDefaults(doc, { layout: { margin: 20 } }).content).toBe(doc.content);
  });
});
