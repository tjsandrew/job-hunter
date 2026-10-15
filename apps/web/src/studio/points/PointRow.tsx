import { useState } from 'react';
import { isEdited, itemKindFor, sectionKind } from '../../editor';
import type { ResumeEntry, ResumeSection } from '../../types';
import { Icon } from '../../ui';
import { clip, linkedPoint, pointVersions, type BankHandle } from './bank';
import { PointMenu, prefersSheet, type MenuAnchor, type MenuEntry } from './PointMenu';

export type PointRowActions = {
  move: (delta: -1 | 1, focus: 'text' | 'up' | 'down' | 'more') => void;
  change: (text: string) => void;
  remove: () => void;
  swapVersion: (versionId: string | null, text: string) => void;
  update: () => void;
  newVersion: () => void;
  newPoint: () => void;
};
export const focusKey = (entryId: string, index: number, part: 'text' | 'up' | 'down' | 'more') => `${entryId}:${index}:${part}`;

/** One point: `[↑] [↓]  <textarea>  [⋮]`, always visible. ⋮ and right-click open the same menu. */
export function PointRow({ entry, index, count, section, bank, actions }: { entry: ResumeEntry; index: number; count: number; section: ResumeSection; bank: BankHandle; actions: PointRowActions }) {
  const [menu, setMenu] = useState<{ anchor: MenuAnchor; sheet: boolean } | null>(null);
  const text = entry.bullets[index], atTop = index === 0, atBottom = index === count - 1;
  const bankNote = bank.status === 'loading' ? 'Loading your profile…' : 'Your profile could not be loaded. Reload the page to try again.';

  const entries = (): MenuEntry[] => {
    const linked = !!entry.source && !!entry.bullet_sources?.[index];
    const found = linkedPoint(bank.bank, entry, index);
    const edited = isEdited(entry, index);
    const ready = bank.status === 'ready';
    const list: MenuEntry[] = [];
    if (linked && (!ready || (found && found.point.alternatives.length > 0))) {
      const current = entry.bullet_sources?.[index]?.alternative_id ?? null;
      list.push({
        type: 'item', id: 'versions', label: 'Versions', disabled: !ready, title: ready ? undefined : bankNote,
        submenu: found ? pointVersions(found.point).map((version, i) => ({ type: 'item' as const, id: `version-${version.id ?? 'main'}`, label: `Version ${i + 1}: ${clip(version.text)}`, checked: version.id === current, onSelect: () => actions.swapVersion(version.id, version.text) })) : [],
      });
    }
    if (!atTop) list.push({ type: 'item', id: 'up', label: 'Move up', onSelect: () => actions.move(-1, 'more') });
    if (!atBottom) list.push({ type: 'item', id: 'down', label: 'Move down', onSelect: () => actions.move(1, 'more') });
    list.push({ type: 'item', id: 'remove', label: 'Remove from resume', onSelect: actions.remove });
    const save: MenuEntry[] = [];
    if (linked && edited && text.trim()) {
      save.push({ type: 'item', id: 'update', label: 'Update in profile', onSelect: actions.update });
      save.push({ type: 'item', id: 'new-version', label: 'Save as new version', onSelect: actions.newVersion });
    }
    if (text.trim() && itemKindFor(sectionKind(section)) && (!linked || edited)) {
      save.push({ type: 'item', id: 'new-point', label: 'Save as new point…', disabled: !ready, title: ready ? undefined : bankNote, onSelect: actions.newPoint });
    }
    if (save.length) list.push({ type: 'separator' }, { type: 'item', id: 'save', label: 'Save to profile', submenu: save });
    return list;
  };
  const openAt = (anchor: MenuAnchor) => setMenu({ anchor, sheet: prefersSheet() });

  return <div className="point-row" onContextMenu={(event) => { event.preventDefault(); openAt({ x: event.clientX, y: event.clientY }); }}>
    <div className="point-move">
      <button type="button" className="icon-button" aria-label="Move point up" title="Move up (Alt+↑)" disabled={atTop} data-pt={focusKey(entry.id, index, 'up')} onClick={() => actions.move(-1, 'up')}><Icon name="up" /></button>
      <button type="button" className="icon-button" aria-label="Move point down" title="Move down (Alt+↓)" disabled={atBottom} data-pt={focusKey(entry.id, index, 'down')} onClick={() => actions.move(1, 'down')}><Icon name="down" /></button>
    </div>
    <textarea aria-label={`Bullet ${index + 1}`} value={text} rows={2} placeholder="Describe an accomplishment and its impact..." data-pt={focusKey(entry.id, index, 'text')}
      onChange={(event) => actions.change(event.target.value)}
      onKeyDown={(event) => {
        if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
          event.preventDefault();
          const delta = event.key === 'ArrowUp' ? -1 : 1;
          if (delta === -1 ? !atTop : !atBottom) actions.move(delta, 'text');
        } else if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
          event.preventDefault();
          const box = event.currentTarget.getBoundingClientRect();
          openAt({ x: box.left + 24, y: box.top + 24 });
        }
      }} />
    <button type="button" className="icon-button point-more" aria-label="More actions for this point" title="More actions" aria-haspopup="menu" aria-expanded={!!menu} data-pt={focusKey(entry.id, index, 'more')}
      onClick={(event) => { if (menu) { setMenu(null); return; } const box = event.currentTarget.getBoundingClientRect(); openAt({ x: box.right, y: box.bottom + 4, align: 'right' }); }}><span aria-hidden="true">⋮</span></button>
    {menu && <PointMenu entries={entries()} anchor={menu.anchor} sheet={menu.sheet} onClose={() => setMenu(null)} />}
  </div>;
}
