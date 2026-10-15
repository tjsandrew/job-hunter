import { useState } from 'react';
import { Icon } from '../../ui';
import type { Resume } from '../../types';
import { BuildFlow } from './BuildFlow';
import type { JobRef } from './BuildFlow';
import './build.css';

export type NewResumeStep = 'start' | 'free' | 'job' | 'copy';
const starts: { step: NewResumeStep | 'blank'; name: string; note: string }[] = [
  { step: 'blank', name: 'Blank', note: 'Type everything yourself' },
  { step: 'free', name: 'From my profile', note: 'A general resume, filtered by focus' },
  { step: 'job', name: 'For a job', note: 'Suggested from your profile for one job' },
  { step: 'copy', name: 'Copy a resume', note: 'Start from one you already have' },
];

/** Replaces the single "Create resume" action: four ways to start. */
export function NewResume({ resumes, jobs, attachTarget, initial = 'start', busy, onBlank, onCopy, onBuilt, onClose }: { resumes: Resume[]; jobs: JobRef[]; attachTarget: { job_id: string; title: string } | null; initial?: NewResumeStep; busy: boolean; onBlank: () => void; onCopy: (resume: Resume) => void; onBuilt: (resume: Resume) => void; onClose: () => void }) {
  const [step, setStep] = useState<NewResumeStep>(initial);
  const [jobChoice, setJobChoice] = useState(attachTarget?.job_id || '');
  const [confirmedJob, setConfirmedJob] = useState<string>(initial === 'job' && attachTarget ? attachTarget.job_id : '');
  const [copyChoice, setCopyChoice] = useState('');
  const job: JobRef | null = confirmedJob ? jobs.find((row) => row.id === confirmedJob) || (attachTarget?.job_id === confirmedJob ? { id: confirmedJob, title: attachTarget.title } : null) : null;
  const source = resumes.find((resume) => resume.id === copyChoice);
  const back = () => { if (step === 'start') onClose(); else { setStep('start'); setConfirmedJob(''); } };
  const heading = step === 'job' ? 'Build a resume for a job' : step === 'free' ? 'Build a resume from your profile' : step === 'copy' ? 'Copy a resume' : 'Start a new resume';
  const lede = step === 'job' ? 'We pick the parts of your profile that match the job. Untick anything you do not want, then create the resume and edit it as usual.' : step === 'free' ? 'Choose a template and an optional focus. Everything matching it is ticked, newest first. Adjust, then create.' : 'Choose how to begin. You can edit everything afterwards.';
  const pick = (next: NewResumeStep | 'blank') => {
    if (next === 'blank') { onBlank(); return; }
    setConfirmedJob(next === 'job' && attachTarget ? attachTarget.job_id : ''); setStep(next);
  };
  return <div className="page-wrap new-resume">
    <div className="page-heading"><div><div className="eyebrow">RESUME STUDIO · NEW RESUME</div><h1>{heading}</h1><p>{lede}</p></div><button className="button ghost" onClick={back}><Icon name="back" /> {step === 'start' ? 'Library' : 'All starts'}</button></div>
    <div className="starts" role="group" aria-label="How to start">{starts.map((start) => <button key={start.step} type="button" className={`start-card ${start.step === step ? 'selected' : ''}`} aria-pressed={start.step === step} disabled={busy} onClick={() => pick(start.step)}><b>{start.name}</b><span>{start.note}</span></button>)}</div>
    {step === 'free' && <BuildFlow key="free" job={null} onBuilt={onBuilt} onCancel={back} />}
    {step === 'job' && !job && <div className="panel build-pick">
      <h2>Which job?</h2>
      {jobs.length ? <><label className="field"><span>Saved job</span><select aria-label="Choose a saved job" value={jobChoice} onChange={(event) => setJobChoice(event.target.value)}><option value="">Select a job…</option>{jobs.map((row) => <option key={row.id} value={row.id}>{row.title}{row.company ? ` · ${row.company}` : ''}</option>)}</select></label><button className="button primary" disabled={!jobChoice} onClick={() => setConfirmedJob(jobChoice)}>Match my profile</button></> : <p className="build-muted">Save a job from Discover first, then come back to build a resume for it.</p>}
    </div>}
    {step === 'job' && job && <BuildFlow key={job.id} job={job} onBuilt={onBuilt} onCancel={back} />}
    {step === 'copy' && <div className="panel build-pick">
      <h2>Which resume?</h2>
      {resumes.length ? <><label className="field"><span>Resume to copy</span><select aria-label="Choose a resume to copy" value={copyChoice} onChange={(event) => setCopyChoice(event.target.value)}><option value="">Select a resume…</option>{resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title}</option>)}</select></label><button className="button primary" disabled={!source || busy} onClick={() => source && onCopy(source)}>{attachTarget ? 'Create tailored copy' : 'Create copy'}</button></> : <p className="build-muted">You have no resumes to copy yet.</p>}
    </div>}
  </div>;
}
