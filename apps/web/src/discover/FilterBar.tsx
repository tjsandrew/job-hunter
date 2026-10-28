import { useEffect, useRef, useState } from 'react';
import { Icon } from '../ui';
import { PreferencesForm, type PreferenceField } from '../preferences/PreferencesForm';
import { activeCount, activePreferences, samePreferences, WORK_MODES, type FilterChoice, type JobPreferences } from './filters';
import './filters.css';

const LEVELS: Record<string, string> = { intern: 'Intern', junior: 'Junior', mid: 'Mid-level', senior: 'Senior', lead: 'Lead', executive: 'Executive' };

function summary(field: PreferenceField, prefs: JobPreferences): string {
  const several = (values: string[], none: string) => (values.length ? values[0] + (values.length > 1 ? ` +${values.length - 1}` : '') : none);
  if (field === 'roles') return several(prefs.roles, 'Any role');
  if (field === 'locations') return several(prefs.locations, 'Any location');
  if (field === 'work_modes') return prefs.work_modes.length ? prefs.work_modes.map((mode) => WORK_MODES.find((item) => item.value === mode)?.label || mode).join(', ') : 'Any work mode';
  if (field === 'seniority') return prefs.seniority ? LEVELS[prefs.seniority] || prefs.seniority : 'Any level';
  return prefs.salary_min !== '' && prefs.salary_min !== null ? `${prefs.salary_currency} ${Number(prefs.salary_min).toLocaleString()}+ / ${prefs.salary_period}` : 'Any salary';
}
const isSet = (field: PreferenceField, prefs: JobPreferences) => !summary(field, prefs).startsWith('Any ');
const FIELDS: { field: PreferenceField; label: string }[] = [
  { field: 'roles', label: 'Role' }, { field: 'locations', label: 'Location' }, { field: 'work_modes', label: 'Work mode' },
  { field: 'seniority', label: 'Level' }, { field: 'salary', label: 'Salary' },
];

/** Discover's filters: a preset ("My preferences", "No filters", "Custom"), one pill per preference, and "All filters". */
export function FilterBar({ choice, setChoice, saved, onSaveDefault, saving, onEditDefaults }: {
  choice: FilterChoice; setChoice: (choice: FilterChoice) => void; saved: JobPreferences;
  onSaveDefault: (prefs: JobPreferences) => void; saving: boolean; onEditDefaults: () => void;
}) {
  const [open, setOpen] = useState<PreferenceField | 'preset' | 'all' | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const prefs = activePreferences(choice, saved);
  const customDiffers = !samePreferences(choice.custom, saved);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(null); };
    document.addEventListener('mousedown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  // Any edit starts from what is shown now; matching the saved defaults again switches back to "My preferences".
  const edit = (next: JobPreferences) => setChoice(samePreferences(next, saved) ? { mode: 'profile', custom: next } : { mode: 'custom', custom: next });
  const pick = (mode: FilterChoice['mode']) => { setChoice({ ...choice, mode }); setOpen(null); };
  const presetLabel = choice.mode === 'profile' ? 'My preferences' : choice.mode === 'none' ? 'No filters' : 'Custom';
  const count = activeCount(prefs);
  return <div className="filter-bar" ref={root}>
    <div className="filter-pills" role="group" aria-label="Job filters">
      <div className="filter-anchor">
        <button type="button" className={`filter-pill preset${choice.mode !== 'none' ? ' on' : ''}`} aria-haspopup="menu" aria-expanded={open === 'preset'} onClick={() => setOpen(open === 'preset' ? null : 'preset')}>
          <Icon name={choice.mode === 'profile' ? 'profile' : 'filter'} /><span>{presetLabel}</span><span className="filter-caret" aria-hidden="true">▾</span>
        </button>
        {open === 'preset' && <div className="filter-menu" role="menu">
          <button type="button" role="menuitemradio" aria-checked={choice.mode === 'profile'} onClick={() => pick('profile')}><strong>My preferences</strong><small>Your Profile defaults</small></button>
          <button type="button" role="menuitemradio" aria-checked={choice.mode === 'none'} onClick={() => pick('none')}><strong>No filters</strong><small>Every open job</small></button>
          {customDiffers && <button type="button" role="menuitemradio" aria-checked={choice.mode === 'custom'} onClick={() => pick('custom')}><strong>Custom</strong><small>Your changes this session</small></button>}
          <button type="button" role="menuitem" className="filter-menu-link" onClick={() => { setOpen(null); onEditDefaults(); }}>Edit defaults in Profile →</button>
        </div>}
      </div>
      {FIELDS.map(({ field, label }) => <div className="filter-anchor field-pill" key={field}>
        <button type="button" className={`filter-pill${isSet(field, prefs) ? ' on' : ''}`} aria-label={`${label}: ${summary(field, prefs)}`} aria-expanded={open === field} onClick={() => setOpen(open === field ? null : field)}>
          <span>{summary(field, prefs)}</span><span className="filter-caret" aria-hidden="true">▾</span>
        </button>
        {open === field && <div className="filter-popover" role="dialog" aria-label={`${label} filter`}>
          <PreferencesForm preferences={prefs} setPreferences={edit} only={field} />
          <div className="filter-popover-foot"><button type="button" className="button secondary small-button" onClick={() => setOpen(null)}>Done</button></div>
        </div>}
      </div>)}
      <button type="button" className="filter-pill all" aria-expanded={open === 'all'} onClick={() => setOpen(open === 'all' ? null : 'all')}>
        <Icon name="filter" /><span className="wide-only">All filters</span><span className="narrow-only">Filters{count ? ` (${count})` : ''}</span>
      </button>
    </div>
    {open === 'all' && <div className="filter-panel" role="dialog" aria-label="All filters">
      <PreferencesForm preferences={prefs} setPreferences={edit} />
      <div className="filter-popover-foot"><button type="button" className="button text-button" onClick={() => pick('none')}>Clear all</button><button type="button" className="button secondary small-button" onClick={() => setOpen(null)}>Done</button></div>
    </div>}
    {choice.mode === 'custom' && <div className="filter-note" role="status"><span>You've changed your filters for this session.</span><span className="filter-note-actions">
      <button type="button" className="filter-link" onClick={() => pick('profile')}>Reset to my preferences</button>
      <button type="button" className="filter-link" disabled={saving} onClick={() => onSaveDefault(choice.custom)}>{saving ? 'Saving…' : 'Save to profile'}</button>
    </span></div>}
    {choice.mode === 'none' && <div className="filter-note" role="status"><span>Showing every open job, without your preferences.</span><button type="button" className="filter-link" onClick={() => pick('profile')}>Use my preferences</button></div>}
  </div>;
}
