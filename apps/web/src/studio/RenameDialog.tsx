import { useState } from 'react';
import { Dialog } from './points/Dialog';

/** Rename a resume or cover letter from its card. ``onSave`` returns an error message, or nothing when it saved. */
export function RenameDialog({ kind, title, onSave, onClose }: { kind: 'resume' | 'cover letter'; title: string; onSave: (title: string) => Promise<string | undefined>; onClose: () => void }) {
  const [text, setText] = useState(title), [saving, setSaving] = useState(false), [error, setError] = useState('');
  const save = async () => {
    const next = text.trim();
    if (!next) { setError('Enter a name'); return; }
    if (next === title) { onClose(); return; }
    setSaving(true); setError('');
    const failed = await onSave(next);
    setSaving(false);
    if (failed) setError(failed); else onClose();
  };
  return <Dialog title={`Rename ${kind}`} onClose={() => { if (!saving) onClose(); }}>
    <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <label className="field"><span>Name</span><input aria-label={`New name for ${title}`} value={text} maxLength={240} disabled={saving} onChange={(event) => { setText(event.target.value); setError(''); }} onFocus={(event) => event.target.select()} /></label>
      <p className="point-dialog-note">Only the name in your library changes. The document, its review and any application it is attached to stay as they are.</p>
      {error && <p role="alert" className="bank-error">{error}</p>}
      <div className="point-dialog-actions">
        <button type="button" className="button secondary" disabled={saving} onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save name'}</button>
      </div>
    </form>
  </Dialog>;
}
