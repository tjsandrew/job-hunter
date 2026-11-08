import { downloadFile } from '../download';
import { useEffect, useRef, useState } from 'react';
import { api, HttpError } from '../api';
import { listKey, readList, writeList } from '../listCache';
import { Field, Icon, Loading, Pill, SelectField } from '../ui';
import { ImportReview } from './ImportReview';
import { PreferencesForm } from '../preferences/PreferencesForm';
import type { ImportDecision, ImportResult, ImportSource, ProfileImport, ItemData, ItemKind, ProfileBank, ProfileDraft, ProfileItem, ProfilePoint, ProfileResponse, Resume, UploadedResume } from '../types';
import './profile.css';

const kindNames: Record<ItemKind, string> = { experience: 'Experience', project: 'Projects', education: 'Education', skill: 'Skills', certification: 'Certifications', award: 'Awards', volunteering: 'Volunteering', custom: 'Custom sections' };
const categories = ['language', 'framework', 'tool', 'domain', 'soft'] as const;
const baseKinds: ItemKind[] = ['experience', 'project', 'education', 'custom'];
const fields: Record<ItemKind, [string, string][]> = {
  experience: [['title', 'Role'], ['organisation', 'Employer'], ['location', 'Location']],
  project: [['name', 'Project name'], ['role', 'Project role'], ['url', 'Project link']],
  education: [['qualification', 'Qualification'], ['institution', 'Institution'], ['grade', 'Grade']],
  skill: [['name', 'Skill name']], certification: [['name', 'Certificate'], ['issuer', 'Issuer'], ['url', 'Certificate link']],
  award: [['title', 'Award'], ['awarder', 'Awarded by']], volunteering: [['title', 'Volunteer role'], ['organisation', 'Organisation']],
  custom: [['title', 'Section title'], ['heading', 'Heading']],
};
const list = (text: string) => [...new Set(text.split(',').map(value => value.trim()).filter(Boolean))];
const str = (value: unknown) => typeof value === 'string' ? value : '';
const itemTitle = (item: ProfileItem) => item.data.title || item.data.name || item.data.qualification || kindNames[item.kind];
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
type WriteResult = { item?: ProfileItem; error?: string };
type Write = (operation: () => Promise<ProfileItem>, message: string, previous?: ProfileItem) => Promise<WriteResult>;

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const SOURCE_PREVIEW = 5;
const IMPORT_LIMIT = 1024 * 1024;
const sourceNames: Record<ProfileImport['source_type'], string> = { upload: 'PDF upload', document: 'Studio resume', json_resume: 'JSON Resume', text: 'Pasted text' };
const importMessage = (record: ProfileImport) => record.result && 'message' in record.result ? record.result.message : 'We could not read this source.';
const importDate = (value: string) => { const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(); };
const readText = (file: File) => typeof file.text === 'function' ? file.text() : new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsText(file); });

export function ProfileView({ userKey, onChanged, onBasicsSaved, onOpenResume, onOpenLibrary, preferences, setPreferences, savePreferences, savingPreferences, uploading, uploadMessage, extractedResumeText, onUpload, resumes, onBusyChange }: {
  userKey: string; onChanged: () => void; onBasicsSaved: (draft: ProfileDraft) => void; onOpenResume: (resume: Resume) => void; onOpenLibrary?: () => void;
  preferences: any; setPreferences: (value: any) => void; savePreferences: () => void; savingPreferences: boolean;
  uploading: boolean; uploadMessage: string; extractedResumeText: string; onUpload: (file?: File) => void;
  resumes: Resume[]; onBusyChange: (busy: boolean) => void;
}) {
  const [bank, setBank] = useState<ProfileBank | null>(null);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [uploads, setUploads] = useState<UploadedResume[]>([]);
  const [showAllSources, setShowAllSources] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [basicsDirty, setBasicsDirty] = useState(false);
  const [adding, setAdding] = useState<ItemKind | null>(null);
  const [extraKinds, setExtraKinds] = useState<ItemKind[]>([]);
  const [toast, setToast] = useState<{message: string; undo?: () => Promise<void>}>();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [imports, setImports] = useState<ProfileImport[]>([]);
  const [reviewing, setReviewing] = useState<ProfileImport | null>(null);
  const [reviewKey, setReviewKey] = useState(0);
  const [failedImport, setFailedImport] = useState<ProfileImport | null>(null);
  const [importing, setImporting] = useState(false);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState('');
  const [pasteOpen, setPasteOpen] = useState(false);
  const alive = useRef(true);
  const lock = useRef(false);
  const changedRef = useRef(onChanged); changedRef.current = onChanged;

  const basicsDirtyRef = useRef(false); basicsDirtyRef.current = basicsDirty;
  const profileKey = listKey('profile', userKey), sourcesKey = listKey('profile-sources', userKey);
  useEffect(() => {
    alive.current = true;
    let active = true;
    // What this page showed last time is put up at once and the server is asked again either way, so the page does not
    // start from a spinner on every visit. Text typed before the answer arrives is never overwritten.
    const seen = readList<{ bank: ProfileBank; profile: ProfileResponse }>(profileKey);
    const seenSources = readList<{ uploads: UploadedResume[]; imports: ProfileImport[] }>(sourcesKey);
    if (seen) { setBank(seen.value.bank); setProfile(seen.value.profile); }
    if (seenSources) { setUploads(seenSources.value.uploads); setImports(seenSources.value.imports); }
    setLoading(!seen); setSourcesLoading(!seenSources); setSourcesError('');
    // Profile content is useful before the optional sources/history arrive.
    Promise.all([api.getBank(), api.getProfile()]).then(([nextBank, nextProfile]) => {
      if (!active) return;
      setBank(nextBank); if (!basicsDirtyRef.current) setProfile(nextProfile);
    }).catch((cause: Error) => active && setError(cause.message)).finally(() => active && setLoading(false));
    Promise.all([api.uploads(), api.imports()]).then(([files, recent]) => {
      if (!active) return;
      setUploads(files.items); setImports(recent.items);
    }).catch((cause: Error) => active && setSourcesError(cause.message)).finally(() => active && setSourcesLoading(false));
    return () => { active = false; alive.current = false; };
  }, [userKey]);
  useEffect(() => { if (bank && profile) writeList(profileKey, { bank, profile }); }, [bank, profile, profileKey]);
  useEffect(() => { if (!sourcesLoading) writeList(sourcesKey, { uploads, imports }); }, [uploads, imports, sourcesLoading, sourcesKey]);

  const reload = async () => {
    const next = await api.getBank();
    if (alive.current) setBank(next);
    return next;
  };
  const begin = () => { if (lock.current) return false; lock.current = true; setPending(true); onBusyChange(true); return true; };
  const end = () => { lock.current = false; onBusyChange(false); if (alive.current) setPending(false); };
  const conflict = async (cause: unknown, itemId?: string) => {
    if (cause instanceof HttpError && cause.status === 409) {
      if (itemId) await api.getItem(itemId).catch(() => undefined);
      await reload();
      const latest = await api.getProfile(); if (alive.current) { setProfile(latest); setBasicsDirty(false); }
      return 'This changed elsewhere, reloaded';
    }
    if (cause instanceof HttpError && cause.code === 'POINT_VERSION_LIMIT') return 'A point keeps up to 5 versions';
    return (cause as Error).message;
  };
  const write: Write = async (operation, message, previous) => {
    if (!begin()) return { error: 'Wait for the current save to finish.' };
    setError('');
    try {
      const item = await operation();
      await reload(); changedRef.current();
      if (alive.current) setToast({ message, undo: previous ? async () => {
        await write(() => api.revertItem(item.id, { expected_revision: item.revision, data: previous.data, tags: previous.tags, parent_id: previous.parent_id }), 'Change undone.');
      } : undefined });
      return { item };
    } catch (cause) {
      let message: string;
      try { message = await conflict(cause, previous?.id); } catch { message = 'Could not reload this profile. Try again.'; }
      if (alive.current) setError(message);
      return { error: message };
    } finally { end(); }
  };
  const reorder = async (item: ProfileItem, direction: number) => {
    if (!bank || !begin()) return;
    const ids = bank.items.filter(row => row.kind === item.kind).map(row => row.id);
    const index = ids.indexOf(item.id), target = index + direction;
    if (target < 0 || target >= ids.length) { end(); return; }
    [ids[index], ids[target]] = [ids[target], ids[index]];
    try { setBank(await api.reorderItems({kind: item.kind, item_ids: ids, expected_bank_revision: bank.bank_revision})); setToast({message: 'Item order saved.'}); changedRef.current(); }
    catch (cause) { setError(await conflict(cause)); }
    finally { end(); }
  };
  const saveBasics = async (draft: ProfileDraft) => {
    if (!profile || !begin()) return false;
    try {
      const next = await api.putProfile(draft, profile.revision); setProfile(next);
      onBasicsSaved(next.draft); await reload(); changedRef.current(); setToast({message: 'Profile saved.'}); return true;
    } catch (cause) { setError(await conflict(cause)); return false; }
    finally { end(); }
  };
  const confirm = async () => {
    if (!bank || !begin()) return;
    try { await api.confirmProfile(bank.bank_revision); await reload(); changedRef.current(); setToast({message: 'Matching profile updated.'}); }
    catch (cause) { setError(await conflict(cause)); }
    finally { end(); }
  };
  const exportBank = async () => {
    if (!begin()) return;
    try { download(new Blob([JSON.stringify(await api.exportProfile(), null, 2)], {type:'application/json'}), 'profile.json'); setToast({message: 'Profile exported.'}); }
    catch (cause) { setError((cause as Error).message); }
    finally { end(); }
  };
  const deleteBank = async (deleteSettings: boolean) => {
    if (!begin()) return;
    try {
      await api.deleteProfile({confirmation:'DELETE', delete_settings: deleteSettings});
      const next = await api.getProfile(); setProfile(next); onBasicsSaved(next.draft);
      await reload(); setUploads([]); setDeleteOpen(false); changedRef.current(); setToast({message:'Profile data deleted. Your resumes and applications were kept.'});
    } catch (cause) { setError((cause as Error).message); }
    finally { end(); }
  };
  const refreshImports = () => api.imports().then(result => alive.current && setImports(result.items)).catch(() => undefined);
  const showImport = (record: ProfileImport) => {
    setFailedImport(null); setReviewing(null);
    if (record.status === 'ready') { setReviewKey(key => key + 1); setReviewing(record); }
    else if (record.status === 'failed') setFailedImport(record);
    else setToast({message: `This import is ${record.status}.`});
  };
  const runImport = async (operation: () => Promise<ProfileImport>) => {
    if (!begin()) return false;
    setError(''); setImporting(true); setToast(undefined);
    try { const record = await operation(); if (alive.current) showImport(record); await refreshImports(); return true; }
    catch (cause) { if (alive.current) setError((cause as Error).message); return false; }
    finally { if (alive.current) setImporting(false); end(); }
  };
  const startImport = (source: ImportSource) => runImport(() => api.startImport(source));
  const importFile = async (file?: File) => {
    if (!file) return;
    if (file.size > IMPORT_LIMIT) { setError('That file is larger than 1 MiB. Choose a smaller JSON Resume file.'); return; }
    let parsed: unknown;
    try { parsed = JSON.parse(await readText(file)); } catch { setError('That file is not valid JSON. Choose a JSON Resume file.'); return; }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) { setError('That file is not a JSON Resume object.'); return; }
    await startImport({json_resume: parsed as Record<string, unknown>});
  };
  const importResumeFile = async (file?: File) => {
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) { setError('Choose a PDF or Word (.docx) resume.'); return; }
    if (file.size > 10 * 1024 * 1024) { setError('The file must be 10 MiB or smaller.'); return; }
    await runImport(async () => {
      const uploaded = await api.uploadResume(file);
      const files = await api.uploads();
      if (alive.current) setUploads(files.items);
      return api.startImport({upload_id: uploaded.upload_id});
    });
  };
  const applyImport = async (decisions: ImportDecision[]): Promise<ImportResult> => {
    if (!bank || !reviewing) throw new Error('This review is no longer open.');
    const result = await api.applyImport(reviewing.id, decisions, bank.profile_epoch);
    if (!alive.current) return result;
    setReviewing(null);
    try { await reload(); const latest = await api.getProfile(); if (alive.current) { setProfile(latest); onBasicsSaved(latest.draft); } } catch { setError('Import applied, but the profile could not be reloaded. Refresh the page.'); }
    changedRef.current(); void refreshImports();
    const { added, merged, skipped } = result.counts;
    if (alive.current) setToast({message: `Added ${added}, merged ${merged}, skipped ${skipped}${result.counts.basics_updated ? `, personal details updated` : ''}${result.conflicts.length ? `. ${result.conflicts.length} ${result.conflicts.length === 1 ? 'conflict was' : 'conflicts were'} kept as current values` : ''}.`});
    return result;
  };
  const discardImport = async (id: string, message = 'Import discarded.') => {
    await api.discardImport(id);
    if (!alive.current) return;
    setReviewing(null); setFailedImport(null); setToast({message}); void refreshImports();
  };
  const reviewImport = async (record: ProfileImport) => {
    if (!begin()) return;
    try { showImport(record.status === 'ready' ? await api.getImport(record.id) : record); } catch (cause) { if (alive.current) setError((cause as Error).message); }
    finally { end(); }
  };
  const refreshUploads = useRef(uploading);
  useEffect(() => {
    if (refreshUploads.current && !uploading) api.uploads().then(result => alive.current && setUploads(result.items)).catch(() => undefined);
    refreshUploads.current = uploading;
  }, [uploading]);

  if (loading) return <div className="page-wrap"><Loading label="Loading your profile bank…" /></div>;
  if (!bank || !profile) return <div className="page-wrap"><p role="alert">{error || 'Your profile could not be loaded.'}</p><button className="button secondary" onClick={() => window.location.reload()}>Retry</button></div>;
  if (reviewing) return <ImportReview key={`${reviewing.id}-${reviewKey}`} record={reviewing} onApply={applyImport} onClose={() => { setReviewing(null); void refreshImports(); }} onDiscard={() => discardImport(reviewing.id)} onReload={async () => { const next = await api.getImport(reviewing.id); if (!alive.current) return; if (next.status === 'ready') { setReviewKey(key => key + 1); setReviewing(next); } else showImport(next); }} />;
  const experiences = bank.items.filter(item => item.kind === 'experience');
  const nested = bank.items.filter(item => item.kind === 'project' && experiences.some(parent => parent.id === item.parent_id));
  const shownKinds = [...new Set([...baseKinds, ...extraKinds, ...bank.items.map(item => item.kind)])].filter(kind => kind !== 'skill');
  const unconfirmed = bank.confirmed_revision === null || bank.bank_revision > bank.confirmed_revision;
  return <div className="page-wrap bank-page">
    <div className="page-heading"><div><div className="eyebrow">YOUR CAREER PROFILE</div><h1>Your profile bank.</h1><p>Keep all your experience here. Choose the points you need for each resume.</p></div><div className="bank-actions"><label className={`button secondary upload-button${pending || uploading ? ' is-disabled' : ''}`}>{importing ? 'Importing…' : 'Import from file'}<input aria-label="Import resume from PDF or Word file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={pending || uploading} onChange={event => { const file = event.target.files?.[0]; event.currentTarget.value = ''; void importResumeFile(file); }} /></label><button className="button secondary" disabled={pending} onClick={() => setPasteOpen(true)}>Paste text</button>{unconfirmed ? <button className="button primary" disabled={pending || basicsDirty} onClick={confirm}>Update my matches <Icon name="check" /></button> : <Pill color="green">Matching profile up to date</Pill>}</div></div>
    <p className="bank-matching-note">Saving keeps your bank current. Update my matches confirms a snapshot for matching; you can keep editing without confirming.</p>
    {error && <div className="bank-error" role="alert">{error}</div>}
    {importing && <div className="bank-matching-note" role="status"><Loading label="Reading your source. This can take a moment…" /></div>}
    {failedImport && <div className="bank-error" role="alert"><p>{importMessage(failedImport)}</p><div className="bank-actions"><button className="button secondary small-button" disabled={pending} onClick={() => runImport(() => api.retryImport(failedImport.id))}>Retry</button><button className="button text-button small-button" disabled={pending} onClick={async () => { try { await discardImport(failedImport.id); } catch (cause) { setError((cause as Error).message); } }}>Discard</button></div></div>}
    {toast && <div className="bank-toast" role="status"><span>{toast.message}</span>{toast.undo && <button className="button text-button small-button" disabled={pending} onClick={toast.undo}>Undo</button>}<button className="icon-button" aria-label="Dismiss notification" onClick={() => setToast(undefined)}>×</button></div>}
    <Basics key={`${userKey}-${profile.revision}`} value={profile.draft} busy={pending} onSave={saveBasics} onDirty={setBasicsDirty} />
    <div className="bank-grid"><div className="bank-stack">
      <div className="bank-add-section"><label>Add section <select aria-label="Add section" value="" disabled={pending} onChange={event => { const kind = event.target.value as ItemKind; setExtraKinds(current => [...current, kind]); setAdding(kind); }}><option value="">Choose a section…</option>{Object.entries(kindNames).filter(([kind]) => kind !== 'skill').map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></label></div>
      {shownKinds.map(kind => <section className="panel bank-section" key={kind} aria-label={kindNames[kind]}><div className="panel-heading"><h2>{kindNames[kind]} <span className="bank-count">{bank.items.filter(item => item.kind === kind).length}</span></h2><button className="button secondary small-button" disabled={pending} onClick={() => setAdding(kind)}>Add {kind === 'custom' ? 'custom section' : kind}</button></div>
        {adding === kind && <ItemForm kind={kind} experiences={experiences} busy={pending} onCancel={() => setAdding(null)} onSave={async (data, parent_id) => { const result = await write(() => api.createItem({kind, data, parent_id}), `${kindNames[kind]} added.`); if (!result.error) setAdding(null); return result.error; }} />}
        {bank.items.filter(item => item.kind === kind && !nested.includes(item)).map(item => <ItemCard key={`${item.id}-${item.revision}`} item={item} experiences={experiences} allItems={bank.items} busy={pending} write={write} onMove={reorder}>
          {nested.filter(child => child.parent_id === item.id).map(child => <ItemCard key={`${child.id}-${child.revision}`} item={child} experiences={experiences} allItems={bank.items} busy={pending} write={write} onMove={reorder} />)}
        </ItemCard>)}
        {!bank.items.some(item => item.kind === kind && !nested.includes(item)) && adding !== kind && <p className="bank-empty">{kind === 'project' && nested.length ? 'Projects within a job appear beneath that experience.' : `Add your ${kindNames[kind].toLowerCase()} when you’re ready.`}</p>}
      </section>)}
    </div><aside className="bank-stack">
      <Skills items={bank.items.filter(item => item.kind === 'skill')} busy={pending} write={write} onMove={reorder} />
      <section className="panel bank-resumes"><div className="panel-heading"><h2>Resume sources</h2><div className="bank-actions"><span className="bank-count">{uploads.length + resumes.length}</span>{onOpenLibrary && <button className="button text-button small-button" onClick={onOpenLibrary}>View all resumes</button>}</div></div>
        <div className="upload-strip"><div><strong>Upload an existing resume</strong><span>PDF or Word (.docx) · up to 10 MiB. Review the extracted text below.</span>{uploadMessage && <small>{uploadMessage}</small>}</div><label className="button secondary upload-button">{uploading ? 'Uploading…' : 'Choose file'}<input aria-label="Upload resume file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={uploading || pending} onChange={event => { void onUpload(event.target.files?.[0]); event.currentTarget.value = ''; }} /></label></div>
        {extractedResumeText && <label className="field"><span>Extracted text candidate · verify details and enter profile facts manually</span><textarea readOnly value={extractedResumeText} rows={8} /></label>}
        {sourcesLoading && <div role="status"><Loading label="Loading your resumes…" /></div>}
        {sourcesError && <p role="alert">Your resume sources could not be loaded. {sourcesError}</p>}
        {uploads.length > 0 && <h3>Uploaded resumes</h3>}
        {uploads.slice(0, showAllSources ? uploads.length : SOURCE_PREVIEW).map(file => <div className="bank-file" key={file.upload_id}><span className="bank-file-icon">PDF</span><div><button className="link-button" onClick={async () => { try { downloadFile(await api.downloadUpload(file.upload_id), file.filename); } catch (cause) { setError((cause as Error).message); } }}>{file.filename}</button><small>{file.status === 'uploaded' ? 'Upload incomplete — choose the file again' : file.status.replaceAll('_',' ')}</small></div><button className="button secondary small-button bank-file-import" disabled={pending || file.status === 'uploaded'} aria-label={`Import ${file.filename} into profile`} onClick={() => startImport({upload_id: file.upload_id})}>Import</button></div>)}
        {resumes.length > 0 && <h3>Created on Job Hunter</h3>}
        {resumes.slice(0, showAllSources ? resumes.length : SOURCE_PREVIEW).map(resume => <div className="bank-file" key={resume.id}><span className="bank-file-icon">CV</span><div><button className="link-button" onClick={() => onOpenResume(resume)}>{resume.title}</button><small>Resume Studio · revision {resume.revision}</small></div><button className="button secondary small-button bank-file-import" disabled={pending} aria-label={`Import ${resume.title} into profile`} onClick={() => startImport({document_id: resume.id})}>Import</button></div>)}
        {(uploads.length > SOURCE_PREVIEW || resumes.length > SOURCE_PREVIEW) && <button className="button text-button" aria-expanded={showAllSources} onClick={() => setShowAllSources(value => !value)}>{showAllSources ? 'Show fewer' : `Show all ${uploads.length + resumes.length}`}</button>}
        {!sourcesLoading && !sourcesError && !uploads.length && !resumes.length && <p className="bank-empty">Your uploaded PDFs and Studio resumes will appear here.</p>}
        {imports.length > 0 && <div className="bank-recent-imports"><h3>Recent imports</h3>{imports.slice(0, 5).map(record => <div className="bank-import-row" key={record.id}><span>{sourceNames[record.source_type]} · {record.status} · {importDate(record.created_at)}</span>{record.status === 'ready' && <button className="button secondary small-button" disabled={pending} aria-label={`Review ${sourceNames[record.source_type]} import from ${importDate(record.created_at)}`} onClick={() => reviewImport(record)}>Review</button>}{record.status === 'failed' && <button className="button secondary small-button" disabled={pending} aria-label={`Retry ${sourceNames[record.source_type]} import from ${importDate(record.created_at)}`} onClick={() => runImport(() => api.retryImport(record.id))}>Retry</button>}</div>)}</div>}
      </section>
      <Preferences preferences={preferences} setPreferences={setPreferences} onSave={savePreferences} busy={savingPreferences} />
    </aside></div>
    <details className="panel bank-backups"><summary>Profile backups</summary><p>Export your profile or restore a JSON backup. JSON Resume files are also supported.</p><div className="bank-actions"><button className="button secondary" disabled={pending} onClick={exportBank}>Export profile backup <Icon name="download" /></button><label className={`button secondary upload-button${pending ? ' is-disabled' : ''}`}>Restore profile backup<input aria-label="Restore profile from JSON backup" type="file" accept=".json,application/json" disabled={pending} onChange={event => { const file = event.target.files?.[0]; event.currentTarget.value = ''; void importFile(file); }} /></label></div></details>
    <section className="panel bank-danger"><div><h2>Danger zone</h2><p>Delete your profile facts and uploaded source files. Your separate resumes and applications are kept.</p></div><button className="button secondary" disabled={pending} onClick={() => setDeleteOpen(true)}>Delete my profile data</button></section>
    {pasteOpen && <PasteDialog busy={pending} onCancel={() => setPasteOpen(false)} onStart={async text => { setPasteOpen(false); await startImport({text}); }} />}
    {deleteOpen && <DeleteDialog busy={pending} onCancel={() => setDeleteOpen(false)} onDelete={deleteBank} />}
  </div>;
}

function Basics({value, busy, onSave, onDirty}: {value: ProfileDraft; busy: boolean; onSave: (draft: ProfileDraft) => Promise<boolean>; onDirty: (dirty: boolean) => void}) {
  const [draft, setDraft] = useState(() => ({name:str(value.name || value.display_name), headline:str(value.headline), email:str(value.email), phone:str(value.phone), location:str(value.location), summary:str(value.summary), links: Array.isArray(value.links) ? value.links.map(link => typeof link === 'string' ? link : str((link as any).url)).join('\n') : ''}));
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState(false);
  const initial = useRef(draft);
  const update = (key: keyof typeof draft, text: string) => { setDraft({...draft,[key]:text}); setDirty(true); onDirty(true); };
  if (!editing) return <section className="panel bank-basics bank-basics-summary"><div className="bank-basics-avatar" aria-hidden="true">{draft.name.split(/\s+/).map(word => word[0]).join('').slice(0,2) || '＋'}</div><div className="bank-basics-details"><h2>{draft.name || 'Your personal details'}</h2><p className="bank-basics-headline">{draft.headline || 'Add your professional headline'}</p><div className="bank-basics-contact">{[draft.email,draft.phone,draft.location].filter(Boolean).map(text => <span key={text}>{text}</span>)}</div><p className="bank-basics-bio">{draft.summary || 'Add a summary and contact details for your resumes.'}</p>{draft.links && <small>{draft.links.split('\n').join(' · ')}</small>}</div><button className="button secondary small-button" disabled={busy} onClick={() => setEditing(true)}>Edit personal details</button></section>;
  return <section className="panel bank-basics"><div className="panel-heading"><div><h2>Personal details</h2><p>Your contact information and professional summary.</p></div><Pill color="neutral">Basics</Pill></div><form onSubmit={async event => { event.preventDefault(); if (await onSave({...draft, links:draft.links.split('\n').map(value => value.trim()).filter(Boolean)})) { setDirty(false); onDirty(false); } }}><fieldset disabled={busy}>
    <div className="form-grid"><Field label="Full name" value={draft.name} onChange={value => update('name',value)} placeholder="e.g. Alex Tan" /><Field label="Professional headline" value={draft.headline} onChange={value => update('headline',value)} placeholder="Product designer · 6 years experience" /><Field label="Email address" type="email" value={draft.email} onChange={value => update('email',value)} /><Field label="Phone number" value={draft.phone} onChange={value => update('phone',value)} /><Field label="Location" value={draft.location} onChange={value => update('location',value)} /><Field label="Links (one per line)" multiline value={draft.links} onChange={value => update('links',value)} /></div>
    <Field label="Professional summary" multiline value={draft.summary} onChange={value => update('summary',value)} /><div className="panel-footer"><span>{dirty ? 'Unsaved profile changes' : 'Personal details saved'}</span><div><button type="button" className="button secondary" onClick={() => {setDraft(initial.current);setDirty(false);onDirty(false);setEditing(false);}}>Cancel</button><button type="submit" className="button primary" disabled={!dirty}>Save profile</button></div></div>
  </fieldset></form></section>;
}

function ItemForm({kind, item, experiences, busy, onCancel, onSave}: {kind: ItemKind; item?: ProfileItem; experiences: ProfileItem[]; busy: boolean; onCancel: () => void; onSave: (data: ItemData, parentId: string | null) => Promise<string | undefined>}) {
  const [data, setData] = useState<ItemData>(() => item ? clone(item.data) : kind === 'skill' ? {bullets:[]} : {bullets:[], current:false});
  const [parent, setParent] = useState(item?.parent_id || '');
  const [error, setError] = useState('');
  const change = (key: string, value: unknown) => setData({...data,[key]:value});
  return <form className="bank-item-form" onSubmit={async event => {event.preventDefault(); setError(await onSave(data,parent || null) || '');}}><fieldset disabled={busy}><div className="form-grid">
    {fields[kind].map(([key,label],index) => <label className="field" key={key}><span>{label}</span><input required={index === 0} maxLength={240} value={str((data as any)[key])} onChange={event => change(key,event.target.value)} /></label>)}
    {kind !== 'skill' && kind !== 'custom' && <><Field label="Start (YYYY or YYYY-MM)" value={data.start || ''} onChange={value => setData({...data,start:value || null,dates_text:undefined})} /><Field label="End (YYYY or YYYY-MM)" value={data.end || ''} onChange={value => setData({...data,end:value || null,current:false,dates_text:undefined})} /><label className="bank-check"><input type="checkbox" checked={!!data.current} onChange={event => setData({...data,current:event.target.checked,end:event.target.checked ? null : data.end,dates_text:undefined})} />Current</label></>}
    {kind === 'project' && <label className="field"><span>Parent experience</span><select value={parent} onChange={event => setParent(event.target.value)}><option value="">Standalone project</option>{experiences.map(row => <option value={row.id} key={row.id}>{itemTitle(row)} · {row.data.organisation}</option>)}</select></label>}
    {kind === 'skill' && <SelectField label="Skill category" value={data.category || 'tool'} options={[...categories]} onChange={value => change('category',value)} />}
  </div>{['experience','project','award','volunteering','custom'].includes(kind) && <Field label="Summary" multiline value={data.summary || ''} onChange={value => change('summary',value)} />}
    {error && <p className="bank-error" role="alert">{error}</p>}<div className="bank-actions"><button className="button primary" type="submit">Save {kind === 'custom' ? 'section' : kind}</button><button className="button secondary" type="button" onClick={onCancel}>Cancel</button></div>
  </fieldset></form>;
}

function ItemCard({item, experiences, allItems, busy, write, onMove, children}: {item: ProfileItem; experiences: ProfileItem[]; allItems: ProfileItem[]; busy: boolean; write: Write; onMove: (item: ProfileItem, direction: number) => void; children?: React.ReactNode}) {
  const [editing, setEditing] = useState(false);
  const [addingPoint, setAddingPoint] = useState(false);
  const sameKind = allItems.filter(row => row.kind === item.kind), index = sameKind.findIndex(row => row.id === item.id);
  const groups: Record<string, ProfilePoint[]> = {};
  for (const point of item.data.bullets) { const tag = point.tags?.[0] || 'Other points'; (groups[tag] ||= []).push(point); }
  return <article className={`bank-item ${item.parent_id ? 'bank-nested' : ''}`} aria-label={itemTitle(item)}>
    <div className="bank-item-top"><div className="bank-item-head"><div className="bank-item-title"><h3>{itemTitle(item)}</h3><small>{item.data.dates_text || [item.data.start, item.data.current ? 'Present' : item.data.end].filter(Boolean).join(' – ')}</small></div><p>{item.data.organisation || item.data.institution || item.data.issuer || item.data.awarder || item.data.role}</p></div><div className="bank-actions bank-row-actions"><button className="icon-button" aria-label={`Move ${itemTitle(item)} up`} title="Move up" disabled={busy || index === 0} onClick={() => onMove(item,-1)}><Icon name="up" /></button><button className="icon-button" aria-label={`Move ${itemTitle(item)} down`} title="Move down" disabled={busy || index === sameKind.length-1} onClick={() => onMove(item,1)}><Icon name="down" /></button><button className="icon-button" disabled={busy} aria-label={`Edit ${item.kind}`} title={`Edit ${item.kind}`} onClick={() => setEditing(true)}><Icon name="edit" /></button><button className="icon-button" disabled={busy} aria-label={`Archive ${itemTitle(item)}`} title="Archive" onClick={() => write(() => api.archiveItem(item.id,item.revision), 'Item archived.', item)}><Icon name="trash" /></button></div></div>
    {editing ? <ItemForm kind={item.kind} item={item} experiences={experiences} busy={busy} onCancel={() => setEditing(false)} onSave={async (data,parent_id) => (await write(() => api.patchItem(item.id,{expected_revision:item.revision,data,parent_id}), 'Item saved.')).error} /> : <>
      {item.data.summary && <p>{item.data.summary}</p>}
      {Object.entries(groups).map(([tag,points],_,all) => <div className="bank-point-group" key={tag}>{(all.length > 1 || tag !== 'Other points') && <h4>{tag}</h4>}<ul className="bank-point-list">{points.map(point => <Point key={point.id} item={item} point={point} busy={busy} write={write} />)}</ul></div>)}
      {addingPoint ? <PointForm busy={busy} onCancel={() => setAddingPoint(false)} onSave={async (text,tags) => (await write(() => api.addPoint(item.id,{expected_revision:item.revision,text,tags}), 'Point added.')).error} /> : <button className="button text-button small-button bank-add-point" disabled={busy} onClick={() => setAddingPoint(true)}><Icon name="plus" />Add point</button>}
    </>}{children && <div className="bank-child-projects">{children}</div>}
  </article>;
}

function PointForm({point, busy, onCancel, onSave, version = false}: {point?: ProfilePoint; busy: boolean; onCancel: () => void; onSave: (text: string,tags: string[]) => Promise<string | undefined>; version?: boolean}) {
  const [text,setText] = useState(point?.text || ''), [tags,setTags] = useState(point?.tags?.join(', ') || ''), [error,setError] = useState('');
  return <form className="bank-point-form" onSubmit={async event => {event.preventDefault(); const error = await onSave(text,list(tags)); setError(error || ''); if (!error) onCancel();}}><fieldset disabled={busy}><label className="field"><span>{version ? 'Version wording' : 'Point wording'}</span><textarea required maxLength={4000} value={text} rows={3} onChange={event => setText(event.target.value)} /></label><label className="field"><span>Point types (comma separated)</span><input value={tags} list="point-tag-suggestions" onChange={event => setTags(event.target.value)} /></label><datalist id="point-tag-suggestions"><option value="backend"/><option value="data"/><option value="leadership"/><option value="mentoring"/></datalist>{error && <p className="bank-error" role="alert">{error}</p>}<div className="bank-actions"><button type="submit" className="button primary small-button">{version ? 'Save version' : 'Save point'}</button><button type="button" className="button secondary small-button" onClick={onCancel}>Cancel</button></div></fieldset></form>;
}

function Point({item, point, busy, write}: {item: ProfileItem; point: ProfilePoint; busy: boolean; write: Write}) {
  const [editing,setEditing] = useState(false), [versions,setVersions] = useState(false), [adding,setAdding] = useState(false);
  return <li className="bank-point" aria-label={point.text}>
    {editing ? <PointForm point={point} busy={busy} onCancel={() => setEditing(false)} onSave={async (text,tags) => {
      // Wording updates preserve the old wording; tag edits use one atomic item patch.
      if (JSON.stringify(tags) !== JSON.stringify(point.tags || [])) {
        const data = clone(item.data), target = data.bullets.find(row => row.id === point.id)!;
        if (text !== point.text) { if (target.alternatives.length >= 4) return 'A point keeps up to 5 versions'; target.alternatives.push({id:`v_${crypto.randomUUID()}`,text:point.text,tags:point.tags,skills:point.skills,provenance:point.provenance}); target.text=text; }
        target.tags=tags; return (await write(() => api.patchItem(item.id,{expected_revision:item.revision,data}), 'Point saved.', item)).error;
      }
      return (await write(() => api.updatePoint(item.id,point.id,{expected_revision:item.revision,text}), 'Point saved.', item)).error;
    }} /> : <div className="bank-point-row"><p>{point.text}</p><div className="bank-actions bank-row-actions"><button className="icon-button" disabled={busy} aria-label="Edit point" title="Edit point" onClick={() => setEditing(true)}><Icon name="edit" /></button><button className={`bank-version-chip ${point.alternatives.length ? 'has-versions' : ''}`} disabled={busy} aria-expanded={versions} aria-label={point.alternatives.length ? `${1 + point.alternatives.length} versions` : '1 version'} title="Versions of this point" onClick={() => setVersions(!versions)}><Icon name="layers" />{1 + point.alternatives.length}</button><button className="icon-button" disabled={busy} aria-label="Delete point" title="Delete point" onClick={() => {
      // Saves the item without this point (and its versions); the toast's Undo restores it.
      const data = clone(item.data); data.bullets = data.bullets.filter(row => row.id !== point.id);
      write(() => api.patchItem(item.id,{expected_revision:item.revision,data}), 'Point deleted.', item);
    }}><Icon name="trash" /></button></div></div>}
    {!!point.tags?.length && <div className="bank-tags">{point.tags.map(tag => <span key={tag}>{tag}</span>)}</div>}
    {versions && <div className="bank-versions"><p className="bank-version-main">Main wording: {point.text}</p>{point.alternatives.map((alternative,index) => <div className="bank-version" key={alternative.id}><p>Version {index+2}: {alternative.text}</p><button className="button secondary small-button" disabled={busy} onClick={() => write(() => api.updatePoint(item.id,point.id,{expected_revision:item.revision,text:alternative.text,alternative_id:alternative.id,make_main:true}), 'Main wording updated.', item)}>Make main</button></div>)}{adding ? <PointForm version busy={busy} onCancel={() => setAdding(false)} onSave={async (text,tags) => (await write(() => api.addAlternative(item.id,point.id,{expected_revision:item.revision,text,tags}), 'Version added.', item)).error} /> : <button className="button text-button small-button" disabled={busy} onClick={() => setAdding(true)}>Add version</button>}</div>}
  </li>;
}

function Skills({items,busy,write,onMove}: {items: ProfileItem[]; busy: boolean; write: Write; onMove: (item: ProfileItem, direction: number) => void}) {
  const [adding,setAdding]=useState(false), [editing,setEditing]=useState<ProfileItem | null>(null);
  useEffect(() => { if (editing) { const latest = items.find(item => item.id === editing.id); if (!latest) setEditing(null); else if (latest.revision !== editing.revision) setEditing(latest); } }, [items, editing]);
  return <section className="panel bank-skills"><div className="panel-heading"><h2>Skills <span className="bank-count">{items.length}</span></h2><button className="button secondary small-button" disabled={busy} onClick={() => setAdding(true)}>Add skill</button></div>
    {adding && <ItemForm kind="skill" experiences={[]} busy={busy} onCancel={() => setAdding(false)} onSave={async data => { const result = await write(() => api.createItem({kind:'skill',data}), 'Skill added.'); if (!result.error) setAdding(false); return result.error; }} />}
    {editing && <ItemForm key={`${editing.id}-${editing.revision}`} kind="skill" item={editing} experiences={[]} busy={busy} onCancel={() => setEditing(null)} onSave={async data => {const result = await write(() => api.patchItem(editing.id,{expected_revision:editing.revision,data}), 'Skill saved.'); if (!result.error) setEditing(null); return result.error;}} />}
    {categories.map(category => { const rows=items.filter(item => (item.data.category || 'tool') === category); return rows.length ? <div className="bank-skill-group" key={category}><h3>{category}</h3><div className="bank-skill-chips">{rows.map(item => <span className="bank-skill-chip" key={item.id}><button disabled={busy} aria-label={`Rename ${item.data.name}`} onClick={() => setEditing(item)}>{item.data.name}</button><button disabled={busy || items[0]?.id === item.id} aria-label={`Move skill ${item.data.name} up`} onClick={() => onMove(item,-1)}>↑</button><button disabled={busy || items[items.length-1]?.id === item.id} aria-label={`Move skill ${item.data.name} down`} onClick={() => onMove(item,1)}>↓</button><button disabled={busy} aria-label={`Archive skill ${item.data.name}`} onClick={() => write(() => api.archiveItem(item.id,item.revision), 'Skill archived.', item)}>×</button></span>)}</div></div> : null; })}
    {!items.length && <p className="bank-empty">Add languages, tools and other skills you use.</p>}
  </section>;
}

function Preferences({preferences,setPreferences,onSave,busy}: {preferences:any;setPreferences:(value:any)=>void;onSave:()=>void;busy:boolean}) {
  return <section className="panel bank-preferences"><div className="panel-heading"><h2>Default job preferences</h2></div><p className="bank-empty">Discover starts from these each time you sign in. Change filters there for one search, or save them here as your default.</p><PreferencesForm preferences={preferences} setPreferences={setPreferences} /><p className="bank-empty">Jobs that do not state a salary are still shown.</p><button className="button primary" disabled={busy} onClick={onSave}>{busy ? 'Saving…' : 'Save preferences'}</button></section>;
}

function DeleteDialog({busy,onCancel,onDelete}: {busy:boolean;onCancel:()=>void;onDelete:(settings:boolean)=>void}) {
  const [text,setText]=useState(''),[settings,setSettings]=useState(false);
  const ref=useRef<HTMLDivElement>(null);
  useEffect(() => { const previous=document.activeElement as HTMLElement | null; ref.current?.focus(); return () => previous?.focus(); },[]);
  return <div className="modal-backdrop"><div className="modal bank-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-profile-title" ref={ref} tabIndex={-1} onKeyDown={event => {
    if(event.key==='Escape' && !busy) onCancel();
    if(event.key==='Tab') {const controls=[...ref.current!.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled])')]; const first=controls[0],last=controls[controls.length-1]; if(event.shiftKey && (document.activeElement===first || document.activeElement===ref.current)){event.preventDefault();last?.focus();} else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}}
  }}><h2 id="delete-profile-title">Delete my profile data?</h2><p>This deletes your contact details, bank items, confirmed snapshots and embeddings, import records, and uploaded source PDFs.</p><p><strong>Kept:</strong> Resume Studio documents, their exports, applications and attached PDFs. Manage those separately in Resume Studio and your tracker.</p><label className="bank-check"><input type="checkbox" checked={settings} disabled={busy} onChange={event=>setSettings(event.target.checked)} />Also delete my resume style defaults</label><Field label="Type DELETE to confirm" value={text} onChange={setText}/><div className="bank-actions"><button className="button secondary" disabled={busy} onClick={onCancel}>Cancel</button><button className="button primary" disabled={busy || text!=='DELETE'} onClick={()=>onDelete(settings)}>Delete profile data</button></div></div></div>;
}

function PasteDialog({busy,onCancel,onStart}: {busy:boolean;onCancel:()=>void;onStart:(text:string)=>void}) {
  const [text,setText]=useState('');
  const ref=useRef<HTMLDivElement>(null);
  const tooLong=new TextEncoder().encode(text).length > IMPORT_LIMIT;
  useEffect(() => { const previous=document.activeElement as HTMLElement | null; ref.current?.querySelector('textarea')?.focus(); return () => previous?.focus(); },[]);
  return <div className="modal-backdrop"><div className="modal bank-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="paste-import-title" ref={ref} onKeyDown={event => {
    if(event.key==='Escape' && !busy) onCancel();
    if(event.key==='Tab') {const controls=[...ref.current!.querySelectorAll<HTMLElement>('button:not([disabled]),textarea:not([disabled])')]; const first=controls[0],last=controls[controls.length-1]; if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();} else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}}
  }}><h2 id="paste-import-title">Paste resume text</h2><p>Paste the text of a resume or CV. You review everything before anything is added to your profile.</p>
    <label className="field"><span>Resume text</span><textarea rows={10} value={text} aria-invalid={tooLong} onChange={event=>setText(event.target.value)} /></label>
    {tooLong && <p className="bank-error" role="alert">This text is larger than 1 MiB. Paste a shorter excerpt.</p>}
    <div className="bank-actions"><button className="button primary" disabled={busy || !text.trim() || tooLong} onClick={() => onStart(text)}>Start import</button><button className="button secondary" disabled={busy} onClick={onCancel}>Cancel</button></div>
  </div></div>;
}
