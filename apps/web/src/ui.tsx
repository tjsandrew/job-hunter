import { useState } from 'react';
export function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = { discover: 'M4 5h16M4 12h10M4 19h16M18 9l3 3-3 3', profile: 'M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', tracker: 'M4 5h16v15H4zM8 3v4m8-4v4M7 11h10m-10 4h6', studio: 'M5 3h14v18H5zM8 7h8M8 11h8M8 15h5', plus: 'M12 5v14m-7-7h14', search: 'm20 20-4.5-4.5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', arrow: 'M5 12h14m-7-7 7 7-7 7', back: 'M19 12H5m7 7-7-7 7-7', save: 'M5 3h12l3 3v15H4V3zm3 0v6h8V3m-8 18v-7h8v7', trash: 'M4 7h16m-10 4v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3', copy: 'M8 8h12v13H8zM4 16V3h12', check: 'm5 12 4 4L19 6', alert: 'M12 8v5m0 4h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z', help: 'M9 9a3 3 0 1 1 4.2 2.7c-.8.4-1.2 1-1.2 1.8M12 17.5h.01', close: 'm6 6 12 12M18 6 6 18', up: 'm6 15 6-6 6 6', down: 'm6 9 6 6 6-6', download: 'M12 3v12m-5-5 5 5 5-5M5 21h14', undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-1', redo: 'm15 14 5-5-5-5m5 5H10a6 6 0 0 0 0 12h1', signout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9', signin: 'M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4m-5-4 5-5-5-5m5 5H3' };
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.arrow} /></svg>;
}

/** The Job Hunter logo (magnifier and briefcase) on a light tile so it reads on both the dark sidebar and white pages. */
export function BrandLogo({ size = 44 }: { size?: number }) { return <span className="brand-logo" style={{ width: size, height: size }}><img src="/logo.png" alt="" width={size} height={size} /></span>; }

export function Loading({ label = 'Loading…' }: { label?: string }) { return <div className="loading"><span className="spinner" />{label}</div>; }

export function Pill({ children, color = 'neutral' }: { children: React.ReactNode; color?: string }) { return <span className={`pill ${color}`}>{children}</span>; }

export function Field({ label, value, onChange, placeholder, type = 'text', help, multiline = false, disabled = false, action }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; help?: string; multiline?: boolean; disabled?: boolean; action?: React.ReactNode }) { return <label className={action ? 'field has-action' : 'field'}><span>{label}</span>{multiline ? <textarea aria-label={action ? label : undefined} disabled={disabled} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} rows={4} /> : <input aria-label={action ? label : undefined} disabled={disabled} type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />}{help && <small>{help}</small>}{action}</label>; }

export function SelectField({ label, value, onChange, options, disabled = false }: { label: string; value: string; onChange: (v: string) => void; options: string[]; disabled?: boolean }) { return <label className="field"><span>{label}</span><select disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)}>{options.map((option) => <option key={option} value={option}>{option || 'Select one'}</option>)}</select></label>; }

export function fmtDate(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' }); }


/** Add values one at a time; each shows as its own removable chip. Enter or a comma adds, Backspace on an empty box removes the last. */
export function TagInput({ label, values, onChange, placeholder, help }: { label: string; values: string[]; onChange: (values: string[]) => void; placeholder?: string; help?: string }) {
  const [draft, setDraft] = useState('');
  const add = (raw: string) => {
    const incoming = raw.split(',').map((part) => part.trim()).filter(Boolean);
    const next = [...values];
    for (const item of incoming) if (!next.some((existing) => existing.toLowerCase() === item.toLowerCase())) next.push(item);
    if (next.length !== values.length) onChange(next);
    setDraft('');
  };
  return <div className="field tag-field" role="group" aria-label={label}>
    <span>{label}</span>
    <div className="tag-box">
      {values.map((value) => <span className="tag-chip" key={value}>{value}<button type="button" aria-label={`Remove ${value}`} onClick={() => onChange(values.filter((item) => item !== value))}>×</button></span>)}
      <input aria-label={`Add ${label}`} value={draft} placeholder={values.length ? '' : placeholder} onChange={(e) => (e.target.value.includes(',') ? add(e.target.value) : setDraft(e.target.value))}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(draft); } else if (e.key === 'Backspace' && !draft && values.length) onChange(values.slice(0, -1)); }}
        onBlur={() => draft.trim() && add(draft)} />
    </div>
    {help && <small>{help}</small>}
  </div>;
}

/** Pick any of a few fixed options as toggle chips. */
export function ChoiceChips({ label, options, values, onChange }: { label: string; options: { value: string; label: string }[]; values: string[]; onChange: (values: string[]) => void }) {
  const selected = new Set(values.map((value) => value.toLowerCase()));
  return <div className="field tag-field" role="group" aria-label={label}>
    <span>{label}</span>
    <div className="tag-box choice-box">
      {options.map((option) => { const on = selected.has(option.value); return <button type="button" key={option.value} aria-pressed={on} className={`tag-chip choice${on ? ' on' : ''}`} onClick={() => onChange(on ? values.filter((value) => value.toLowerCase() !== option.value) : [...values, option.value])}>{option.label}</button>; })}
    </div>
  </div>;
}
