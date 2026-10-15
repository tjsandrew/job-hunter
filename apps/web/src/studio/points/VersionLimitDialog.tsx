import { useState } from 'react';
import { Dialog } from './Dialog';
import { LIMIT_TITLE } from './profileSave';

/** "Replace which one?" when a save would pass the 5-version limit. The main wording can't be dropped, so only the other versions are listed. */
export function VersionLimitDialog({ versions, mainText, canSkipOld, onReplace, onSkipOld, onCancel }: { versions: { id: string; text: string }[]; mainText: string; canSkipOld: boolean; onReplace: (id: string) => void; onSkipOld: () => void; onCancel: () => void }) {
  const [choice, setChoice] = useState('');
  return <Dialog title={LIMIT_TITLE} onClose={onCancel}>
    <p className="point-dialog-note">The version you choose is removed from your profile. The main wording ("{mainText}") always stays.</p>
    <div className="point-dialog-choices" role="radiogroup" aria-label="Versions you can replace">
      {versions.map((version, number) => <label key={version.id} className="point-dialog-choice"><input type="radio" name="point-replace" checked={choice === version.id} onChange={() => setChoice(version.id)} /><span>{`Version ${number + 2}: ${version.text}`}</span></label>)}
    </div>
    <div className="point-dialog-actions">
      <button type="button" className="button primary" disabled={!choice} onClick={() => onReplace(choice)}>Replace selected version</button>
      {canSkipOld && <button type="button" className="button secondary" onClick={onSkipOld}>Don't keep the old wording</button>}
      <button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
    </div>
  </Dialog>;
}
