import { useEffect, useRef, useState } from 'react';
import type { CoverLetter, LetterRequest, LetterTone, Me } from '../types';
import { Icon } from '../ui';
import './letters.css';

export type LetterJob = { id: string; title: string; company?: string | null };
type Mode = 'write' | 'improve' | 'blank';

const TONES: { value: LetterTone; label: string }[] = [{ value: 'formal', label: 'Formal' }, { value: 'friendly', label: 'Friendly' }, { value: 'concise', label: 'Concise' }];
export const MIN_SOURCE = 40;

/** The window that starts a cover letter: written from the profile, an existing letter improved, or a blank one. */
export function LetterStart({ jobs, jobId, lockJob, letters, me, busy, error, onStart, onClose }: {
  jobs: LetterJob[]; jobId: string | null; lockJob: boolean; letters: CoverLetter[]; me: Me | null; busy: boolean; error: string;
  onStart: (jobId: string, request: LetterRequest) => void; onClose: () => void;
}) {
  const [job, setJob] = useState(jobId && jobs.some((item) => item.id === jobId) ? jobId : jobs[0]?.id ?? '');
  const [mode, setMode] = useState<Mode>('write');
  const [tone, setTone] = useState<LetterTone>('formal');
  const [points, setPoints] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [pasted, setPasted] = useState('');
  const [own, setOwn] = useState('');
  const dialog = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const busyRef = useRef(busy); busyRef.current = busy;
  useEffect(() => {
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busyRef.current) { event.preventDefault(); closeRef.current(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const aiReady = !!me?.letter_available;
  const remaining = me?.allowance.remaining ?? 0;
  const limit = me?.allowance.limit ?? 5;
  const ai = mode !== 'blank';
  const sourceOk = mode !== 'improve' || !!sourceId || pasted.trim().length >= MIN_SOURCE;
  const canStart = !!job && !busy && sourceOk && (!ai || aiReady);
  const submit = () => {
    if (!canStart) return;
    const request: LetterRequest = { mode };
    if (ai) { request.tone = tone; if (points.trim()) request.points = points.trim(); }
    if (mode === 'improve') { if (sourceId) request.source_document_id = sourceId; else request.source_text = pasted.trim(); }
    if (mode === 'blank' && own.trim()) request.source_text = own.trim();      // the person's own letter, put in the editor as it is
    onStart(job, request);
  };
  const choice = (value: Mode, title: string, text: string) => <label className={`letter-choice ${mode === value ? 'selected' : ''}`}><input type="radio" name="letter-mode" checked={mode === value} disabled={busy} onChange={() => setMode(value)} /><span><b>{title}</b><small>{text}</small></span></label>;
  const label = mode === 'blank' ? (own.trim() ? 'Use my letter' : 'Start a blank letter') : `${mode === 'write' ? 'Write with AI' : 'Improve with AI'} (${remaining} of ${limit} left)`;
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
    <section ref={dialog} tabIndex={-1} className="modal letter-start" role="dialog" aria-modal="true" aria-labelledby="letter-start-title">
      <div className="modal-heading"><div><div className="eyebrow">COVER LETTER</div><h2 id="letter-start-title">Write a cover letter</h2><p>AI writes a first draft you can edit, check and attach. Nothing is sent to the employer.</p></div><button type="button" className="icon-button" aria-label="Close" disabled={busy} onClick={onClose}><Icon name="close" /></button></div>
      {!jobs.length ? <p className="packet-empty">Save a job from Discover first. A letter is written for one job.</p> : <>
        <label className="field"><span>Job</span><select aria-label="Job for this letter" value={job} disabled={busy || lockJob} onChange={(event) => setJob(event.target.value)}>{jobs.map((item) => <option key={item.id} value={item.id}>{item.title}{item.company ? ` · ${item.company}` : ''}</option>)}</select></label>
        <div className="letter-choices" role="radiogroup" aria-label="How do you want to start?">
          {choice('write', 'Write it for me', 'From your confirmed profile and this job\'s description. No draft needed.')}
          {choice('improve', 'Improve a letter I have', 'Pick a saved letter, or paste one. AI rewrites it for this job and keeps your facts.')}
          {choice('blank', 'Start blank, or paste my own', 'Write it yourself, or paste a letter you already have. Free, no AI.')}
        </div>
        {mode === 'blank' && <label className="field"><span>Paste a letter you already have (optional)</span><textarea aria-label="Your own letter" rows={5} disabled={busy} value={own} onChange={(event) => setOwn(event.target.value.slice(0, 8000))} placeholder="It is put in the editor as it is, with your greeting and sign-off in their own boxes. Leave empty for a blank letter." /></label>}
        {mode === 'improve' && <div className="letter-source">
          {letters.length > 0 && <label className="field"><span>Start from a saved letter</span><select aria-label="Saved letter to improve" value={sourceId} disabled={busy} onChange={(event) => setSourceId(event.target.value)}><option value="">Paste a letter instead</option>{letters.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
          {!sourceId && <label className="field"><span>Paste your letter</span><textarea aria-label="Letter to improve" rows={5} disabled={busy} value={pasted} onChange={(event) => setPasted(event.target.value.slice(0, 8000))} placeholder="Paste the letter you have, at least a few sentences." /><small>{pasted.trim().length < MIN_SOURCE ? `At least ${MIN_SOURCE} characters.` : `${pasted.length.toLocaleString()} / 8,000 characters`}</small></label>}
        </div>}
        {ai && <>
          <div className="letter-tones" role="group" aria-label="Tone">{TONES.map((item) => <button key={item.value} type="button" className={tone === item.value ? 'selected' : ''} aria-pressed={tone === item.value} disabled={busy} onClick={() => setTone(item.value)}>{item.label}</button>)}</div>
          <label className="field"><span>Anything to stress? (optional)</span><textarea aria-label="Anything to stress" rows={2} disabled={busy} value={points} onChange={(event) => setPoints(event.target.value.slice(0, 600))} placeholder="For example: a project, a skill, or why this company" /></label>
          {!aiReady && <p className="packet-empty" role="status">No AI model is configured here, so only a blank letter can be started.</p>}
          {aiReady && remaining === 0 && <p className="packet-empty" role="status">You have used all {limit} AI uses this month. A job you already used one on still works; for any other job, start a blank letter.</p>}
          <p className="letter-cost">Uses 1 AI use, unless you already used one on this job this month. Writing from scratch needs a confirmed profile.</p>
        </>}
        {busy && <p className="letter-busy" role="status"><span className="spinner" /> Writing your letter… this can take up to 30 seconds.</p>}
        {error && <p className="letter-error" role="alert">{error}</p>}
      </>}
      <div className="modal-footer"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancel</button><button type="button" className="button primary" disabled={!canStart} onClick={submit}>{busy ? 'Working…' : label}</button></div>
    </section>
  </div>;
}
