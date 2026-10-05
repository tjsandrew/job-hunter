import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, getDevUser, setDevUser, HttpError } from './api';
import { addEntry, addSection, blankContent, moveItem, removeEntry, removeSection, updateBullet, updateEntry } from './editor';
import type { Application, Job, Me, ProfileDraft, Recommendation, Resume, ResumeContent, ResumeEntry, ResumeSection } from './types';

type Page = 'discover' | 'profile' | 'tracker' | 'studio';
const pageNames: Record<Page, string> = { discover: 'Discover', profile: 'Profile', tracker: 'Application tracker', studio: 'Resume studio' };
const emptyProfile = { name: '', email: '', phone: '', location: '', headline: '', summary: '', skills: '' };
const statusOptions = ['saved', 'preparing', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];
const asString = (value: unknown) => typeof value === 'string' ? value : '';
const profileToForm = (draft: ProfileDraft | undefined) => ({ ...emptyProfile, ...(draft || {}), skills: Array.isArray(draft?.skills) ? draft.skills.join(', ') : asString(draft?.skills) });
const formToProfile = (form: typeof emptyProfile): ProfileDraft => ({ ...form, skills: form.skills.split(',').map((x) => x.trim()).filter(Boolean) });

function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = { discover: 'M4 5h16M4 12h10M4 19h16M18 9l3 3-3 3', profile: 'M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', tracker: 'M4 5h16v15H4zM8 3v4m8-4v4M7 11h10m-10 4h6', studio: 'M5 3h14v18H5zM8 7h8M8 11h8M8 15h5', plus: 'M12 5v14m-7-7h14', search: 'm20 20-4.5-4.5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', arrow: 'M5 12h14m-7-7 7 7-7 7', back: 'M19 12H5m7 7-7-7 7-7', save: 'M5 3h12l3 3v15H4V3zm3 0v6h8V3m-8 18v-7h8v7', trash: 'M4 7h16m-10 4v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3', copy: 'M8 8h12v13H8zM4 16V3h12', check: 'm5 12 4 4L19 6', close: 'm6 6 12 12M18 6 6 18', up: 'm6 15 6-6 6 6', down: 'm6 9 6 6 6-6', download: 'M12 3v12m-5-5 5 5 5-5M5 21h14', undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-1', redo: 'm15 14 5-5-5-5m5 5H10a6 6 0 0 0 0 12h1' };
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.arrow} /></svg>;
}
function Loading({ label = 'Loading…' }: { label?: string }) { return <div className="loading"><span className="spinner" />{label}</div>; }
function Pill({ children, color = 'neutral' }: { children: React.ReactNode; color?: string }) { return <span className={`pill ${color}`}>{children}</span>; }
function initials(name: string) { return name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() || 'JH'; }
function fmtDate(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' }); }
function fmtDay(value?: string | null) { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
function salaryPeriod(value?: string | null) { if (!value) return ''; const normalized = value.toLowerCase(); if (normalized.includes('month')) return 'month'; if (normalized.includes('hour')) return 'hour'; if (normalized.includes('year') || normalized.includes('annual')) return 'year'; return value.replace(/^per[-_ ]?/i, '').replaceAll('-', ' '); }
function safeHttpUrl(value?: string) { if (!value) return null; try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } }

export default function App() {
  const [page, setPage] = useState<Page>('discover');
  const [user, setUser] = useState<'alice' | 'bob'>(getDevUser());
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState(false);
  const [fatal, setFatal] = useState('');
  const [toast, setToast] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [jobs, setJobs] = useState<Recommendation[]>([]);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [recommendationsDegraded, setRecommendationsDegraded] = useState(false);
  const [rankingStatus, setRankingStatus] = useState('');
  const [recommendationTotal, setRecommendationTotal] = useState(0);
  const [nextJobOffset, setNextJobOffset] = useState<number | null>(null);
  const [loadingMoreJobs, setLoadingMoreJobs] = useState(false);
  const searchRequestRevision = useRef(0);
  const [apps, setApps] = useState<Application[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [profile, setProfile] = useState<typeof emptyProfile>(emptyProfile);
  const [profileRevision, setProfileRevision] = useState(0);
  const [confirmed, setConfirmed] = useState<number | null>(null);
  const [profileSaved, setProfileSaved] = useState(true);
  const [preferences, setPreferences] = useState<any>({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: '', salary_currency: 'SGD', salary_period: 'year' });
  const [prefSaving, setPrefSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [extractedResumeText, setExtractedResumeText] = useState('');
  const [query, setQuery] = useState('');
  const [trackerQuery, setTrackerQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [activeResume, setActiveResume] = useState<Resume | null>(null);
  const latestResumeRef = useRef<Resume | null>(activeResume);
  const resumeSaveLock = useRef(false);
  latestResumeRef.current = activeResume;
  const [previewUrl, setPreviewUrl] = useState('');
  const [studioTab, setStudioTab] = useState<'edit' | 'preview'>('edit');
  const [saving, setSaving] = useState(false);
  const [saveLabel, setSaveLabel] = useState('Saved');
  const [history, setHistory] = useState<ResumeContent[]>([]);
  const [future, setFuture] = useState<ResumeContent[]>([]);
  const [busyJob, setBusyJob] = useState('');
  const [busyResumeAction, setBusyResumeAction] = useState(false);
  const [trackerEdit, setTrackerEdit] = useState<Application | null>(null);
  const [trackerSaving, setTrackerSaving] = useState(false);
  const [resumeAttachTarget, setResumeAttachTarget] = useState<{ job_id: string; title: string; revision: number } | null>(null);
  const [jobDetail, setJobDetail] = useState<Job | null>(null);

  useEffect(() => {
    let alive = true;
    setBusy(true); setFatal('');
    Promise.all([api.me(), api.getProfile(), api.getPreferences()])
      .then(([identity, profileData, prefs]) => {
        if (!alive) return;
        setMe(identity);
        if (profileSaved) { setProfile(profileToForm(profileData.draft)); setConfirmed(profileData.confirmed_revision ?? null); } setProfileRevision(profileData.revision || 0);
        setPreferences({ ...preferences, ...prefs, salary_min: prefs.salary_min ?? '' });
      }).catch((error: Error) => alive && setFatal(error.message)).finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [user, bootstrapAttempt, profileSaved]);

  useEffect(() => {
    let alive = true;
    setRecordsLoading(true);
    Promise.all([api.applications(), api.documents()]).then(([applications, documents]) => {
      if (!alive) return;
      setApps(applications.items || []); setResumes(documents.items || []);
    }).catch((error: Error) => alive && setFatal(error.message)).finally(() => alive && setRecordsLoading(false));
    return () => { alive = false; };
  }, [user, refresh, bootstrapAttempt]);

  useEffect(() => {
    let alive = true;
    const revision = ++searchRequestRevision.current;
    setLoadingMoreJobs(false); setRecommendationLoading(true);
    const timer = window.setTimeout(() => {
      api.recommendations(query, 0).then((result) => {
        if (!alive) return;
        setJobs(result.items || []); setRecommendationTotal(result.total ?? result.items.length);
        setNextJobOffset(result.next_offset ?? null); setRecommendationsDegraded(Boolean(result.degraded_mode)); setRankingStatus(result.ranking_status || '');
      }).catch((error: Error) => alive && setFatal(error.message)).finally(() => alive && setRecommendationLoading(false));
    }, 250);
    return () => { alive = false; clearTimeout(timer); if (searchRequestRevision.current === revision) searchRequestRevision.current += 1; };
  }, [user, query, refresh, bootstrapAttempt]);

  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 3200); return () => window.clearTimeout(timer); }, [toast]);
  const announce = (message: string) => { setToast(message); };
  const switchUser = (next: 'alice' | 'bob') => {
    if (next === user) return;
    if ((activeResume && saveLabel !== 'Saved') || saving || prefSaving || uploading || busyResumeAction || busyJob || trackerEdit || trackerSaving) {
      announce('Finish or close the current save or action before switching users.'); return;
    }
    setDevUser(next); setUser(next); setMe(null); setFatal('');
    setJobs([]); setRecommendationLoading(true); setRecordsLoading(true); setRecommendationTotal(0); setNextJobOffset(null); setRankingStatus(''); setApps([]); setResumes([]);
    setProfile(emptyProfile); setProfileRevision(0); setConfirmed(null); setProfileSaved(true);
    setPreferences({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: '', salary_currency: 'SGD', salary_period: 'year', revision: 0 });
    setUploadMessage(''); setExtractedResumeText(''); setQuery(''); setTrackerQuery(''); setStatusFilter('all');
    setActiveResume(null); setHistory([]); setFuture([]); setSaveLabel('Saved'); setStudioTab('edit'); setTrackerEdit(null); setResumeAttachTarget(null); setJobDetail(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl); setPreviewUrl(''); setToast('');
  };
  const filteredApps = useMemo(() => apps.filter((app) => (statusFilter === 'all' || app.status === statusFilter) && `${app.job?.title || ''} ${app.job?.company || ''}`.toLowerCase().includes(trackerQuery.toLowerCase())), [apps, statusFilter, trackerQuery]);

  const loadMoreJobs = async () => {
    if (nextJobOffset === null || loadingMoreJobs) return;
    setLoadingMoreJobs(true);
    const revision = searchRequestRevision.current;
    try {
      const result = await api.recommendations(query, nextJobOffset);
      if (revision !== searchRequestRevision.current) return;
      setJobs((current) => [...current, ...result.items.filter((item) => !current.some((loaded) => loaded.job.id === item.job.id))]);
      setRecommendationTotal(result.total ?? recommendationTotal); setNextJobOffset(result.next_offset ?? null); setRankingStatus(result.ranking_status || rankingStatus);
    } catch (error) { announce((error as Error).message); }
    finally { setLoadingMoreJobs(false); }
  };

  const review = async (job: Job, decision: 'saved' | 'dismissed') => {
    setBusyJob(job.id);
    try {
      await api.reviewJob(job.id, decision);
      setJobs((current) => current.filter((item) => item.job.id !== job.id));
      if (decision === 'saved') void api.applications().then((result) => setApps(result.items || [])).catch(() => undefined);
      setRefresh((value) => value + 1);
      announce(decision === 'saved' ? `${job.title} saved to your tracker.` : 'Job dismissed.');
    } catch (error) { announce((error as Error).message); }
    finally { setBusyJob(''); }
  };
  const saveProfile = async () => {
    setPrefSaving(true);
    try {
      await api.putProfile(formToProfile(profile), profileRevision);
      setProfileRevision((x) => x + 1); setProfileSaved(true); setRefresh((x) => x + 1); announce('Profile saved.');
    } catch (error) { announce((error as Error).message); }
    finally { setPrefSaving(false); }
  };
  const confirmProfile = async () => {
    setPrefSaving(true);
    try { const result: any = await api.confirmProfile(profileRevision); setConfirmed(result.revision); announce('Profile confirmed.'); }
    catch (error) { announce((error as Error).message); }
    finally { setPrefSaving(false); }
  };
  const uploadProfileResume = async (file?: File) => {
    if (!file) return;
    if (file.type !== 'application/pdf' || !file.name.toLowerCase().endsWith('.pdf')) { announce('Choose a PDF resume.'); return; }
    if (file.size > 10 * 1024 * 1024) { announce('PDF must be 10 MiB or smaller.'); return; }
    setUploading(true); setUploadMessage('Uploading and extracting PDF text…'); setExtractedResumeText('');
    try { const response = await api.uploadResume(file); setUploadMessage(`${response.message}${response.page_count ? ` · ${response.page_count} pages` : ''}${response.error_code ? ` · ${response.error_code}` : ''}`); setExtractedResumeText(response.extracted_text || ''); announce(response.extracted_text ? 'PDF text extracted for review.' : 'PDF uploaded; no readable text was returned.'); }
    catch (error) { setUploadMessage(''); announce((error as Error).message); }
    finally { setUploading(false); }
  };
  const savePreferences = async () => {
    setPrefSaving(true);
    const payload = { ...preferences, roles: String(preferences.rolesText ?? (preferences.roles || []).join(', ')).split(',').map((x: string) => x.trim()).filter(Boolean), locations: String(preferences.locationsText ?? (preferences.locations || []).join(', ')).split(',').map((x: string) => x.trim()).filter(Boolean), work_modes: String(preferences.workModesText ?? (preferences.work_modes || []).join(', ')).split(',').map((x: string) => x.trim()).filter(Boolean), salary_min: preferences.salary_min === '' ? null : Number(preferences.salary_min), expected_revision: preferences.revision || 0 };
    delete payload.rolesText; delete payload.locationsText; delete payload.workModesText;
    try { const updated: any = await api.putPreferences(payload); setPreferences({ ...preferences, ...updated }); setRefresh((x) => x + 1); announce('Preferences saved.'); }
    catch (error) { announce((error as Error).message); }
    finally { setPrefSaving(false); }
  };

  const createResume = async (jobId?: string) => {
    setBusyResumeAction(true);
    const fullContent = blankContent(); fullContent.name = profile.name;
    fullContent.email = profile.email; fullContent.phone = profile.phone; fullContent.location = profile.location; fullContent.summary = profile.summary;
    try {
      const created = await api.createDocument({ title: resumeAttachTarget ? `Resume for ${resumeAttachTarget.title}` : 'Untitled resume', template: 'classic', content: fullContent, layout: { font_size: 11, margin: 18, font_family: 'auto', line_spacing: 1.25, page_size: 'A4' }, job_id: jobId });
      setResumes((items) => [created, ...items]); openResume(created); announce('Resume created.');
    } catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };

  const createTailoredCopy = async (source: Resume) => {
    if (!resumeAttachTarget) return;
    setBusyResumeAction(true);
    try { const copy = await api.duplicateDocument(source.id, `${source.title} — ${resumeAttachTarget.title}`, resumeAttachTarget.job_id); setResumes((items) => [copy, ...items]); openResume(copy); announce('A separate resume draft was created for this application. Review it before attaching.'); }
    catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const openResume = (resume: Resume) => { const linkedApp = resume.job_id ? apps.find((application) => application.job_id === resume.job_id) : undefined; setResumeAttachTarget(linkedApp ? { job_id: linkedApp.job_id, title: linkedApp.job?.title || 'this opportunity', revision: linkedApp.revision } : null); setActiveResume(structuredClone(resume)); setHistory([]); setFuture([]); setStudioTab('edit'); setSaveLabel('Saved'); setPage('studio'); };
  const prepareApplicationResume = (application: Application) => {
    const attached = resumes.find((resume) => resume.id === application.resume_packet?.document_id);
    // Reopen this application's draft; never reuse a document linked to another job.
    const existing = attached?.job_id === application.job_id ? attached
      : resumes.find((resume) => resume.job_id === application.job_id);
    if (existing) openResume(existing);
    else { setActiveResume(null); setPage('studio'); }
    setResumeAttachTarget({ job_id: application.job_id, title: application.job?.title || 'this opportunity', revision: application.revision });
    setTrackerEdit(null);
  };
  const returnToApplication = () => {
    if (saving || saveLabel !== 'Saved') { announce('Wait for changes to save before returning.'); return; }
    const application = apps.find((item) => item.job_id === resumeAttachTarget?.job_id);
    setResumeAttachTarget(null); setActiveResume(null); setPage('tracker');
    setTrackerEdit(application || null);
  };

  const pushContent = (content: ResumeContent) => {
    if (!activeResume) return;
    setHistory((items) => [...items.slice(-49), activeResume.content]); setFuture([]); setActiveResume({ ...activeResume, content, reviewed_revision: null }); setSaveLabel('Unsaved');
  };
  const updateResume = (patch: Partial<Resume>) => { if (!activeResume) return; setActiveResume({ ...activeResume, ...patch, reviewed_revision: null }); setSaveLabel('Unsaved'); };
  const undo = () => { if (!activeResume || !history.length) return; const prior = history[history.length - 1]; setFuture((items) => [activeResume.content, ...items]); setHistory((items) => items.slice(0, -1)); setActiveResume({ ...activeResume, content: prior, reviewed_revision: null }); setSaveLabel('Unsaved'); };
  const redo = () => { if (!activeResume || !future.length) return; const next = future[0]; setHistory((items) => [...items, activeResume.content]); setFuture((items) => items.slice(1)); setActiveResume({ ...activeResume, content: next, reviewed_revision: null }); setSaveLabel('Unsaved'); };

  const persistResume = useCallback(async (resume: Resume) => {
    if (resumeSaveLock.current) return;
    resumeSaveLock.current = true;
    setSaving(true); setSaveLabel('Saving…');
    try {
      const updated = await api.patchDocument(resume.id, { title: resume.title, template: resume.template, content: resume.content, layout: resume.layout, expected_revision: resume.revision });
      const latest = latestResumeRef.current;
      const payloadOf = (item: Resume) => JSON.stringify([item.title, item.template, item.content, item.layout]);
      if (latest?.id === updated.id && latest.revision === resume.revision && payloadOf(latest) === payloadOf(resume)) {
        latestResumeRef.current = updated;
        setActiveResume(updated);
        setResumes((items) => items.map((item) => item.id === updated.id ? updated : item));
        setSaveLabel('Saved');
      } else if (latest?.id === updated.id) {
        // The server accepted this revision while the user continued typing.
        // Rebase the newer local draft onto the returned revision so the next
        // debounced save uses the right expected_revision.
        const rebased = { ...latest, revision: updated.revision, reviewed_revision: null };
        latestResumeRef.current = rebased;
        setActiveResume(rebased);
        setResumes((items) => items.map((item) => item.id === updated.id ? rebased : item));
        setSaveLabel('Unsaved');
      } else {
        setResumes((items) => items.map((item) => item.id === updated.id ? updated : item));
      }
    } catch (error) {
      const httpError = error as HttpError;
      setSaveLabel(httpError.status === 409 ? 'Conflict' : 'Save failed');
      announce(httpError.status === 409 ? 'This resume changed on the server. Reload it before saving more edits; your local edits are still here.' : httpError.message);
    } finally { resumeSaveLock.current = false; setSaving(false); }
  }, []);
  useEffect(() => {
    if (!activeResume || saveLabel !== 'Unsaved') return;
    const snapshot = structuredClone(activeResume);
    const timer = window.setTimeout(() => { void persistResume(snapshot); }, 700);
    return () => window.clearTimeout(timer);
  }, [activeResume, saveLabel, persistResume]);

  const duplicateResume = async () => {
    if (!activeResume) return; setBusyResumeAction(true);
    try { const copy = await api.duplicateDocument(activeResume.id, `${activeResume.title} copy`, resumeAttachTarget?.job_id); setResumes((items) => [copy, ...items]); openResume(copy); announce('A separate resume copy was created.'); }
    catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const reviewResume = async () => {
    if (!activeResume) return; setBusyResumeAction(true);
    try { const updated = await api.reviewDocument(activeResume.id, activeResume.revision); setActiveResume(updated); setResumes((items) => items.map((item) => item.id === updated.id ? updated : item)); announce(`Revision ${updated.revision} is reviewed and ready to export.`); }
    catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const attachResumeToApplication = async () => {
    if (!activeResume || !resumeAttachTarget || activeResume.reviewed_revision !== activeResume.revision || saveLabel !== 'Saved') return;
    setBusyResumeAction(true);
    try {
      const updated = await api.putApplication(resumeAttachTarget.job_id, { resume_document_id: activeResume.id, expected_resume_revision: activeResume.revision, expected_revision: resumeAttachTarget.revision });
      setApps((items) => items.map((item) => item.job_id === updated.job_id ? { ...item, ...updated } : item));
      setResumeAttachTarget(null); setActiveResume(null); setPage('tracker');
      setTrackerEdit({ ...apps.find((item) => item.job_id === updated.job_id), ...updated });
      announce(`Reviewed revision ${activeResume.revision} attached as a stored PDF snapshot. It has not been sent to the employer.`);
    } catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const exportResume = async () => {
    if (!activeResume || activeResume.reviewed_revision !== activeResume.revision) return;
    setBusyResumeAction(true);
    try { const result = await api.exportDocument(activeResume.id); const blob = await api.downloadExport(result.export_id); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${activeResume.title.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'resume'}.pdf`; document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 60_000); announce(`Exported revision ${result.revision}.`); }
    catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const previewResume = async () => {
    if (!activeResume) return;
    if (saveLabel !== 'Saved') { announce('Wait for autosave to finish before opening the server-rendered PDF preview.'); return; }
    try { const blob = await api.previewDocument(activeResume.id); const url = URL.createObjectURL(blob); setPreviewUrl((previous) => { if (previous) URL.revokeObjectURL(previous); return url; }); }
    catch (error) { announce((error as Error).message); }
  };
  const reloadResume = async () => { if (!activeResume) return; try { const docs = await api.documents(); const latest = docs.items.find((doc) => doc.id === activeResume.id); if (latest) { setResumes(docs.items); openResume(latest); announce('Latest server version loaded.'); } } catch (error) { announce((error as Error).message); } };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">j</div><div><strong>job hunter</strong><span>CAREER WORKSPACE</span></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{(['discover', 'profile', 'tracker', 'studio'] as Page[]).map((item) => <button key={item} aria-label={pageNames[item]} className={`nav-link ${page === item ? 'active' : ''}`} onClick={() => setPage(item)}><Icon name={item} /><span>{pageNames[item]}</span>{item === 'tracker' && apps.length > 0 && <b className="nav-count">{apps.length}</b>}</button>)}</nav>
      <div className="sidebar-bottom">
        <div className="ai-card"><span className="ai-icon">✳</span><div><strong>AI assistant</strong><p>Generation is unavailable in this local POC.</p><span className="status-dot" /> Offline</div></div>
        <div className="account-row"><div className="avatar">{initials(me?.display_name || user)}</div><div className="account-name"><strong>{me?.display_name || user}</strong><span>{user}@local.dev</span></div><select aria-label="Development user" value={user} onChange={(e) => switchUser(e.target.value as 'alice' | 'bob')}><option value="alice">Alice</option><option value="bob">Bob</option></select></div>
        <p className="dev-note">LOCAL DEVELOPMENT · {user.toUpperCase()}</p>
      </div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><span className="crumb-sep">/</span><strong>{activeResume && page === 'studio' ? activeResume.title : pageNames[page]}</strong></div><div className="topbar-right"><Pill color="green">Local POC</Pill><button className="help-button" title="Refresh workspace" aria-label="Refresh workspace" onClick={() => setRefresh((x) => x + 1)}>↻</button><select className="top-user-switch" aria-label="Development user" value={user} onChange={(e) => switchUser(e.target.value as 'alice' | 'bob')}><option value="alice">Alice</option><option value="bob">Bob</option></select><div className="avatar small">{initials(me?.display_name || user)}</div></div></header>
      <div className="content-area">
        {fatal && <div className="fatal"><div className="fatal-icon">!</div><div><strong>Could not load your workspace</strong><p>{fatal}</p><button className="button secondary small-button" onClick={() => { setFatal(''); setBootstrapAttempt((x) => x + 1); setRefresh((x) => x + 1); }}>Try again</button></div></div>}
        {!fatal && busy && <Loading label="Connecting to your workspace…" />}
        {!fatal && !busy && <>
          {page === 'discover' && <Discover jobs={jobs} loading={recommendationLoading} total={recommendationTotal} hasMore={nextJobOffset !== null} loadingMore={loadingMoreJobs} onLoadMore={loadMoreJobs} query={query} setQuery={setQuery} busyJob={busyJob} onReview={review} onDetails={setJobDetail} degraded={recommendationsDegraded} rankingStatus={rankingStatus} />}
          {page === 'profile' && <ProfileView profile={profile} setProfile={(value) => { setProfile(value); setProfileSaved(false); }} revision={profileRevision} confirmed={confirmed} saved={profileSaved} saving={prefSaving || uploading} onSave={saveProfile} onConfirm={confirmProfile} preferences={preferences} setPreferences={setPreferences} savePreferences={savePreferences} uploading={uploading} uploadMessage={uploadMessage} extractedResumeText={extractedResumeText} onUpload={uploadProfileResume} />}
          {page === 'tracker' && <Tracker apps={filteredApps} loading={recordsLoading} query={trackerQuery} setQuery={setTrackerQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter} onEdit={setTrackerEdit} />}
          {page === 'studio' && <Studio resumes={resumes} loading={recordsLoading} active={activeResume} attachTarget={resumeAttachTarget} tab={studioTab} setTab={setStudioTab} busy={busyResumeAction} saving={saving} saveLabel={saveLabel} history={history} future={future} onCreate={createResume} onOpen={openResume} onCreateTailoredCopy={createTailoredCopy} onAttach={attachResumeToApplication} onReturn={returnToApplication} onBack={() => { if (saveLabel !== 'Saved') { announce('Wait for the current changes to save before leaving the editor.'); return; } setActiveResume(null); }} onUpdate={updateResume} onContent={pushContent} onUndo={undo} onRedo={redo} onDuplicate={duplicateResume} onReview={reviewResume} onExport={exportResume} onPreview={previewResume} onReload={() => { if (saveLabel !== 'Saved') { announce('Wait for the current changes to save before reloading.'); return; } reloadResume(); }} />}
        </>}
      </div>
    </main>
    {toast && <div className="toast" role="status">{toast}<button onClick={() => setToast('')} aria-label="Dismiss notification"><Icon name="close" /></button></div>}
    {previewUrl && <div className="modal-backdrop pdf-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) { URL.revokeObjectURL(previewUrl); setPreviewUrl(''); } }}><section className="pdf-modal" role="dialog" aria-modal="true" aria-label="PDF resume preview"><div className="pdf-modal-head"><strong>PDF preview · server rendered</strong><button className="icon-button" aria-label="Close PDF preview" onClick={() => { URL.revokeObjectURL(previewUrl); setPreviewUrl(''); }}><Icon name="close" /></button></div><iframe title="Resume PDF preview" src={previewUrl} /></section></div>}
    {jobDetail && <JobDetailModal job={jobDetail} onClose={() => setJobDetail(null)} onReview={review} />}
    {trackerEdit && <TrackerModal application={trackerEdit} resumes={resumes} saving={trackerSaving} onClose={() => setTrackerEdit(null)} onPrepare={() => prepareApplicationResume(trackerEdit)} onDownload={async (exportId) => { try { const blob = await api.downloadExport(exportId); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${trackerEdit.resume_packet?.title || 'resume'}-revision-${trackerEdit.resume_packet?.revision || ''}.pdf`; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1500); } catch (error) { announce((error as Error).message); } }} onSave={async (changes) => { setTrackerSaving(true); try { const result = await api.putApplication(trackerEdit.job_id, { ...changes, expected_revision: trackerEdit.revision }); setApps((items) => items.map((item) => item.job_id === result.job_id ? { ...item, ...result } : item)); setTrackerEdit(null); announce('Application record updated. The packet is stored locally; it has not been sent to the employer.'); } catch (error) { announce((error as Error).message); } finally { setTrackerSaving(false); } }} />}
  </div>;
}

function Discover({ jobs, loading, total, hasMore, loadingMore, onLoadMore, query, setQuery, busyJob, onReview, onDetails, degraded, rankingStatus }: { jobs: Recommendation[]; loading: boolean; total: number; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void; query: string; setQuery: (v: string) => void; busyJob: string; onReview: (job: Job, decision: 'saved' | 'dismissed') => void; onDetails: (job: Job) => void; degraded: boolean; rankingStatus: string }) {
  return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR NEXT OPPORTUNITY</div><h1>Find your next move.</h1><p>Explore roles matched to your experience and preferences.</p></div><span className="ai-unavailable-badge">AI unavailable</span></div>
    <div className="discovery-summary"><div className="discovery-icon"><Icon name="search" /></div><div><strong>Opportunities from your sources</strong><p>{total} roles match your current filters. Review each one and save what feels right.</p></div></div>
    <div className="toolbar"><label className="search-field"><Icon name="search" /><input aria-label="Search jobs" placeholder="Search title, company, location..." value={query} onChange={(e) => setQuery(e.target.value)} /></label><span className="result-count">{total} results</span></div>
    {degraded && <div className="degraded-note"><span className="note-dot" /> {rankingStatus || 'Local text and skill matching is active.'}</div>}
    {jobs.length ? <><div className="job-list">{jobs.map(({ job, reasons, review }) => { const sourceUrl = safeHttpUrl(job.url || job.source_url); return <article className="job-card" key={job.id}><div className="company-logo">{initials(job.company || 'Company')}</div><div className="job-main"><div className="job-title-row"><h2><button className="job-title-button" onClick={() => onDetails(job)}>{job.title}</button></h2></div><div className="company-line"><strong>{job.company}</strong><span>·</span><span>{job.location || 'Location not specified'}</span>{job.work_mode && job.work_mode !== 'Not stated' && <><span>·</span><span>{job.work_mode}</span></>}</div><div className="job-tags">{job.employment_type && <Pill>{job.employment_type}</Pill>}{job.salary_min != null && <Pill>{job.salary_currency || ''} {Number(job.salary_min).toLocaleString()}{job.salary_max != null ? `–${Number(job.salary_max).toLocaleString()}` : '+'} {job.salary_period ? `/ ${salaryPeriod(job.salary_period)}` : ''}</Pill>}{job.source && <Pill>{job.source}{job.source_board ? ` · ${job.source_board}` : ''}</Pill>}</div>{reasons?.length ? <div className="match-reasons"><span>WHY IT MATCHES</span>{reasons.slice(0, 2).map((reason) => <span key={reason} className="reason"><Icon name="check" />{reason}</span>)}</div> : null}<p className="job-description">{job.description || 'The source did not provide a description.'}</p><button type="button" className="job-details-button" onClick={() => onDetails(job)}>Read full description</button><div className="job-foot">{job.posted_at && <span>Posted {fmtDay(job.posted_at)}</span>}{job.fetched_at && <span>Source checked {fmtDay(job.fetched_at)}</span>}{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">View source listing ↗</a>}</div></div><div className="job-actions"><button className="button ghost" disabled={busyJob === job.id} onClick={() => onReview(job, 'dismissed')}><Icon name="close" /> Pass</button><button className="button primary" disabled={busyJob === job.id || review === 'saved'} onClick={() => onReview(job, 'saved')}><Icon name="save" /> {review === 'saved' ? 'Saved' : 'Save job'}</button></div></article>; })}</div>{hasMore && <div className="load-more-row"><span>Showing {jobs.length} of {total}</span><button className="button secondary" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? 'Loading…' : 'Load more roles'}</button></div>}</> : loading ? <Loading label="Loading matching roles…" /> : <div className="empty-state"><div className="empty-art">⌕</div><h2>No roles found</h2><p>Try a different search or come back after new listings arrive.</p></div>}
  </div>;
}

function ProfileView({ profile, setProfile, revision, confirmed, saved, saving, onSave, onConfirm, preferences, setPreferences, savePreferences, uploading, uploadMessage, extractedResumeText, onUpload }: { profile: typeof emptyProfile; setProfile: (v: typeof emptyProfile) => void; revision: number; confirmed: number | null; saved: boolean; saving: boolean; onSave: () => void; onConfirm: () => void; preferences: any; setPreferences: (v: any) => void; savePreferences: () => void; uploading: boolean; uploadMessage: string; extractedResumeText: string; onUpload: (file?: File) => void }) {
  const update = (key: keyof typeof emptyProfile, value: string) => setProfile({ ...profile, [key]: value });
  const prefValue = (key: string, textKey: string) => preferences[textKey] ?? (Array.isArray(preferences[key]) ? preferences[key].join(', ') : preferences[key] ?? '');
  return <div className="page-wrap narrow-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR CAREER PROFILE</div><h1>A little about you.</h1><p>Keep your experience and preferences current to help us find the right fit.</p></div><Pill color={saved && confirmed === revision ? 'green' : 'amber'}>{saved && confirmed === revision ? 'Confirmed' : 'Not confirmed'}</Pill></div>
    <section className="panel"><div className="panel-heading"><div><h2>Personal details</h2><p>These details are used to prepare your resume.</p></div><span className="panel-step">01</span></div><div className="upload-strip"><div><strong>Start with your existing resume</strong><span>PDF only · up to 10 MiB · extracted text is a review candidate; AI fact structuring is unavailable</span>{uploadMessage && <small>{uploadMessage}</small>}</div><label className="button secondary upload-button">{uploading ? 'Uploading…' : 'Choose PDF'}<input aria-label="Upload resume PDF" type="file" accept="application/pdf,.pdf" disabled={uploading} onChange={(e) => { const file = e.target.files?.[0]; void onUpload(file); e.currentTarget.value = ''; }} /></label></div>{extractedResumeText && <label className="field extracted-candidate"><span>Extracted text candidate · verify details and enter profile facts manually</span><textarea readOnly value={extractedResumeText} rows={8} /></label>}<div className="form-grid"><Field label="Full name" value={profile.name} onChange={(v) => update('name', v)} placeholder="e.g. Alex Tan" /><Field label="Email address" value={profile.email} onChange={(v) => update('email', v)} placeholder="alex@example.com" type="email" /><Field label="Phone number" value={profile.phone} onChange={(v) => update('phone', v)} placeholder="+65 8123 4567" /><Field label="Location" value={profile.location} onChange={(v) => update('location', v)} placeholder="Singapore" /></div><Field label="Professional headline" value={profile.headline} onChange={(v) => update('headline', v)} placeholder="Product designer · 6 years experience" /><Field label="Professional summary" value={profile.summary} onChange={(v) => update('summary', v)} placeholder="A few sentences about your experience and what you do best..." multiline /><Field label="Skills" value={profile.skills} onChange={(v) => update('skills', v)} placeholder="Product strategy, Figma, User research" help="Separate skills with commas." /><div className="panel-footer"><span>{saved ? `Saved · revision ${revision}` : 'Unsaved profile changes'}</span><div><button className="button secondary" disabled={saving || saved} onClick={onSave}>Save profile</button><button className="button primary" disabled={saving || !saved || confirmed === revision} onClick={onConfirm}>Confirm profile <Icon name="check" /></button></div></div></section>
    <section className="panel"><div className="panel-heading"><div><h2>Job preferences</h2><p>Tell us what your next role should look like.</p></div><span className="panel-step">02</span></div><div className="form-grid"><Field label="Roles or job titles" value={prefValue('roles', 'rolesText')} onChange={(v) => setPreferences({ ...preferences, rolesText: v })} placeholder="Product manager, UX designer" /><Field label="Preferred locations" value={prefValue('locations', 'locationsText')} onChange={(v) => setPreferences({ ...preferences, locationsText: v })} placeholder="Singapore, Tokyo" /><SelectField label="Seniority" value={preferences.seniority || ''} onChange={(v) => setPreferences({ ...preferences, seniority: v })} options={['', 'Intern', 'Junior', 'Mid-level', 'Senior', 'Lead', 'Executive']} /><Field label="Work modes" value={prefValue('work_modes', 'workModesText')} onChange={(v) => setPreferences({ ...preferences, workModesText: v })} placeholder="On-site, Hybrid, Remote" /></div><p className="preference-scope-note">Role, location and work-mode preferences affect local results. Salary and seniority filters are planned.</p><div className="form-grid salary-fields"><Field label="Minimum salary" value={String(preferences.salary_min ?? '')} onChange={(v) => setPreferences({ ...preferences, salary_min: v })} placeholder="e.g. 5000" type="number" /><SelectField label="Currency" value={preferences.salary_currency || 'SGD'} onChange={(v) => setPreferences({ ...preferences, salary_currency: v })} options={['SGD', 'USD', 'AUD', 'GBP', 'EUR']} /><SelectField label="Salary period" value={preferences.salary_period || 'year'} onChange={(v) => setPreferences({ ...preferences, salary_period: v })} options={['year', 'month', 'hour']} /></div><div className="panel-footer"><span>Preferences are private to your account.</span><button className="button primary" disabled={saving} onClick={savePreferences}>Save preferences <Icon name="save" /></button></div></section>
    <div className="info-banner"><span className="info-icon">i</span><div><strong>Your profile stays yours.</strong><p>Resume edits never silently change your confirmed profile. Confirm your profile again when you want to update the facts used for matching.</p></div></div>
  </div>;
}
function Field({ label, value, onChange, placeholder, type = 'text', help, multiline = false, disabled = false }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; help?: string; multiline?: boolean; disabled?: boolean }) { return <label className="field"><span>{label}</span>{multiline ? <textarea disabled={disabled} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} rows={4} /> : <input disabled={disabled} type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />}{help && <small>{help}</small>}</label>; }
function SelectField({ label, value, onChange, options, disabled = false }: { label: string; value: string; onChange: (v: string) => void; options: string[]; disabled?: boolean }) { return <label className="field"><span>{label}</span><select disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)}>{options.map((option) => <option key={option} value={option}>{option || 'Select one'}</option>)}</select></label>; }

function JobDetailModal({ job, onClose, onReview }: { job: Job; onClose: () => void; onReview: (job: Job, decision: 'saved' | 'dismissed') => void }) {
  const sourceUrl = safeHttpUrl(job.url || job.source_url);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal job-detail-modal" role="dialog" aria-modal="true" aria-labelledby="job-detail-title" tabIndex={-1}><div className="modal-heading"><div><div className="eyebrow">FULL JOB DESCRIPTION</div><h2 id="job-detail-title">{job.title}</h2><p>{job.company} · {job.location || 'Location not specified'}{job.work_mode ? ` · ${job.work_mode}` : ''}</p></div><button className="icon-button" aria-label="Close job details" onClick={onClose}><Icon name="close" /></button></div><div className="job-detail-meta">{job.source_board && <span>Source: {job.source_board}</span>}{job.posted_at && <span>Posted {fmtDay(job.posted_at)}</span>}{job.employment_type && <span>{job.employment_type}</span>}</div><div className="job-detail-description">{job.description || 'The source did not provide a description.'}</div>{sourceUrl && <a className="job-source-link" href={sourceUrl} target="_blank" rel="noreferrer">Open original listing ↗</a>}<div className="modal-footer"><button className="button secondary" onClick={() => { onReview(job, 'dismissed'); onClose(); }}>Pass</button><button className="button primary" onClick={() => { onReview(job, 'saved'); onClose(); }}><Icon name="save" /> Save job</button></div></section></div>;
}

function Tracker({ apps, loading, query, setQuery, statusFilter, setStatusFilter, onEdit }: { apps: Application[]; loading: boolean; query: string; setQuery: (v: string) => void; statusFilter: string; setStatusFilter: (v: string) => void; onEdit: (app: Application) => void }) {
  const counts = statusOptions.map((status) => ({ status, count: apps.filter((app) => app.status === status).length }));
  return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR SEARCH, AT A GLANCE</div><h1>Keep the momentum.</h1><p>Track progress and keep the materials you prepared for each opportunity.</p></div><span className="tracker-total"><strong>{apps.length}</strong> tracked roles</span></div><div className="stat-grid">{[{ label: 'Saved', color: 'blue', key: 'saved' }, { label: 'In progress', color: 'purple', key: 'preparing' }, { label: 'Applied', color: 'orange', key: 'applied' }, { label: 'Interviews', color: 'green', key: 'interviewing' }].map((stat) => <div className="stat-card" key={stat.key}><div><span>{stat.label}</span><strong>{counts.find((item) => item.status === stat.key)?.count || 0}</strong></div><span className={`stat-mark ${stat.color}`} /></div>)}</div><div className="toolbar tracker-toolbar"><label className="search-field"><Icon name="search" /><input aria-label="Search applications" placeholder="Search applications..." value={query} onChange={(e) => setQuery(e.target.value)} /></label><select aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">All statuses</option>{statusOptions.map((status) => <option key={status} value={status}>{status[0].toUpperCase() + status.slice(1)}</option>)}</select><span className="result-count">{apps.length} applications</span></div>{loading ? <Loading label="Loading applications…" /> : apps.length ? <><div className="tracker-table-wrap"><table className="tracker-table"><thead><tr><th>ROLE</th><th>STATUS</th><th>APPLIED</th><th>PACKET</th><th></th></tr></thead><tbody>{apps.map((application) => <tr key={application.id}><td><div className="tracker-role"><div className="company-logo tiny">{initials(application.job?.company || '')}</div><div><strong>{application.job?.title || 'Job role'}</strong><span>{application.job?.company || 'Company'}</span></div></div></td><td><Pill color={application.status === 'interviewing' || application.status === 'offer' ? 'green' : application.status === 'applied' || application.status === 'preparing' ? 'blue' : 'neutral'}>{application.status}</Pill></td><td>{fmtDate(application.applied_at)}</td><td className="note-cell">{application.resume_packet ? `Resume · rev ${application.resume_packet.revision}` : 'No resume'}{application.cover_letter_text ? ' · Cover letter' : ''}</td><td><button className="button secondary small-button" aria-label={`Edit application: ${application.job?.title || 'Job role'}`} onClick={() => onEdit(application)}>Details</button></td></tr>)}</tbody></table></div><div className="tracker-responsive-cards">{apps.map((application) => <article className="tracker-responsive-card" key={`mobile-${application.id}`}><div className="tracker-responsive-head"><div><strong>{application.job?.title || 'Job role'}</strong><span>{application.job?.company || 'Company'}</span></div><Pill color={application.status === 'interviewing' || application.status === 'offer' ? 'green' : application.status === 'applied' || application.status === 'preparing' ? 'blue' : 'neutral'}>{application.status}</Pill></div><p>{application.resume_packet ? `${application.resume_packet.title} · rev ${application.resume_packet.revision}` : 'No resume snapshot'}{application.cover_letter_text ? ' · Cover letter saved' : ''}</p><button className="button secondary" aria-label={`Edit application: ${application.job?.title || 'Job role'}`} onClick={() => onEdit(application)}>View application</button></article>)}</div></> : <div className="empty-state compact"><div className="empty-art">↗</div><h2>{query || statusFilter !== 'all' ? 'No matching applications' : 'No applications yet'}</h2><p>{query || statusFilter !== 'all' ? 'Try another search or status filter.' : 'Save interesting jobs from Discover and they’ll appear here.'}</p></div>}</div>;
}
function TrackerModal({ application, resumes, saving, onClose, onSave, onDownload, onPrepare }: { application: Application; resumes: Resume[]; saving: boolean; onClose: () => void; onSave: (v: Record<string, unknown>) => void; onDownload: (exportId: string) => void; onPrepare: () => void }) {
  const [status, setStatus] = useState(application.status); const [notes, setNotes] = useState(application.notes || ''); const [appliedAt, setAppliedAt] = useState(application.applied_at?.slice(0, 10) || '');
  const initialLetter = application.cover_letter_text || ''; const [coverLetter, setCoverLetter] = useState(initialLetter); const [resumeChoice, setResumeChoice] = useState('');
  const reviewedResumes = resumes.filter((resume) => resume.reviewed_revision === resume.revision);
  const sourceUrl = safeHttpUrl(application.job?.url || application.job?.source_url);
  const selected = reviewedResumes.find((resume) => resume.id === resumeChoice);
  const modalRef = useRef<HTMLElement | null>(null);
  const dirty = status !== application.status || notes !== (application.notes || '') || appliedAt !== (application.applied_at?.slice(0, 10) || '') || coverLetter !== initialLetter || resumeChoice !== '';
  const dirtyRef = useRef(dirty); dirtyRef.current = dirty;
  const savingRef = useRef(saving); savingRef.current = saving;
  const closeRef = useRef(onClose); closeRef.current = onClose;
  const attemptClose = () => { if (savingRef.current) return; if (dirtyRef.current && !window.confirm('Discard unsaved application changes?')) return; closeRef.current(); };
  const attemptCloseRef = useRef(attemptClose); attemptCloseRef.current = attemptClose;
  useEffect(() => { const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null; modalRef.current?.focus(); const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); attemptCloseRef.current(); return; } if (event.key === 'Tab' && modalRef.current) { const items = [...modalRef.current.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')]; if (!items.length) { event.preventDefault(); modalRef.current.focus(); return; } const first = items[0], last = items[items.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } } }; window.addEventListener('keydown', onKey); return () => { window.removeEventListener('keydown', onKey); previous?.focus(); }; }, []);
  const submit = () => {
    const changes: Record<string, unknown> = { status, notes, applied_at: appliedAt ? new Date(`${appliedAt}T12:00:00`).toISOString() : null };
    if (resumeChoice === '__clear') changes.resume_export_id = null;
    else if (selected) { changes.resume_document_id = selected.id; changes.expected_resume_revision = selected.revision; }
    if (coverLetter !== initialLetter) changes.cover_letter_text = coverLetter || null;
    onSave(changes);
  };
  return <div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && attemptClose()}><section ref={modalRef} tabIndex={-1} className="modal tracker-modal" role="dialog" aria-modal="true" aria-labelledby="application-modal-title"><form onSubmit={(e) => { e.preventDefault(); submit(); }}><div className="modal-heading"><div><div className="eyebrow">APPLICATION DETAILS</div><h2 id="application-modal-title">{application.job?.title || 'Job application'}</h2><p>{application.job?.company}</p></div><button type="button" className="icon-button" aria-label="Close" disabled={saving} onClick={attemptClose}><Icon name="close" /></button></div>
    <div className="tracker-source-row">{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">View original job posting ↗</a> : <span>Source link unavailable</span>}</div>
    <div className="tracker-fields"><SelectField label="Status" value={status} onChange={setStatus} options={statusOptions} disabled={saving} /><Field label="Date applied" value={appliedAt} onChange={setAppliedAt} type="date" disabled={saving} /></div>
    <Field label="Notes" value={notes} onChange={setNotes} placeholder="Add a reminder or follow-up note..." multiline disabled={saving} />
    <section className="packet-section"><div className="packet-heading"><div><h3>Application packet</h3><p>Stored for your reference. Nothing is sent to the employer.</p></div><button type="button" className="button secondary small-button" disabled={saving || dirty} onClick={onPrepare}>Prepare resume</button></div>{dirty && <p className="packet-empty">Save or discard your current application edits before preparing a resume.</p>}
      {application.resume_packet ? <div className="attached-resume"><div><strong>{application.resume_packet.title}</strong><span>Reviewed revision {application.resume_packet.revision} · PDF snapshot</span></div><button type="button" className="button secondary small-button" disabled={saving} onClick={() => onDownload(application.resume_packet!.export_id)}>Download</button></div> : <p className="packet-empty">No resume snapshot attached.</p>}
      <label className="field"><span>{application.resume_packet ? 'Replace resume snapshot' : 'Attach reviewed resume'}</span><select aria-label="Attach reviewed resume" value={resumeChoice} disabled={saving} onChange={(e) => setResumeChoice(e.target.value)}><option value="">{application.resume_packet ? 'Keep current attachment' : 'No resume selected'}</option>{reviewedResumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title} · revision {resume.revision}</option>)}{application.resume_packet && <option value="__clear">Remove attached resume</option>}</select>{!reviewedResumes.length && <small>Review a current resume revision in Resume Studio before attaching it.</small>}</label>
      <Field label="Cover letter (written by you)" value={coverLetter} onChange={(value) => setCoverLetter(value.slice(0, 20000))} placeholder="Write or paste the letter you prepared for this role…" multiline disabled={saving} help={`${coverLetter.length.toLocaleString()} / 20,000 characters`} />
      {application.cover_letter_text && <div className="packet-saved-note">Cover letter saved with this application. <button type="button" className="link-button" onClick={() => { const blob = new Blob([application.cover_letter_text || ''], { type: 'text/plain;charset=utf-8' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${(application.job?.company || 'application').replace(/[^a-z0-9]+/gi, '-')}-cover-letter.txt`; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1500); }}>Download saved cover letter</button></div>}
    </section>
    <div className="modal-footer"><button type="button" className="button secondary" disabled={saving} onClick={attemptClose}>Cancel</button><button className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save application record'}</button></div></form></section></div>;
}

function Studio({ resumes, loading, active, attachTarget, tab, setTab, busy, saving, saveLabel, history, future, onCreate, onOpen, onCreateTailoredCopy, onAttach, onReturn, onBack, onUpdate, onContent, onUndo, onRedo, onDuplicate, onReview, onExport, onPreview, onReload }: { resumes: Resume[]; loading: boolean; active: Resume | null; attachTarget: { job_id: string; title: string; revision: number } | null; tab: 'edit' | 'preview'; setTab: (tab: 'edit' | 'preview') => void; busy: boolean; saving: boolean; saveLabel: string; history: ResumeContent[]; future: ResumeContent[]; onCreate: (jobId?: string) => void; onOpen: (resume: Resume) => void; onCreateTailoredCopy: (resume: Resume) => void; onAttach: () => void; onReturn: () => void; onBack: () => void; onUpdate: (patch: Partial<Resume>) => void; onContent: (content: ResumeContent) => void; onUndo: () => void; onRedo: () => void; onDuplicate: () => void; onReview: () => void; onExport: () => void; onPreview: () => void; onReload: () => void }) {
  const [sourceResumeId, setSourceResumeId] = useState('');
  const sourceResume = resumes.find((resume) => resume.id === sourceResumeId);
  if (!active && loading) return <div className="page-wrap"><Loading label="Loading your resume library…" /></div>;
  if (!active) return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR DOCUMENTS</div><h1>Your story, on paper.</h1><p>Create a polished resume that sounds like you. No AI needed.</p></div><button className="button primary" disabled={busy} onClick={() => onCreate(attachTarget?.job_id)}><Icon name="plus" /> Create resume</button></div><div className="studio-callout"><div className="callout-symbol">Aa</div><div><strong>Built for thoughtful applications.</strong><p>Start from a blank page, keep your details in one place, and create a tailored copy for every opportunity.</p></div><div className="callout-types"><span>2 templates</span><span>PDF export</span><span>Autosave</span></div></div>{attachTarget && <section className="prepare-banner"><div><strong>Preparing for {attachTarget.title}</strong><p>Create a separate draft, review the finished revision, then attach its PDF snapshot to this application.</p></div><div className="prepare-actions"><label className="field"><span>Start from a resume</span><select aria-label="Choose a resume to tailor" value={sourceResumeId} onChange={(event) => setSourceResumeId(event.target.value)}><option value="">Select a resume…</option>{resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title}</option>)}</select></label><button className="button secondary" disabled={!sourceResume || busy} onClick={() => sourceResume && onCreateTailoredCopy(sourceResume)}>Create tailored copy</button><button className="button ghost" disabled={busy} onClick={onReturn}>Return to tracker</button></div></section>}{resumes.length ? <><div className="section-toolbar"><div><h2>Resume library</h2><p>{resumes.length} {resumes.length === 1 ? 'document' : 'documents'}</p></div></div><div className="resume-grid">{resumes.map((resume) => <button className="resume-card" key={resume.id} onClick={() => attachTarget ? onCreateTailoredCopy(resume) : onOpen(resume)} aria-label={attachTarget ? `Create tailored copy from ${resume.title}` : `Open ${resume.title}`}><div className={`resume-thumb ${resume.template}`}><div className="thumb-name">{resume.content.name || 'Your Name'}</div><div className="thumb-line long" /><div className="thumb-line" /><div className="thumb-gap" />{resume.content.sections.slice(0, 2).map((section) => <div className="thumb-section" key={section.id}><div className="thumb-head">{section.title || 'Section'}</div><div className="thumb-line long" />{section.entries.slice(0, 2).map((entry) => <div className="thumb-line" key={entry.id} />)}<div className="thumb-gap" /></div>)}</div><div className="resume-card-foot"><div><strong>{resume.title}</strong><span>Edited {fmtDate(resume.updated_at)}</span></div><span className={`mini-status ${resume.reviewed_revision === resume.revision ? 'reviewed' : ''}`}>{resume.reviewed_revision === resume.revision ? 'Reviewed' : 'Draft'}</span></div></button>)}</div></> : <div className="empty-state"><div className="empty-art">Aa</div><h2>A clean slate.</h2><p>Your resume library is empty. Create a resume to get started.</p><button className="button primary" onClick={() => onCreate(attachTarget?.job_id)}><Icon name="plus" /> Create your first resume</button></div>}</div>;
  return <div className="editor-page" data-busy={busy ? 'true' : 'false'} aria-busy={busy}><div className="editor-head">{attachTarget && <div className="active-prepare-banner"><span>Preparing for <strong>{attachTarget.title}</strong></span><button className="button primary small-button" disabled={busy || saving || saveLabel !== 'Saved' || active.reviewed_revision !== active.revision} onClick={onAttach}>Attach reviewed revision</button><button className="button ghost small-button" disabled={busy || saving || saveLabel !== 'Saved'} onClick={onReturn}>Return to tracker</button></div>}<button className="back-link" onClick={onBack}><Icon name="back" /> Library</button><div className="editor-title"><input aria-label="Resume title" disabled={busy} value={active.title} onChange={(e) => onUpdate({ title: e.target.value })} /><span className={`save-state ${saveLabel === 'Saved' ? 'saved' : ''}`}><i />{saveLabel}{saving ? '…' : ''}</span></div><div className="editor-actions"><button className="icon-button" title="Undo" aria-label="Undo" onClick={onUndo} disabled={busy || !history.length}><Icon name="undo" /></button><button className="icon-button" title="Redo" aria-label="Redo" onClick={onRedo} disabled={busy || !future.length}><Icon name="redo" /></button><button className="button secondary" onClick={onDuplicate} disabled={busy || saving || saveLabel !== 'Saved'}><Icon name="copy" /> Duplicate</button><button className="button primary" onClick={onExport} disabled={busy || active.reviewed_revision !== active.revision}><Icon name="download" /> Export PDF</button></div></div><div className="editor-toolbar"><div className="template-select"><span>STYLE</span><button className={active.template === 'classic' ? 'selected' : ''} disabled={busy} onClick={() => onUpdate({ template: 'classic' })}>Classic serif</button><button className={active.template === 'modern' ? 'selected' : ''} disabled={busy} onClick={() => onUpdate({ template: 'modern' })}>Modern sans</button></div><div className="layout-controls"><div className="editor-view-toggle" role="group" aria-label="Editor view"><button className={tab === 'edit' ? 'selected' : ''} aria-pressed={tab === 'edit'} onClick={() => setTab('edit')}>Edit</button><button className={tab === 'preview' ? 'selected' : ''} aria-pressed={tab === 'preview'} onClick={() => setTab('preview')}>Preview</button></div><label>Size <select aria-label="Font size" value={active.layout.font_size} disabled={busy} onChange={(e) => onUpdate({ layout: { ...active.layout, font_size: Math.min(16, Math.max(8, Number(e.target.value))) } })}>{[8, 9, 10, 11, 12, 13, 14, 15, 16].map((size) => <option key={size}>{size}</option>)}</select></label><label>Margin <select aria-label="Page margin" value={active.layout.margin} disabled={busy} onChange={(e) => onUpdate({ layout: { ...active.layout, margin: Math.min(35, Math.max(10, Number(e.target.value))) } })}>{[10, 12, 15, 18, 20, 24, 28, 30, 35].map((size) => <option key={size} value={size}>{size} mm</option>)}</select></label><label>Typeface <select aria-label="Resume typeface" disabled={busy} value={active.layout.font_family || 'auto'} onChange={(e) => onUpdate({ layout: { ...active.layout, font_family: e.target.value as NonNullable<Resume['layout']['font_family']> } })}>{[['auto', 'Template default'], ['serif', 'Serif'], ['sans', 'Sans serif'], ['mono', 'Monospace']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Line spacing <select aria-label="Line spacing" disabled={busy} value={active.layout.line_spacing || 1.25} onChange={(e) => onUpdate({ layout: { ...active.layout, line_spacing: Number(e.target.value) } })}>{[1, 1.15, 1.25, 1.4, 1.6, 1.8].map((value) => <option key={value} value={value}>{value.toFixed(2).replace(/0$/, '')}</option>)}</select></label><label>Paper <select aria-label="Page size" disabled={busy} value={active.layout.page_size || 'A4'} onChange={(e) => onUpdate({ layout: { ...active.layout, page_size: e.target.value as 'A4' | 'letter' } })}><option value="A4">A4</option><option value="letter">US Letter</option></select></label><button className="button ghost preview-button" onClick={onPreview} disabled={saving || saveLabel !== 'Saved'}><Icon name="search" /> PDF preview</button></div></div><div className="editor-main" inert={busy}><div className={`editor-pane ${tab === 'preview' ? 'hidden-mobile' : ''}`}><div className="editor-pane-head"><div><strong>Resume content</strong><span>Edit your story and structure.</span></div><div><button className="button text-button" onClick={onReview} disabled={busy || saveLabel !== 'Saved'}>{active.reviewed_revision === active.revision ? <><Icon name="check" /> Reviewed</> : 'Mark as reviewed'}</button></div></div><div className="editor-scroll"><ContactEditor content={active.content} onContent={onContent} /><Field label="Professional summary" value={active.content.summary} onChange={(value) => onContent({ ...active.content, summary: value })} multiline placeholder="Write a short introduction that highlights your strengths..." /><div className="section-edit-toolbar"><h3>Sections</h3><button className="button text-button" onClick={() => onContent(addSection(active.content))}><Icon name="plus" /> Add section</button></div>{active.content.sections.map((section, index) => <SectionEditor key={section.id} section={section} index={index} count={active.content.sections.length} content={active.content} onContent={onContent} />)}<div className="editor-end-note">Your resume remains editable after review. Any change creates a new revision and will need review before export.</div></div></div><div className={`preview-pane ${tab === 'edit' ? 'hidden-mobile' : ''}`}><div className="preview-head"><div><strong>Live preview</strong><span>Approximate layout · final PDF generated by server</span></div><span className="page-count">{active.layout.page_size || 'A4'} · live layout</span></div><div className="paper-stage"><ResumePreview resume={active} /></div></div></div><div className="editor-footer"><span><span className="footer-dot" />{saveLabel === 'Saved' ? 'All changes saved' : saveLabel}</span><span>Changes are saved automatically</span><button className="button secondary small-button" disabled={busy || active.reviewed_revision !== active.revision} onClick={onExport}><Icon name="download" /> Export reviewed PDF</button><button className="link-button" onClick={onReload}>Reload latest</button></div></div>;
}

function ContactEditor({ content, onContent }: { content: ResumeContent; onContent: (v: ResumeContent) => void }) {
  const keys: (keyof ResumeContent)[] = ['name', 'email', 'phone', 'location']; const labels: Record<string, string> = { name: 'Full name', email: 'Email', phone: 'Phone', location: 'Location' };
  return <div className="contact-editor"><h3>Contact details</h3><div className="form-grid two-col">{keys.map((key) => <Field key={key} label={labels[key]} value={content[key] as string} onChange={(value) => onContent({ ...content, [key]: value })} placeholder={labels[key]} />)}</div></div>;
}
function SectionEditor({ section, index, count, content, onContent }: { section: ResumeSection; index: number; count: number; content: ResumeContent; onContent: (value: ResumeContent) => void }) {
  const patchSection = (patch: Partial<ResumeSection>) => onContent({ ...content, sections: content.sections.map((item) => item.id === section.id ? { ...item, ...patch } : item) });
  const move = (delta: -1 | 1) => onContent({ ...content, sections: moveItem(content.sections, index, delta) });
  const patchEntry = (id: string, patch: Partial<ResumeEntry>) => onContent(updateEntry(content, section.id, id, patch));
  const removeBullet = (entry: ResumeEntry, bulletIndex: number) => patchEntry(entry.id, { bullets: entry.bullets.filter((_, i) => i !== bulletIndex) });
  return <section className="section-editor"><div className="section-edit-head"><div className="section-grip">⠿</div><input aria-label="Section title" className="section-title-input" value={section.title} onChange={(e) => patchSection({ title: e.target.value })} /><button className="icon-button" title="Move section up" disabled={index === 0} onClick={() => move(-1)}><Icon name="up" /></button><button className="icon-button" title="Move section down" disabled={index === count - 1} onClick={() => move(1)}><Icon name="down" /></button><button className="icon-button danger" title="Remove section" onClick={() => onContent(removeSection(content, section.id))}><Icon name="trash" /></button></div>{section.entries.map((entry, entryIndex) => <div className="entry-editor" key={entry.id}><div className="entry-edit-head"><span>Entry {entryIndex + 1}</span><button className="icon-button danger" title="Remove entry" onClick={() => onContent({ ...content, sections: content.sections.map((item) => item.id === section.id ? removeEntry(item, entry.id) : item) })}><Icon name="trash" /></button></div><div className="form-grid two-col"><Field label="Role or degree" value={entry.heading} onChange={(v) => patchEntry(entry.id, { heading: v })} placeholder="Senior Product Designer" /><Field label="Company or school" value={entry.subheading} onChange={(v) => patchEntry(entry.id, { subheading: v })} placeholder="Company name" /></div><Field label="Dates" value={entry.dates} onChange={(v) => patchEntry(entry.id, { dates: v })} placeholder="Jan 2022 – Present" />{entry.bullets.map((bullet, bulletIndex) => <div className="bullet-row" key={`${entry.id}-${bulletIndex}`}><span>•</span><textarea aria-label={`Bullet ${bulletIndex + 1}`} value={bullet} rows={2} placeholder="Describe an accomplishment and its impact..." onChange={(e) => onContent(updateBullet(content, section.id, entry.id, bulletIndex, e.target.value))} /><button className="icon-button danger" title="Remove bullet" disabled={entry.bullets.length < 2} onClick={() => removeBullet(entry, bulletIndex)}><Icon name="close" /></button></div>)}<button className="button text-button" onClick={() => patchEntry(entry.id, { bullets: [...entry.bullets, ''] })}><Icon name="plus" /> Add bullet</button></div>)}<button className="button secondary add-entry" onClick={() => patchSection(addEntry(section))}><Icon name="plus" /> Add entry</button></section>;
}
function ResumePreview({ resume }: { resume: Resume }) {
  const { content } = resume;
  return <article className={`resume-paper ${resume.template} font-${resume.layout.font_family || 'auto'} paper-${resume.layout.page_size || 'A4'}`} style={{ fontSize: `${resume.layout.font_size}px`, padding: `${resume.layout.margin * 2.5}px`, lineHeight: resume.layout.line_spacing || 1.25 }}><header className="paper-header"><h1>{content.name || 'Your Name'}</h1><div>{[content.email, content.phone, content.location].filter(Boolean).join('  ·  ') || 'Email · Phone · Location'}</div></header>{content.summary && <p className="paper-summary">{content.summary}</p>}{content.sections.map((section) => <section className="paper-section" key={section.id}><h2>{section.title || 'Section'}</h2>{section.entries.map((entry) => <div className="paper-entry" key={entry.id}><div className="paper-entry-head"><strong>{entry.heading || 'Role, degree, or project'}</strong><span>{entry.dates}</span></div><div className="paper-subheading">{entry.subheading}</div>{entry.bullets.some(Boolean) && <ul>{entry.bullets.filter(Boolean).map((bullet, i) => <li key={i}>{bullet}</li>)}</ul>}</div>)}</section>)}</article>;
}
