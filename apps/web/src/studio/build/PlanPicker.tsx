import { Icon } from '../../ui';
import { kindLabels, moveDraftItem, movePoint, nestedUnder, planKinds, setVersion, toggleItem, togglePoint, toggleSkill } from './buildPlan';
import type { Draft, DraftItem } from './buildPlan';

const clip = (text: string, length = 70) => text.length > length ? `${text.slice(0, length - 1)}…` : text;

/** Item, point, version and skill pickers shared by the free build and the build for a job. */
export function PlanPicker({ draft, reasons, cap, disabled, onChange }: { draft: Draft; reasons: Record<string, string[]>; cap: number; disabled?: boolean; onChange: (draft: Draft) => void }) {
  const renderItem = (item: DraftItem, index: number, siblings: DraftItem[], nested = false) => (
      <div key={item.id} className={`plan-item ${item.on ? '' : 'off'} ${nested ? 'nested' : ''}`}>
          {nested && <span className="plan-nested-label">Project in this role</span>}
          <div className="plan-item-head">
            <label className="plan-check"><input type="checkbox" disabled={disabled} checked={item.on} onChange={(event) => onChange(toggleItem(draft, item.id, event.target.checked, cap))} /><span><strong>{item.title}</strong>{item.sub && <small>{item.sub}{item.dates ? ` · ${item.dates}` : ''}</small>}{!item.sub && item.dates && <small>{item.dates}</small>}</span></label>
            <span className="plan-move"><button type="button" className="icon-button" aria-label={`Move ${item.title} up`} disabled={disabled || index === 0} onClick={() => onChange(moveDraftItem(draft, item.id, -1))}><Icon name="up" /></button><button type="button" className="icon-button" aria-label={`Move ${item.title} down`} disabled={disabled || index === siblings.length - 1} onClick={() => onChange(moveDraftItem(draft, item.id, 1))}><Icon name="down" /></button></span>
          </div>
          {item.on && !!reasons[item.id]?.length && <p className="plan-reason">{reasons[item.id].join(' · ')}</p>}
          {item.on && item.points.length > 0 && <ul className="plan-points">
            {item.points.map((point, pointIndex) => {
              const shown = point.alt ? point.versions.find((version) => version.id === point.alt)?.text || point.text : point.text;
              const why = reasons[`${item.id}:${point.id}`];
              return <li key={point.id} className={point.on ? '' : 'off'}>
                <div className="plan-point-row">
                  <label className="plan-check"><input type="checkbox" disabled={disabled} checked={point.on} onChange={(event) => onChange(togglePoint(draft, item.id, point.id, event.target.checked))} /><span>{shown}</span></label>
                  <span className="plan-move"><button type="button" className="icon-button" aria-label={`Move point up: ${clip(shown, 40)}`} disabled={disabled || pointIndex === 0} onClick={() => onChange(movePoint(draft, item.id, point.id, -1))}><Icon name="up" /></button><button type="button" className="icon-button" aria-label={`Move point down: ${clip(shown, 40)}`} disabled={disabled || pointIndex === item.points.length - 1} onClick={() => onChange(movePoint(draft, item.id, point.id, 1))}><Icon name="down" /></button></span>
                </div>
                {point.on && !!why?.length && <p className="plan-reason">{why.join(' · ')}</p>}
                {point.on && point.versions.length > 0 && <label className="plan-version">Wording <select aria-label={`Wording for: ${clip(point.text, 40)}`} disabled={disabled} value={point.alt || ''} onChange={(event) => onChange(setVersion(draft, item.id, point.id, event.target.value || null))}><option value="">Main wording</option>{point.versions.map((version, versionIndex) => <option key={version.id} value={version.id}>Version {versionIndex + 1}: {clip(version.text)}</option>)}</select></label>}
              </li>;
            })}
          </ul>}
      </div>
  );
  return <div className="plan-picker">
    {planKinds.map((kind) => {
      // Projects that belong to a job are listed under it; the resume itself stays flat.
      const items = draft.items.filter((item) => item.kind === kind && !nestedUnder(draft, item));
      if (!items.length) return null;
      return <section key={kind} className="plan-group" aria-label={kindLabels[kind]}>
        <h3>{kindLabels[kind]}</h3>
        {items.map((item, index) => {
          const children = kind === 'experience' ? draft.items.filter((row) => nestedUnder(draft, row) === item.id) : [];
          return <div key={item.id} className="plan-block">{renderItem(item, index, items)}{children.map((child, childIndex) => renderItem(child, childIndex, children, true))}</div>;
        })}
      </section>;
    })}
    {draft.skills.length > 0 && <section className="plan-group" aria-label="Skills"><h3>Skills</h3><div className="plan-skills">{draft.skills.map((skill) => <label key={skill.id} className={`plan-skill ${skill.on ? 'on' : ''}`}><input type="checkbox" disabled={disabled} checked={skill.on} onChange={(event) => onChange(toggleSkill(draft, skill.id, event.target.checked))} />{skill.name}</label>)}</div></section>}
    {!draft.items.length && !draft.skills.length && <p className="plan-empty">Your profile has nothing to build from yet. Add experience on the Profile page, or start with a blank resume.</p>}
  </div>;
}
