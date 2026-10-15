import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpError } from '../api';
import type { ImportCandidate, ProfileImport } from '../types';
import { ImportReview } from './ImportReview';

afterEach(cleanup);
const quote = (text: string) => ({ source_sha256: 'abc', page: 1, text });
const newRole = (): ImportCandidate => ({ candidate_id: 'c-new', kind: 'experience', data: { title: 'Data Engineer', organisation: 'Fictional Harbour', bullets: [] }, evidence: { title: quote('Data Engineer at Fictional Harbour'), organisation: null }, match: { status: 'new' } });
const ambiguous = (): ImportCandidate => ({ candidate_id: 'c-amb', kind: 'project', data: { name: 'Route Planner', bullets: [] }, evidence: { name: quote('Route Planner') }, match: { status: 'ambiguous', options: [{ item_id: 'p1', item_revision: 2, label: 'Route Planner v1' }, { item_id: 'p2', item_revision: 4, label: 'Route Planner v2' }] } });
const basics = (): ImportCandidate => ({ candidate_id: 'basics', kind: 'basics', data: { name: 'Fictional Alex', headline: 'Platform engineer' }, evidence: { name: quote('Fictional Alex'), headline: quote('Platform engineer') }, match: { status: 'update', basics_revision: 7, conflicts: { headline: { existing: 'Backend engineer', incoming: 'Platform engineer' } } } });
const record = (candidates: ImportCandidate[]): ProfileImport => ({ id: 'imp-1', source_type: 'text', status: 'ready', parser: 'heuristic-v1', profile_epoch: 0, input_ref: { sha256: 'abc' }, candidates, error_code: null, created_at: '2026-10-14T00:00:00Z', applied_at: null, result: null });
const result = { import_id: 'imp-1', bank_revision: 10, counts: { added: 1, merged: 0, skipped: 0, basics_updated: 0 }, conflicts: [] };

function setup(candidates: ImportCandidate[], onApply = vi.fn(async () => result)) {
  const handlers = { onApply, onClose: vi.fn(), onDiscard: vi.fn(async () => undefined), onReload: vi.fn(async () => undefined) };
  render(<ImportReview record={record(candidates)} {...handlers} />);
  return { user: userEvent.setup(), ...handlers };
}

describe('ImportReview', () => {
  it('shows evidence quotes and flags values not found in the source', () => {
    setup([newRole()]);
    expect(screen.getByText(/From the source · page 1: Data Engineer at Fictional Harbour/)).toBeInTheDocument();
    expect(screen.getAllByText('Not found in the source, check this')).toHaveLength(1);
  });

  it('toggles Add, Merge and Skip and does not call apply until clicked', async () => {
    const matched = { ...newRole(), match: { status: 'update' as const, item_id: 'exp-1', item_revision: 3 } };
    const { user, onApply } = setup([matched]);
    const group = screen.getByRole('group', { name: 'Decision for Data Engineer' });
    expect(screen.getByRole('button', { name: 'Merge' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(screen.getByRole('button', { name: 'Skip' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Title')).toBeDisabled();
    expect(screen.getByRole('button', { name: /Apply to profile/ })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add' })).toHaveAttribute('aria-pressed', 'true');
    expect(onApply).not.toHaveBeenCalled();
  });

  it('requires a merge target for an ambiguous candidate before apply is enabled', async () => {
    const { user, onApply } = setup([ambiguous()]);
    expect(screen.getByRole('button', { name: /Apply to profile/ })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Merge' }));
    expect(screen.getByText(/Choose a merge target first/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Apply to profile/ })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Merge target for Route Planner'), 'p2');
    expect(screen.getByRole('button', { name: /Apply to profile/ })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(onApply).toHaveBeenCalledWith([expect.objectContaining({ candidate_id: 'c-amb', action: 'merge', target_item_id: 'p2', expected_revision: 4 })]);
  });

  it('lets a basics conflict keep the current value or use the imported one', async () => {
    const { user, onApply } = setup([basics()]);
    expect(screen.getByLabelText('Headline conflict')).toHaveValue('keep');
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(onApply).toHaveBeenLastCalledWith([expect.objectContaining({ candidate_id: 'basics', accepted_fields: ['name'], expected_revision: 7 })]);
    await user.selectOptions(screen.getByLabelText('Headline conflict'), 'use');
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(onApply).toHaveBeenLastCalledWith([expect.objectContaining({ accepted_fields: ['name', 'headline'] })]);
    await user.selectOptions(screen.getByLabelText('Headline conflict'), 'keep');
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(onApply).toHaveBeenLastCalledWith([expect.objectContaining({ accepted_fields: ['name'] })]);
  });

  it('sends the expected decisions including edited data', async () => {
    const { user, onApply } = setup([newRole(), basics()]);
    await user.clear(screen.getByLabelText('Title'));
    await user.type(screen.getByLabelText('Title'), 'Senior Data Engineer');
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(onApply).toHaveBeenCalledTimes(1);
    const sent = (onApply.mock.calls[0] as unknown as [any[]])[0];
    expect(sent).toHaveLength(2);
    expect(sent[0]).toMatchObject({ candidate_id: 'c-new', action: 'add', data: { title: 'Senior Data Engineer' } });
  });

  it.each([
    ['REVISION_CONFLICT', /changed elsewhere/],
    ['PROFILE_EPOCH_CHANGED', /profile was deleted/],
  ])('shows the %s conflict message and keeps the review open', async (code, message) => {
    const { user } = setup([newRole()], vi.fn(async () => { throw new HttpError('conflict', 409, code); }));
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    await waitFor(() => expect(screen.getByRole('button', { name: /Apply to profile/ })).toBeEnabled());
  });
});
