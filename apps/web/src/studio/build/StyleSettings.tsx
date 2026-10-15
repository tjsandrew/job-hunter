import { useState } from 'react';
import { api } from '../../api';
import type { Resume, ResumeContent, ResumeLayout, Template } from '../../types';
import { applyDefaults, saveAsDefault } from './defaults';
import { dateFormats, presentLabels } from './dates';
import './build.css';

type Key = 'date_format' | 'present_label' | 'heading_style' | 'accent_color' | 'bullet_char' | 'header_align' | 'contact_separator' | 'section_spacing' | 'skills_layout';
const choices: { key: Key; label: string; options: { value: string; label: string }[]; fallback: (resume: Resume) => string }[] = [
  { key: 'date_format', label: 'Date format', options: dateFormats.map((value) => ({ value, label: value })), fallback: () => 'Jul 2023' },
  { key: 'present_label', label: 'Ongoing label', options: presentLabels.map((value) => ({ value, label: value })), fallback: () => 'Present' },
  { key: 'heading_style', label: 'Headings', options: [{ value: 'rule', label: 'Rule under' }, { value: 'small-caps', label: 'Small caps' }, { value: 'bold', label: 'Bold' }], fallback: () => 'rule' },
  { key: 'accent_color', label: 'Accent colour', options: [{ value: 'black', label: 'Black' }, { value: 'navy', label: 'Navy' }, { value: 'teal', label: 'Teal' }, { value: 'maroon', label: 'Maroon' }], fallback: () => 'black' },
  { key: 'bullet_char', label: 'Bullets', options: [{ value: '•', label: '• Dot' }, { value: '–', label: '– Dash' }, { value: '▪', label: '▪ Square' }], fallback: () => '•' },
  { key: 'header_align', label: 'Header', options: [{ value: 'center', label: 'Centred' }, { value: 'left', label: 'Left' }], fallback: (resume) => resume.template === 'modern' ? 'left' : 'center' },
  { key: 'contact_separator', label: 'Contact separator', options: [{ value: '·', label: '·  dot' }, { value: '|', label: '|  bar' }, { value: 'newline', label: 'New line' }], fallback: () => '·' },
  { key: 'section_spacing', label: 'Section spacing', options: [{ value: 'compact', label: 'Compact' }, { value: 'normal', label: 'Normal' }, { value: 'airy', label: 'Airy' }], fallback: () => 'normal' },
  { key: 'skills_layout', label: 'Skills', options: [{ value: '', label: 'As written' }, { value: 'inline', label: 'One line' }, { value: 'grouped', label: 'Grouped' }, { value: 'columns', label: 'Columns' }], fallback: () => '' },
];

/** Style and date controls for the editor's "Layout settings" panel, plus the per-user defaults buttons. */
export function StyleSettings({ resume, busy, onUpdate, onApplyDefaults }: { resume: Resume; busy: boolean; onUpdate: (patch: Partial<Resume>) => void; onApplyDefaults: (patch: { template: Template; layout: ResumeLayout; content: ResumeContent }) => void }) {
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);
  const run = async (action: () => Promise<string>) => {
    setWorking(true); setMessage(''); setFailed(false);
    try { setMessage(await action()); } catch (error) { setFailed(true); setMessage((error as Error).message); }
    finally { setWorking(false); }
  };
  const change = (key: Key, value: string) => {
    const layout = { ...resume.layout } as Record<string, unknown>;
    if (value === '') delete layout[key]; else layout[key] = value;
    onUpdate({ layout: layout as ResumeLayout });
  };
  return <>
    {choices.map(({ key, label, options, fallback }) => <label key={key} className="style-field">{label} <select aria-label={label} disabled={busy} value={(resume.layout[key] as string | undefined) ?? fallback(resume)} onChange={(event) => change(key, event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>)}
    <div className="style-defaults">
      <button type="button" className="button secondary small-button" disabled={busy || working} onClick={() => void run(async () => { await saveAsDefault(resume); return 'Saved as your default for new resumes.'; })}>Save as my default</button>
      <button type="button" className="button secondary small-button" disabled={busy || working} onClick={() => void run(async () => {
        const settings = await api.getSettings();
        if (!settings.resume_defaults || !Object.keys(settings.resume_defaults).length) return 'You have not saved defaults yet.';
        onApplyDefaults(applyDefaults(resume, settings.resume_defaults));
        return 'Your defaults were applied.';
      })}>Apply my defaults</button>
      {message && <p className={`style-message ${failed ? 'error' : ''}`} role={failed ? 'alert' : 'status'}>{message}</p>}
    </div>
  </>;
}
