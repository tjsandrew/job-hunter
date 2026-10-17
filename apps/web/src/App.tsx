import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, getDevUser, setDevUser, HttpError } from './api';
import { blankContent } from './editor';
import type { Application, Job, Me, Recommendation, Resume, ResumeContent } from './types';

import { Field, Icon, Loading, Pill, SelectField, fmtDate } from './ui';
import { emptyProfile, profileToForm } from './profile/form';
import { ProfileView } from './profile/ProfileView';
import { Studio } from './studio/Studio';
import { applyDefaults } from './studio/build/defaults';

type Page = 'discover' | 'profile' | 'tracker' | 'studio';
const pageNames: Record<Page, string> = { discover: 'Discover', profile: 'Profile', tracker: 'Application tracker', studio: 'Resume studio' };
const statusOptions = ['saved', 'preparing', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];

function initials(name: string) { return name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() || 'JH'; }

function fmtDay(value?: string | null) { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
function salaryPeriod(value?: string | null) { if (!value) return ''; const normalized = value.toLowerCase(); if (normalized.includes('month')) return 'month'; if (normalized.includes('hour')) return 'hour'; if (normalized.includes('year') || normalized.includes('annual')) return 'year'; return value.replace(/^per[-_ ]?/i, '').replaceAll('-', ' '); }
function safeHttpUrl(value?: string) { if (!value) return null; try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } }

export default function App() {
  const [page, setPage] = useState<Page>('discover');
  const [user, setUser] = useState<'alice' | 'casey'>(getDevUser());
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState(false);
  const [fatal, setFatal] = useState('');
  const [toast, setToast] = useState('');
  const [toastAction, setToastAction] = useState<{ label: string; run: () => void } | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [jobs, setJobs] = useState<Recommendation[]>([]);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [recommendationsDegraded, setRecommendationsDegraded] = useState(false);
  const [rankingStatus, setRankingStatus] = useState('');
  const [discoverMode, setDiscoverMode] = useState<'for-you' | 'all'>('for-you');
  const [forYouNote, setForYouNote] = useState('');
  const [recommendationTotal, setRecommendationTotal] = useState(0);
  const [nextJobOffset, setNextJobOffset] = useState<number | null>(null);
  const [loadingMoreJobs, setLoadingMoreJobs] = useState(false);
  const searchRequestRevision = useRef(0);
  const [apps, setApps] = useState<Application[]>([]);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [profile, setProfile] = useState<typeof emptyProfile>(emptyProfile);
  const [profileBusy, setProfileBusy] = useState(false);
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
        setProfile(profileToForm(profileData.draft));
        setPreferences({ ...preferences, ...prefs, salary_min: prefs.salary_min ?? '' });
      }).catch((error: Error) => alive && setFatal(error.message)).finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [user, bootstrapAttempt]);

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
      fetchJobs(discoverMode, query, 0).then((result) => {
        if (!alive) return;
        setJobs(result.items || []); setRecommendationTotal(result.total ?? result.items.length);
        setNextJobOffset(result.next_offset ?? null); setRecommendationsDegraded(Boolean(result.degraded_mode)); setRankingStatus(result.ranking_status || '');
        setForYouNote(result.note);
      }).catch((error: Error) => alive && setFatal(error.message)).finally(() => alive && setRecommendationLoading(false));
    }, 250);
    return () => { alive = false; clearTimeout(timer); if (searchRequestRevision.current === revision) searchRequestRevision.current += 1; };
  }, [user, query, refresh, bootstrapAttempt, discoverMode]);

  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => { setToast(''); setToastAction(null); }, toastAction ? 9000 : 3200); return () => window.clearTimeout(timer); }, [toast, toastAction]);
  const announce = (message: string) => { setToast(message); setToastAction(null); };
  const switchUser = (next: 'alice' | 'casey') => {
    if (next === user) return;
    if ((activeResume && saveLabel !== 'Saved') || saving || prefSaving || uploading || busyResumeAction || busyJob || trackerEdit || trackerSaving || profileBusy) {
      announce('Finish or close the current save or action before switching users.'); return;
    }
    setDevUser(next); setUser(next); setMe(null); setFatal('');
    setJobs([]); setRecommendationLoading(true); setRecordsLoading(true); setRecommendationTotal(0); setNextJobOffset(null); setRankingStatus(''); setApps([]); setResumes([]);
    setProfile(emptyProfile);
    setPreferences({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: '', salary_currency: 'SGD', salary_period: 'year', revision: 0 });
    setUploadMessage(''); setExtractedResumeText(''); setQuery(''); setTrackerQuery(''); setStatusFilter('all');
    setActiveResume(null); setHistory([]); setFuture([]); setSaveLabel('Saved'); setStudioTab('edit'); setTrackerEdit(null); setResumeAttachTarget(null); setJobDetail(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl); setPreviewUrl(''); setToast('');
  };
  const filteredApps = useMemo(() => apps.filter((app) => (statusFilter === 'all' || app.status === statusFilter) && `${app.job?.title || ''} ${app.job?.company || ''}`.toLowerCase().includes(trackerQuery.toLowerCase())), [apps, statusFilter, trackerQuery]);

  // "For you" first; if it cannot answer (disabled, error) fall back to the original keyword list and say so.
  const fetchJobs = async (mode: 'for-you' | 'all', q: string, offset: number) => {
    if (mode === 'all') return { ...(await api.recommendations(q, offset)), note: '' };
    try {
      const result = await api.recommendationsForYou(q, offset);
      return { ...result, note: result.ranking_mode === 'keyword_fallback' ? (result.fallback_reason || 'For you is not ready yet, so all jobs are shown.') : '' };
    } catch {
      return { ...(await api.recommendations(q, offset)), note: 'For you is unavailable right now, so all jobs are shown.' };
    }
  };

  const loadMoreJobs = async () => {
    if (nextJobOffset === null || loadingMoreJobs) return;
    setLoadingMoreJobs(true);
    const revision = searchRequestRevision.current;
    try {
      const result = await fetchJobs(discoverMode, query, nextJobOffset);
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
  const uploadProfileResume = async (file?: File) => {
    if (!file) return;
    const lowerName = file.name.toLowerCase();
    if (lowerName.endsWith('.doc')) { announce('Legacy Word (.doc) files are not supported. Save it as PDF or .docx and upload again.'); return; }
    if (!lowerName.endsWith('.pdf') && !lowerName.endsWith('.docx')) { announce('Choose a PDF or Word (.docx) resume.'); return; }
    if (file.size > 10 * 1024 * 1024) { announce('The file must be 10 MiB or smaller.'); return; }
    setUploading(true); setUploadMessage('Uploading and extracting text…'); setExtractedResumeText('');
    try { const response = await api.uploadResume(file); setUploadMessage(`${response.message}${response.page_count ? ` · ${response.page_count} pages` : ''}${response.error_code ? ` · ${response.error_code}` : ''}`); setExtractedResumeText(response.extracted_text || ''); announce(response.extracted_text ? 'Resume text extracted for review.' : 'Resume uploaded; no readable text was returned.'); }
    catch (error) { setUploadMessage(''); announce((error as Error).message); }
    finally { setUploading(false); }
  };
  const savePreferences = async () => {
    setPrefSaving(true);
    const list = (value: unknown): string[] => (Array.isArray(value) ? value.map((x) => String(x).trim()).filter(Boolean) : []);
    const payload = { ...preferences, roles: list(preferences.roles), locations: list(preferences.locations), work_modes: list(preferences.work_modes), salary_min: preferences.salary_min === '' ? null : Number(preferences.salary_min), expected_revision: preferences.revision || 0 };
    try { const updated: any = await api.putPreferences(payload); setPreferences({ ...preferences, ...updated }); setRefresh((x) => x + 1); announce('Preferences saved.'); }
    catch (error) {
      if (error instanceof HttpError && error.status === 409) {
        try { const latest = await api.getPreferences(); setPreferences({ ...latest, salary_min: latest.salary_min ?? '' }); announce('This changed elsewhere, reloaded'); }
        catch (reloadError) { announce((reloadError as Error).message); }
      } else announce((error as Error).message);
    }
    finally { setPrefSaving(false); }
  };

  const createResume = async (jobId?: string) => {
    setBusyResumeAction(true);
    const fullContent = blankContent(); fullContent.name = profile.name;
    fullContent.email = profile.email; fullContent.phone = profile.phone; fullContent.location = profile.location; fullContent.summary = profile.summary;
    try {
      // A new resume starts from the user's saved defaults; without them it is the built-in blank.
      let defaults: Awaited<ReturnType<typeof api.getSettings>>['resume_defaults'] | undefined;
      try { defaults = (await api.getSettings()).resume_defaults; } catch { /* no settings yet */ }
      const start = applyDefaults({ template: 'classic', content: fullContent, layout: { font_size: 11, margin: 18, font_family: 'auto', line_spacing: 1.25, page_size: 'A4' } }, defaults);
      const created = await api.createDocument({ title: resumeAttachTarget ? `Resume for ${resumeAttachTarget.title}` : 'Untitled resume', template: start.template, content: start.content, layout: start.layout, job_id: jobId });
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
  const copyResume = async (source: Resume) => {
    setBusyResumeAction(true);
    try { const copy = await api.duplicateDocument(source.id, `${source.title} copy`); setResumes((items) => [copy, ...items]); openResume(copy); announce('A separate resume copy was created.'); }
    catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const restoreResume = async (resume: Resume, index: number) => {
    try {
      const restored = await api.restoreDocument(resume.id);
      setResumes((items) => items.some((item) => item.id === restored.id) ? items : [...items.slice(0, index), restored, ...items.slice(index)]);
      announce(`"${restored.title}" restored.`);
    } catch (error) { announce((error as Error).message); }
  };
  const deleteResume = async (resume: Resume) => {
    if (busyResumeAction) return;
    setBusyResumeAction(true);
    try {
      await api.archiveDocument(resume.id);
      const index = Math.max(0, resumes.findIndex((item) => item.id === resume.id));
      setResumes((items) => items.filter((item) => item.id !== resume.id));
      // The open resume went away: back to the library.
      if (activeResume?.id === resume.id) { setActiveResume(null); setHistory([]); setFuture([]); setSaveLabel('Saved'); setStudioTab('edit'); }
      setToast(`"${resume.title}" deleted.`);
      setToastAction({ label: 'Undo', run: () => void restoreResume(resume, index) });
    } catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };
  const resumeBuilt = (created: Resume) => { setResumes((items) => [created, ...items]); openResume(created); announce('Resume created from your profile. Review it before exporting.'); };
  const buildJobs = useMemo(() => apps.filter((item) => item.job).map((item) => ({ id: item.job_id, title: item.job!.title, company: item.job!.company, location: item.job!.location, work_mode: item.job!.work_mode })), [apps]);
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
  // "Apply my defaults": one ordinary edit of layout and sections, so undo (sections) and autosave cover it.
  const applyStyleDefaults = (patch: Partial<Resume>, content: ResumeContent) => {
    if (!activeResume) return;
    if (JSON.stringify(content) !== JSON.stringify(activeResume.content)) { setHistory((items) => [...items.slice(-49), activeResume.content]); setFuture([]); }
    setActiveResume({ ...activeResume, ...patch, content, reviewed_revision: null }); setSaveLabel('Unsaved');
  };
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
        <div className="account-row"><div className="avatar">{initials(me?.display_name || user)}</div><div className="account-name"><strong>{me?.display_name || user}</strong><span>{user}@local.dev</span></div><select aria-label="Development user" value={user} onChange={(e) => switchUser(e.target.value as 'alice' | 'casey')}><option value="alice">Alice</option><option value="casey">Casey</option></select></div>
        <p className="dev-note">LOCAL DEVELOPMENT · {user.toUpperCase()}</p>
      </div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><span className="crumb-sep">/</span><strong>{activeResume && page === 'studio' ? activeResume.title : pageNames[page]}</strong></div><div className="topbar-right"><Pill color="green">Local POC</Pill><button className="help-button" title="Refresh workspace" aria-label="Refresh workspace" onClick={() => setRefresh((x) => x + 1)}>↻</button><select className="top-user-switch" aria-label="Development user" value={user} onChange={(e) => switchUser(e.target.value as 'alice' | 'casey')}><option value="alice">Alice</option><option value="casey">Casey</option></select><div className="avatar small">{initials(me?.display_name || user)}</div></div></header>
      <div className="content-area">
        {fatal && <div className="fatal"><div className="fatal-icon">!</div><div><strong>Could not load your workspace</strong><p>{fatal}</p><button className="button secondary small-button" onClick={() => { setFatal(''); setBootstrapAttempt((x) => x + 1); setRefresh((x) => x + 1); }}>Try again</button></div></div>}
        {!fatal && busy && <Loading label="Connecting to your workspace…" />}
        {!fatal && !busy && <>
          {page === 'discover' && <Discover jobs={jobs} loading={recommendationLoading} total={recommendationTotal} hasMore={nextJobOffset !== null} loadingMore={loadingMoreJobs} onLoadMore={loadMoreJobs} query={query} setQuery={setQuery} busyJob={busyJob} onReview={review} onDetails={setJobDetail} degraded={recommendationsDegraded} rankingStatus={rankingStatus} mode={discoverMode} setMode={setDiscoverMode} forYouNote={forYouNote} thinProfile={!(preferences.roles || []).length || !preferences.seniority} />}
          {page === 'profile' && <ProfileView key={user} userKey={user} onChanged={() => setRefresh(value => value + 1)} onBasicsSaved={draft => setProfile(profileToForm(draft))} onOpenResume={openResume} preferences={preferences} setPreferences={setPreferences} savePreferences={savePreferences} savingPreferences={prefSaving} uploading={uploading} uploadMessage={uploadMessage} extractedResumeText={extractedResumeText} onUpload={uploadProfileResume} resumes={resumes} onBusyChange={setProfileBusy} />}
          {page === 'tracker' && <Tracker apps={filteredApps} loading={recordsLoading} query={trackerQuery} setQuery={setTrackerQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter} onEdit={setTrackerEdit} />}
          {page === 'studio' && <Studio onDelete={deleteResume} resumes={resumes} loading={recordsLoading} active={activeResume} attachTarget={resumeAttachTarget} tab={studioTab} setTab={setStudioTab} busy={busyResumeAction} saving={saving} saveLabel={saveLabel} history={history} future={future} onCreate={createResume} onOpen={openResume} onCreateTailoredCopy={createTailoredCopy} onCopyResume={copyResume} onBuilt={resumeBuilt} onApplyDefaults={applyStyleDefaults} jobs={buildJobs} onAttach={attachResumeToApplication} onReturn={returnToApplication} onBack={() => { if (saveLabel !== 'Saved') { announce('Wait for the current changes to save before leaving the editor.'); return; } setActiveResume(null); }} onUpdate={updateResume} onContent={pushContent} onUndo={undo} onRedo={redo} onDuplicate={duplicateResume} onReview={reviewResume} onExport={exportResume} onPreview={previewResume} onReload={() => { if (saveLabel !== 'Saved') { announce('Wait for the current changes to save before reloading.'); return; } reloadResume(); }} />}
        </>}
      </div>
    </main>
    {toast && <div className="toast" role="status">{toast}{toastAction && <button className="toast-action" onClick={() => { const action = toastAction; setToastAction(null); setToast(''); action.run(); }}>{toastAction.label}</button>}<button onClick={() => { setToast(''); setToastAction(null); }} aria-label="Dismiss notification"><Icon name="close" /></button></div>}
    {previewUrl && <div className="modal-backdrop pdf-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) { URL.revokeObjectURL(previewUrl); setPreviewUrl(''); } }}><section className="pdf-modal" role="dialog" aria-modal="true" aria-label="PDF resume preview"><div className="pdf-modal-head"><strong>PDF preview · server rendered</strong><button className="icon-button" aria-label="Close PDF preview" onClick={() => { URL.revokeObjectURL(previewUrl); setPreviewUrl(''); }}><Icon name="close" /></button></div><iframe title="Resume PDF preview" src={previewUrl} /></section></div>}
    {jobDetail && <JobDetailModal job={jobDetail} onClose={() => setJobDetail(null)} onReview={review} />}
    {trackerEdit && <TrackerModal application={trackerEdit} resumes={resumes} saving={trackerSaving} onClose={() => setTrackerEdit(null)} onPrepare={() => prepareApplicationResume(trackerEdit)} onDownload={async (exportId) => { try { const blob = await api.downloadExport(exportId); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${trackerEdit.resume_packet?.title || 'resume'}-revision-${trackerEdit.resume_packet?.revision || ''}.pdf`; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1500); } catch (error) { announce((error as Error).message); } }} onSave={async (changes) => { setTrackerSaving(true); try { const result = await api.putApplication(trackerEdit.job_id, { ...changes, expected_revision: trackerEdit.revision }); setApps((items) => items.map((item) => item.job_id === result.job_id ? { ...item, ...result } : item)); setTrackerEdit(null); announce('Application record updated. The packet is stored locally; it has not been sent to the employer.'); } catch (error) { announce((error as Error).message); } finally { setTrackerSaving(false); } }} />}
  </div>;
}

function Discover({ jobs, loading, total, hasMore, loadingMore, onLoadMore, query, setQuery, busyJob, onReview, onDetails, degraded, rankingStatus, mode, setMode, forYouNote, thinProfile }: { jobs: Recommendation[]; loading: boolean; total: number; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void; query: string; setQuery: (v: string) => void; busyJob: string; onReview: (job: Job, decision: 'saved' | 'dismissed') => void; onDetails: (job: Job) => void; degraded: boolean; rankingStatus: string; mode: 'for-you' | 'all'; setMode: (mode: 'for-you' | 'all') => void; forYouNote: string; thinProfile: boolean }) {
  return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR NEXT OPPORTUNITY</div><h1>Find your next move.</h1><p>Explore roles matched to your experience and preferences.</p></div><span className="ai-unavailable-badge">AI unavailable</span></div>
    <div className="discovery-summary"><div className="discovery-icon"><Icon name="search" /></div><div><strong>Opportunities from your sources</strong><p>{total} roles match your current filters. Review each one and save what feels right.</p></div></div>
    <div className="mode-toggle" role="group" aria-label="Job list"><button type="button" aria-pressed={mode === 'for-you'} className={mode === 'for-you' ? 'on' : ''} onClick={() => setMode('for-you')}>For you</button><button type="button" aria-pressed={mode === 'all'} className={mode === 'all' ? 'on' : ''} onClick={() => setMode('all')}>All jobs</button></div>
    <div className="toolbar"><label className="search-field"><Icon name="search" /><input aria-label="Search jobs" placeholder="Search title, company, location..." value={query} onChange={(e) => setQuery(e.target.value)} /></label><span className="result-count">{total} results</span></div>
    {mode === 'for-you' && forYouNote && <div className="degraded-note"><span className="note-dot" /> {forYouNote}</div>}
    {mode === 'for-you' && !forYouNote && thinProfile && <div className="degraded-note"><span className="note-dot" /> Add your target roles and seniority in Job preferences to sharpen these matches.</div>}
    {(mode === 'all' || forYouNote) && degraded && <div className="degraded-note"><span className="note-dot" /> {rankingStatus || 'Local text and skill matching is active.'}</div>}
    {jobs.length ? <><div className="job-list">{jobs.map(({ job, reasons, review }) => { const sourceUrl = safeHttpUrl(job.url || job.source_url); return <article className="job-card" key={job.id}><div className="company-logo">{initials(job.company || 'Company')}</div><div className="job-main"><div className="job-title-row"><h2><button className="job-title-button" onClick={() => onDetails(job)}>{job.title}</button></h2></div><div className="company-line"><strong>{job.company}</strong><span>·</span><span>{job.location || 'Location not specified'}</span>{job.work_mode && job.work_mode !== 'Not stated' && <><span>·</span><span>{job.work_mode}</span></>}</div><div className="job-tags">{job.employment_type && <Pill>{job.employment_type}</Pill>}{job.salary_min != null && <Pill>{job.salary_currency || ''} {Number(job.salary_min).toLocaleString()}{job.salary_max != null ? `–${Number(job.salary_max).toLocaleString()}` : '+'} {job.salary_period ? `/ ${salaryPeriod(job.salary_period)}` : ''}</Pill>}{job.source && <Pill>{job.source}{job.source_board ? ` · ${job.source_board}` : ''}</Pill>}</div>{reasons?.length ? <div className="match-reasons"><span>WHY IT MATCHES</span>{reasons.slice(0, 2).map((reason) => <span key={reason} className="reason"><Icon name="check" />{reason}</span>)}</div> : null}<p className="job-description">{job.description || 'The source did not provide a description.'}</p><button type="button" className="job-details-button" onClick={() => onDetails(job)}>Read full description</button><div className="job-foot">{job.posted_at && <span>Posted {fmtDay(job.posted_at)}</span>}{job.fetched_at && <span>Source checked {fmtDay(job.fetched_at)}</span>}{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">View source listing ↗</a>}</div></div><div className="job-actions"><button className="button ghost" disabled={busyJob === job.id} onClick={() => onReview(job, 'dismissed')}><Icon name="close" /> Pass</button><button className="button primary" disabled={busyJob === job.id || review === 'saved'} onClick={() => onReview(job, 'saved')}><Icon name="save" /> {review === 'saved' ? 'Saved' : 'Save job'}</button></div></article>; })}</div>{hasMore && <div className="load-more-row"><span>Showing {jobs.length} of {total}</span><button className="button secondary" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? 'Loading…' : 'Load more roles'}</button></div>}</> : loading ? <Loading label="Loading matching roles…" /> : <div className="empty-state"><div className="empty-art">⌕</div><h2>No roles found</h2><p>Try a different search or come back after new listings arrive.</p></div>}
  </div>;
}

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
