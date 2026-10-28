import { useEffect, useState } from 'react';
import { api } from '../api';
import { ChoiceChips, Field, SelectField, TagInput } from '../ui';
import { WORK_MODES } from '../discover/filters';

export type PreferenceField = 'roles' | 'locations' | 'work_modes' | 'seniority' | 'salary';

/** The job preference controls, shared by the Profile defaults and the Discover filters. `only` shows a single field. */
export function PreferencesForm({ preferences, setPreferences, only }: { preferences: any; setPreferences: (value: any) => void; only?: PreferenceField }) {
  const list = (key: string): string[] => (Array.isArray(preferences[key]) ? preferences[key] : []);
  const [seniorityOptions, setSeniorityOptions] = useState<{ value: string; label: string }[]>([]);
  const [optionsError, setOptionsError] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const show = (field: PreferenceField) => !only || only === field;
  useEffect(() => {
    if (!show('seniority')) return;
    let alive = true;
    setOptionsLoading(true); setOptionsError(false);
    api.getSeniorityOptions().then((result) => { if (alive) setSeniorityOptions(result.items); })
      .catch(() => { if (alive) setOptionsError(true); })
      .finally(() => { if (alive) setOptionsLoading(false); });
    return () => { alive = false; };
  }, [retry, only]);
  return <>
    {show('roles') && <TagInput label="Roles or job titles" placeholder="e.g. Backend Engineer, then press Enter" values={list('roles')} onChange={(roles) => setPreferences({ ...preferences, roles })} />}
    {show('locations') && <TagInput label="Preferred locations" placeholder="e.g. Singapore, then press Enter" values={list('locations')} onChange={(locations) => setPreferences({ ...preferences, locations })} />}
    {show('work_modes') && <ChoiceChips label="Work modes" options={WORK_MODES} values={list('work_modes')} onChange={(work_modes) => setPreferences({ ...preferences, work_modes })} />}
    {show('seniority') && <label className="field"><span>Seniority</span><select value={preferences.seniority || ''} disabled={optionsLoading || optionsError} onChange={(event) => setPreferences({ ...preferences, seniority: event.target.value })}><option value="">{optionsLoading ? 'Loading levels…' : optionsError ? 'Levels unavailable' : 'Any level'}</option>{seniorityOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}
    {show('seniority') && optionsError && <p role="alert">Could not load seniority levels. <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></p>}
    {show('salary') && <><Field label="Minimum salary" type="number" value={String(preferences.salary_min ?? '')} onChange={(salary_min) => setPreferences({ ...preferences, salary_min })} />
      <div className="form-grid"><SelectField label="Currency" value={preferences.salary_currency || 'SGD'} options={['SGD', 'USD', 'AUD', 'GBP', 'EUR']} onChange={(salary_currency) => setPreferences({ ...preferences, salary_currency })} /><SelectField label="Salary period" value={preferences.salary_period || 'year'} options={['year', 'month', 'hour']} onChange={(salary_period) => setPreferences({ ...preferences, salary_period })} /></div></>}
  </>;
}
