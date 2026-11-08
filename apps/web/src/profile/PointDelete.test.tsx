// Deleting points in import review and in the profile bank (bug report 2026-11-08: a wrapped PDF line became two points
// and neither could be removed; a cleared point was sent blank and rejected).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../api';
import type { ImportCandidate, ProfileBank, ProfileImport, ProfileItem } from '../types';
import { ImportReview } from './ImportReview';
import { ProfileView } from './ProfileView';

vi.mock('../api', async importOriginal => {
  const original = await importOriginal<typeof import('../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map(key => [key, vi.fn()])) };
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const split = [{ id: 'b1', text: 'Moved nightly ETL jobs to AWS Glue, cutting run time' }, { id: 'b2', text: 'by half.' }, { id: 'b3', text: 'Built Airflow pipelines.' }];

describe('import review', () => {
  const candidate = (): ImportCandidate => ({ candidate_id: 'c1', kind: 'experience', data: { title: 'Data Engineer', bullets: structuredClone(split) }, evidence: { title: null }, match: { status: 'new' } });
  const record = (): ProfileImport => ({ id: 'imp-1', source_type: 'text', status: 'ready', parser: 'heuristic-v1', profile_epoch: 0, input_ref: { sha256: 'abc' }, candidates: [candidate()], error_code: null, created_at: '2026-11-08T00:00:00Z', applied_at: null, result: null });
  const result = { import_id: 'imp-1', bank_revision: 1, counts: { added: 1, merged: 0, skipped: 0, basics_updated: 0 }, conflicts: [] };
  const sentTexts = (onApply: ReturnType<typeof vi.fn>) => (onApply.mock.calls[0] as any)[0][0].data.bullets.map((point: { text: string }) => point.text);

  it('deletes a point and applies without it', async () => {
    const onApply = vi.fn(async () => result);
    render(<ImportReview record={record()} onApply={onApply} onClose={vi.fn()} onDiscard={vi.fn()} onReload={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Delete point 2' }));
    expect(screen.getAllByRole('textbox', { name: /Point \d wording/ })).toHaveLength(2);
    expect(screen.getByRole('textbox', { name: 'Point 2 wording' })).toHaveValue('Built Airflow pipelines.');
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(sentTexts(onApply)).toEqual(['Moved nightly ETL jobs to AWS Glue, cutting run time', 'Built Airflow pipelines.']);
  });

  it('treats a cleared point as deleted instead of sending it blank', async () => {
    const onApply = vi.fn(async () => result);
    render(<ImportReview record={record()} onApply={onApply} onClose={vi.fn()} onDiscard={vi.fn()} onReload={vi.fn()} />);
    const user = userEvent.setup();
    await user.clear(screen.getByRole('textbox', { name: 'Point 2 wording' }));
    await user.type(screen.getByRole('textbox', { name: 'Point 2 wording' }), '   ');
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(sentTexts(onApply)).toEqual(['Moved nightly ETL jobs to AWS Glue, cutting run time', 'Built Airflow pipelines.']);
  });
});

describe('profile bank', () => {
  it('deletes a saved point with a revision check and offers Undo', async () => {
    const item: ProfileItem = { id: 'exp-1', kind: 'experience', position: 0, revision: 3, archived_at: null, origin: 'import', import_id: 'imp-1', parent_id: null, tags: [], data: { title: 'Data Engineer', bullets: split.map(point => ({ ...point, tags: [], alternatives: [] })) } };
    let bank: ProfileBank = { basics: {}, items: [item], grouped: { experience: [], project: [], education: [], skill: [], certification: [], award: [], volunteering: [], custom: [] }, bank_revision: 9, confirmed_revision: 9, profile_epoch: 0 };
    const mockApi = vi.mocked(api);
    mockApi.getBank.mockImplementation(async () => structuredClone(bank));
    mockApi.getProfile.mockResolvedValue({ draft: {}, revision: 1, bank_revision: 9, confirmed_revision: 9 });
    mockApi.getSeniorityOptions.mockResolvedValue({ items: [] });
    mockApi.uploads.mockResolvedValue({ items: [], next_cursor: null });
    mockApi.imports.mockResolvedValue({ items: [], next_cursor: null });
    mockApi.patchItem.mockImplementation(async (_id, changes) => { const saved = { ...item, ...changes, revision: 4 } as ProfileItem; bank = { ...bank, items: [saved], bank_revision: 10 }; return structuredClone(saved); });
    const callbacks = { onChanged: vi.fn(), onBasicsSaved: vi.fn(), onOpenResume: vi.fn(), setPreferences: vi.fn(), savePreferences: vi.fn(), onUpload: vi.fn(), onBusyChange: vi.fn() };
    render(<ProfileView {...callbacks} userKey="alice" preferences={{ roles: [], locations: ['Singapore'], work_modes: [] }} savingPreferences={false} uploading={false} uploadMessage="" extractedResumeText="" resumes={[]} />);
    const user = userEvent.setup();
    const point = await screen.findByLabelText('by half.');
    await user.click(within(point).getByRole('button', { name: 'Delete point' }));
    expect(mockApi.patchItem).toHaveBeenCalledWith('exp-1', expect.objectContaining({ expected_revision: 3, data: expect.objectContaining({ bullets: [expect.objectContaining({ id: 'b1' }), expect.objectContaining({ id: 'b3' })] }) }));
    await waitFor(() => expect(screen.queryByLabelText('by half.')).not.toBeInTheDocument());
    expect(screen.getByRole('status')).toHaveTextContent('Point deleted.');
    expect(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });
});
