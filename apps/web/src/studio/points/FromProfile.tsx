import { useState } from 'react';
import { entryFromItem, formatItemDates, itemKindFor, itemLabel, sectionKind } from '../../editor';
import type { ProfileItem, ResumeEntry, ResumeSection } from '../../types';
import { bankItem, clip, pointVersions, type BankHandle } from './bank';
import { Dialog } from './Dialog';

/** "More from this job in your profile": points of the entry's item that are not on this resume yet. */
export function MoreFromJob({ entry, bank, onAdd }: { entry: ResumeEntry; bank: BankHandle; onAdd: (point: ProfileItem['data']['bullets'][number]) => void }) {
  if (!entry.source) return null;
  const item = bankItem(bank.bank, entry.source.item_id);
  if (!item) return null;
  const used = new Set((entry.bullet_sources ?? []).map((source) => source?.bullet_id));
  const unused = item.data.bullets.filter((point) => !used.has(point.id));
  if (!unused.length) return null;
  return <div className="more-from-job" role="group" aria-label="More from this job in your profile">
    <div className="more-from-job-title">More from this job in your profile</div>
    {unused.map((point) => <div className="more-from-job-row" key={point.id}><span>{clip(point.text, 160)}</span><button type="button" className="button text-button small-button" aria-label={`Add point: ${clip(point.text, 60)}`} onClick={() => onAdd(point)}>+ Add</button></div>)}
  </div>;
}

type Pick = { checked: boolean; alt: string | null };
const DEFAULT_POINTS = 4;
const initialPicks = (item: ProfileItem) => Object.fromEntries(item.data.bullets.map((point, i) => [point.id, { checked: i < DEFAULT_POINTS, alt: null as string | null }])) as Record<string, Pick>;

/** Picker for "Add from profile": items of the section's kind with point checkboxes and a version selector per point. */
export function AddFromProfileDialog({ section, bank, used, onAdd, onClose }: { section: ResumeSection; bank: BankHandle; used: Set<string>; onAdd: (entries: ResumeEntry[]) => void; onClose: () => void }) {
  const kind = itemKindFor(sectionKind(section));
  const active = (bank.bank?.items ?? []).filter((item) => !item.archived_at);
  const items = active.filter((item) => item.kind === kind);
  // Projects that belong to a job are listed under that job (the resume itself stays flat).
  const jobs = active.filter((item) => item.kind === 'experience');
  const childrenOf = (job: ProfileItem) => active.filter((item) => item.kind === 'project' && item.parent_id === job.id);
  const rows: { item?: ProfileItem; job?: ProfileItem; nested?: boolean }[] = [];
  if (kind === 'experience') for (const item of items) rows.push({ item }, ...childrenOf(item).map((child) => ({ item: child, nested: true })));
  else if (kind === 'project') {
    const parented = new Set(jobs.map((job) => job.id));
    for (const item of items) if (!item.parent_id || !parented.has(item.parent_id)) rows.push({ item });
    for (const job of jobs) { const children = childrenOf(job); if (children.length) rows.push({ job }, ...children.map((child) => ({ item: child, nested: true }))); }
  } else for (const item of items) rows.push({ item });
  const selectable = rows.flatMap((row) => row.item ? [row.item] : []);
  const [chosen, setChosen] = useState<Record<string, Record<string, Pick>>>({});
  const toggleItem = (item: ProfileItem) => setChosen((current) => {
    const next = { ...current };
    if (next[item.id]) delete next[item.id]; else next[item.id] = initialPicks(item);
    return next;
  });
  const setPick = (item: ProfileItem, pointId: string, patch: Partial<Pick>) => setChosen((current) => ({ ...current, [item.id]: { ...current[item.id], [pointId]: { ...current[item.id][pointId], ...patch } } }));
  const confirm = () => {
    const entries = selectable.filter((item) => chosen[item.id]).map((item) => entryFromItem(item, item.data.bullets.filter((point) => chosen[item.id][point.id]?.checked).map((point) => ({ point, alternativeId: chosen[item.id][point.id].alt }))));
    if (entries.length) onAdd(entries);
  };
  return <Dialog title="Add from your profile" onClose={onClose}>
    {bank.status !== 'ready' ? <p className="point-dialog-note" role="status">{bank.status === 'loading' ? 'Loading your profile…' : 'Your profile could not be loaded. Reload the page to try again.'}</p>
      : !selectable.length ? <p className="point-dialog-note">Nothing of this kind in your profile yet. Add it on the Profile page, or type an entry here.</p>
      : <div className="point-picker">{rows.map((row) => {
        if (!row.item) return <div className="point-picker-group" key={`job-${row.job!.id}`}>{itemLabel(row.job!)}</div>;
        const item = row.item;
        const picks = chosen[item.id], dates = formatItemDates(item.data);
        return <div className={`point-picker-item ${row.nested ? 'nested' : ''}`} key={item.id}>
          {row.nested && <small className="point-picker-nested-label">Project in this role</small>}
          <label className="point-picker-head"><input type="checkbox" checked={!!picks} onChange={() => toggleItem(item)} /><span><strong>{itemLabel(item)}</strong>{dates && <small> {dates}</small>}{used.has(item.id) && <small> · already on this resume</small>}</span></label>
          {picks && <div className="point-picker-points">
            {item.data.bullets.length === 0 && <small>This item has no points yet.</small>}
            {item.data.bullets.map((point) => {
              const versions = pointVersions(point);
              return <div className="point-picker-point" key={point.id}>
                <label><input type="checkbox" checked={picks[point.id]?.checked ?? false} onChange={(event) => setPick(item, point.id, { checked: event.target.checked })} /><span>{clip(versions.find((version) => version.id === (picks[point.id]?.alt ?? null))?.text ?? point.text, 140)}</span></label>
                {versions.length > 1 && <select aria-label={`Version of: ${clip(point.text, 40)}`} value={picks[point.id]?.alt ?? ''} onChange={(event) => setPick(item, point.id, { alt: event.target.value || null })}>{versions.map((version, i) => <option key={version.id ?? 'main'} value={version.id ?? ''}>Version {i + 1}: {clip(version.text, 50)}</option>)}</select>}
              </div>;
            })}
          </div>}
        </div>;
      })}</div>}
    <div className="point-dialog-actions">
      <button type="button" className="button primary" disabled={!Object.keys(chosen).length} onClick={confirm}>Add to resume</button>
      <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
    </div>
  </Dialog>;
}
