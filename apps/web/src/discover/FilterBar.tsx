import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { Icon } from '../ui';
import { PreferencesForm, type PreferenceField } from '../preferences/PreferencesForm';
import { activeCount, activePreferences, DEFAULT_POSTED, POSTED_OPTIONS, postedLabel, samePreferences, WORK_MODES, type FilterChoice, type JobPreferences } from './filters';
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

/** Discover's filters: a preset ("My preferences", "No filters", "Custom"), "Posted", one pill per preference, and "All filters". */
export function FilterBar({ choice, setChoice, saved, onSaveDefault, saving, onEditDefaults }: {
  choice: FilterChoice; setChoice: (choice: FilterChoice) => void; saved: JobPreferences;
  onSaveDefault: (prefs: JobPreferences) => void; saving: boolean; onEditDefaults: () => void;
}) {
  const [open, setOpenState] = useState<PreferenceField | 'preset' | 'posted' | 'all' | null>(null);
  const [left, setLeft] = useState(0);   // where the open dropdown sits: under its pill, kept inside the bar
  const root = useRef<HTMLDivElement>(null);
  const setOpen = (next: typeof open, from?: HTMLElement) => {
    if (next && from && root.current) {
      const bar = root.current.getBoundingClientRect(), pill = from.getBoundingClientRect();
      setLeft(Math.max(0, Math.min(pill.left - bar.left, bar.width - 320)));
    }
    setOpenState(next);
  };
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
  const edit = (next: JobPreferences) => setChoice({ ...choice, mode: samePreferences(next, saved) ? 'profile' : 'custom', custom: next });
  const pickPosted = (posted: number) => { setChoice({ ...choice, posted }); setOpen(null); };
  const pick = (mode: FilterChoice['mode']) => { setChoice({ ...choice, mode }); setOpen(null); };
  const presetLabel = choice.mode === 'profile' ? 'My preferences' : choice.mode === 'none' ? 'No filters' : 'Custom';
  const count = activeCount(prefs);
  const toggle = (next: NonNullable<typeof open>) => (event: ReactMouseEvent<HTMLElement>) => setOpen(open === next ? null : next, event.currentTarget);
  const field = FIELDS.find((item) => item.field === open);
  // One row of pills that never wraps (it scrolls sideways when narrow). Dropdowns open below the row so the scroll
  // area cannot clip them, and Reset / Save sit at the end of the row rather than taking a line of their own.
  return <div className="filter-bar" ref={root}>
    <div className="filter-pills" role="group" aria-label="Job filters">
      <button type="button" className={`filter-pill preset${choice.mode !== 'none' ? ' on' : ''}`} aria-haspopup="menu" aria-expanded={open === 'preset'} onClick={toggle('preset')}>
        <Icon name={choice.mode === 'profile' ? 'profile' : 'filter'} /><span>{presetLabel}</span><span className="filter-caret" aria-hidden="true">▾</span>
      </button>
      <button type="button" className={`filter-pill field-pill${choice.posted !== 365 ? ' on' : ''}`} aria-haspopup="menu" aria-label={`Posted: ${postedLabel(choice.posted)}`} aria-expanded={open === 'posted'} onClick={toggle('posted')}>
        <span>{postedLabel(choice.posted)}</span><span className="filter-caret" aria-hidden="true">▾</span>
      </button>
      {FIELDS.map(({ field: name, label }) => <button type="button" key={name} className={`filter-pill field-pill${isSet(name, prefs) ? ' on' : ''}`} aria-label={`${label}: ${summary(name, prefs)}`} aria-expanded={open === name} onClick={toggle(name)}>
        <span>{summary(name, prefs)}</span><span className="filter-caret" aria-hidden="true">▾</span>
      </button>)}
      <button type="button" className="filter-pill all" aria-expanded={open === 'all'} onClick={toggle('all')}>
        <Icon name="filter" /><span className="wide-only">All filters</span><span className="narrow-only">Filters{count ? ` (${count})` : ''}</span>
      </button>
      {choice.mode === 'custom' && <span className="filter-actions">
        <button type="button" className="filter-link" aria-label="Reset to my preferences" title="Reset to my preferences" onClick={() => pick('profile')}>Reset</button>
        <button type="button" className="filter-link" aria-label="Save to profile" title="Save these filters as your Profile defaults" disabled={saving} onClick={() => onSaveDefault(choice.custom)}>{saving ? 'Saving…' : 'Save'}</button>
      </span>}
      {choice.mode === 'none' && <span className="filter-actions"><button type="button" className="filter-link" aria-label="Use my preferences" title="Use my preferences" onClick={() => pick('profile')}>Reset</button></span>}
    </div>
    <span className="sr-only" role="status">{choice.mode === 'custom' ? "You've changed your filters for this session." : choice.mode === 'none' ? 'Showing every open job, without your preferences.' : ''}</span>
    {open === 'preset' && <div className="filter-menu" role="menu" style={{ left }}>
      <button type="button" role="menuitemradio" aria-checked={choice.mode === 'profile'} onClick={() => pick('profile')}><strong>My preferences</strong><small>Your Profile defaults</small></button>
      <button type="button" role="menuitemradio" aria-checked={choice.mode === 'none'} onClick={() => pick('none')}><strong>No filters</strong><small>Jobs without your preferences</small></button>
      {customDiffers && <button type="button" role="menuitemradio" aria-checked={choice.mode === 'custom'} onClick={() => pick('custom')}><strong>Custom</strong><small>Your changes this session</small></button>}
      <button type="button" role="menuitem" className="filter-menu-link" onClick={() => { setOpen(null); onEditDefaults(); }}>Edit defaults in Profile →</button>
    </div>}
    {open === 'posted' && <div className="filter-menu" role="menu" aria-label="Posted" style={{ left }}>
      {POSTED_OPTIONS.map((option) => <button type="button" key={option.days} role="menuitemradio" aria-checked={choice.posted === option.days} onClick={() => pickPosted(option.days)}>
        <strong>{option.label}</strong>{option.days === DEFAULT_POSTED && <small>Default</small>}
      </button>)}
    </div>}
    {field && <div className="filter-popover" role="dialog" aria-label={`${field.label} filter`} style={{ left }}>
      <PreferencesForm preferences={prefs} setPreferences={edit} only={field.field} />
      <div className="filter-popover-foot"><button type="button" className="button secondary small-button" onClick={() => setOpen(null)}>Done</button></div>
    </div>}
    {open === 'all' && <div className="filter-panel" role="dialog" aria-label="All filters">
      <PreferencesForm preferences={prefs} setPreferences={edit} />
      <div className="filter-popover-foot"><button type="button" className="button text-button" onClick={() => pick('none')}>Clear all</button><button type="button" className="button secondary small-button" onClick={() => setOpen(null)}>Done</button></div>
    </div>}
  </div>;
}
