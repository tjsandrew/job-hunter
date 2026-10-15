import { useEffect, useRef, useState } from 'react';
import { itemKindFor, markSaved, sectionKind, updateEntryWith } from '../../editor';
import type { BulletSource, ResumeContent, ResumeEntry, ResumeSection } from '../../types';
import type { BankHandle } from './bank';
import { Dialog } from './Dialog';
import { NewPointDialog } from './NewPointDialog';
import { CONFLICT_MESSAGE, saveAsNewPoint, saveAsNewVersion, undoSave, updateInProfile, type NewPointTarget, type SaveOptions, type SaveResult, type UndoPlan } from './profileSave';
import { VersionLimitDialog } from './VersionLimitDialog';

type Target = { entryId: string; index: number; text: string };
type Undo = { plan: UndoPlan; entryId: string; saved: BulletSource | null; previous: BulletSource | null; revision?: number };
type Toast = { message: string; error?: boolean; undo?: Undo };
type Limit = Target & { mode: 'update' | 'version'; versions: { id: string; text: string }[]; mainText: string };

/** Profile writes for one section: runs the API call first, then updates the resume entry through onContent (so undo and autosave cover it). */
export function useProfileSave({ section, bank, getContent, onContent }: { section: ResumeSection; bank: BankHandle; getContent: () => ResumeContent; onContent: (value: ResumeContent) => void }) {
  const [toast, setToast] = useState<Toast>();
  const [conflict, setConflict] = useState<(Target & { currentText: string }) | null>(null);
  const [chooser, setChooser] = useState<Target | null>(null);
  const [limit, setLimit] = useState<Limit | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  useEffect(() => {
    if (!toast || toast.error) return;
    const timer = window.setTimeout(() => setToast(undefined), toast.undo ? 10000 : 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const entryFor = (target: Target): { entry: ResumeEntry; index: number } | undefined => {
    const entry = getContent().sections.find((item) => item.id === section.id)?.entries.find((item) => item.id === target.entryId);
    if (!entry) return undefined;
    const index = entry.bullets[target.index] === target.text ? target.index : entry.bullets.indexOf(target.text);
    return index < 0 ? undefined : { entry, index };
  };
  const run = async (target: Target, action: (entry: ResumeEntry, index: number) => Promise<SaveResult>) => {
    const found = entryFor(target);
    if (!found || lock.current) return;
    lock.current = true; setBusy(true); setToast(undefined);
    try {
      const result = await action(found.entry, found.index);
      if (!result.ok) {
        if (result.reason === 'conflict') setConflict({ ...target, currentText: result.currentText });
        else if (result.reason === 'limit') setLimit({ ...target, mode: result.mode, versions: result.versions, mainText: result.mainText });
        else setToast({ message: result.message, error: true });
        return;
      }
      const latest = entryFor(target);
      const previous = latest?.entry.bullet_sources?.[latest.index] ?? null, revision = latest?.entry.source?.item_revision;
      if (latest && result.keepsLink) onContent(updateEntryWith(getContent(), section.id, target.entryId, (entry) => markSaved(entry, latest.index, result.source, result.item.revision)));
      void bank.refresh();
      setToast({ message: result.message, undo: { plan: result.undo, entryId: target.entryId, saved: result.keepsLink ? result.source : null, previous, revision } });
    } finally { lock.current = false; setBusy(false); }
  };
  /** Takes the profile save back, then puts the resume entry's earlier source link back through onContent. */
  const undo = async (value: Undo) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setToast(undefined);
    try {
      const result = await undoSave(value.plan);
      if (!result.ok) { setToast({ message: result.message, error: true }); return; }
      if (value.saved) {
        const { saved, previous, revision } = value;
        const entry = getContent().sections.find((item) => item.id === section.id)?.entries.find((item) => item.id === value.entryId);
        const index = entry?.bullet_sources?.findIndex((row) => row && row.bullet_id === saved.bullet_id && (row.alternative_id ?? null) === (saved.alternative_id ?? null)) ?? -1;
        if (entry && index >= 0) onContent(updateEntryWith(getContent(), section.id, value.entryId, (current) => {
          const sources = current.bullets.map((_, i) => current.bullet_sources?.[i] ?? null);
          sources[index] = previous;
          return { ...current, bullet_sources: sources, ...(current.source && revision !== undefined ? { source: { ...current.source, item_revision: revision } } : {}) };
        }));
      }
      void bank.refresh();
      setToast({ message: 'Undone. Your profile is back as it was.' });
    } finally { lock.current = false; setBusy(false); }
  };
  const targetOf = (entry: ResumeEntry, index: number): Target => ({ entryId: entry.id, index, text: entry.bullets[index] });

  const actions = {
    update: (entry: ResumeEntry, index: number) => run(targetOf(entry, index), updateInProfile),
    newVersion: (entry: ResumeEntry, index: number) => run(targetOf(entry, index), saveAsNewVersion),
    newPoint: (entry: ResumeEntry, index: number) => setChooser(targetOf(entry, index)),
  };

  const retry = (options: SaveOptions) => {
    const pending = limit; setLimit(null);
    if (pending) void run(pending, (entry, index) => pending.mode === 'update' ? updateInProfile(entry, index, options) : saveAsNewVersion(entry, index, options));
  };
  const kind = itemKindFor(sectionKind(section));
  const chosen = chooser && entryFor(chooser);
  const overlays = <>
    {chooser && chosen && kind && <NewPointDialog kind={kind} text={chooser.text} items={(bank.bank?.items ?? []).filter((item) => item.kind === kind && !item.archived_at)} preselected={chosen.entry.source?.item_id}
      onCancel={() => setChooser(null)} onConfirm={(choice: NewPointTarget) => { const target = chooser; setChooser(null); void run(target, (entry, index) => saveAsNewPoint(section, entry, index, choice)); }} />}
    {limit && <VersionLimitDialog versions={limit.versions} mainText={limit.mainText} canSkipOld={limit.mode === 'update'} onReplace={(id) => retry({ replaceAlternativeId: id })} onSkipOld={() => retry({ keepPrevious: false })} onCancel={() => setLimit(null)} />}
    {conflict && <Dialog title={CONFLICT_MESSAGE} role="alertdialog" onClose={() => setConflict(null)}>
      <p className="point-dialog-note">Your profile now says:</p>
      <blockquote className="point-dialog-quote">{conflict.currentText || 'This point is empty in your profile.'}</blockquote>
      <p className="point-dialog-note">Your resume keeps its own wording either way. Saving as a new version keeps both in your profile.</p>
      <div className="point-dialog-actions">
        <button type="button" className="button primary" onClick={() => { const target = conflict; setConflict(null); void run(target, saveAsNewVersion); }}>Save as new version</button>
        <button type="button" className="button secondary" onClick={() => setConflict(null)}>Cancel</button>
      </div>
    </Dialog>}
    {(toast || busy) && <div className={`point-toast${toast?.error ? ' is-error' : ''}`} role={toast?.error ? 'alert' : 'status'}><span>{toast ? toast.message : 'Saving to your profile…'}</span>{toast?.undo && <button type="button" className="button secondary point-toast-undo" onClick={() => void undo(toast.undo as Undo)}>Undo</button>}{toast && <button type="button" className="icon-button" aria-label="Dismiss notification" onClick={() => setToast(undefined)}>×</button>}</div>}
  </>;
  return { actions, overlays, busy, notify: (message: string) => setToast({ message }) };
}
