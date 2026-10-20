import { useRef, useState } from 'react';
import { api } from '../api';
import { downloadFile } from '../download';
import type { Resume } from '../types';

export function GeneratedResumeDownload({resume, busy, onReview}: {resume: Resume; busy: boolean; onReview: () => void}) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const reviewed = resume.reviewed_revision === resume.revision;
  const download = async () => {
    if (lock.current || busy) return;
    if (!reviewed) { onReview(); return; }
    lock.current = true; setDownloading(true); setError('');
    try {
      const exported = await api.exportDocument(resume.id);
      downloadFile(await api.downloadExport(exported.export_id), `${resume.title.replace(/[^a-z0-9-_]+/gi, '-').toLowerCase() || 'resume'}.pdf`);
    } catch (cause) { setError((cause as Error).message); }
    finally { lock.current = false; setDownloading(false); }
  };
  return <div className="resume-card-download">
    <button className="button secondary small-button" disabled={busy || downloading} aria-label={reviewed ? `Download ${resume.title} as PDF` : `Review ${resume.title} to download`} onClick={() => void download()}>{downloading ? 'Preparing PDF…' : reviewed ? 'Download PDF' : 'Review to download'}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}
