import { useState } from 'react';
import { itemLabel } from '../../editor';
import type { ItemKind, ProfileItem } from '../../types';
import { Dialog } from './Dialog';
import type { NewPointTarget } from './profileSave';

const nouns: Record<string, string> = { experience: 'experience', education: 'education', project: 'project', custom: 'section' };

/** "Which experience?" for Save as new point: an existing item of the section's kind, or a new one. */
export function NewPointDialog({ kind, items, preselected, text, onConfirm, onCancel }: { kind: ItemKind; items: ProfileItem[]; preselected?: string; text: string; onConfirm: (target: NewPointTarget) => void; onCancel: () => void }) {
  const noun = nouns[kind] ?? 'item';
  const [choice, setChoice] = useState<string>(preselected && items.some((item) => item.id === preselected) ? preselected : '');
  return <Dialog title={`Which ${noun}?`} onClose={onCancel}>
    <p className="point-dialog-note">This point is added to your profile as a new point. Your resume keeps its own wording.</p>
    <blockquote className="point-dialog-quote">{text || 'Empty point'}</blockquote>
    <div className="point-dialog-choices" role="radiogroup" aria-label={`Which ${noun}?`}>
      {items.map((item) => <label key={item.id} className="point-dialog-choice"><input type="radio" name="point-target" checked={choice === item.id} onChange={() => setChoice(item.id)} /><span>{itemLabel(item)}</span></label>)}
      <label className="point-dialog-choice"><input type="radio" name="point-target" checked={choice === 'new'} onChange={() => setChoice('new')} /><span>New {noun}</span></label>
    </div>
    <div className="point-dialog-actions">
      <button type="button" className="button primary" disabled={!choice || !text.trim()} onClick={() => onConfirm(choice === 'new' ? { create: true } : { itemId: choice })}>Save to profile</button>
      <button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
    </div>
  </Dialog>;
}
