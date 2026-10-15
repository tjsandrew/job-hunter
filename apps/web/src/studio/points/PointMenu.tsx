import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

export type MenuEntry =
  | { type: 'separator' }
  | { type: 'item'; id: string; label: string; checked?: boolean; disabled?: boolean; title?: string; onSelect?: () => void; submenu?: MenuEntry[] };
export type MenuAnchor = { x: number; y: number; align?: 'left' | 'right' };

const isItem = (entry: MenuEntry): entry is Extract<MenuEntry, { type: 'item' }> => entry.type === 'item';
export const prefersSheet = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 640px), (pointer: coarse)').matches;

/**
 * The point menu: ARIA menu with one level of submenu. Desktop shows a popup at the anchor; touch and narrow screens show the
 * same entries as a bottom sheet where each submenu becomes a titled section. Keyboard: arrows, Right opens a submenu, Left/Esc close it.
 */
export function PointMenu({ entries, anchor, sheet, label = 'Point actions', onClose }: { entries: MenuEntry[]; anchor: MenuAnchor; sheet: boolean; label?: string; onClose: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [place, setPlace] = useState<{ left: number; top: number; flip: boolean }>({ left: anchor.x, top: anchor.y, flip: false });
  const returnTo = useRef<Element | null>(typeof document === 'undefined' ? null : document.activeElement);
  const close = useRef(onClose); close.current = onClose;
  const focusSub = useRef(false);
  // After Right opens a submenu, move focus into it.
  useEffect(() => {
    if (!focusSub.current) return;
    focusSub.current = false;
    root.current?.querySelector<HTMLElement>('[data-level="sub"] [role="menuitem"]:not([aria-disabled="true"])')?.focus();
  }, [open]);

  useLayoutEffect(() => {
    if (sheet || !root.current) return;
    const box = root.current.getBoundingClientRect(), margin = 8;
    const left = anchor.align === 'right' ? anchor.x - box.width : anchor.x;
    setPlace({
      left: Math.max(margin, Math.min(left, window.innerWidth - box.width - margin)),
      top: Math.max(margin, Math.min(anchor.y, window.innerHeight - box.height - margin)),
      flip: left + box.width * 2 + margin > window.innerWidth,
    });
  }, [anchor, sheet]);
  useEffect(() => {
    if (root.current) enabled(root.current)[0]?.focus();
    // A click on the button that opened the menu is left to that button, so it can toggle the menu closed.
    const away = (event: Event) => { const target = event.target as Element; if (!root.current?.contains(target) && !target.closest?.('[aria-haspopup="menu"][aria-expanded="true"]')) close.current(); };
    document.addEventListener('mousedown', away); window.addEventListener('resize', close.current);
    const previous = returnTo.current;
    return () => {
      document.removeEventListener('mousedown', away); window.removeEventListener('resize', close.current);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  const enabled = (scope: ParentNode) => [...scope.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')];
  // Items of one menu level; in sheet mode the groups are part of the single top level.
  const focusables = (level: HTMLElement) => enabled(level).filter((item) => item.closest('[role="menu"]') === level);
  const onKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    const level = target.closest<HTMLElement>('[role="menu"]');
    if (!level || target.getAttribute('role') !== 'menuitem') return;
    const items = focusables(level), at = items.indexOf(target);
    const go = (next: number) => { event.preventDefault(); items[(next + items.length) % items.length]?.focus(); };
    if (event.key === 'ArrowDown') go(at + 1);
    else if (event.key === 'ArrowUp') go(at - 1);
    else if (event.key === 'Home') go(0);
    else if (event.key === 'End') go(items.length - 1);
    else if (event.key === 'Tab') close.current();
    else if (event.key === 'ArrowRight' && target.getAttribute('aria-haspopup') === 'menu') {
      event.preventDefault(); focusSub.current = true; setOpen(target.dataset.id ?? null);
    } else if ((event.key === 'ArrowLeft' || event.key === 'Escape') && level.dataset.level === 'sub') {
      event.preventDefault(); event.stopPropagation(); setOpen(null);
      level.parentElement?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    } else if (event.key === 'Escape') { event.preventDefault(); close.current(); }
  };

  const renderItem = (entry: Extract<MenuEntry, { type: 'item' }>, nested: boolean) => {
    const common = { role: 'menuitem' as const, className: `point-menu-item${entry.disabled ? ' is-disabled' : ''}`, 'aria-disabled': entry.disabled || undefined, title: entry.title, tabIndex: -1, 'data-id': entry.id };
    const choose = () => { if (entry.disabled) return; close.current(); entry.onSelect?.(); };
    if (entry.submenu && !sheet) {
      const expanded = open === entry.id;
      return <div className="point-menu-parent" key={entry.id}>
        <button type="button" {...common} aria-haspopup="menu" aria-expanded={expanded} onClick={() => !entry.disabled && setOpen(expanded ? null : entry.id)}><span>{entry.label}</span><span aria-hidden="true">▸</span></button>
        {expanded && <div role="menu" aria-label={entry.label} data-level="sub" className={`point-menu point-submenu${place.flip ? ' flip' : ''}`}>{entry.submenu.map((child, i) => isItem(child) ? renderItem(child, true) : <div role="separator" key={i} />)}</div>}
      </div>;
    }
    return <button type="button" key={entry.id} {...common} aria-current={entry.checked || undefined} data-nested={nested || undefined} onClick={choose}>
      <span>{entry.label}</span>{entry.checked && <span aria-hidden="true">✓</span>}
    </button>;
  };
  const renderSheet = () => entries.map((entry, i) => !isItem(entry) ? <div role="separator" key={`s${i}`} /> : entry.submenu
    ? <div role="group" aria-label={entry.label} key={entry.id} className="point-sheet-group"><div className="point-sheet-title">{entry.label}</div>{entry.submenu.map((child, j) => isItem(child) ? renderItem(child, true) : <div role="separator" key={j} />)}</div>
    : renderItem(entry, false));

  const menu = <div className={sheet ? 'point-sheet-backdrop' : undefined}>
    <div ref={root} role="menu" aria-label={label} data-level="top" className={`point-menu ${sheet ? 'point-sheet' : 'point-popup'}`} style={sheet ? undefined : { left: place.left, top: place.top }} onKeyDown={onKeyDown} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); }}>
      {sheet ? renderSheet() : entries.map((entry, i) => isItem(entry) ? renderItem(entry, false) : <div role="separator" key={`s${i}`} />)}
      {sheet && <button type="button" className="point-menu-item point-sheet-cancel" role="menuitem" tabIndex={-1} onClick={() => close.current()}>Cancel</button>}
    </div>
  </div>;
  return createPortal(menu, document.body);
}
