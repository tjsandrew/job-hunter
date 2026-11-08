import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, HttpError } from '../api';
import { downloadFile } from '../download';
import type { DocumentTab } from '../routes';
import type { Application, CoverLetter, LetterContent, LetterNote, LetterRequest, Me, ResumeLayout, Template } from '../types';
import { Icon, Loading, fmtDateTime } from '../ui';
import { DocTabs } from './DocTabs';
import { LetterEditor } from './LetterEditor';
import { LetterStart } from './LetterStart';
import './letters.css';

const SAVE_DELAY_MS = 700;
type Start = { jobId: string | null; lockJob: boolean };

/** The cover letters of the "My resumes" page: the list, starting a letter, and the editor with its preview. */
export function Letters({ me, apps, resumeCount, activeId, target, refresh, onOpen, onTargetDone, onSection, onMeChanged, onApplicationSaved, announce }: {
  me: Me | null; apps: Application[]; resumeCount: number; activeId: string | null; target: string | null; refresh: number;
  onOpen: (id: string | null) => void; onTargetDone: () => void; onSection: (section: DocumentTab) => void;
  onMeChanged: () => void; onApplicationSaved: (application: Application) => void; announce: (message: string) => void;
}) {
  const [letters, setLetters] = useState<CoverLetter[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [active, setActive] = useState<CoverLetter | null>(null);
  const [notes, setNotes] = useState<Record<string, LetterNote[]>>({});
  const [saveLabel, setSaveLabel] = useState('Saved');
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState<Start | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');
  const latest = useRef<CoverLetter | null>(null);
  const dirty = useRef(false);
  const saving = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const flushRef = useRef<() => void>(() => undefined);
  const announceRef = useRef(announce); announceRef.current = announce;

  const loadLetters = useCallback(() => {
    setLoadError('');
    return api.letters().then((result) => { setLetters(result.items || []); return result.items || []; })
      .catch((error: Error) => { setLoadError(error.message); setLetters([]); return [] as CoverLetter[]; });
  }, []);
  useEffect(() => { void loadLetters(); }, [loadLetters, refresh]);

  // The address names a letter: open it once the list is here; a link to a letter that is gone goes back to the list.
  useEffect(() => {
    if (!activeId) { latest.current = null; setActive(null); return; }
    if (letters === null || latest.current?.id === activeId) return;
    const found = letters.find((item) => item.id === activeId);
    if (found) { latest.current = structuredClone(found); dirty.current = false; setActive(latest.current); setSaveLabel('Saved'); }
    else { announceRef.current('That cover letter was not found.'); onOpen(null); }
  }, [activeId, letters, onOpen]);

  // Opened from an application: open the letter already written for that job, or start one.
  useEffect(() => {
    if (!target || letters === null) return;
    const existing = letters.find((item) => item.job_id === target);
    if (existing) onOpen(existing.id); else { setStart({ jobId: target, lockJob: true }); setStartError(''); }
    onTargetDone();
  }, [target, letters, onOpen, onTargetDone]);

  const flush = useCallback(async () => {
    const snapshot = latest.current;
    if (!snapshot || saving.current || !dirty.current) return;
    saving.current = true; dirty.current = false; setSaveLabel('Saving…');
    let retry = true;   // after a failed save the next edit tries again; it does not loop on its own
    try {
      const saved = await api.patchLetter(snapshot.id, { expected_revision: snapshot.revision, title: snapshot.title, template: snapshot.template, content: snapshot.content, layout: snapshot.layout });
      if (latest.current?.id === snapshot.id) {
        latest.current = { ...latest.current, revision: saved.revision, reviewed_revision: saved.reviewed_revision, updated_at: saved.updated_at };
        setActive(latest.current);
      }
      setLetters((items) => (items || []).map((item) => (item.id === snapshot.id ? { ...item, title: snapshot.title, content: snapshot.content, layout: snapshot.layout, template: snapshot.template, revision: saved.revision, reviewed_revision: saved.reviewed_revision, updated_at: saved.updated_at } : item)));
      setSaveLabel(dirty.current ? 'Unsaved changes' : 'Saved');
    } catch (error) {
      if (error instanceof HttpError && error.status === 409) {
        announceRef.current('This letter changed somewhere else. The latest version was loaded.');
        const items = await loadLetters();
        const fresh = items.find((item) => item.id === snapshot.id);
        if (fresh) { latest.current = structuredClone(fresh); dirty.current = false; setActive(latest.current); setSaveLabel('Saved'); }
      } else { retry = false; dirty.current = true; setSaveLabel('Not saved'); announceRef.current((error as Error).message); }
    } finally {
      saving.current = false;
      if (dirty.current && retry) timer.current = window.setTimeout(() => flushRef.current(), SAVE_DELAY_MS);
    }
  }, [loadLetters]);
  flushRef.current = () => void flush();
  useEffect(() => () => { window.clearTimeout(timer.current); flushRef.current(); }, []);

  const edit = (changes: Partial<CoverLetter>) => {
    if (!latest.current) return;
    latest.current = { ...latest.current, ...changes, reviewed_revision: null };
    dirty.current = true; setActive(latest.current); setSaveLabel('Unsaved changes');
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => flushRef.current(), SAVE_DELAY_MS);
  };

  const jobOptions = useMemo(() => apps.filter((item) => item.job).map((item) => ({ id: item.job_id, title: item.job!.title, company: item.job!.company })), [apps]);
  const applicationFor = (jobId?: string | null) => (jobId ? apps.find((item) => item.job_id === jobId) : undefined);
  const jobTitleFor = (letter: CoverLetter) => applicationFor(letter.job_id)?.job?.title;

  const begin = async (jobId: string, request: LetterRequest) => {
    setStarting(true); setStartError('');
    try {
      const result = await api.createLetter(jobId, request);
      setLetters((items) => [result.document, ...(items || [])]);
      setNotes((current) => ({ ...current, [result.document.id]: result.notes }));
      setStart(null);
      if (request.mode !== 'blank') onMeChanged();
      onOpen(result.document.id);
      announce(request.mode === 'blank' ? 'A blank cover letter was created.' : 'Your cover letter is ready. Check it, edit it, then review it before attaching.');
    } catch (error) { setStartError((error as Error).message); }
    finally { setStarting(false); }
  };

  const review = async () => {
    if (!latest.current) return;
    setBusy(true);
    try {
      const reviewed = await api.reviewLetter(latest.current.id, latest.current.revision);
      latest.current = { ...latest.current, reviewed_revision: reviewed.reviewed_revision };
      setActive(latest.current);
      setLetters((items) => (items || []).map((item) => (item.id === reviewed.id ? { ...item, reviewed_revision: reviewed.reviewed_revision } : item)));
    } catch (error) { announce((error as Error).message); }
    finally { setBusy(false); }
  };
  const download = async () => {
    if (!latest.current) return;
    setBusy(true);
    try {
      const made = await api.exportDocument(latest.current.id);
      downloadFile(await api.downloadExport(made.export_id), `${latest.current.title.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'cover-letter'}.pdf`);
      announce(`Downloaded revision ${made.revision}.`);
    } catch (error) { announce((error as Error).message); }
    finally { setBusy(false); }
  };
  const attach = async () => {
    const letter = latest.current;
    if (!letter?.job_id) return;
    const application = applicationFor(letter.job_id);
    setBusy(true);
    try {
      const saved = await api.putApplication(letter.job_id, { cover_letter_document_id: letter.id, expected_cover_letter_revision: letter.revision, expected_revision: application?.revision ?? 0 });
      onApplicationSaved(saved);
      announce('The reviewed letter is attached to your application as a PDF snapshot.');
    } catch (error) { announce((error as Error).message); }
    finally { setBusy(false); }
  };
  const remove = async (letter: CoverLetter) => {
    if (!window.confirm(`Delete "${letter.title}"? A copy attached to an application stays there.`)) return;
    setBusy(true);
    try {
      await api.archiveDocument(letter.id);
      setLetters((items) => (items || []).filter((item) => item.id !== letter.id));
      if (activeId === letter.id) onOpen(null);
      announce(`"${letter.title}" deleted.`);
    } catch (error) { announce((error as Error).message); }
    finally { setBusy(false); }
  };
  const back = () => {
    if (saveLabel !== 'Saved') { announce('Wait for the letter to save before leaving the editor.'); return; }
    onOpen(null);
  };

  const startDialog = start && <LetterStart jobs={jobOptions} jobId={start.jobId} lockJob={start.lockJob} letters={letters || []} me={me} busy={starting} error={startError}
    onStart={(jobId, request) => void begin(jobId, request)} onClose={() => { setStart(null); setStartError(''); }} />;

  if (activeId && active) {
    const application = applicationFor(active.job_id);
    const packet = application?.cover_letter_packet;
    return <>
      <LetterEditor letter={active} notes={notes[active.id] || []} jobTitle={jobTitleFor(active)} saveLabel={saveLabel} busy={busy}
        attachLabel={active.job_id ? 'Attach reviewed letter' : null} attachedRevision={packet && packet.document_id === active.id ? packet.revision : null}
        onTitle={(title) => edit({ title })} onContent={(content: LetterContent) => edit({ content })} onLayout={(layout: ResumeLayout) => edit({ layout })} onTemplate={(template: Template) => edit({ template })}
        onReview={() => void review()} onDownload={() => void download()} onAttach={() => void attach()} onBack={back} onDelete={() => void remove(active)}
        onAnother={active.job_id ? () => { setStart({ jobId: active.job_id!, lockJob: true }); setStartError(''); } : undefined} />
      {startDialog}
    </>;
  }
  if (activeId && letters === null) return <div className="page-wrap"><Loading label="Loading your cover letter…" /></div>;

  const lettered = new Set((letters || []).map((item) => item.job_id).filter(Boolean));
  const waiting = apps.filter((item) => item.job && !lettered.has(item.job_id) && !['rejected', 'withdrawn'].includes(item.status)).slice(0, 6);
  const remaining = me?.allowance.remaining ?? 0, limit = me?.allowance.limit ?? 5;
  return <div className="page-wrap letters-page">
    <div className="page-heading"><div><div className="eyebrow">YOUR DOCUMENTS</div><h1>My resumes</h1><p>Keep your resumes and cover letters here. Open one to edit it, or prepare it for a job.</p></div>
      <button className="button primary" onClick={() => { setStart({ jobId: null, lockJob: false }); setStartError(''); }}><Icon name="plus" /> Write cover letter</button></div>
    <DocTabs section="letters" onSection={onSection} resumeCount={resumeCount} letterCount={letters?.length ?? null} />
    {loadError && <p className="letter-error" role="alert">{loadError}</p>}
    {letters === null ? <Loading label="Loading your cover letters…" /> : <>
      <section aria-label="Your cover letters">
        <div className="section-toolbar"><div><h2>Your cover letters</h2><p>One for each job. Each is written for a single application.</p></div></div>
        {letters.length ? <div className="resume-grid">{letters.map((letter) => {
          const packet = applicationFor(letter.job_id)?.cover_letter_packet;
          const reviewed = letter.reviewed_revision === letter.revision;
          return <div className="resume-card-wrap" key={letter.id}>
            <button className="resume-card" onClick={() => onOpen(letter.id)} aria-label={`Open ${letter.title}`}>
              <div className="resume-thumb classic letter-thumb"><div className="thumb-name">{letter.content.name || 'Your Name'}</div><div className="thumb-line long" /><div className="thumb-gap" /><div className="thumb-line" /><div className="thumb-line long" /><div className="thumb-line long" /><div className="thumb-line" /><div className="thumb-gap" /><div className="thumb-line long" /><div className="thumb-line" /></div>
              <div className="resume-card-foot"><div><strong>{letter.title}</strong><span>{jobTitleFor(letter) ? `${jobTitleFor(letter)} · ` : ''}Edited {fmtDateTime(letter.updated_at)}</span></div>
                <span className="letter-statuses"><span className={`mini-status ${reviewed ? 'reviewed' : ''}`}>{reviewed ? 'Reviewed' : 'Draft'}</span>{packet?.document_id === letter.id && <span className="mini-status reviewed">Attached</span>}</span></div>
            </button>
            <button className="icon-button danger resume-card-delete" title="Delete letter" aria-label={`Delete ${letter.title}`} disabled={busy} onClick={() => void remove(letter)}><Icon name="trash" /></button>
          </div>;
        })}</div> : <div className="empty-state"><div className="empty-art">Aa</div><h2>No cover letters yet.</h2><p>Write one for a job you saved. AI can write a first draft from your profile, or you can start blank.</p></div>}
      </section>
      {waiting.length > 0 && <section aria-label="Saved jobs without a letter"><div className="section-toolbar"><div><h2>Saved jobs without a letter</h2><p>A quick way to start one</p></div></div>
        <ul className="letter-waiting">{waiting.map((item) => <li key={item.id}><div><strong>{item.job!.title}</strong><span>{item.job!.company}{item.job!.location ? ` · ${item.job!.location}` : ''}</span></div>
          <button className="button secondary small-button" onClick={() => { setStart({ jobId: item.job_id, lockJob: false }); setStartError(''); }}>Write with AI ({remaining} of {limit} left)</button></li>)}</ul></section>}
    </>}
    {startDialog}
  </div>;
}
