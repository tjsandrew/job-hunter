import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';

/** Small modal used by the point actions: focus moves in, Esc closes, Tab stays inside, focus returns afterwards. */
export function Dialog({ title, onClose, children, role = 'dialog' }: { title: string; onClose: () => void; children: React.ReactNode; role?: 'dialog' | 'alertdialog' }) {
  const id = useId(), box = useRef<HTMLDivElement>(null), close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement;
    box.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') { event.stopPropagation(); close.current(); return; }
    if (event.key !== 'Tab' || !box.current) return;
    const stops = [...box.current.querySelectorAll<HTMLElement>('input, select, textarea, button:not([disabled])')].filter((el) => !(el as HTMLInputElement).disabled);
    if (!stops.length) return;
    const first = stops[0], last = stops[stops.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  return createPortal(<div className="modal-backdrop"><div className="modal point-dialog" role={role} aria-modal="true" aria-labelledby={id} ref={box} onKeyDown={onKeyDown}><h2 id={id}>{title}</h2>{children}</div></div>, document.body);
}
