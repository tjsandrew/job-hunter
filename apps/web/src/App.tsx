import { downloadFile } from './download';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, getDevUser, setDevUser, HttpError } from './api';
import { cloudAuth, signOut, signedInEmail } from './auth';
import { blankContent } from './editor';
import { clearLists, listKey, readList, SETTINGS_KEY, writeList } from './listCache';
import { parseRoute, routePath, type DocumentTab, type Page } from './routes';
import { Letters } from './letters/Letters';
import { PrepareResume } from './studio/PrepareResume';
import { PlanPanel, PlanPill } from './plan/PlanPanel';
import type { Application, CoverLetter, DiscoverMode, FitSummary, Job, Me, Recommendation, Resume, ResumeContent } from './types';

import { FitPanel } from './FitPanel';
import { BrandLogo, Field, Icon, Loading, Pill, SelectField, fmtDate } from './ui';
import { emptyProfile, profileToForm } from './profile/form';
import { ProfileView } from './profile/ProfileView';
import { Studio } from './studio/Studio';
import { applyDefaults } from './studio/build/defaults';

const pageNames: Record<Page, string> = { discover: 'Discover', profile: 'Profile', tracker: 'Application tracker', studio: 'My resumes' };
const statusOptions = ['saved', 'preparing', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];

function initials(name: string) { return name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() || 'JH'; }

function fmtDay(value?: string | null) { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
function salaryPeriod(value?: string | null) { if (!value) return ''; const normalized = value.toLowerCase(); if (normalized.includes('month')) return 'month'; if (normalized.includes('hour')) return 'hour'; if (normalized.includes('year') || normalized.includes('annual')) return 'year'; return value.replace(/^per[-_ ]?/i, '').replaceAll('-', ' '); }
function sourceName(source?: string | null) { const names: Record<string, string> = { greenhouse: 'Greenhouse', lever: 'Lever', smartrecruiters: 'SmartRecruiters', mycareersfuture: 'MyCareersFuture', adzuna: 'Adzuna' }; return source ? names[source.toLowerCase()] || source : 'another source'; }
function sourceLabel(job: Job) { if (!job.source) return job.source_board || ''; const board = job.source_board && job.source_board !== 'sg' ? ` · ${job.source_board}` : ''; return `${sourceName(job.source)}${board}`; }
function otherSources(job: Job) { return Array.from(new Set((job.also_seen_on || []).map((seen) => sourceName(seen.source)))); }
function safeHttpUrl(value?: string) { if (!value) return null; try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; } }

export default function App() {
  const [initialRoute] = useState(() => parseRoute(location.pathname));   // the address this page was opened at (see routes.ts)
  const [page, setPage] = useState<Page>(initialRoute.page);
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
  const [discoverMode, setDiscoverMode] = useState<DiscoverMode>(initialRoute.mode);
  const [forYouNote, setForYouNote] = useState('');
  const [forYouPending, setForYouPending] = useState(false);   // the profile's vector is still being prepared: offer "Check again"
  const [forYouRecheck, setForYouRecheck] = useState(0);
  // When the server says For you is switched off (FOR_YOU_DISABLED) the toggle is hidden and the keyword list is used silently.
  const [forYouAvailable, setForYouAvailable] = useState(true);
  // Saved and Passed are lists of the user's own choices, so they do not depend on For you being available.
  const effectiveMode: DiscoverMode = discoverMode === 'saved' || discoverMode === 'passed' ? discoverMode : forYouAvailable ? discoverMode : 'all';
  const [fitMarks, setFitMarks] = useState<Record<string, FitSummary>>({});   // jobs this user already ran a fit check on
  const [fitRunning, setFitRunning] = useState<string[]>([]);                  // jobs whose fit check is still running
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
  const [section, setSection] = useState<DocumentTab>(initialRoute.tab);                 // "My resumes" shows resumes or cover letters
  const [activeLetterId, setActiveLetterId] = useState<string | null>(initialRoute.letterId);
  const [letterTarget, setLetterTarget] = useState<string | null>(null);                 // a job to start a cover letter for
  const [planOpen, setPlanOpen] = useState(false);
  const [prepareFor, setPrepareFor] = useState<Application | null>(null);               // the application a resume is being prepared for (the window)
  const [buildRequested, setBuildRequested] = useState(false);                          // open the resume builder as soon as My resumes shows
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
  // A listing or resume named by the address that is still being fetched or found (a refresh, a pasted link, the back button).
  const [wantedJob, setWantedJob] = useState<string | null>(initialRoute.jobId);
  const [wantedResume, setWantedResume] = useState<string | null>(initialRoute.resumeId);
  const [signInEmail, setSignInEmail] = useState('');
  useEffect(() => { if (cloudAuth) void signedInEmail().then(setSignInEmail); }, []);

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
    if (page !== 'discover') { setRecommendationLoading(false); return; }
    const revision = ++searchRequestRevision.current;
    setLoadingMoreJobs(false);
    type JobsResult = Awaited<ReturnType<typeof fetchJobs>>;
    const show = (result: JobsResult) => {
      setJobs(result.items || []); setRecommendationTotal(result.total ?? result.items.length);
      setNextJobOffset(result.next_offset ?? null); setRecommendationsDegraded(Boolean(result.degraded_mode)); setRankingStatus(result.ranking_status || '');
      setForYouNote(result.note); setForYouPending(result.pending);
    };
    // A list seen a moment ago (same tab, search and refresh count) is shown at once; an older one is shown while a newer one is fetched.
    const key = listKey(user, effectiveMode, query.trim(), refresh, bootstrapAttempt, forYouRecheck, forYouAvailable);
    const cached = readList<JobsResult>(key);
    if (cached) show(cached.value);
    setRecommendationLoading(!cached);
    const timer = cached?.fresh ? undefined : window.setTimeout(() => {
      fetchJobs(effectiveMode, query, 0).then((result) => {
        if (!alive) return;
        writeList(key, result); show(result);
      }).catch((error: Error) => alive && !cached && setFatal(error.message)).finally(() => alive && setRecommendationLoading(false));
    }, cached ? 0 : 250);
    return () => { alive = false; clearTimeout(timer); if (searchRequestRevision.current === revision) searchRequestRevision.current += 1; };
  }, [user, query, refresh, bootstrapAttempt, discoverMode, page, forYouRecheck]);

  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => { setToast(''); setToastAction(null); }, toastAction ? 9000 : Math.min(10000, Math.max(3200, toast.length * 55))); return () => window.clearTimeout(timer); }, [toast, toastAction]);
  const announce = (message: string) => { setToast(message); setToastAction(null); };
  const loadFitMarks = useCallback(() => {
    api.fitSummaries().then((result) => { setFitMarks(Object.fromEntries(result.items.map((item) => [item.job_id, item]))); setFitRunning(result.running ?? []); }).catch(() => undefined);
  }, []);
  useEffect(() => { loadFitMarks(); }, [user, bootstrapAttempt, loadFitMarks]);
  // While a check runs, ask again every few seconds so the tracker flips from "In progress" to the score by itself.
  const anyFitRunning = fitRunning.length > 0;
  useEffect(() => {
    if (!anyFitRunning) return;
    const timer = window.setInterval(loadFitMarks, 4000);
    return () => window.clearInterval(timer);
  }, [anyFitRunning, loadFitMarks]);
  const switchUser = (next: 'alice' | 'casey') => {
    if (next === user) return;
    if ((activeResume && saveLabel !== 'Saved') || saving || prefSaving || uploading || busyResumeAction || busyJob || trackerEdit || trackerSaving || profileBusy) {
      announce('Finish or close the current save or action before switching users.'); return;
    }
    setDevUser(next); setUser(next); setMe(null); setFatal(''); clearLists();
    setJobs([]); setRecommendationLoading(true); setRecordsLoading(true); setRecommendationTotal(0); setNextJobOffset(null); setRankingStatus(''); setApps([]); setResumes([]);
    setProfile(emptyProfile); setFitMarks({}); setFitRunning([]); setDiscoverMode('for-you');
    setPreferences({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: '', salary_currency: 'SGD', salary_period: 'year', revision: 0 });
    setUploadMessage(''); setExtractedResumeText(''); setQuery(''); setTrackerQuery(''); setStatusFilter('all');
    setActiveResume(null); setHistory([]); setFuture([]); setSaveLabel('Saved'); setStudioTab('edit'); setTrackerEdit(null); setResumeAttachTarget(null); setJobDetail(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl); setPreviewUrl(''); setToast('');
  };
  const filteredApps = useMemo(() => apps.filter((app) => (statusFilter === 'all' || app.status === statusFilter) && `${app.job?.title || ''} ${app.job?.company || ''}`.toLowerCase().includes(trackerQuery.toLowerCase())), [apps, statusFilter, trackerQuery]);

  // "For you" first; if it cannot answer (disabled, error) fall back to the original keyword list and say so.
  const fetchJobs = async (mode: DiscoverMode, q: string, offset: number) => {
    if (mode === 'saved' || mode === 'passed') return { ...(await api.reviewedJobs(mode === 'saved' ? 'saved' : 'dismissed', q, offset)), note: '', pending: false };
    if (mode === 'all' || !forYouAvailable) return { ...(await api.recommendations(q, offset)), note: '', pending: false };
    try {
      const result = await api.recommendationsForYou(q, offset);
      return { ...result, note: result.ranking_mode === 'keyword_fallback' ? (result.fallback_reason || 'For you is not ready yet, so all jobs are shown.') : '', pending: result.ranking_mode === 'keyword_fallback' && result.fallback_code === 'profile_embedding_pending' };
    } catch (error) {
      if (error instanceof HttpError && error.code === 'FOR_YOU_DISABLED') {   // switched off on this deployment: not an error, so no note and no further tries
        setForYouAvailable(false);
        return { ...(await api.recommendations(q, offset)), note: '', pending: false };
      }
      return { ...(await api.recommendations(q, offset)), note: 'For you is unavailable right now, so all jobs are shown.', pending: false };
    }
  };

  const loadMoreJobs = async () => {
    if (nextJobOffset === null || loadingMoreJobs) return;
    setLoadingMoreJobs(true);
    const revision = searchRequestRevision.current;
    try {
      const result = await fetchJobs(effectiveMode, query, nextJobOffset);
      if (revision !== searchRequestRevision.current) return;
      setJobs((current) => [...current, ...result.items.filter((item) => !current.some((loaded) => loaded.job.id === item.job.id))]);
      setRecommendationTotal(result.total ?? recommendationTotal); setNextJobOffset(result.next_offset ?? null); setRankingStatus(result.ranking_status || rankingStatus);
    } catch (error) { announce((error as Error).message); }
    finally { setLoadingMoreJobs(false); }
  };

  const review = async (job: Job, decision: 'saved' | 'dismissed' | 'none') => {
    setBusyJob(job.id);
    try {
      await api.reviewJob(job.id, decision);
      setJobs((current) => current.filter((item) => item.job.id !== job.id));
      if (decision === 'saved') void api.applications().then((result) => setApps(result.items || [])).catch(() => undefined);
      setRefresh((value) => value + 1);
      announce(decision === 'saved' ? `${job.title} saved to your tracker.` : decision === 'none' ? `${job.title} is back in your Discover list.` : 'Job dismissed.');
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
      try {
        const remembered = readList<Awaited<ReturnType<typeof api.getSettings>>>(SETTINGS_KEY);
        if (remembered?.fresh) defaults = remembered.value.resume_defaults;
        else { const settings = await api.getSettings(); writeList(SETTINGS_KEY, settings); defaults = settings.resume_defaults; }
      } catch { /* no settings yet */ }
      const start = applyDefaults({ template: 'classic', content: fullContent, layout: { font_size: 11, margin: 18, font_family: 'auto', line_spacing: 1.25, page_size: 'A4' } }, defaults);
      const created = await api.createDocument({ title: resumeAttachTarget ? `Resume for ${resumeAttachTarget.title}` : 'Untitled resume', template: start.template, content: start.content, layout: start.layout, job_id: jobId });
      setResumes((items) => [created, ...items]); openResume(created); announce('Resume created.');
    } catch (error) { announce((error as Error).message); }
    finally { setBusyResumeAction(false); }
  };

  const aiNote = { off: '', applied: ' AI reworded some bullets; check them.', unchanged: ' AI made no changes.', fallback: ' AI was unavailable, so only the rule-based ordering was applied.' };
  // Returns whether the copy was made, so a window that asked for it knows when to close.
  const createTailoredCopy = async (source: Resume, mode: 'rules' | 'ai' = 'rules', target = resumeAttachTarget): Promise<boolean> => {
    if (!target) return false;
    setBusyResumeAction(true);
    try {
      const { document: copy, ai } = await api.tailorDocument(source.id, target.job_id, `${source.title} — ${target.title}`, mode);
      if (mode === 'ai') api.me().then(setMe).catch(() => undefined);
      setResumes((items) => [copy, ...items]); openResume(copy);
      announce(`A tailored draft was created for this application.${aiNote[ai.status]} Review it before attaching.`);
      return true;
    }
    catch (error) { announce((error as Error).message); return false; }
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
  const openResume = (resume: Resume) => { const linkedApp = resume.job_id ? apps.find((application) => application.job_id === resume.job_id) : undefined; setResumeAttachTarget(linkedApp ? { job_id: linkedApp.job_id, title: linkedApp.job?.title || 'this opportunity', revision: linkedApp.revision } : null); setActiveResume(structuredClone(resume)); setHistory([]); setFuture([]); setStudioTab('edit'); setSaveLabel('Saved'); setSection('resumes'); setActiveLetterId(null); setPage('studio'); };
  const prepareApplicationResume = (application: Application) => {
    const attached = resumes.find((resume) => resume.id === application.resume_packet?.document_id);
    // Reopen this application's draft; never reuse a document linked to another job.
    const existing = attached?.job_id === application.job_id ? attached
      : resumes.find((resume) => resume.job_id === application.job_id);
    setTrackerEdit(null);
    if (existing) {
      openResume(existing);
      setResumeAttachTarget({ job_id: application.job_id, title: application.job?.title || 'this opportunity', revision: application.revision });
    } else setPrepareFor(application);       // no draft for this job yet: a window offers a tailored copy or a new resume, no page change
  };
  const prepareTarget = (application: Application) => ({ job_id: application.job_id, title: application.job?.title || 'this opportunity', revision: application.revision });
  const buildForApplication = (application: Application) => {
    setPrepareFor(null); setResumeAttachTarget(prepareTarget(application)); setBuildRequested(true);
    setActiveResume(null); setSection('resumes'); setActiveLetterId(null); setPage('studio');
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
    try { const result = await api.exportDocument(activeResume.id); const blob = await api.downloadExport(result.export_id); downloadFile(blob, `${activeResume.title.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'resume'}.pdf`); announce(`Exported revision ${result.revision}.`); }
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

  const openResumeLibrary = () => {
    if (activeResume && saveLabel !== 'Saved') { announce('Wait for your resume changes to save before opening the library.'); return; }
    setActiveResume(null); setResumeAttachTarget(null); setSection('resumes'); setActiveLetterId(null); setPage('studio');
    document.scrollingElement?.scrollTo?.({top: 0, left: 0});
  };
  const switchSection = (next: DocumentTab) => { setSection(next); setActiveLetterId(null); };
  const openLetter = useCallback((id: string | null) => setActiveLetterId(id), []);
  const letterTargetDone = useCallback(() => setLetterTarget(null), []);
  const refreshMe = useCallback(() => { api.me().then(setMe).catch(() => undefined); }, []);
  const applicationSaved = useCallback((saved: Application) => setApps((items) => (items.some((item) => item.job_id === saved.job_id) ? items.map((item) => (item.job_id === saved.job_id ? saved : item)) : [saved, ...items])), []);
  const prepareApplicationLetter = (application: Application) => { setTrackerEdit(null); setLetterTarget(application.job_id); setSection('letters'); setActiveLetterId(null); setActiveResume(null); setPage('studio'); };

  const confirmSignOut = () => { if (window.confirm("Sign out? Wait for any pending resume save before continuing.")) { clearLists(); void signOut(); } };
  // The API names every cloud account "Job seeker" and has no email, so the sidebar uses the profile name,
  // then the sign-in email. Local development keeps the seeded dev user.
  const emailName = signInEmail.split('@')[0].replace(/[._-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  const shownName = cloudAuth ? (profile.name.trim() || emailName || 'Your account') : (me?.display_name || user);
  const shownSub = cloudAuth ? (signInEmail || 'Signed in') : `${user}@local.dev`;
  const aiReady = !!(me?.ai_available || me?.fit_available);

  // ---- addresses: every page, list and opened listing has its own link (routes.ts) ----
  const onLetters = page === 'studio' && section === 'letters';
  const currentPath = routePath({ page, mode: discoverMode, jobId: jobDetail?.id ?? null, resumeId: page === 'studio' && !onLetters ? activeResume?.id ?? null : null, tab: onLetters ? 'letters' : 'resumes', letterId: onLetters ? activeLetterId : null });
  const address = useRef({ path: currentPath, unsaved: false, synced: false, resumeId: null as string | null, openResume });
  address.current.path = currentPath;
  address.current.unsaved = !!activeResume && saveLabel !== 'Saved';
  address.current.resumeId = activeResume?.id ?? null;
  address.current.openResume = openResume;

  // The address follows the screen. The first time it only tidies the address (/ becomes /discover); afterwards each change is a
  // history entry, except closing a listing we opened from a list, which steps back so the Back button is not left on the listing.
  useEffect(() => {
    if (wantedJob || wantedResume) return;   // still opening the linked listing or resume: do not overwrite its link
    if (location.pathname === currentPath) { address.current.synced = true; return; }
    if (!address.current.synced) { window.history.replaceState({ app: true }, '', currentPath); address.current.synced = true; return; }
    const state = window.history.state as { app?: boolean; from?: string } | null;
    if (!jobDetail && state?.app && state.from === currentPath && location.pathname.startsWith('/jobs/')) { window.history.back(); return; }
    window.history.pushState({ app: true, from: location.pathname }, '', currentPath);
  }, [currentPath, wantedJob, wantedResume, jobDetail]);

  // The screen follows the address when it changes from outside: the Back and Forward buttons.
  useEffect(() => {
    const onPop = () => {
      const target = parseRoute(location.pathname);
      if (address.current.unsaved && location.pathname !== address.current.path) {   // never walk away from unsaved resume changes
        window.history.pushState({ app: true, from: location.pathname }, '', address.current.path);
        announce('Wait for your resume changes to save before leaving this resume.');
        return;
      }
      if (target.jobId) setWantedJob(target.jobId);
      else { setJobDetail(null); setPage(target.page); setDiscoverMode(target.mode); }
      setSection(target.tab); setActiveLetterId(target.letterId);
      if (target.resumeId) setWantedResume(target.resumeId);
      else if (target.page === 'studio' && !target.jobId) { setActiveResume(null); setResumeAttachTarget(null); }
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  // Open the listing the address names (the list may not contain it, so ask the API).
  useEffect(() => {
    if (!wantedJob) return;
    if (jobDetail?.id === wantedJob) { setWantedJob(null); return; }
    let cancelled = false;
    api.job(wantedJob).then((found) => { if (!cancelled) { setJobDetail(found); setWantedJob(null); } })
      .catch(() => { if (!cancelled) { announce('That job is no longer listed.'); setWantedJob(null); } });
    return () => { cancelled = true; };
  }, [wantedJob]);

  // Open the resume the address names, once the library has loaded.
  useEffect(() => {
    if (!wantedResume || recordsLoading) return;
    if (address.current.resumeId !== wantedResume) {
      const found = resumes.find((resume) => resume.id === wantedResume);
      if (found) address.current.openResume(found); else announce('That resume was not found.');
    }
    setWantedResume(null);
  }, [wantedResume, recordsLoading, resumes]);

  useEffect(() => {
    const here = jobDetail ? jobDetail.title : page === 'studio' && activeResume ? activeResume.title : pageNames[page];
    document.title = `${here} · Job Hunter`;
  }, [page, jobDetail, activeResume?.id, activeResume?.title]);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><BrandLogo size={42} /><div><strong>job hunter</strong><span>CAREER WORKSPACE</span></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{(['discover', 'profile', 'tracker', 'studio'] as Page[]).map((item) => <button key={item} aria-label={pageNames[item]} className={`nav-link ${page === item ? 'active' : ''}`} onClick={() => item === 'studio' ? openResumeLibrary() : setPage(item)}><Icon name={item} /><span>{pageNames[item]}</span>{item === 'tracker' && apps.length > 0 && <b className="nav-count">{apps.length}</b>}</button>)}</nav>
      <div className="sidebar-bottom">
        {(aiReady || !cloudAuth) && <div className="ai-card"><span className="ai-icon">✳</span><div><strong>AI assistant</strong><p>{aiReady ? 'Fit checks and resume tailoring are available.' : 'No AI model is configured on this machine.'}</p><span className={`status-dot ${aiReady ? 'on' : ''}`} /> {aiReady ? 'Ready' : 'Offline'}</div></div>}
        <PlanPill me={me} open={planOpen} onClick={() => setPlanOpen((value) => !value)} />
        <div className="account-row"><button type="button" className="account-button" aria-label="Your plan and account" aria-haspopup="dialog" onClick={() => setPlanOpen(true)}><div className="avatar">{initials(shownName)}</div><div className="account-name"><strong>{shownName}</strong><span title={shownSub}>{shownSub}</span></div></button>{cloudAuth ? <button className="signout-button icon-only" title="Sign out" aria-label="Sign out" onClick={confirmSignOut}><Icon name="signout" /></button> : (<select aria-label="Development user" value={user} onChange={(e) => switchUser(e.target.value as 'alice' | 'casey')}><option value="alice">Alice</option><option value="casey">Casey</option></select>)}</div>
        {!cloudAuth && <p className="dev-note">LOCAL DEVELOPMENT · {user.toUpperCase()}</p>}
      </div>
    </aside>
    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><span className="crumb-sep">/</span><strong>{activeResume && page === 'studio' ? activeResume.title : pageNames[page]}</strong></div><div className="topbar-right">{!cloudAuth && <Pill color="green">Local POC</Pill>}<button className="help-button" title="Refresh workspace" aria-label="Refresh workspace" disabled={busy || recordsLoading || recommendationLoading} aria-busy={recordsLoading || recommendationLoading} onClick={() => setRefresh((x) => x + 1)}>↻</button>{!busy && recordsLoading && <span role="status">Refreshing…</span>}{cloudAuth ? <button className="signout-button" onClick={confirmSignOut}><Icon name="signout" /> Sign out</button> : (<select className="top-user-switch" aria-label="Development user" value={user} onChange={(e) => switchUser(e.target.value as 'alice' | 'casey')}><option value="alice">Alice</option><option value="casey">Casey</option></select>)}<div className="avatar small" title={shownName}>{initials(shownName)}</div></div></header>
      <div className="content-area">
        {fatal && <div className="fatal"><div className="fatal-icon">!</div><div><strong>Could not load your workspace</strong><p>{fatal}</p><button className="button secondary small-button" onClick={() => { setFatal(''); setBootstrapAttempt((x) => x + 1); setRefresh((x) => x + 1); }}>Try again</button></div></div>}
        {!fatal && busy && <Loading label="Connecting to your workspace…" />}
        {!fatal && !busy && <>
          {page === 'discover' && <Discover jobs={jobs} loading={recommendationLoading} total={recommendationTotal} hasMore={nextJobOffset !== null} loadingMore={loadingMoreJobs} onLoadMore={loadMoreJobs} query={query} setQuery={setQuery} busyJob={busyJob} onReview={review} onDetails={setJobDetail} degraded={recommendationsDegraded} rankingStatus={rankingStatus} mode={effectiveMode} forYouAvailable={forYouAvailable} setMode={setDiscoverMode} fitMarks={fitMarks} forYouNote={forYouNote} forYouPending={forYouPending} onRecheck={() => setForYouRecheck((x) => x + 1)} thinProfile={!(preferences.roles || []).length || !preferences.seniority} aiReady={!!(me?.ai_available || me?.fit_available)} />}
          {page === 'profile' && <ProfileView key={user} userKey={user} onChanged={() => setRefresh(value => value + 1)} onBasicsSaved={draft => setProfile(profileToForm(draft))} onOpenResume={openResume} onOpenLibrary={openResumeLibrary} preferences={preferences} setPreferences={setPreferences} savePreferences={savePreferences} savingPreferences={prefSaving} uploading={uploading} uploadMessage={uploadMessage} extractedResumeText={extractedResumeText} onUpload={uploadProfileResume} resumes={resumes} onBusyChange={setProfileBusy} />}
          {page === 'tracker' && <Tracker apps={filteredApps} loading={recordsLoading} query={trackerQuery} setQuery={setTrackerQuery} statusFilter={statusFilter} setStatusFilter={setStatusFilter} onEdit={setTrackerEdit} fitMarks={fitMarks} fitRunning={fitRunning} onOpenJob={setJobDetail} />}
          {page === 'studio' && section === 'letters' && <Letters me={me} apps={apps} resumeCount={resumes.length} activeId={activeLetterId} target={letterTarget} refresh={refresh} onOpen={openLetter} onTargetDone={letterTargetDone} onSection={switchSection} onMeChanged={refreshMe} onApplicationSaved={applicationSaved} announce={announce} />}
          {page === 'studio' && section === 'resumes' && <Studio section={section} onSection={switchSection} startBuild={buildRequested} onBuildStarted={() => setBuildRequested(false)} onDelete={deleteResume} resumes={resumes} loading={recordsLoading} active={activeResume} attachTarget={resumeAttachTarget} tab={studioTab} setTab={setStudioTab} busy={busyResumeAction} saving={saving} saveLabel={saveLabel} history={history} future={future} onCreate={createResume} onOpen={openResume} onCreateTailoredCopy={createTailoredCopy} onTailorWithAI={(resume) => createTailoredCopy(resume, 'ai')} ai={{ available: !!me?.ai_available, remaining: me?.allowance.remaining ?? 0, limit: me?.allowance.limit ?? 5 }} onCopyResume={copyResume} onBuilt={resumeBuilt} onApplyDefaults={applyStyleDefaults} jobs={buildJobs} onAttach={attachResumeToApplication} onReturn={returnToApplication} onBack={() => { if (saveLabel !== 'Saved') { announce('Wait for the current changes to save before leaving the editor.'); return; } setActiveResume(null); }} onUpdate={updateResume} onContent={pushContent} onUndo={undo} onRedo={redo} onDuplicate={duplicateResume} onReview={reviewResume} onExport={exportResume} onPreview={previewResume} onReload={() => { if (saveLabel !== 'Saved') { announce('Wait for the current changes to save before reloading.'); return; } reloadResume(); }} />}
        </>}
      </div>
    </main>
    {toast && <div className="toast" role="status">{toast}{toastAction && <button className="toast-action" onClick={() => { const action = toastAction; setToastAction(null); setToast(''); action.run(); }}>{toastAction.label}</button>}<button onClick={() => { setToast(''); setToastAction(null); }} aria-label="Dismiss notification"><Icon name="close" /></button></div>}
    {previewUrl && <div className="modal-backdrop pdf-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) { URL.revokeObjectURL(previewUrl); setPreviewUrl(''); } }}><section className="pdf-modal" role="dialog" aria-modal="true" aria-label="PDF resume preview"><div className="pdf-modal-head"><strong>PDF preview · server rendered</strong><button className="icon-button" aria-label="Close PDF preview" onClick={() => { URL.revokeObjectURL(previewUrl); setPreviewUrl(''); }}><Icon name="close" /></button></div><iframe title="Resume PDF preview" src={previewUrl} /></section></div>}
    {jobDetail && <JobDetailModal job={jobDetail} onClose={() => setJobDetail(null)} onReview={review} fit={{ available: !!me?.fit_available, remaining: me?.allowance.remaining ?? 0 }} onFitUsed={() => { api.me().then(setMe).catch(() => undefined); loadFitMarks(); }} />}
    {planOpen && me && <PlanPanel me={me} name={shownName} email={cloudAuth ? shownSub : ''} onClose={() => setPlanOpen(false)} onProfile={() => { setPlanOpen(false); setPage('profile'); }} onSignOut={cloudAuth ? () => { setPlanOpen(false); confirmSignOut(); } : undefined} onDemoUpgrade={() => announce('Demo only: no payment was taken and your plan did not change.')} />}
    {prepareFor && <PrepareResume jobTitle={prepareFor.job?.title || 'this job'} resumes={resumes} ai={{ available: !!me?.ai_available, remaining: me?.allowance.remaining ?? 0, limit: me?.allowance.limit ?? 5 }} busy={busyResumeAction}
      onTailor={async (source, mode) => { if (await createTailoredCopy(source, mode, prepareTarget(prepareFor))) setPrepareFor(null); }} onBuild={() => buildForApplication(prepareFor)} onClose={() => setPrepareFor(null)} />}
    {trackerEdit && <TrackerModal application={trackerEdit} resumes={resumes} saving={trackerSaving} onClose={() => setTrackerEdit(null)} onPrepare={() => prepareApplicationResume(trackerEdit)} onPrepareLetter={() => prepareApplicationLetter(trackerEdit)} onDownload={async (exportId) => { try { const blob = await api.downloadExport(exportId); const packet = trackerEdit.cover_letter_packet?.export_id === exportId ? trackerEdit.cover_letter_packet : trackerEdit.resume_packet; downloadFile(blob, `${packet?.title || 'document'}-revision-${packet?.revision || ''}.pdf`); } catch (error) { announce((error as Error).message); } }} onSave={async (changes) => { setTrackerSaving(true); try { const result = await api.putApplication(trackerEdit.job_id, { ...changes, expected_revision: trackerEdit.revision }); setApps((items) => items.map((item) => item.job_id === result.job_id ? { ...item, ...result } : item)); setTrackerEdit(null); announce('Application record updated. The packet is stored locally; it has not been sent to the employer.'); } catch (error) { announce((error as Error).message); } finally { setTrackerSaving(false); } }} />}
  </div>;
}

function Discover({ jobs, loading, total, hasMore, loadingMore, onLoadMore, query, setQuery, busyJob, onReview, onDetails, degraded, rankingStatus, mode, setMode, forYouNote, forYouPending, onRecheck, thinProfile, forYouAvailable, aiReady, fitMarks }: { jobs: Recommendation[]; loading: boolean; total: number; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void; query: string; setQuery: (v: string) => void; busyJob: string; onReview: (job: Job, decision: 'saved' | 'dismissed' | 'none') => void; onDetails: (job: Job) => void; degraded: boolean; rankingStatus: string; mode: DiscoverMode; setMode: (mode: DiscoverMode) => void; forYouNote: string; forYouPending: boolean; onRecheck: () => void; thinProfile: boolean; forYouAvailable: boolean; aiReady: boolean; fitMarks: Record<string, FitSummary> }) {
  return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR NEXT OPPORTUNITY</div><h1>Find your next move.</h1><p>Explore roles matched to your experience and preferences.</p></div>{!aiReady && <span className="ai-unavailable-badge">AI unavailable</span>}</div>
    <div className="discovery-summary"><div className="discovery-icon"><Icon name="search" /></div><div><strong>Opportunities from your sources</strong><p>{mode === 'saved' ? `${total} roles you saved. They are also in your tracker.` : mode === 'passed' ? `${total} roles you passed on. Restore one to see it in Discover again.` : `${total} roles match your current filters. Review each one and save what feels right.`}</p></div></div>
    <div className="mode-toggle" role="group" aria-label="Job list">{([['for-you', 'For you'], ['all', 'All jobs'], ['saved', 'Saved'], ['passed', 'Passed']] as const).filter(([key]) => key !== 'for-you' || forYouAvailable).map(([key, label]) => <button key={key} type="button" aria-pressed={mode === key} className={mode === key ? 'on' : ''} onClick={() => setMode(key)}>{label}</button>)}</div>
    <div className="toolbar"><label className="search-field"><Icon name="search" /><input aria-label="Search jobs" placeholder="Search title, company, location..." value={query} onChange={(e) => setQuery(e.target.value)} /></label><span className="result-count">{total} results</span></div>
    {mode === 'for-you' && forYouNote && <div className="degraded-note" role="status"><span className="note-dot" /> {forYouNote}{forYouPending && <button type="button" className="button secondary small-button recheck-button" disabled={loading} onClick={onRecheck}>Check again</button>}</div>}
    {mode === 'for-you' && !forYouNote && thinProfile && <div className="degraded-note"><span className="note-dot" /> Add your target roles and seniority in Job preferences to sharpen these matches.</div>}
    {(mode === 'all' || (forYouNote && !forYouPending)) && degraded && <div className="degraded-note"><span className="note-dot" /> {rankingStatus || 'Local text and skill matching is active.'}</div>}
    {jobs.length ? <><div className="job-list">{jobs.map(({ job, reasons, review }) => { const sourceUrl = safeHttpUrl(job.url || job.source_url); return <article className="job-card" key={job.id}><div className="company-logo">{initials(job.company || 'Company')}</div><div className="job-main"><div className="job-title-row"><h2><button className="job-title-button" onClick={() => onDetails(job)}>{job.title}</button></h2></div><div className="company-line"><strong>{job.company}</strong><span>·</span><span>{job.location || 'Location not specified'}</span>{job.work_mode && job.work_mode !== 'Not stated' && <><span>·</span><span>{job.work_mode}</span></>}</div><div className="job-tags">{fitMarks[job.id] && <span className={`fit-chip ${fitMarks[job.id].percent === null ? 'none' : fitMarks[job.id].percent! >= 70 ? 'high' : fitMarks[job.id].percent! >= 40 ? 'mid' : 'low'}`} title={fitMarks[job.id].stale ? 'You checked this job before your profile changed. Open it and run the check again.' : 'You have already checked your fit for this job.'}><Icon name="check" /> Fit checked{fitMarks[job.id].percent !== null ? ` · ${fitMarks[job.id].percent}%` : ''}{fitMarks[job.id].stale ? ' · out of date' : ''}</span>}{job.employment_type && <Pill>{job.employment_type}</Pill>}{job.salary_min != null && <Pill>{job.salary_currency || ''} {Number(job.salary_min).toLocaleString()}{job.salary_max != null ? `–${Number(job.salary_max).toLocaleString()}` : '+'} {job.salary_period ? `/ ${salaryPeriod(job.salary_period)}` : ''}</Pill>}{job.source && <Pill>{sourceLabel(job)}</Pill>}{otherSources(job).length > 0 && <span className="pill blue" title="The same posting is listed on more than one site; we show it once.">Also on {otherSources(job).join(', ')}</span>}</div>{reasons?.length ? <div className="match-reasons"><span>WHY IT MATCHES</span>{reasons.slice(0, 2).map((reason) => <span key={reason} className="reason"><Icon name="check" />{reason}</span>)}</div> : null}<p className="job-description">{job.description || 'The source did not provide a description.'}</p><button type="button" className="job-details-button" onClick={() => onDetails(job)}>Read full description</button><div className="job-foot">{job.posted_at && <span>Posted {fmtDay(job.posted_at)}</span>}{job.fetched_at && <span>Source checked {fmtDay(job.fetched_at)}</span>}{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">View source listing ↗</a>}</div></div>{mode === 'passed' ? <div className="job-actions"><button className="button ghost" disabled={busyJob === job.id} onClick={() => onReview(job, 'none')}><Icon name="undo" /> Restore</button><button className="button primary" disabled={busyJob === job.id} onClick={() => onReview(job, 'saved')}><Icon name="save" /> Save job</button></div> : mode === 'saved' ? <div className="job-actions"><button className="button primary" disabled><Icon name="save" /> Saved</button></div> : <div className="job-actions"><button className="button ghost" disabled={busyJob === job.id} onClick={() => onReview(job, 'dismissed')}><Icon name="close" /> Pass</button><button className="button primary" disabled={busyJob === job.id || review === 'saved'} onClick={() => onReview(job, 'saved')}><Icon name="save" /> {review === 'saved' ? 'Saved' : 'Save job'}</button></div>}</article>; })}</div>{hasMore && <div className="load-more-row"><span>Showing {jobs.length} of {total}</span><button className="button secondary" onClick={onLoadMore} disabled={loadingMore}>{loadingMore ? 'Loading…' : 'Load more roles'}</button></div>}</> : loading ? <Loading label="Loading matching roles…" /> : <div className="empty-state"><div className="empty-art">⌕</div><h2>{mode === 'saved' ? 'No saved roles yet' : mode === 'passed' ? 'No passed roles' : 'No roles found'}</h2><p>{mode === 'saved' ? 'Roles you save from Discover appear here, and in your tracker.' : mode === 'passed' ? 'Roles you pass on appear here, so you can bring one back.' : 'Try a different search or come back after new listings arrive.'}</p></div>}
  </div>;
}

function JobDetailModal({ job, onClose, onReview, fit, onFitUsed }: { job: Job; onClose: () => void; onReview: (job: Job, decision: 'saved' | 'dismissed' | 'none') => void; fit: { available: boolean; remaining: number }; onFitUsed: () => void }) {
  const sourceUrl = safeHttpUrl(job.url || job.source_url);
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, [onClose]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal job-detail-modal" role="dialog" aria-modal="true" aria-labelledby="job-detail-title" tabIndex={-1}><div className="modal-heading"><div><div className="eyebrow">FULL JOB DESCRIPTION</div><h2 id="job-detail-title">{job.title}</h2><p>{job.company} · {job.location || 'Location not specified'}{job.work_mode ? ` · ${job.work_mode}` : ''}</p></div><button className="icon-button" aria-label="Close job details" onClick={onClose}><Icon name="close" /></button></div><div className="job-detail-meta">{sourceLabel(job) && <span>Source: {sourceLabel(job)}</span>}{otherSources(job).length > 0 && <span>Also listed on {otherSources(job).join(', ')}</span>}{job.posted_at && <span>Posted {fmtDay(job.posted_at)}</span>}{job.employment_type && <span>{job.employment_type}</span>}</div><div className="job-detail-description">{job.description || 'The source did not provide a description.'}</div>{sourceUrl && <a className="job-source-link" href={sourceUrl} target="_blank" rel="noreferrer">Open original listing ↗</a>}{(job.also_seen_on || []).map((seen) => { const href = safeHttpUrl(seen.source_url || undefined); return href ? <a key={seen.job_id} className="job-source-link" style={{ marginLeft: 14 }} href={href} target="_blank" rel="noreferrer">Also on {sourceName(seen.source)} ↗</a> : null; })}<FitPanel jobId={job.id} available={fit.available} remaining={fit.remaining} onUsed={onFitUsed} onStarted={onFitUsed} /><div className="modal-footer"><button className="button secondary" onClick={() => { onReview(job, 'dismissed'); onClose(); }}>Pass</button><button className="button primary" onClick={() => { onReview(job, 'saved'); onClose(); }}><Icon name="save" /> Save job</button></div></section></div>;
}

/** What is in an application's packet, for the tracker: the resume snapshot and the cover letter, each attached or missing. */
export function packetLines(application: Application): { label: string; attached: boolean }[] {
  const letter = application.cover_letter_packet;
  return [
    application.resume_packet ? { label: `Resume · rev ${application.resume_packet.revision}`, attached: true } : { label: 'No resume', attached: false },
    letter ? { label: `Cover letter · rev ${letter.revision}`, attached: true }
      : application.cover_letter_text ? { label: 'Cover letter (text)', attached: true } : { label: 'No cover letter', attached: false },
  ];
}

/** The tracker's fit cell. Every state is a button that opens the job (the same window as on Discover, where the fit
 *  breakdown and "Check my fit" live): the saved percentage, "In progress" while a check runs, or "Not run". */
function FitCell({ application, mark, running, onOpenJob }: { application: Application; mark: FitSummary | undefined; running: boolean; onOpenJob: (job: Job) => void }) {
  const job = application.job;
  if (!job) return <span className="fit-cell-empty">-</span>;
  const open = () => onOpenJob(job);
  if (running) return <button type="button" className="fit-chip running" onClick={open} aria-label={`Fit check for ${job.title} is in progress. Open job details.`} title="The check is still running. Open the job to follow it.">In progress</button>;
  if (!mark) return <button type="button" className="fit-chip notrun" onClick={open} aria-label={`Fit not run for ${job.title}. Open job details to check it.`} title="Open the job to check your fit.">Not run</button>;
  const tone = mark.percent === null ? 'none' : mark.percent >= 70 ? 'high' : mark.percent >= 40 ? 'mid' : 'low';
  const score = mark.percent === null ? 'No score' : `${mark.percent}%`;
  return <button type="button" className={`fit-chip ${tone}`} onClick={open}
    aria-label={`Fit with your profile for ${job.title}: ${score}${mark.stale ? ', out of date' : ''}. Open job details.`}
    title={mark.stale ? 'You checked this job before your profile changed. Open it and run the check again.' : 'Open the job to see the fit details.'}>
    {score}{mark.stale ? ' · out of date' : ''}
  </button>;
}

function Tracker({ apps, loading, query, setQuery, statusFilter, setStatusFilter, onEdit, fitMarks, fitRunning, onOpenJob }: { fitMarks: Record<string, FitSummary>; fitRunning: string[]; onOpenJob: (job: Job) => void; apps: Application[]; loading: boolean; query: string; setQuery: (v: string) => void; statusFilter: string; setStatusFilter: (v: string) => void; onEdit: (app: Application) => void }) {
  const counts = statusOptions.map((status) => ({ status, count: apps.filter((app) => app.status === status).length }));
  return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">YOUR SEARCH, AT A GLANCE</div><h1>Keep the momentum.</h1><p>Track progress and keep the materials you prepared for each opportunity.</p></div><span className="tracker-total"><strong>{apps.length}</strong> tracked roles</span></div><div className="stat-grid">{[{ label: 'Saved', color: 'blue', key: 'saved' }, { label: 'In progress', color: 'purple', key: 'preparing' }, { label: 'Applied', color: 'orange', key: 'applied' }, { label: 'Interviews', color: 'green', key: 'interviewing' }].map((stat) => <div className="stat-card" key={stat.key}><div><span>{stat.label}</span><strong>{counts.find((item) => item.status === stat.key)?.count || 0}</strong></div><span className={`stat-mark ${stat.color}`} /></div>)}</div><div className="toolbar tracker-toolbar"><label className="search-field"><Icon name="search" /><input aria-label="Search applications" placeholder="Search applications..." value={query} onChange={(e) => setQuery(e.target.value)} /></label><select aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">All statuses</option>{statusOptions.map((status) => <option key={status} value={status}>{status[0].toUpperCase() + status.slice(1)}</option>)}</select><span className="result-count">{apps.length} applications</span></div>{loading ? <Loading label="Loading applications…" /> : apps.length ? <><div className="tracker-table-wrap"><table className="tracker-table"><thead><tr><th>ROLE</th><th>STATUS</th><th>FIT</th><th>APPLIED</th><th>PACKET</th><th></th></tr></thead><tbody>{apps.map((application) => <tr key={application.id}><td><div className="tracker-role"><div className="company-logo tiny">{initials(application.job?.company || '')}</div><div><strong>{application.job?.title || 'Job role'}</strong><span>{application.job?.company || 'Company'}</span></div></div></td><td><Pill color={application.status === 'interviewing' || application.status === 'offer' ? 'green' : application.status === 'applied' || application.status === 'preparing' ? 'blue' : 'neutral'}>{application.status}</Pill></td><td><FitCell application={application} mark={fitMarks[application.job_id]} running={fitRunning.includes(application.job_id)} onOpenJob={onOpenJob} /></td><td>{fmtDate(application.applied_at)}</td><td className="note-cell packet-cell">{packetLines(application).map((line) => <div key={line.label} className={line.attached ? '' : 'packet-missing'}>{line.label}</div>)}</td><td><button className="button secondary small-button" aria-label={`Edit application: ${application.job?.title || 'Job role'}`} onClick={() => onEdit(application)}>Details</button></td></tr>)}</tbody></table></div><div className="tracker-responsive-cards">{apps.map((application) => <article className="tracker-responsive-card" key={`mobile-${application.id}`}><div className="tracker-responsive-head"><div><strong>{application.job?.title || 'Job role'}</strong><span>{application.job?.company || 'Company'}</span></div><Pill color={application.status === 'interviewing' || application.status === 'offer' ? 'green' : application.status === 'applied' || application.status === 'preparing' ? 'blue' : 'neutral'}>{application.status}</Pill></div><p>{packetLines(application).map((line) => line.label).join(' · ')}</p><p className="tracker-fit-line">Fit: <FitCell application={application} mark={fitMarks[application.job_id]} running={fitRunning.includes(application.job_id)} onOpenJob={onOpenJob} /></p><button className="button secondary" aria-label={`Edit application: ${application.job?.title || 'Job role'}`} onClick={() => onEdit(application)}>View application</button></article>)}</div></> : <div className="empty-state compact"><div className="empty-art">↗</div><h2>{query || statusFilter !== 'all' ? 'No matching applications' : 'No applications yet'}</h2><p>{query || statusFilter !== 'all' ? 'Try another search or status filter.' : 'Save interesting jobs from Discover and they’ll appear here.'}</p></div>}</div>;
}
function TrackerModal({ application, resumes, saving, onClose, onSave, onDownload, onPrepare, onPrepareLetter }: { application: Application; resumes: Resume[]; saving: boolean; onClose: () => void; onSave: (v: Record<string, unknown>) => void; onDownload: (exportId: string) => void; onPrepare: () => void; onPrepareLetter: () => void }) {
  const [status, setStatus] = useState(application.status); const [notes, setNotes] = useState(application.notes || ''); const [appliedAt, setAppliedAt] = useState(application.applied_at?.slice(0, 10) || '');
  const [resumeChoice, setResumeChoice] = useState('');
  const [letterChoice, setLetterChoice] = useState('');
  const [letters, setLetters] = useState<CoverLetter[]>([]);
  // The person's cover letters, for the "attach reviewed cover letter" list; a failure just leaves the list empty.
  useEffect(() => {
    let alive = true;
    Promise.resolve().then(() => api.letters()).then((result) => { if (alive) setLetters(result?.items || []); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  const reviewedResumes = resumes.filter((resume) => resume.reviewed_revision === resume.revision);
  const sourceUrl = safeHttpUrl(application.job?.url || application.job?.source_url);
  const selected = reviewedResumes.find((resume) => resume.id === resumeChoice);
  // Reviewed letters only (the same rule as resumes), the ones written for this job first.
  const reviewedLetters = letters.filter((letter) => letter.reviewed_revision === letter.revision)
    .sort((a, b) => Number(b.job_id === application.job_id) - Number(a.job_id === application.job_id));
  const selectedLetter = reviewedLetters.find((letter) => letter.id === letterChoice);
  const modalRef = useRef<HTMLElement | null>(null);
  const dirty = status !== application.status || notes !== (application.notes || '') || appliedAt !== (application.applied_at?.slice(0, 10) || '') || resumeChoice !== '' || letterChoice !== '';
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
    if (letterChoice === '__clear') changes.cover_letter_document_id = null;
    else if (selectedLetter) { changes.cover_letter_document_id = selectedLetter.id; changes.expected_cover_letter_revision = selectedLetter.revision; }
    onSave(changes);
  };
  return <div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && attemptClose()}><section ref={modalRef} tabIndex={-1} className="modal tracker-modal" role="dialog" aria-modal="true" aria-labelledby="application-modal-title"><form onSubmit={(e) => { e.preventDefault(); submit(); }}><div className="modal-heading"><div><div className="eyebrow">APPLICATION DETAILS</div><h2 id="application-modal-title">{application.job?.title || 'Job application'}</h2><p>{application.job?.company}</p></div><button type="button" className="icon-button" aria-label="Close" disabled={saving} onClick={attemptClose}><Icon name="close" /></button></div>
    <div className="tracker-source-row">{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">View original job posting ↗</a> : <span>Source link unavailable</span>}</div>
    <div className="tracker-fields"><SelectField label="Status" value={status} onChange={setStatus} options={statusOptions} disabled={saving} /><Field label="Date applied" value={appliedAt} onChange={setAppliedAt} type="date" disabled={saving} /></div>
    <Field label="Notes" value={notes} onChange={setNotes} placeholder="Add a reminder or follow-up note..." multiline disabled={saving} />
    <section className="packet-section"><div className="packet-heading"><div><h3>Application packet</h3><p>Stored for your reference. Nothing is sent to the employer.</p></div><button type="button" className="button secondary small-button" disabled={saving || dirty} onClick={onPrepare}>Prepare resume</button></div>{dirty && <p className="packet-empty">Save or discard your current application edits before preparing a resume.</p>}
      {application.resume_packet ? <div className="attached-resume"><div><strong>{application.resume_packet.title}</strong><span>Reviewed revision {application.resume_packet.revision} · PDF snapshot</span></div><button type="button" className="button secondary small-button" disabled={saving} onClick={() => onDownload(application.resume_packet!.export_id)}>Download</button></div> : <p className="packet-empty">No resume snapshot attached.</p>}
      <label className="field"><span>{application.resume_packet ? 'Replace resume snapshot' : 'Attach reviewed resume'}</span><select aria-label="Attach reviewed resume" value={resumeChoice} disabled={saving} onChange={(e) => setResumeChoice(e.target.value)}><option value="">{application.resume_packet ? 'Keep current attachment' : 'No resume selected'}</option>{reviewedResumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title} · revision {resume.revision}</option>)}{application.resume_packet && <option value="__clear">Remove attached resume</option>}</select>{!reviewedResumes.length && <small>Review a current resume revision in Resume Studio before attaching it.</small>}</label>
      <div className="packet-heading letter-packet"><div><h3>Cover letter</h3><p>Write one with AI, or paste your own letter into the editor.</p></div><button type="button" className="button secondary small-button" disabled={saving || dirty} onClick={onPrepareLetter}>{application.cover_letter_packet ? 'Open cover letter' : 'Prepare cover letter'}</button></div>
      {application.cover_letter_packet && <div className="attached-resume"><div><strong>{application.cover_letter_packet.title}</strong><span>Reviewed revision {application.cover_letter_packet.revision} · PDF snapshot</span></div><button type="button" className="button secondary small-button" disabled={saving} onClick={() => onDownload(application.cover_letter_packet!.export_id)}>Download</button></div>}
      <label className="field"><span>{application.cover_letter_packet ? 'Replace cover letter snapshot' : 'Attach reviewed cover letter'}</span><select aria-label="Attach reviewed cover letter" value={letterChoice} disabled={saving} onChange={(e) => setLetterChoice(e.target.value)}><option value="">{application.cover_letter_packet ? 'Keep current attachment' : 'No cover letter selected'}</option>{reviewedLetters.map((letter) => <option key={letter.id} value={letter.id}>{letter.title} · revision {letter.revision}</option>)}{application.cover_letter_packet && <option value="__clear">Remove attached cover letter</option>}</select>{!reviewedLetters.length && <small>Review a cover letter in the letter editor before attaching it.</small>}</label>
      {application.cover_letter_text && <div className="packet-saved-note">Cover letter text saved with this application earlier. <button type="button" className="link-button" onClick={() => { const blob = new Blob([application.cover_letter_text || ''], { type: 'text/plain;charset=utf-8' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${(application.job?.company || 'application').replace(/[^a-z0-9]+/gi, '-')}-cover-letter.txt`; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1500); }}>Download saved cover letter</button></div>}
    </section>
    <div className="modal-footer"><button type="button" className="button secondary" disabled={saving} onClick={attemptClose}>Cancel</button><button className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save application record'}</button></div></form></section></div>;
}
