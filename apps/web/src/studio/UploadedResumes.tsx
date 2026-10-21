import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { downloadFile } from '../download';
import { Loading } from '../ui';
import { Dialog } from './points/Dialog';
import type { UploadedResume } from '../types';

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
  return <section className="uploaded-resumes" aria-label="Uploaded resumes">
    <div className="section-toolbar"><div><h2>Uploaded resumes</h2><p>Your original PDF and Word files. Import their details from the Profile page.</p></div></div>
    {loading && <Loading label="Loading uploaded resumes…" />}
    {error && <p role="alert">{error} <button className="button text-button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
    {!loading && !error && !files.length && <p className="bank-empty">No uploaded resumes yet. Use Import from file on your Profile page.</p>}
    <div className="uploaded-resume-list">{files.map(file => <div className="uploaded-resume-row" key={file.upload_id}>
      <div><strong>{file.filename}</strong><small>{file.status === 'uploaded' ? 'Upload incomplete — choose the file again on Profile' : file.status.replaceAll('_', ' ')}</small></div>
      <button className="button secondary small-button" disabled={file.status === 'uploaded' || !!downloading} onClick={() => void download(file)} aria-label={`Download uploaded ${file.filename}`}>{downloading === file.upload_id ? 'Downloading…' : 'Download'}</button>
      <button className="button text-button danger small-button" disabled={deleting || downloading === file.upload_id} aria-label={`Delete uploaded ${file.filename}`} onClick={() => { setDeleteError(''); setTarget(file); }}>Delete</button>
    </div>)}</div>
    {target && <Dialog role="alertdialog" title={`Delete uploaded "${target.filename}"?`} onClose={() => { if (!deleteLock.current) setTarget(null); }}>
      <p>This permanently deletes the original file. Imported profile details, generated resumes, and application PDFs will be kept.</p>
      {deleteError && <p role="alert">{deleteError}</p>}
      <div className="dialog-actions"><button className="button secondary" disabled={deleting} onClick={() => setTarget(null)}>Cancel</button><button className="button danger" disabled={deleting} onClick={() => void remove()}>{deleting ? 'Deleting…' : 'Delete upload'}</button></div>
    </Dialog>}
  </section>;
}
