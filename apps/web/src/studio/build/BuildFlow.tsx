import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../../api';
import { Loading } from '../../ui';
import type { Resume, SkillCategory, Template } from '../../types';
import { createFromBank, suggestPlan } from './buildApi';
import type { Suggestion } from './buildApi';
import { applyFocus, applyOverrides, applySuggestion, bankToDraft, countSelected, draftToPlan, focusOptions, noOverrides, recordOverrides } from './buildPlan';
import type { Draft, Overrides } from './buildPlan';
import { buildOptionsFrom } from './defaults';
import { PlanPicker } from './PlanPicker';
import './build.css';

export type JobRef = { id: string; title: string; company?: string; location?: string | null; work_mode?: string | null };
const categories: SkillCategory[] = ['tool', 'language', 'framework', 'domain', 'soft'];

/** The free build ("From my profile") and the build for a job share this screen: a pre-selected plan the user confirms before anything is created. */
export function BuildFlow({ job, onBuilt, onCancel }: { job: JobRef | null; onBuilt: (resume: Resume) => void; onCancel: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [base, setBase] = useState<Draft>({ items: [], skills: [] });
  const [draft, setDraft] = useState<Draft>({ items: [], skills: [] });
  const [options, setOptions] = useState(() => buildOptionsFrom(undefined));
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [focus, setFocus] = useState<string[]>([]);
  const [title, setTitle] = useState(job ? `${job.title}${job.company ? ` – ${job.company}` : ''}` : 'Resume from my profile');
  const [template, setTemplate] = useState<Template>('classic');
  const [useSummary, setUseSummary] = useState(true);
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState('');
  const [categoryFor, setCategoryFor] = useState<Record<string, SkillCategory>>({});
  const [note, setNote] = useState('');
  const first = useRef(true);
  const jobId = job?.id;
  // The user's own ticks, order and wording choices; they are laid over every refreshed suggestion or focus.
  const manual = useRef<Overrides>(noOverrides());
  const focusRef = useRef<string[]>([]);
  focusRef.current = focus;
  const jobFor = useRef(jobId);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError('');
    (async () => {
      const [bank, settings] = await Promise.all([api.getBank(), api.getSettings().catch(() => null)]);
      const opts = buildOptionsFrom(settings?.resume_defaults);
      const empty = bankToDraft(bank);
      const result = jobId ? await suggestPlan(jobId, opts.pointsPerItem) : null;
      if (!alive) return;
      if (jobFor.current !== jobId) { jobFor.current = jobId; manual.current = noOverrides(); }
      setOptions(opts); setBase(empty); setSuggestion(result);
      setDraft(applyOverrides(result ? applySuggestion(empty, result) : applyFocus(empty, focusRef.current, opts.pointsPerItem), manual.current));
      if (first.current) { setTemplate(opts.template); setUseSummary(opts.includeSummary); first.current = false; }
    })().catch((problem) => { if (alive) setError((problem as Error).message); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [jobId, reload]);

  const counts = countSelected(draft);
  const tags = useMemo(() => focusOptions(base), [base]);
  const toggleFocus = (tag: string) => {
    const next = focus.includes(tag) ? focus.filter((value) => value !== tag) : [...focus, tag];
    setFocus(next); setDraft(applyOverrides(applyFocus(base, next, options.pointsPerItem), manual.current));
  };
  const edit = (next: Draft) => { manual.current = recordOverrides(draft, next, manual.current); setDraft(next); };
  const addSkill = async (name: string) => {
    setAdding(name); setError(''); setNote('');
    try {
      await api.createItem({ kind: 'skill', data: { name, category: categoryFor[name] || 'tool', bullets: [] } });
      setNote(`${name} added to your profile. Suggestions refreshed.`);
      setReload((value) => value + 1);
    } catch (problem) { setError((problem as Error).message); }
    finally { setAdding(''); }
  };
  const create = async () => {
    setCreating(true); setError('');
    try {
      const plan = draftToPlan(draft, { title: title.trim() || 'Untitled resume', template, job_id: job?.id ?? null, summary: useSummary ? { mode: 'profile' } : { mode: 'custom', text: '' }, sectionOrder: options.sectionOrder });
      onBuilt(await createFromBank(plan));
    } catch (problem) { setError((problem as Error).message); setCreating(false); }
  };

  if (loading && first.current) return <Loading label={job ? 'Matching your profile to this job…' : 'Loading your profile…'} />;
  const covered = suggestion?.coverage.covered || [], missing = suggestion?.coverage.missing || [];
  const total = covered.length + missing.length;
  return <div className="build-flow" aria-busy={loading || creating}>
    {error && <div className="build-error" role="alert">{error} <button className="link-button" onClick={() => setReload((value) => value + 1)}>Try again</button></div>}
    {note && <div className="build-note" role="status">{note}</div>}
    <div className={`build-grid ${job ? '' : 'single'}`}>
      <div className="panel build-main">
        <div className="panel-heading"><h2>{job ? 'Suggested from your profile' : 'Your profile, ready to pick from'}</h2>{suggestion && <span className="pill neutral">{suggestion.strategy}</span>}</div>
        {!job && tags.length > 0 && <div className="build-focus" role="group" aria-label="Focus"><span>Focus on</span>{tags.map((tag) => <button key={tag} type="button" className={focus.includes(tag) ? 'selected' : ''} aria-pressed={focus.includes(tag)} onClick={() => toggleFocus(tag)}>{tag}</button>)}</div>}
        {loading ? <Loading label="Updating…" /> : <PlanPicker draft={draft} reasons={suggestion?.reasons || {}} cap={options.pointsPerItem} disabled={creating} onChange={edit} />}
        {job && <p className="build-later">Suggestions only: nothing is created until you press Create resume. Rewording and tailored summaries will come later, and you will approve each one.</p>}
      </div>
      <div className="build-side">
        {job && <div className="panel build-job">
          <div><strong className="build-job-title">{job.title}</strong><p className="build-job-sub">{[job.company, job.location, job.work_mode].filter(Boolean).join(' · ')}</p></div>
          <div><div className="build-cover-row"><span>Job skills covered by your profile</span><b>{covered.length} of {total}</b></div><div className="build-meter" role="meter" aria-label="Skills coverage" aria-valuemin={0} aria-valuemax={total} aria-valuenow={covered.length}><span style={{ width: total ? `${(covered.length / total) * 100}%` : '0%' }} /></div></div>
          <div><h3>Covered</h3>{covered.length ? <div className="build-chips">{covered.map((skill) => <span key={skill} className="pill green">{skill}</span>)}</div> : <p className="build-muted">None of the job's listed skills are in your profile yet.</p>}</div>
          <div><h3>Not in your profile</h3>{missing.length ? <ul className="build-missing">{missing.map((skill) => <li key={skill}><span>{skill}</span><select aria-label={`Category for ${skill}`} disabled={!!adding || creating} value={categoryFor[skill] || 'tool'} onChange={(event) => setCategoryFor({ ...categoryFor, [skill]: event.target.value as SkillCategory })}>{categories.map((category) => <option key={category}>{category}</option>)}</select><button type="button" className="button secondary small-button" aria-label={`I have this · add to profile: ${skill}`} disabled={!!adding || creating} onClick={() => void addSkill(skill)}>{adding === skill ? 'Adding…' : 'I have this · add to profile'}</button></li>)}</ul> : <p className="build-muted">Nothing missing.</p>}</div>
        </div>}
        <div className="panel build-create">
          <label className="field"><span>Resume title</span><input value={title} disabled={creating} onChange={(event) => setTitle(event.target.value)} /></label>
          <label className="field"><span>Template</span><select aria-label="Template" value={template} disabled={creating} onChange={(event) => setTemplate(event.target.value as Template)}><option value="classic">Classic serif</option><option value="modern">Modern sans</option></select></label>
          <label className="build-check"><input type="checkbox" checked={useSummary} disabled={creating} onChange={(event) => setUseSummary(event.target.checked)} />Use my profile summary</label>
          <p className="build-muted" aria-live="polite">{counts.items} {counts.items === 1 ? 'item' : 'items'}, {counts.points} {counts.points === 1 ? 'point' : 'points'}, {counts.skills} {counts.skills === 1 ? 'skill' : 'skills'} selected{job ? ' · attaches to your application for this job' : ''}</p>
          <div className="build-actions"><button type="button" className="button primary" disabled={creating || loading || (!counts.items && !counts.skills)} onClick={() => void create()}>{creating ? 'Creating…' : 'Create resume'}</button><button type="button" className="button ghost" disabled={creating} onClick={onCancel}>Cancel</button></div>
        </div>
      </div>
    </div>
  </div>;
}
