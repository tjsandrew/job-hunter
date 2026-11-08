import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { api, HttpError } from '../api';
import { resume } from './build/testData';

vi.mock('../api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map((key) => [key, vi.fn()])) };
});
const mockApi = vi.mocked(api);
const first = resume({ id: 'r1', title: 'Backend Engineer – Stripe' }), second = resume({ id: 'r2', title: 'Data resume' });

beforeEach(() => {
  vi.resetAllMocks();
  mockApi.fitSummaries.mockResolvedValue({ items: [] });
  mockApi.me.mockResolvedValue({ user_id: '1', display_name: 'Alice Tan', plan: 'free', allowance: { limit: 5, used: 0, remaining: 5, period: '2026-10' }, ai_available: false });
  mockApi.getProfile.mockResolvedValue({ draft: { name: 'Alice Tan', email: '', phone: '', location: '', summary: 'Backend engineer who likes data.', skills: [] }, revision: 0, confirmed_revision: null });
  mockApi.getBank.mockResolvedValue({ basics: {}, items: [], grouped: { experience: [], education: [], project: [], skill: [], certification: [], award: [], volunteering: [], custom: [] }, bank_revision: 1, confirmed_revision: null, profile_epoch: 0 });
  mockApi.getPreferences.mockResolvedValue({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: null, salary_currency: 'SGD', salary_period: 'year', revision: 0 });
  mockApi.recommendations.mockResolvedValue({ items: [], total: 0, next_offset: null, degraded_mode: true });
  mockApi.applications.mockResolvedValue({ items: [] });
  mockApi.documents.mockResolvedValue({ items: [first, second] });
  mockApi.archiveDocument.mockResolvedValue(undefined);
  mockApi.restoreDocument.mockImplementation(async (id) => id === 'r1' ? first : second);
});
afterEach(() => cleanup());
const goToStudio = async (user: ReturnType<typeof userEvent.setup>) => user.click(within(await screen.findByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'My documents' }));
const titles = () => [...document.querySelectorAll('.resume-card-foot strong')].map((node) => node.textContent);

describe('deleting a resume', () => {
  it('asks first, archives on confirm, and offers Undo that restores it in place', async () => {
    const user = userEvent.setup(); render(<App />); await goToStudio(user);
    await user.click(await screen.findByRole('button', { name: 'Delete Backend Engineer – Stripe' }));
    const dialog = screen.getByRole('alertdialog', { name: /Delete "Backend Engineer – Stripe"\?/ });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(mockApi.archiveDocument).not.toHaveBeenCalled();
    expect(titles()).toEqual(['Backend Engineer – Stripe', 'Data resume']);

    await user.click(screen.getByRole('button', { name: 'Delete Backend Engineer – Stripe' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete resume' }));
    await waitFor(() => expect(mockApi.archiveDocument).toHaveBeenCalledWith('r1'));
    await waitFor(() => expect(titles()).toEqual(['Data resume']));
    expect(screen.getByRole('status')).toHaveTextContent('"Backend Engineer – Stripe" deleted.');

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(mockApi.restoreDocument).toHaveBeenCalledWith('r1'));
    await waitFor(() => expect(titles()).toEqual(['Backend Engineer – Stripe', 'Data resume']));
    expect(screen.getByRole('status')).toHaveTextContent('restored');
  });

  it('shows the server message when deleting fails and keeps the resume', async () => {
    mockApi.archiveDocument.mockRejectedValue(new HttpError('Resource not found', 404));
    const user = userEvent.setup(); render(<App />); await goToStudio(user);
    await user.click(await screen.findByRole('button', { name: 'Delete Data resume' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete resume' }));
    expect(await screen.findByText('Resource not found')).toBeInTheDocument();
    expect(titles()).toEqual(['Backend Engineer – Stripe', 'Data resume']);
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('returns to the library when the open resume is deleted', async () => {
    const user = userEvent.setup(); render(<App />); await goToStudio(user);
    await user.click(await screen.findByRole('button', { name: 'Open Backend Engineer – Stripe' }));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Delete resume' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete resume' }));
    await waitFor(() => expect(mockApi.archiveDocument).toHaveBeenCalledWith('r1'));
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Resume title' })).toBeNull());
    expect(titles()).toEqual(['Data resume']);
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(titles()).toEqual(['Backend Engineer – Stripe', 'Data resume']));
  });
});

describe('Use profile summary', () => {
  const openFirst = async (user: ReturnType<typeof userEvent.setup>) => {
    await goToStudio(user);
    await user.click(await screen.findByRole('button', { name: 'Open Backend Engineer – Stripe' }));
    return screen.findByRole('textbox', { name: 'Professional summary' });
  };

  it('fills the summary from the profile as an undoable edit', async () => {
    const user = userEvent.setup(); render(<App />);
    const summary = await openFirst(user);
    expect(summary).toHaveValue('Backend engineer.');
    const button = screen.getByRole('button', { name: 'Use profile summary' });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(summary).toHaveValue('Backend engineer who likes data.');
    expect(screen.getAllByText('Unsaved').length).toBeGreaterThan(0);      // goes through the normal autosave path
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(summary).toHaveValue('Backend engineer.');
  });

  it('is disabled with a tooltip when the profile has no summary', async () => {
    mockApi.getProfile.mockResolvedValue({ draft: { name: 'Alice Tan', summary: '  ', skills: [] }, revision: 0, confirmed_revision: null });
    const user = userEvent.setup(); render(<App />);
    await openFirst(user);
    expect(screen.getByRole('button', { name: 'Use profile summary' })).toBeDisabled();
    expect(screen.getByTitle(/no summary/i)).toBeInTheDocument();
  });

  it('stays disabled when the profile cannot be read', async () => {
    mockApi.getProfile.mockResolvedValueOnce({ draft: { name: 'Alice Tan', summary: 'x', skills: [] }, revision: 0, confirmed_revision: null }).mockRejectedValue(new HttpError('down', 500));
    const user = userEvent.setup(); render(<App />);
    await openFirst(user);
    expect(screen.getByRole('button', { name: 'Use profile summary' })).toBeDisabled();
  });
});


it('My documents opens the saved library even when an editor was open', async () => {
  const user = userEvent.setup(); render(<App />); await goToStudio(user);
  await user.click(await screen.findByRole('button', {name: 'Open Backend Engineer – Stripe'}));
  expect(await screen.findByRole('textbox', {name: 'Resume title'})).toBeInTheDocument();
  await goToStudio(user);
  expect(await screen.findByRole('heading', {name: 'My documents'})).toBeInTheDocument();
  expect(titles()).toEqual(['Backend Engineer – Stripe', 'Data resume']);
});


it('separates original uploaded files from resumes created in the app', async () => {
  mockApi.uploads.mockResolvedValue({items: [{upload_id: 'upload-1', filename: 'original.pdf', status: 'ready_for_review', page_count: 1}], next_cursor: null});
  const user = userEvent.setup(); render(<App />); await goToStudio(user);
  const generated = await screen.findByRole('region', {name: 'Created on Job Hunter'});
  expect(within(generated).getByRole('button', {name: 'Open Backend Engineer – Stripe'})).toBeInTheDocument();
  expect(screen.queryByText('original.pdf')).not.toBeInTheDocument();
  // Uploaded originals are their own tab of My documents, at their own address.
  await user.click(screen.getByRole('tab', {name: /Uploaded files/}));
  expect(window.location.pathname).toBe('/resumes/uploads');
  const uploaded = await screen.findByRole('region', {name: 'Uploaded resumes'});
  expect(await within(uploaded).findByText('original.pdf')).toBeInTheDocument();
  expect(within(uploaded).getByRole('button', {name: 'Download uploaded original.pdf'})).toBeEnabled();
});

it('renames a resume from its card without opening it', async () => {
  mockApi.patchDocument.mockImplementation(async (_id, values) => ({ ...first, title: values.title!, revision: first.revision + 1 }));
  const user = userEvent.setup(); render(<App />); await goToStudio(user);
  await user.click(await screen.findByRole('button', { name: 'Rename Backend Engineer – Stripe' }));
  const input = screen.getByRole('textbox', { name: 'New name for Backend Engineer – Stripe' });
  await user.clear(input); await user.type(input, 'Stripe backend');
  await user.click(screen.getByRole('button', { name: 'Save name' }));
  expect(mockApi.patchDocument).toHaveBeenCalledWith('r1', { title: 'Stripe backend', expected_revision: first.revision });
  await waitFor(() => expect(titles()).toContain('Stripe backend'));
  expect(screen.queryByRole('textbox', { name: 'Resume title' })).not.toBeInTheDocument();   // still in the library
});
