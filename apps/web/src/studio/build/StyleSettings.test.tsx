import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../../api';
import { StyleSettings } from './StyleSettings';
import { resume } from './testData';

vi.mock('../../api', async (importOriginal) => ({ ...await importOriginal<typeof import('../../api')>(), api: { getSettings: vi.fn(), putSettings: vi.fn() } }));
const mockApi = vi.mocked(api);
const onUpdate = vi.fn(), onApplyDefaults = vi.fn();
beforeEach(() => { vi.resetAllMocks(); });
afterEach(() => cleanup());
const show = (doc = resume()) => render(<StyleSettings resume={doc} busy={false} onUpdate={onUpdate} onApplyDefaults={onApplyDefaults} />);
const select = (name: string) => screen.getByRole('combobox', { name }) as HTMLSelectElement;

describe('StyleSettings', () => {
  it('shows today\'s defaults when the keys are absent', () => {
    show();
    expect(['Date format', 'Ongoing label', 'Headings', 'Accent colour', 'Bullets', 'Header', 'Contact separator', 'Section spacing', 'Skills'].map((name) => select(name).value))
      .toEqual(['Jul 2023', 'Present', 'rule', 'black', '•', 'center', '·', 'normal', '']);
  });
  it('defaults the header to left for the modern template and reads saved keys', () => {
    show(resume({ template: 'modern', layout: { font_size: 11, margin: 18, heading_style: 'bold', date_format: '07/2023', skills_layout: 'columns' } }));
    expect(select('Header').value).toBe('left'); expect(select('Headings').value).toBe('bold'); expect(select('Date format').value).toBe('07/2023'); expect(select('Skills').value).toBe('columns');
  });
  it('offers every value of every key', () => {
    show();
    const values = (name: string) => [...select(name).options].map((option) => option.value);
    expect(values('Date format')).toEqual(['Jul 2023', 'July 2023', '07/2023', '2023']);
    expect(values('Ongoing label')).toEqual(['Present', 'Current', 'Now']);
    expect(values('Headings')).toEqual(['rule', 'small-caps', 'bold']);
    expect(values('Accent colour')).toEqual(['black', 'navy', 'teal', 'maroon']);
    expect(values('Bullets')).toEqual(['•', '–', '▪']);
    expect(values('Header')).toEqual(['center', 'left']);
    expect(values('Contact separator')).toEqual(['·', '|', 'newline']);
    expect(values('Section spacing')).toEqual(['compact', 'normal', 'airy']);
    expect(values('Skills')).toEqual(['', 'inline', 'grouped', 'columns']);
  });
  it('updates one layout key and keeps the rest', async () => {
    const user = userEvent.setup(); show(resume({ layout: { font_size: 12, margin: 15 } }));
    await user.selectOptions(select('Accent colour'), 'teal');
    expect(onUpdate).toHaveBeenCalledWith({ layout: { font_size: 12, margin: 15, accent_color: 'teal' } });
  });
  it('lets skills go back to "as written" by removing the key', async () => {
    const user = userEvent.setup(); show(resume({ layout: { font_size: 11, margin: 18, skills_layout: 'inline' } }));
    await user.selectOptions(select('Skills'), '');
    expect(onUpdate).toHaveBeenCalledWith({ layout: { font_size: 11, margin: 18 } });
  });
  it('saves as my default with the settings revision it read', async () => {
    const user = userEvent.setup();
    mockApi.getSettings.mockResolvedValue({ revision: 4, resume_defaults: { build: { points_per_item: 3 } } });
    mockApi.putSettings.mockResolvedValue({ revision: 5, resume_defaults: {} });
    const doc = resume({ template: 'modern', layout: { font_size: 11, margin: 18, accent_color: 'navy' } });
    show(doc);
    await user.click(screen.getByRole('button', { name: 'Save as my default' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved as your default');
    expect(mockApi.putSettings).toHaveBeenCalledWith({ expected_revision: 4, resume_defaults: {
      build: { points_per_item: 3 }, template: 'modern', layout: { font_size: 11, margin: 18, accent_color: 'navy' },
      sections: [{ kind: 'experience', title: 'Experience' }, { kind: 'skills', title: 'Skills' }, { kind: 'custom', title: 'Fun facts' }] } });
  });
  it('shows a failed save, such as a settings conflict', async () => {
    mockApi.getSettings.mockResolvedValue({ revision: 4, resume_defaults: {} });
    mockApi.putSettings.mockRejectedValue(new Error('Settings changed elsewhere.'));
    show(); await userEvent.click(screen.getByRole('button', { name: 'Save as my default' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Settings changed elsewhere.');
  });
  it('applies my defaults as one change to template, layout and sections', async () => {
    const user = userEvent.setup();
    mockApi.getSettings.mockResolvedValue({ revision: 4, resume_defaults: { template: 'modern', layout: { heading_style: 'bold', accent_color: 'maroon' }, sections: [{ kind: 'skills' }, { kind: 'experience' }] } });
    const doc = resume(); show(doc);
    await user.click(screen.getByRole('button', { name: 'Apply my defaults' }));
    await waitFor(() => expect(onApplyDefaults).toHaveBeenCalledTimes(1));
    const result = onApplyDefaults.mock.calls[0][0];
    expect(result.template).toBe('modern');
    expect(result.layout).toEqual({ font_size: 11, margin: 18, heading_style: 'bold', accent_color: 'maroon' });
    expect(result.content.sections.map((section: { title: string }) => section.title)).toEqual(['Skills', 'Experience', 'Fun facts']);
    expect(mockApi.putSettings).not.toHaveBeenCalled();
  });
  it('says so when no defaults are saved and changes nothing', async () => {
    mockApi.getSettings.mockResolvedValue({ revision: 0, resume_defaults: {} });
    show(); await userEvent.click(screen.getByRole('button', { name: 'Apply my defaults' }));
    expect(await screen.findByRole('status')).toHaveTextContent('not saved defaults');
    expect(onApplyDefaults).not.toHaveBeenCalled();
  });
});
