import { useEffect, useRef, useState } from 'react';
import { addBullet, addEntry, itemKindFor, moveBullet, moveItem, removeBullet, removeEntry, removeSection, replaceWithVersion, sectionKind, setBullet, updateEntry, updateEntryWith } from '../editor';
import { Field, Icon } from '../ui';
import type { ResumeContent, ResumeEntry, ResumeSection } from '../types';
import { useProfileBank, type BankHandle } from './points/bank';
import { AddFromProfileDialog, MoreFromJob } from './points/FromProfile';
import { focusKey, PointRow } from './points/PointRow';
import { useProfileSave } from './points/useProfileSave';
import './points/points.css';

export function SectionEditor({ section, index, count, content, onContent, bank: bankOverride }: { section: ResumeSection; index: number; count: number; content: ResumeContent; onContent: (value: ResumeContent) => void; bank?: BankHandle }) {
  const bank = useProfileBank(bankOverride);
  const latest = useRef(content); latest.current = content;
  const root = useRef<HTMLElement>(null);
  const pendingFocus = useRef<string | undefined>(undefined);
  const [picker, setPicker] = useState(false);
  const save = useProfileSave({ section, bank, getContent: () => latest.current, onContent });
  // Keep keyboard focus on the point that just moved.
  useEffect(() => {
    if (!pendingFocus.current) return;
    const target = [...(root.current?.querySelectorAll<HTMLElement>('[data-pt]') ?? [])].find((el) => el.dataset.pt === pendingFocus.current);
    pendingFocus.current = undefined; target?.focus();
  });

  const kind = sectionKind(section), itemKind = itemKindFor(kind), known = kind !== 'custom' || section.kind === 'custom';
  // A section's inferred kind is saved the first time it is edited.
  const patchSection = (patch: Partial<ResumeSection>) => onContent({ ...content, sections: content.sections.map((item) => item.id === section.id ? { ...item, ...(!item.kind && kind !== 'custom' ? { kind } : {}), ...patch } : item) });
  const move = (delta: -1 | 1) => onContent({ ...content, sections: moveItem(content.sections, index, delta) });
  const patchEntry = (id: string, patch: Partial<ResumeEntry>) => onContent(updateEntry(content, section.id, id, patch));
  const change = (id: string, edit: (entry: ResumeEntry) => ResumeEntry) => onContent(updateEntryWith(content, section.id, id, edit));
  const usedItems = new Set(content.sections.flatMap((item) => item.entries.map((entry) => entry.source?.item_id).filter((id): id is string => !!id)));

  const pointActions = (entry: ResumeEntry, i: number) => ({
    move: (delta: -1 | 1, focus: 'text' | 'up' | 'down' | 'more') => {
      const target = i + delta;
      pendingFocus.current = focusKey(entry.id, target, (focus === 'up' && target === 0) ? 'down' : (focus === 'down' && target === entry.bullets.length - 1) ? 'up' : focus);
      change(entry.id, (current) => moveBullet(current, i, delta));
    },
    change: (text: string) => change(entry.id, (current) => setBullet(current, i, text)),
    remove: () => { pendingFocus.current = entry.bullets.length > 1 ? focusKey(entry.id, Math.min(i, entry.bullets.length - 2), 'more') : undefined; change(entry.id, (current) => removeBullet(current, i)); },
    swapVersion: (versionId: string | null, text: string) => change(entry.id, (current) => replaceWithVersion(current, i, text, versionId)),
    update: () => void save.actions.update(entry, i),
    newVersion: () => void save.actions.newVersion(entry, i),
    newPoint: () => save.actions.newPoint(entry, i),
  });
  const addFromProfileTitle = bank.status === 'ready' ? undefined : bank.status === 'loading' ? 'Loading your profile…' : 'Your profile could not be loaded. Reload the page to try again.';

  return <section ref={root} className={`section-editor${section.hidden ? ' is-hidden' : ''}`}>
    <div className="section-edit-head"><div className="section-grip">⠿</div><input aria-label="Section title" className="section-title-input" value={section.title} onChange={(e) => patchSection({ title: e.target.value })} />
      {section.hidden && <span className="section-hidden-note">Hidden on the resume</span>}
      <button type="button" className="button text-button small-button section-hide" aria-pressed={!!section.hidden} aria-label={section.hidden ? 'Show section on the resume' : 'Hide section on the resume'} title={section.hidden ? 'Show this section on the resume' : 'Keep this section but leave it off the resume'} onClick={() => patchSection({ hidden: !section.hidden })}>{section.hidden ? 'Show' : 'Hide'}</button>
      <button className="icon-button" title="Move section up" disabled={index === 0} onClick={() => move(-1)}><Icon name="up" /></button><button className="icon-button" title="Move section down" disabled={index === count - 1} onClick={() => move(1)}><Icon name="down" /></button><button className="icon-button danger" title="Remove section" onClick={() => onContent(removeSection(content, section.id))}><Icon name="trash" /></button></div>
    {section.entries.map((entry, entryIndex) => <div className="entry-editor" key={entry.id}><div className="entry-edit-head"><span>Entry {entryIndex + 1}</span><button className="icon-button danger" title="Remove entry" onClick={() => onContent({ ...content, sections: content.sections.map((item) => item.id === section.id ? removeEntry(item, entry.id) : item) })}><Icon name="trash" /></button></div><div className="form-grid two-col"><Field label="Role or degree" value={entry.heading} onChange={(v) => patchEntry(entry.id, { heading: v })} placeholder="Senior Product Designer" /><Field label="Company or school" value={entry.subheading} onChange={(v) => patchEntry(entry.id, { subheading: v })} placeholder="Company name" /></div><Field label="Dates" value={entry.dates} onChange={(v) => patchEntry(entry.id, { dates: v })} placeholder="Jan 2022 – Present" />{entry.date_range && <small className="point-date-note">Dates come from your profile. Editing this text keeps them as you type them.</small>}
      {entry.bullets.map((_, bulletIndex) => <PointRow key={`${entry.id}-${bulletIndex}`} entry={entry} index={bulletIndex} count={entry.bullets.length} section={section} bank={bank} actions={pointActions(entry, bulletIndex)} />)}
      <button className="button text-button" onClick={() => change(entry.id, (current) => addBullet(current))}><Icon name="plus" /> Add bullet</button>
      <MoreFromJob entry={entry} bank={bank} onAdd={(point) => change(entry.id, (current) => addBullet(current, point.text, { bullet_id: point.id, alternative_id: null, base_text: point.text }))} />
    </div>)}
    <div className="section-add-row"><button className="button secondary add-entry" onClick={() => patchSection(addEntry(section))}><Icon name="plus" /> Add entry</button>
      {known && itemKind && <button className="button secondary add-entry" disabled={bank.status !== 'ready'} title={addFromProfileTitle} onClick={() => setPicker(true)}><Icon name="plus" /> Add from profile</button>}</div>
    {picker && <AddFromProfileDialog section={section} bank={bank} used={usedItems} onClose={() => setPicker(false)} onAdd={(entries) => { setPicker(false); patchSection({ entries: [...section.entries, ...entries] }); save.notify(`Added ${entries.length === 1 ? entries[0].heading || 'an entry' : `${entries.length} entries`} from your profile.`); }} />}
    {save.overlays}
  </section>;
}
