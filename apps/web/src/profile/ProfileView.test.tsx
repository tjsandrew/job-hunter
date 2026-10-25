import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api, HttpError } from '../api';
import type { ProfileBank, ProfileImport, ProfileItem, ProfileResponse } from '../types';
import { ProfileView } from './ProfileView';

vi.mock('../api', async importOriginal => {
  const original = await importOriginal<typeof import('../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map(key => [key, vi.fn()])) };
});
const importRecord = (overrides: Partial<ProfileImport> = {}): ProfileImport => ({ id: 'imp-1', source_type: 'upload', status: 'ready', parser: 'heuristic-v1', profile_epoch: 0, input_ref: { sha256: 'abc', upload_id: 'upload-1' }, candidates: [{ candidate_id: 'c1', kind: 'experience', data: { title: 'Imported Role', bullets: [] }, evidence: { title: { source_sha256: 'abc', page: 1, text: 'Imported Role' } }, match: { status: 'new' } }], error_code: null, created_at: '2026-10-14T00:00:00Z', applied_at: null, result: null, ...overrides });
const mockApi = vi.mocked(api);
const copy = <T,>(value: T): T => structuredClone(value);
let bank: ProfileBank;
let profile: ProfileResponse;
const callbacks = { onChanged: vi.fn(), onBasicsSaved: vi.fn(), onOpenResume: vi.fn(), setPreferences: vi.fn(), savePreferences: vi.fn(), onUpload: vi.fn(), onBusyChange: vi.fn() };
const experience = (): ProfileItem => ({ id: 'exp-1', kind: 'experience', position: 0, revision: 3, archived_at: null, origin: 'manual', import_id: null, parent_id: null, tags: [], data: { title: 'Backend Engineer', organisation: 'Fictional Harbour', bullets: [{ id: 'point-1', text: 'Built reliable APIs', tags: ['backend'], skills: ['Python'], alternatives: [{ id: 'version-1', text: 'Improved service reliability', tags: ['impact'] }] }] } });
const saveItem = (item: ProfileItem) => {
  bank.items = [...bank.items.filter(row => row.id !== item.id), item].sort((a, b) => a.position - b.position);
  bank.bank_revision += 1;
  return copy(item);
};

beforeEach(() => {
  vi.resetAllMocks();
  profile = { draft: { name: 'Fictional Alex', headline: 'Backend engineer', email: 'alex@example.invalid', phone: '', location: 'Singapore', summary: 'Build reliable services.', links: ['https://example.invalid'], skills: ['Legacy skill'], experience: [{ role: 'Legacy role' }] }, revision: 4, bank_revision: 9, confirmed_revision: 8 };
  bank = { basics: profile.draft, items: [experience()], grouped: { experience: [], project: [], education: [], skill: [], certification: [], award: [], volunteering: [], custom: [] }, bank_revision: 9, confirmed_revision: 8, profile_epoch: 0 };
  mockApi.getBank.mockImplementation(async () => copy(bank));
  mockApi.getProfile.mockImplementation(async () => copy(profile));
  mockApi.getSeniorityOptions.mockResolvedValue({items:[{value:'intern',label:'Intern'},{value:'junior',label:'Junior / Entry-level'},{value:'mid',label:'Mid-level'},{value:'senior',label:'Senior'},{value:'lead',label:'Lead'},{value:'executive',label:'Executive'}]});
  mockApi.uploads.mockResolvedValue({ items: [], next_cursor: null });
  mockApi.imports.mockResolvedValue({ items: [], next_cursor: null });
  mockApi.getItem.mockImplementation(async id => copy(bank.items.find(item => item.id === id)!));
  mockApi.putProfile.mockImplementation(async draft => { profile = { ...profile, draft, revision: profile.revision + 1 }; bank.basics = draft; bank.bank_revision += 1; return copy(profile); });
  mockApi.confirmProfile.mockImplementation(async revision => { bank.confirmed_revision = revision; return { revision, bank_revision: revision, profile_version_id: 'snapshot-1' }; });
  mockApi.createItem.mockImplementation(async values => saveItem({ id: `new-${values.kind}`, kind: values.kind, data: values.data, parent_id: values.parent_id || null, position: 1, revision: 1, archived_at: null, origin: 'manual', import_id: null, tags: values.tags || [] }));
  mockApi.patchItem.mockImplementation(async (id, changes) => { const old = bank.items.find(item => item.id === id)!; return saveItem({ ...old, ...changes, revision: old.revision + 1 }); });
  mockApi.addPoint.mockImplementation(async (id, values) => { const old = bank.items.find(item => item.id === id)!; return saveItem({ ...old, revision: old.revision + 1, data: { ...old.data, bullets: [...old.data.bullets, { ...values, id: 'new-point', alternatives: [] }] } }); });
  mockApi.updatePoint.mockImplementation(async (id, pointId, values) => { const old = bank.items.find(item => item.id === id)!; return saveItem({ ...old, revision: old.revision + 1, data: { ...old.data, bullets: old.data.bullets.map(point => point.id === pointId ? { ...point, text: values.text } : point) } }); });
  mockApi.addAlternative.mockImplementation(async (id, pointId, values) => { const old = bank.items.find(item => item.id === id)!; return saveItem({ ...old, revision: old.revision + 1, data: { ...old.data, bullets: old.data.bullets.map(point => point.id === pointId ? { ...point, alternatives: [...point.alternatives, { ...values, id: 'new-version' }] } : point) } }); });
  mockApi.archiveItem.mockImplementation(async id => { const archived = { ...bank.items.find(item => item.id === id)!, revision: 4, archived_at: '2026-10-14T00:00:00Z' }; bank.items = bank.items.filter(item => item.id !== id); bank.bank_revision += 1; return copy(archived); });
  mockApi.revertItem.mockImplementation(async (id, changes) => saveItem({ ...experience(), id, ...changes, revision: changes.expected_revision + 1, archived_at: null }));
  mockApi.deleteProfile.mockImplementation(async () => { bank.items = []; bank.basics = {}; bank.bank_revision += 1; bank.profile_epoch += 1; profile.draft = {}; return { deleted: true, bank_revision: bank.bank_revision, profile_epoch: bank.profile_epoch }; });
});
afterEach(cleanup);

async function setup() {
  const user = userEvent.setup();
  render(<ProfileView {...callbacks} userKey="alice" preferences={{ roles: [], locations: ['Singapore'], work_modes: [] }} savingPreferences={false} uploading={false} uploadMessage="" extractedResumeText="" resumes={[]} />);
  await screen.findByRole('heading', { name: 'Your profile bank.' });
  return user;
}

describe('Profile bank', () => {
  it('shows the profile it had last time at once while it asks the server again', async () => {
    await setup();
    cleanup();
    let release!: (value: ProfileBank) => void;
    mockApi.getBank.mockReturnValue(new Promise<ProfileBank>((resolve) => { release = resolve; }));      // the second visit's answer is still on its way
    render(<ProfileView {...callbacks} userKey="alice" preferences={{ roles: [], locations: ['Singapore'], work_modes: [] }} savingPreferences={false} uploading={false} uploadMessage="" extractedResumeText="" resumes={[]} />);
    expect(screen.getByRole('heading', { name: 'Your profile bank.' })).toBeInTheDocument();           // no spinner first
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
    expect(mockApi.getBank).toHaveBeenCalledTimes(2);
    release({ ...copy(bank), items: [{ ...experience(), data: { ...experience().data, title: 'Staff Engineer' } }] });
    expect(await screen.findByText('Staff Engineer')).toBeInTheDocument();
  });

  it('does not show one person the last profile of another', async () => {
    await setup();
    cleanup();
    mockApi.getBank.mockReturnValue(new Promise(() => undefined));
    render(<ProfileView {...callbacks} userKey="casey" preferences={{ roles: [], locations: [], work_modes: [] }} savingPreferences={false} uploading={false} uploadMessage="" extractedResumeText="" resumes={[]} />);
    expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument();
  });

  it('loads canonical seniority options and keeps target roles free-text', async () => {
    const user = await setup();
    expect(await screen.findByRole('option', {name:'Junior / Entry-level'})).toHaveValue('junior');
    expect(screen.getByRole('option', {name:'Executive'})).toHaveValue('executive');
    await user.selectOptions(screen.getByLabelText('Seniority'), 'junior');
    expect(callbacks.setPreferences).toHaveBeenCalledWith(expect.objectContaining({seniority:'junior'}));
    expect(screen.getByText('Roles or job titles')).toBeInTheDocument();
  });

  it('disables seniority selection and offers retry when options fail', async () => {
    mockApi.getSeniorityOptions.mockRejectedValueOnce(new Error('offline'));
    const user = await setup();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load seniority levels');
    expect(screen.getByLabelText('Seniority')).toBeDisabled();
    await user.click(screen.getByRole('button', {name:'Retry'}));
    expect(await screen.findByRole('option', {name:'Junior / Entry-level'})).toHaveValue('junior');
    expect(screen.getByLabelText('Seniority')).toBeEnabled();
  });
  it('shows the five latest resume sources and expands on request', async () => {
    mockApi.uploads.mockResolvedValue({ items: Array.from({ length: 7 }, (_, index) => ({ upload_id: `upload-${index}`, filename: `fictional-${index}.pdf`, status: 'ready_for_review' })), next_cursor: null } as never);
    const user = userEvent.setup();
    render(<ProfileView {...callbacks} userKey="alice" preferences={{ roles: [], locations: [], work_modes: [] }} savingPreferences={false} uploading={false} uploadMessage="" extractedResumeText="" resumes={[]} />);
    await screen.findByText('fictional-0.pdf');
    expect(screen.queryByText('fictional-5.pdf')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Import (coming soon)' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show all 7' }));
    expect(screen.getByText('fictional-6.pdf')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show fewer' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('offers PDF and Word (.docx) resume files only', async () => {
    await setup();
    const input = screen.getByLabelText('Upload resume file');
    expect(input).toHaveAttribute('accept', '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    expect(screen.getByText(/PDF or Word \(\.docx\) · up to 10 MiB/)).toBeInTheDocument();
    expect(screen.getByText('Choose file')).toBeInTheDocument();
  });

  it('saves only basics and requires an explicit save before matching confirmation', async () => {
    const user = await setup();
    await user.click(screen.getByRole('button', { name: 'Edit personal details' }));
    await user.clear(screen.getByLabelText('Full name'));
    await user.type(screen.getByLabelText('Full name'), 'Fictional Jordan');
    expect(screen.getByRole('button', { name: 'Update my matches' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(mockApi.putProfile).toHaveBeenCalledTimes(1));
    expect(mockApi.putProfile).toHaveBeenCalledWith({ name: 'Fictional Jordan', headline: 'Backend engineer', email: 'alex@example.invalid', phone: '', location: 'Singapore', summary: 'Build reliable services.', links: ['https://example.invalid'] }, 4);
    expect(await screen.findByText('Profile saved.')).toBeInTheDocument();
    expect(callbacks.onBasicsSaved).toHaveBeenCalled();
  });

  it('confirms the current bank revision rather than the basics revision', async () => {
    const user = await setup();
    await user.click(screen.getByRole('button', { name: 'Update my matches' }));
    await waitFor(() => expect(mockApi.confirmProfile).toHaveBeenCalledWith(9));
    expect(await screen.findByText('Matching profile up to date')).toBeInTheDocument();
  });

  it('adds and explicitly edits an item using its expected revision', async () => {
    const user = await setup();
    await user.click(screen.getByRole('button', { name: 'Add project' }));
    await user.type(screen.getByLabelText('Project name'), 'Synthetic pipeline');
    await user.click(screen.getByRole('button', { name: 'Save project' }));
    expect(await screen.findByRole('article', { name: 'Synthetic pipeline' })).toBeInTheDocument();
    expect(mockApi.createItem).toHaveBeenCalledWith(expect.objectContaining({ kind: 'project', data: expect.objectContaining({ name: 'Synthetic pipeline' }) }));
    await user.click(within(screen.getByRole('article', { name: 'Backend Engineer' })).getByRole('button', { name: 'Edit experience' }));
    await user.clear(screen.getByLabelText('Role'));
    await user.type(screen.getByLabelText('Role'), 'Senior Backend Engineer');
    expect(mockApi.patchItem).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Save experience' }));
    await waitFor(() => expect(mockApi.patchItem).toHaveBeenCalledWith('exp-1', expect.objectContaining({ expected_revision: 3, data: expect.objectContaining({ title: 'Senior Backend Engineer' }) })));
    expect(await screen.findByRole('article', { name: 'Senior Backend Engineer' })).toBeInTheDocument();
  });

  it('adds a typed point and edits its wording with revision checks', async () => {
    const user = await setup();
    await user.click(within(screen.getByRole('article', { name: 'Backend Engineer' })).getByRole('button', { name: 'Add point' }));
    await user.type(screen.getByLabelText('Point wording'), 'Built synthetic reports');
    await user.type(screen.getByLabelText('Point types (comma separated)'), 'data, leadership');
    await user.click(screen.getByRole('button', { name: 'Save point' }));
    expect(await screen.findByText('Built synthetic reports')).toBeInTheDocument();
    expect(mockApi.addPoint).toHaveBeenCalledWith('exp-1', { expected_revision: 3, text: 'Built synthetic reports', tags: ['data', 'leadership'] });
    await user.click(screen.getAllByRole('button', { name: 'Edit point' })[0]);
    await user.clear(screen.getByLabelText('Point wording'));
    await user.type(screen.getByLabelText('Point wording'), 'Built tested APIs');
    await user.click(screen.getByRole('button', { name: 'Save point' }));
    await waitFor(() => expect(mockApi.updatePoint).toHaveBeenCalledWith('exp-1', 'point-1', { expected_revision: 4, text: 'Built tested APIs' }));
    expect(await screen.findByText('Built tested APIs')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });

  it('lists versions, adds a version and makes the selected wording main', async () => {
    const user = await setup();
    await user.click(screen.getByRole('button', { name: '2 versions' }));
    expect(screen.getByText('Version 2: Improved service reliability')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add version' }));
    await user.type(screen.getByLabelText('Version wording'), 'Supported dependable services');
    await user.click(screen.getByRole('button', { name: 'Save version' }));
    await waitFor(() => expect(mockApi.addAlternative).toHaveBeenCalledWith('exp-1', 'point-1', { expected_revision: 3, text: 'Supported dependable services', tags: [] }));
    await user.click(await screen.findByRole('button', { name: '3 versions' }));
    expect(screen.getByText('Version 3: Supported dependable services')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Make main' })[0]);
    await waitFor(() => expect(mockApi.updatePoint).toHaveBeenCalledWith('exp-1', 'point-1', { expected_revision: 4, text: 'Improved service reliability', alternative_id: 'version-1', make_main: true }));
  });

  it('reloads a conflicting item and discards the stale edit without overwriting', async () => {
    const user = await setup();
    mockApi.patchItem.mockImplementationOnce(async () => { bank.items[0] = { ...experience(), revision: 8, data: { ...experience().data, title: 'Updated elsewhere' } }; throw new HttpError('Revision conflict', 409, 'REVISION_CONFLICT'); });
    await user.click(screen.getByRole('button', { name: 'Edit experience' }));
    await user.clear(screen.getByLabelText('Role'));
    await user.type(screen.getByLabelText('Role'), 'Stale local wording');
    await user.click(screen.getByRole('button', { name: 'Save experience' }));
    expect(await screen.findByText('This changed elsewhere, reloaded')).toBeInTheDocument();
    expect(mockApi.getBank).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole('article', { name: 'Updated elsewhere' })).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Stale local wording')).not.toBeInTheDocument();
    expect(mockApi.patchItem).toHaveBeenCalledTimes(1);
  });

  it('archives an item and restores it through revision-checked undo', async () => {
    const user = await setup();
    const previous = copy(experience());
    await user.click(screen.getByRole('button', { name: 'Archive Backend Engineer' }));
    expect(await screen.findByText('Item archived.')).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Backend Engineer' })).not.toBeInTheDocument();
    expect(mockApi.archiveItem).toHaveBeenCalledWith('exp-1', 3);
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(mockApi.revertItem).toHaveBeenCalledWith('exp-1', { expected_revision: 4, data: previous.data, tags: previous.tags, parent_id: null }));
    expect(await screen.findByRole('article', { name: 'Backend Engineer' })).toBeInTheDocument();
  });

  it('requires the exact typed deletion confirmation and includes the settings choice', async () => {
    const user = await setup();
    await user.click(screen.getByRole('button', { name: 'Delete my profile data' }));
    const dialog = screen.getByRole('dialog', { name: 'Delete my profile data?' });
    const submit = within(dialog).getByRole('button', { name: 'Delete profile data' });
    expect(submit).toBeDisabled();
    expect(within(dialog).getByText(/Resume Studio documents, their exports, applications/)).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText('Type DELETE to confirm'), 'delete');
    expect(submit).toBeDisabled();
    expect(mockApi.deleteProfile).not.toHaveBeenCalled();
    await user.clear(within(dialog).getByLabelText('Type DELETE to confirm'));
    await user.type(within(dialog).getByLabelText('Type DELETE to confirm'), 'DELETE');
    await user.click(within(dialog).getByLabelText('Also delete my resume style defaults'));
    await user.click(submit);
    await waitFor(() => expect(mockApi.deleteProfile).toHaveBeenCalledWith({ confirmation: 'DELETE', delete_settings: true }));
    expect(await screen.findByText(/Profile data deleted/)).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows a duplicate skill error inline and retains the entered name', async () => {
    const user = await setup();
    mockApi.createItem.mockRejectedValueOnce(new HttpError('This skill already exists in the profile', 422, 'DUPLICATE_SKILL'));
    await user.click(screen.getByRole('button', { name: 'Add skill' }));
    await user.type(screen.getByLabelText('Skill name'), 'Python');
    await user.click(screen.getByRole('button', { name: 'Save skill' }));
    await waitFor(() => expect(screen.getAllByRole('alert').some(element => element.textContent?.includes('This skill already exists'))).toBe(true));
    expect(screen.getByLabelText('Skill name')).toHaveValue('Python');
    expect(mockApi.createItem).toHaveBeenCalledWith(expect.objectContaining({ kind: 'skill', data: expect.objectContaining({ name: 'Python' }) }));
  });

  it('explains the five-version limit without dropping any saved wording', async () => {
    const user = await setup();
    mockApi.addAlternative.mockRejectedValueOnce(new HttpError('A point allows 5 versions', 422, 'POINT_VERSION_LIMIT'));
    await user.click(screen.getByRole('button', { name: '2 versions' }));
    await user.click(screen.getByRole('button', { name: 'Add version' }));
    await user.type(screen.getByLabelText('Version wording'), 'Overflow wording');
    await user.click(screen.getByRole('button', { name: 'Save version' }));
    await waitFor(() => expect(screen.getAllByRole('alert').some(element => element.textContent === 'A point keeps up to 5 versions')).toBe(true));
    expect(screen.getByLabelText('Version wording')).toHaveValue('Overflow wording');
    expect(bank.items[0].data.bullets[0].alternatives).toHaveLength(1);
  });

  it('reloads a conflicting basics save and clears the dirty matching lock', async () => {
    const user = await setup();
    mockApi.putProfile.mockImplementationOnce(async () => {
      profile = { ...profile, revision: 8, draft: { ...profile.draft, name: 'Latest remote candidate' } };
      bank.basics = profile.draft;
      throw new HttpError('Revision conflict', 409, 'REVISION_CONFLICT');
    });
    await user.click(screen.getByRole('button', { name: 'Edit personal details' }));
    await user.clear(screen.getByLabelText('Full name'));
    await user.type(screen.getByLabelText('Full name'), 'Stale local candidate');
    expect(screen.getByRole('button', { name: 'Update my matches' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByText('This changed elsewhere, reloaded')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Latest remote candidate' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update my matches' })).toBeEnabled();
    expect(screen.queryByDisplayValue('Stale local candidate')).not.toBeInTheDocument();
    expect(mockApi.putProfile).toHaveBeenCalledTimes(1);
  });

  it('reloads a conflicting skill editor with the newer revision and name', async () => {
    bank.items.push({ ...experience(), id: 'skill-1', kind: 'skill', position: 0, revision: 2, data: { name: 'Python', category: 'language', bullets: [] } });
    const user = await setup();
    mockApi.patchItem.mockImplementationOnce(async () => {
      bank.items = bank.items.map(item => item.id === 'skill-1' ? { ...item, revision: 5, data: { ...item.data, name: 'Python 3' } } : item);
      throw new HttpError('Revision conflict', 409, 'REVISION_CONFLICT');
    });
    await user.click(screen.getByRole('button', { name: 'Rename Python' }));
    await user.clear(screen.getByLabelText('Skill name'));
    await user.type(screen.getByLabelText('Skill name'), 'Stale skill name');
    await user.click(screen.getByRole('button', { name: 'Save skill' }));
    expect(await screen.findByText('This changed elsewhere, reloaded')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Skill name')).toHaveValue('Python 3'));
    expect(screen.queryByDisplayValue('Stale skill name')).not.toBeInTheDocument();
    expect(mockApi.patchItem).toHaveBeenCalledWith('skill-1', expect.objectContaining({ expected_revision: 2 }));
    expect(mockApi.patchItem).toHaveBeenCalledTimes(1);
  });



  const withUpload = () => mockApi.uploads.mockResolvedValue({ items: [{ upload_id: 'upload-1', filename: 'fictional.pdf', status: 'ready_for_review', page_count: 1 }], next_cursor: null });

  it('imports an upload, reviews it, applies with the profile epoch and reloads the bank', async () => {
    withUpload();
    bank.profile_epoch = 2;
    mockApi.startImport.mockResolvedValue(importRecord());
    mockApi.applyImport.mockImplementation(async () => { bank.bank_revision += 1; return { import_id: 'imp-1', bank_revision: bank.bank_revision, counts: { added: 3, merged: 1, skipped: 2, basics_updated: 0 }, conflicts: [{ candidate_id: 'c1', fields: {} }] }; });
    const user = await setup();
    await user.click(await screen.findByRole('button', { name: 'Import fictional.pdf into profile' }));
    expect(mockApi.startImport).toHaveBeenCalledWith({ upload_id: 'upload-1' });
    expect(await screen.findByRole('heading', { name: 'Review what we found' })).toBeInTheDocument();
    expect(mockApi.applyImport).not.toHaveBeenCalled();
    const loads = mockApi.getBank.mock.calls.length;
    await user.click(screen.getByRole('button', { name: /Apply to profile/ }));
    expect(mockApi.applyImport).toHaveBeenCalledWith('imp-1', [expect.objectContaining({ candidate_id: 'c1', action: 'add' })], 2);
    expect(await screen.findByText(/Added 3, merged 1, skipped 2/)).toHaveTextContent('1 conflict was');
    expect(screen.getByRole('heading', { name: 'Your profile bank.' })).toBeInTheDocument();
    expect(mockApi.getBank.mock.calls.length).toBeGreaterThan(loads);
  });

  it('imports a Studio resume by document id', async () => {
    mockApi.startImport.mockResolvedValue(importRecord({ source_type: 'document' }));
    const user = userEvent.setup();
    render(<ProfileView {...callbacks} userKey="alice" preferences={{ roles: [], locations: [], work_modes: [] }} savingPreferences={false} uploading={false} uploadMessage="" extractedResumeText="" resumes={[{ id: 'doc-1', title: 'Fictional CV', revision: 2 } as never]} />);
    await user.click(await screen.findByRole('button', { name: 'Import Fictional CV into profile' }));
    expect(mockApi.startImport).toHaveBeenCalledWith({ document_id: 'doc-1' });
  });

  it('starts an import from pasted text', async () => {
    mockApi.startImport.mockResolvedValue(importRecord({ source_type: 'text' }));
    const user = await setup();
    await user.click(screen.getByRole('button', { name: 'Paste text' }));
    expect(screen.getByRole('button', { name: 'Start import' })).toBeDisabled();
    await user.click(screen.getByLabelText('Resume text'));
    await user.paste('Fictional Alex\nBackend Engineer');
    await user.click(screen.getByRole('button', { name: 'Start import' }));
    expect(mockApi.startImport).toHaveBeenCalledWith({ text: 'Fictional Alex\nBackend Engineer' });
    expect(await screen.findByRole('heading', { name: 'Review what we found' })).toBeInTheDocument();
  });

  it('imports a JSON Resume file and rejects invalid JSON without calling the API', async () => {
    mockApi.startImport.mockResolvedValue(importRecord({ source_type: 'json_resume' }));
    const user = await setup();
    await user.click(screen.getByText('Profile backups'));
    const input = screen.getByLabelText('Restore profile from JSON backup');
    await user.upload(input, new File(['{not json'], 'broken.json', { type: 'application/json' }));
    expect(await screen.findByText(/not valid JSON/)).toBeInTheDocument();
    expect(mockApi.startImport).not.toHaveBeenCalled();
    await user.upload(input, new File(['{"basics":{"name":"Fictional Alex"}}'], 'resume.json', { type: 'application/json' }));
    await waitFor(() => expect(mockApi.startImport).toHaveBeenCalledWith({ json_resume: { basics: { name: 'Fictional Alex' } } }));
  });

  it('shows a failed import with Retry and Discard', async () => {
    withUpload();
    mockApi.startImport.mockResolvedValue(importRecord({ status: 'failed', error_code: 'UNREADABLE', candidates: [], result: { message: 'We could not read any text in this PDF.' } }));
    mockApi.retryImport.mockResolvedValue(importRecord({ id: 'imp-2' }));
    mockApi.discardImport.mockResolvedValue(importRecord({ status: 'discarded' }));
    const user = await setup();
    await user.click(await screen.findByRole('button', { name: 'Import fictional.pdf into profile' }));
    expect(await screen.findByText('We could not read any text in this PDF.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(mockApi.retryImport).toHaveBeenCalledWith('imp-1');
    expect(await screen.findByRole('heading', { name: 'Review what we found' })).toBeInTheDocument();
  });

  it('lists recent imports with Review and Retry actions', async () => {
    mockApi.imports.mockResolvedValue({ items: [importRecord({ id: 'ready-1' }), importRecord({ id: 'failed-1', status: 'failed', candidates: [] })], next_cursor: null });
    mockApi.getImport.mockResolvedValue(importRecord({ id: 'ready-1' }));
    const user = await setup();
    expect(await screen.findByRole('heading', { name: 'Recent imports' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Review PDF upload import/ }));
    expect(mockApi.getImport).toHaveBeenCalledWith('ready-1');
    expect(await screen.findByRole('heading', { name: 'Review what we found' })).toBeInTheDocument();
  });

});


it('prevents importing a source whose file upload did not finish', async () => {
  mockApi.uploads.mockResolvedValue({items: [{upload_id: 'incomplete', filename: 'incomplete.pdf', status: 'uploaded', page_count: null}], next_cursor: null});
  await setup();
  expect(await screen.findByText('Upload incomplete — choose the file again')).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Import incomplete.pdf into profile'})).toBeDisabled();
});


it('shows profile content while resume sources are still loading', async () => {
  let finish!: (value: {items: never[]; next_cursor: null}) => void;
  mockApi.uploads.mockImplementationOnce(() => new Promise(done => { finish = done; }));
  await setup();
  expect(await screen.findByRole('heading', {name: 'Your profile bank.'})).toBeInTheDocument();
  expect(screen.getByText('Loading your resumes…')).toBeInTheDocument();
  finish({items: [], next_cursor: null});
  await waitFor(() => expect(screen.queryByText('Loading your resumes…')).not.toBeInTheDocument());
});

it('uploads a PDF from the main import action and opens review once', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.uploadResume>>) => void;
  mockApi.uploadResume.mockImplementationOnce(() => new Promise(done => { finish = done; }));
  mockApi.startImport.mockResolvedValue(importRecord());
  const user = await setup();
  const input = screen.getByLabelText('Import resume from PDF or Word file');
  await user.upload(input, new File(['%PDF'], 'resume.pdf', {type: 'application/pdf'}));
  expect(input).toBeDisabled();
  expect(screen.getByText('Importing…')).toBeInTheDocument();
  expect(mockApi.startImport).not.toHaveBeenCalled();
  finish({upload_id: 'new-upload', filename: 'resume.pdf', status: 'ready_for_review', page_count: 1, extracted_text: 'Synthetic Applicant', error_code: null, message: 'Ready', ai_available: false});
  expect(await screen.findByRole('heading', {name: 'Review what we found'})).toBeInTheDocument();
  expect(mockApi.startImport).toHaveBeenCalledExactlyOnceWith({upload_id: 'new-upload'});
});
