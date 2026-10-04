import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { api, HttpError } from './api';

vi.mock('./api', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api')>();
  return { ...original, api: {
    me: vi.fn(), getProfile: vi.fn(), getPreferences: vi.fn(), recommendations: vi.fn(), applications: vi.fn(), documents: vi.fn(),
    uploadResume: vi.fn(), reviewJob: vi.fn(), putProfile: vi.fn(), confirmProfile: vi.fn(), putPreferences: vi.fn(), createDocument: vi.fn(), patchDocument: vi.fn(),
    duplicateDocument: vi.fn(), reviewDocument: vi.fn(), exportDocument: vi.fn(), previewDocument: vi.fn(), downloadExport: vi.fn(),
  } };
});
const mockApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.me.mockResolvedValue({ user_id: '1', display_name: 'Alice Tan', plan: 'free', allowance: { limit: 5, used: 0, remaining: 5, period: '2026-10' }, ai_available: false });
  mockApi.getProfile.mockResolvedValue({ draft: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', skills: [] }, revision: 0, confirmed_revision: null });
  mockApi.getPreferences.mockResolvedValue({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: null, salary_currency: 'SGD', salary_period: 'year', revision: 0 });
  mockApi.recommendations.mockResolvedValue({ items: [{ job: { id: 'role-1', title: 'Product Designer', company: 'Northstar', location: 'Singapore', description: 'Design clear tools for people.' }, score: 0.91, reasons: ['Product design experience'] }], total: 1, next_offset: null, degraded_mode: true });
  mockApi.applications.mockResolvedValue({ items: [] }); mockApi.documents.mockResolvedValue({ items: [] });
});
afterEach(() => cleanup());

describe('Job Hunter user journey', () => {
  it('loads real API-backed recommendations and sends the Save decision', async () => {
    const user = userEvent.setup(); render(<App />);
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    mockApi.recommendations.mockResolvedValue({ items: [], total: 0, next_offset: null, degraded_mode: true });
    await user.click(screen.getByRole('button', { name: /save job/i }));
    await waitFor(() => expect(mockApi.reviewJob).toHaveBeenCalledWith('role-1', 'saved'));
    expect(await screen.findByText('No roles found')).toBeInTheDocument();
  });

  it('searches the backend and loads later recommendation pages', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    mockApi.recommendations.mockResolvedValueOnce({ items: [{ job: { id: 'role-2', title: 'Data Engineer', company: 'Northstar', location: 'Singapore' }, reasons: [] }], total: 21, next_offset: 20, degraded_mode: true });
    const search = screen.getByRole('textbox', { name: 'Search jobs' });
    await user.type(search, 'engineer');
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenLastCalledWith('engineer', 0), { timeout: 1500 });
    expect(await screen.findByText('Data Engineer')).toBeInTheDocument();
    mockApi.recommendations.mockResolvedValueOnce({ items: [{ job: { id: 'role-3', title: 'Platform Engineer', company: 'Northstar', location: 'Singapore' }, reasons: [] }], total: 21, next_offset: null, degraded_mode: true });
    await user.click(screen.getByRole('button', { name: 'Load more roles' }));
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenLastCalledWith('engineer', 20));
    expect(await screen.findByText('Platform Engineer')).toBeInTheDocument();
  });

  it('shows extracted PDF text as a review candidate without changing profile facts', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    mockApi.uploadResume.mockResolvedValue({ upload_id: 'up-1', filename: 'resume.pdf', status: 'extracted', page_count: 1, error_code: null, message: 'Extracted text is a review candidate only.', ai_available: false, extracted_text: 'Jordan Tan\nProduct designer\nEmail: jordan@example.com' });
    const file = new File(['%PDF-1.4 sample'], 'resume.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload resume PDF'), file);
    expect(await screen.findByLabelText(/Extracted text candidate/)).toHaveValue('Jordan Tan\nProduct designer\nEmail: jordan@example.com');
    expect(screen.getByPlaceholderText('e.g. Alex Tan')).toHaveValue('Alice Tan');
  });

  it('provides a manual resume path and communicates AI unavailability', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Resume studio' }));
    expect(screen.getByText(/Your resume library is empty/)).toBeInTheDocument();
    mockApi.createDocument.mockResolvedValue({ id: 'resume-1', title: 'Untitled resume', kind: 'resume', revision: 1, template: 'classic', content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: null });
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    await waitFor(() => expect(mockApi.createDocument).toHaveBeenCalled());
    const request = mockApi.createDocument.mock.calls[0][0];
    expect(request.content).toMatchObject({ name: 'Alice Tan', email: 'alice@example.com' });
    expect(request.template).toBe('classic');
  });

  it('allows profile edits and requires explicit save before confirmation', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    const headline = screen.getByPlaceholderText('Product designer · 6 years experience');
    await user.type(headline, 'Product designer');
    expect(screen.getByText('Unsaved profile changes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /confirm profile/i })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(mockApi.putProfile).toHaveBeenCalled());
  });

  it('keeps local resume edits on a revision conflict and blocks account switching while dirty', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Resume studio' }));
    mockApi.createDocument.mockResolvedValue({ id: 'resume-2', title: 'Untitled resume', kind: 'resume', revision: 1, template: 'classic', content: { name: 'Alice Tan', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: null });
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    const summary = await screen.findByRole('textbox', { name: 'Professional summary' });
    await user.type(summary, 'My latest local draft');
    const userSelect = screen.getAllByRole('combobox', { name: 'Development user' })[0];
    await user.selectOptions(userSelect, 'bob');
    expect(userSelect).toHaveValue('alice');

    mockApi.patchDocument.mockRejectedValue(new HttpError('Revision conflict.', 409));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 760)); });
    await waitFor(() => expect(mockApi.patchDocument).toHaveBeenCalled());
    expect(screen.getByRole('textbox', { name: 'Professional summary' })).toHaveValue('My latest local draft');
    expect(screen.getAllByText('Conflict')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /export pdf/i })).toBeDisabled();
  });

  it('rebases typing made during a slow save and autosaves it against the accepted revision', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Resume studio' }));
    const baseResume = { id: 'resume-slow', title: 'Untitled resume', kind: 'resume' as const, revision: 1, template: 'classic' as const, content: { name: 'Alice Tan', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: null };
    mockApi.createDocument.mockResolvedValue(baseResume);
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    const summary = await screen.findByRole('textbox', { name: 'Professional summary' });
    await user.type(summary, 'First draft');

    let finishFirstSave!: (resume: typeof baseResume) => void;
    mockApi.patchDocument.mockImplementationOnce(() => new Promise((resolve) => { finishFirstSave = resolve; }));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 740)); });
    expect(mockApi.patchDocument).toHaveBeenCalledTimes(1);

    await user.clear(summary);
    await user.type(summary, 'Newer typing during save');
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 740)); });
    expect(mockApi.patchDocument).toHaveBeenCalledTimes(1);

    await act(async () => finishFirstSave({ ...baseResume, revision: 2, content: { ...baseResume.content, summary: 'First draft' } }));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 740)); });
    await waitFor(() => expect(mockApi.patchDocument).toHaveBeenCalledTimes(2));
    expect(mockApi.patchDocument.mock.calls[1][1]).toMatchObject({ expected_revision: 2, content: { summary: 'Newer typing during save' } });
    expect(screen.getByRole('textbox', { name: 'Professional summary' })).toHaveValue('Newer typing during save');
  });
});
