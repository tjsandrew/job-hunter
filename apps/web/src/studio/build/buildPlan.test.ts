import { describe, expect, it } from 'vitest';
import { applyFocus, applySuggestion, bankToDraft, countSelected, draftToPlan, focusOptions, moveDraftItem, movePoint, setVersion, toggleItem, togglePoint } from './buildPlan';
import type { Suggestion } from './buildApi';
import { bank } from './testData';

const meta = { title: 'T', template: 'classic' as const, job_id: null, summary: { mode: 'profile' as const } };
const onPoints = (draft: ReturnType<typeof bankToDraft>, id: string) => draft.items.find((item) => item.id === id)!.points.filter((point) => point.on).map((point) => point.id);

describe('bankToDraft', () => {
  it('lists items newest first within each kind and leaves everything unticked', () => {
    const draft = bankToDraft(bank());
    expect(draft.items.map((item) => item.id)).toEqual(['exp-1', 'exp-2', 'edu-1', 'proj-1']);
    expect(draft.items.some((item) => item.on) || draft.skills.some((skill) => skill.on)).toBe(false);
    expect(draft.skills.map((skill) => skill.name)).toEqual(['Python', 'SQL']);
  });
  it('lists the point types of the bank as focus options', () => {
    expect(focusOptions(bankToDraft(bank()))).toEqual(['backend', 'data', 'frontend', 'leadership']);
  });
  it('ignores archived items', () => {
    const data = bank(); data.items[1].archived_at = '2026-10-01T00:00:00Z';
    expect(bankToDraft(data).items.map((item) => item.id)).not.toContain('exp-2');
  });
});

describe('applyFocus', () => {
  it('ticks every item without a focus, capped per item', () => {
    const draft = applyFocus(bankToDraft(bank()), [], 4);
    expect(draft.items.every((item) => item.on)).toBe(true);
    expect(onPoints(draft, 'exp-1')).toEqual(['b1', 'b2', 'b3', 'b4']);
  });
  it('ticks only matching points and drops items that do not match, keeping education', () => {
    const draft = applyFocus(bankToDraft(bank()), ['backend'], 2);
    expect(onPoints(draft, 'exp-1')).toEqual(['b1', 'b3']);
    expect(draft.items.find((item) => item.id === 'exp-2')!.on).toBe(false);
    expect(draft.items.find((item) => item.id === 'proj-1')!.on).toBe(false);
    expect(draft.items.find((item) => item.id === 'edu-1')!.on).toBe(true);
  });
  it('keeps skills used by ticked points, or all skills when nothing matches', () => {
    const data = bank(); data.items[0].data.bullets[0].skills = ['Python'];
    expect(applyFocus(bankToDraft(data), ['backend'], 4).skills.map((skill) => skill.on)).toEqual([true, false]);
    expect(applyFocus(bankToDraft(bank()), ['backend'], 4).skills.map((skill) => skill.on)).toEqual([true, true]);
  });
});

describe('applySuggestion and draftToPlan', () => {
  const suggestion: Suggestion = { strategy: 'keyword-v1', reasons: {}, coverage: { covered: [], missing: [] }, plan: { sections: [
    { kind: 'experience', items: [{ item_id: 'exp-2', picks: [{ bullet_id: 'd1' }] }, { item_id: 'exp-1', picks: [{ bullet_id: 'b3', alternative_id: 'v1' }, { bullet_id: 'b1' }] }] },
    { kind: 'skills', skill_ids: ['skill-sql'] },
  ] } };
  it('ticks the plan in its own order and leaves the rest unticked after it', () => {
    const draft = applySuggestion(bankToDraft(bank()), suggestion);
    expect(draft.items.map((item) => [item.id, item.on])).toEqual([['exp-2', true], ['exp-1', true], ['edu-1', false], ['proj-1', false]]);
    expect(draft.items[1].points.map((point) => [point.id, point.on, point.alt])).toEqual([['b3', true, 'v1'], ['b1', true, null], ['b2', false, null], ['b4', false, null], ['b5', false, null]]);
    expect(draft.skills.map((skill) => skill.on)).toEqual([false, true]);
  });
  it('builds the exact plan the server expects', () => {
    const draft = applySuggestion(bankToDraft(bank()), suggestion);
    expect(draftToPlan(draft, { ...meta, title: 'Backend Engineer – Stripe', template: 'modern', job_id: 'job-1' })).toEqual({
      title: 'Backend Engineer – Stripe', template: 'modern', job_id: 'job-1', summary: { mode: 'profile' },
      sections: [
        { kind: 'experience', items: [{ item_id: 'exp-2', picks: [{ bullet_id: 'd1' }] }, { item_id: 'exp-1', picks: [{ bullet_id: 'b3', alternative_id: 'v1' }, { bullet_id: 'b1' }] }] },
        { kind: 'skills', skill_ids: ['skill-sql'] },
      ] });
  });
  it('orders sections by the user defaults and omits empty ones', () => {
    const draft = applyFocus(bankToDraft(bank()), [], 1);
    const plan = draftToPlan(draft, { ...meta, sectionOrder: ['skills', 'projects', 'education'] });
    expect(plan.sections.map((section) => section.kind)).toEqual(['skills', 'projects', 'education', 'experience']);
    expect(draftToPlan({ items: [], skills: [] }, meta).sections).toEqual([]);
  });
  it('ignores a suggested version the item does not have', () => {
    const bad: Suggestion = { ...suggestion, plan: { sections: [{ kind: 'experience', items: [{ item_id: 'exp-1', picks: [{ bullet_id: 'b1', alternative_id: 'nope' }, { bullet_id: 'gone' }] }] }] } };
    expect(onPoints(applySuggestion(bankToDraft(bank()), bad), 'exp-1')).toEqual(['b1']);
    expect(applySuggestion(bankToDraft(bank()), bad).items[0].points[0].alt).toBeNull();
  });
});

describe('editing helpers', () => {
  it('toggles, picks versions and reorders without mutating', () => {
    const start = applyFocus(bankToDraft(bank()), [], 2);
    const next = movePoint(setVersion(togglePoint(start, 'exp-1', 'b3', true), 'exp-1', 'b3', 'v1'), 'exp-1', 'b3', -1);
    expect(next.items[0].points.map((point) => point.id).slice(0, 3)).toEqual(['b1', 'b3', 'b2']);
    expect(next.items[0].points[1].alt).toBe('v1');
    expect(start.items[0].points[2].on).toBe(false);
  });
  it('ticking an empty item picks its first points, and items move within their kind', () => {
    const draft = toggleItem(bankToDraft(bank()), 'exp-1', true, 2);
    expect(onPoints(draft, 'exp-1')).toEqual(['b1', 'b2']);
    expect(moveDraftItem(draft, 'exp-1', 1).items.map((item) => item.id).slice(0, 2)).toEqual(['exp-2', 'exp-1']);
    expect(moveDraftItem(draft, 'exp-1', -1)).toBe(draft);
    expect(moveDraftItem(draft, 'edu-1', 1)).toBe(draft);
    expect(countSelected(draft)).toEqual({ items: 1, points: 2, skills: 0 });
  });
});
