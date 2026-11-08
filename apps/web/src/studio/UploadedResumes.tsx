import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { downloadFile } from '../download';
import { Icon, Loading } from '../ui';
import { Dialog } from './points/Dialog';
import type { UploadedResume } from '../types';

const extensionOf = (filename: string) => (filename.match(/\.(pdf|docx)$/i)?.[1] || '').toLowerCase();
const withoutExtension = (filename: string) => filename.replace(/\.(pdf|docx)$/i, '');

/** "Uploaded 9 Nov 2026, 3:42 pm" in the viewer's locale; empty if the server sent no time. */
export function uploadedAt(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : `Uploaded ${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}, ${date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`;
}

export function UploadedResumes() {
  const [files, setFiles] = useState<UploadedResume[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [downloading, setDownloading] = useState('');
  const [target, setTarget] = useState<UploadedResume | null>(null);
  const [deleting, setDeleting] = useState(false);
  const deleteLock = useRef(false);
  const [deleteError, setDeleteError] = useState('');
  const [renaming, setRenaming] = useState<{ id: string; text: string; saving: boolean; error: string } | null>(null);
  const remove = async () => {
    if (!target || deleteLock.current) return;
    deleteLock.current = true; setDeleting(true); setDeleteError('');
    try {
      await api.deleteUpload(target.upload_id);
      setFiles(current => current.filter(file => file.upload_id !== target.upload_id));
      setTarget(null);
    } catch (cause) { setDeleteError((cause as Error).message); }
    finally { deleteLock.current = false; setDeleting(false); }
  };
  // The name is a display label only: imports link to the upload by id, and the stored file is not moved.
  const rename = async () => {
    if (!renaming || renaming.saving) return;
    const text = renaming.text.trim();
    if (!text) { setRenaming({ ...renaming, error: 'Enter a name' }); return; }
    setRenaming({ ...renaming, saving: true, error: '' });
    try {
      const saved = await api.renameUpload(renaming.id, text);
      setFiles(current => current.map(file => file.upload_id === saved.upload_id ? { ...file, filename: saved.filename } : file));
      setRenaming(null);
    } catch (cause) { setRenaming(current => current && { ...current, saving: false, error: (cause as Error).message }); }
  };
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    (async () => {
      try { const result = await api.uploads(); if (active) setFiles(result?.items || []); }
      catch (cause) { if (active) setError((cause as Error).message); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [retry]);
  const download = async (file: UploadedResume) => {
    if (downloading) return;
    setDownloading(file.upload_id); setError('');
    try { downloadFile(await api.downloadUpload(file.upload_id), file.filename); }
    catch (cause) { setError((cause as Error).message); }
    finally { setDownloading(''); }
  };
  const visible = files;
  return <section className="library-section uploaded-resumes" aria-label="Uploaded resumes">
    <div className="library-section-head"><div><h2>Uploaded files <span className="library-count">{files.length}</span></h2><p>Original PDF and Word files you uploaded. They are kept as-is; import their details from the Profile page.</p></div></div>
    {loading && <Loading label="Loading uploaded resumes…" />}
    {error && <p role="alert">{error} <button className="button text-button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {!loading && !error && !files.length && <p className="bank-empty">No uploaded resumes yet. Use Import from file on your Profile page.</p>}
    <div className="uploaded-resume-list">{visible.map(file => {
      const extension = extensionOf(file.filename);
      const editing = renaming?.id === file.upload_id ? renaming : null;
      const status = file.status === 'uploaded' ? 'Upload incomplete — choose the file again on Profile' : file.status.replaceAll('_', ' ');
      return <div className="uploaded-resume-row" key={file.upload_id}>
        <span className="uploaded-resume-type" aria-hidden="true">{extension === 'docx' ? 'DOCX' : 'PDF'}</span>
        <div className="uploaded-resume-main">
          {editing ? <form className="uploaded-resume-rename" onSubmit={event => { event.preventDefault(); void rename(); }}>
            <input aria-label={`New name for ${file.filename}`} value={editing.text} maxLength={250} autoFocus disabled={editing.saving}
              onChange={event => setRenaming({ ...editing, text: event.target.value, error: '' })}
              onKeyDown={event => { if (event.key === 'Escape') setRenaming(null); }} />
            {extension && <span className="uploaded-resume-ext">.{extension}</span>}
            <button type="submit" className="button primary small-button" disabled={editing.saving}>{editing.saving ? 'Saving…' : 'Save'}</button>
            <button type="button" className="button secondary small-button" disabled={editing.saving} onClick={() => setRenaming(null)}>Cancel</button>
            {editing.error && <small role="alert" className="uploaded-resume-error">{editing.error}</small>}
          </form> : <strong>{file.filename}</strong>}
          <small className="uploaded-resume-meta">{[uploadedAt(file.created_at), file.page_count ? `${file.page_count} page${file.page_count === 1 ? '' : 's'}` : '', status].filter(Boolean).join(' · ')}</small>
        </div>
        {!editing && <div className="uploaded-resume-actions">
          <button className="icon-button" disabled={!!renaming || deleting} aria-label={`Rename uploaded ${file.filename}`} title="Rename" onClick={() => setRenaming({ id: file.upload_id, text: withoutExtension(file.filename), saving: false, error: '' })}><Icon name="edit" /></button>
          <button className="button secondary small-button" disabled={file.status === 'uploaded' || !!downloading} onClick={() => void download(file)} aria-label={`Download uploaded ${file.filename}`}>{downloading === file.upload_id ? 'Downloading…' : 'Download'}</button>
          <button className="button text-button danger small-button" disabled={deleting || downloading === file.upload_id} aria-label={`Delete uploaded ${file.filename}`} onClick={() => { setDeleteError(''); setTarget(file); }}>Delete</button>
        </div>}
      </div>;
    })}</div>
    {target && <Dialog role="alertdialog" title={`Delete uploaded "${target.filename}"?`} onClose={() => { if (!deleteLock.current) setTarget(null); }}>
      <p>This permanently deletes the original file. Imported profile details, generated resumes, and application PDFs will be kept.</p>
      {deleteError && <p role="alert">{deleteError}</p>}
      <div className="dialog-actions"><button className="button secondary" disabled={deleting} onClick={() => setTarget(null)}>Cancel</button><button className="button danger" disabled={deleting} onClick={() => void remove()}>{deleting ? 'Deleting…' : 'Delete upload'}</button></div>
    </Dialog>}
  </section>;
}
