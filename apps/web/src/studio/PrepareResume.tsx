import { useEffect, useRef, useState } from 'react';
import type { Resume } from '../types';
import { Icon } from '../ui';
import './prepare.css';

/** The window that starts a resume for an application: a tailored copy of one of the person's resumes, or a new one from the profile. */
export function PrepareResume({ jobTitle, resumes, ai, busy, onTailor, onBuild, onClose }: {
  jobTitle: string; resumes: Resume[]; ai: { available: boolean; remaining: number; limit: number }; busy: boolean;
  onTailor: (source: Resume, mode: 'rules' | 'ai') => void; onBuild: () => void; onClose: () => void;
}) {
  const [sourceId, setSourceId] = useState('');
  const source = resumes.find((resume) => resume.id === sourceId);
  const dialog = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const busyRef = useRef(busy); busyRef.current = busy;
  useEffect(() => {
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busyRef.current) { event.preventDefault(); closeRef.current(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
    <section ref={dialog} tabIndex={-1} className="modal prepare-dialog" role="dialog" aria-modal="true" aria-labelledby="prepare-title">
      <div className="modal-heading"><div><div className="eyebrow">APPLICATION PACKET</div><h2 id="prepare-title">Prepare a resume</h2><p>For <strong>{jobTitle}</strong>. Create a separate draft, review the finished revision, then attach its PDF snapshot to this application.</p></div><button type="button" className="icon-button" aria-label="Close" disabled={busy} onClick={onClose}><Icon name="close" /></button></div>
      <label className="field"><span>Start from a resume</span>
        <select aria-label="Choose a resume to tailor" value={sourceId} disabled={busy || !resumes.length} onChange={(event) => setSourceId(event.target.value)}>
          <option value="">{resumes.length ? 'Select a resume…' : 'You have no resumes yet'}</option>
          {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title}</option>)}
        </select></label>
      <ul className="prepare-help">
        <li><b>Create tailored copy</b> puts the bullets that match this job first. Your wording is not changed. Free.</li>
        <li><b>Tailor with AI</b> does that, then rewords some bullets to fit the job. It uses 1 AI use this month (a job you already used is free). If the AI is unavailable you get the plain copy.</li>
        <li><b>Build from my profile</b> makes a new resume for this job from your confirmed profile.</li>
      </ul>
      {busy && <p className="prepare-busy" role="status"><span className="spinner" /> Creating your draft…</p>}
      <div className="prepare-choices">
        <button type="button" className="button secondary" disabled={!source || busy} onClick={() => source && onTailor(source, 'rules')}>Create tailored copy</button>
        <button type="button" className="button secondary" disabled={!source || busy || !ai.available} title={ai.available ? undefined : 'No AI model is configured'} onClick={() => source && onTailor(source, 'ai')}>Tailor with AI ({ai.remaining} of {ai.limit} left)</button>
        <button type="button" className="button primary" disabled={busy} onClick={onBuild}>Build from my profile</button>
      </div>
      <div className="modal-footer"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>Cancel</button></div>
    </section>
  </div>;
}
