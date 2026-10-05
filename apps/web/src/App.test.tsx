import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { api, HttpError } from './api';

vi.mock('./api', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api')>();
  return { ...original, api: {
    me: vi.fn(), getProfile: vi.fn(), getPreferences: vi.fn(), recommendations: vi.fn(), applications: vi.fn(), documents: vi.fn(),
    uploadResume: vi.fn(), reviewJob: vi.fn(), putProfile: vi.fn(), confirmProfile: vi.fn(), putPreferences: vi.fn(), putApplication: vi.fn(), createDocument: vi.fn(), patchDocument: vi.fn(),
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

  it('opens the complete source job description with source provenance', async () => {
    const user = userEvent.setup();
    const description = 'About the team\nResponsibilities\n- Design workflows\nQualifications\n- Portfolio required';
    mockApi.recommendations.mockResolvedValue({ items: [{ job: { id: 'role-detail', title: 'Product Designer', company: 'Northstar', location: 'Singapore', source_board: 'Greenhouse', source_url: 'https://jobs.example/full', description }, reasons: [] }], total: 1, next_offset: null, degraded_mode: false });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(screen.getByRole('button', { name: 'Read full description' }));
    const dialog = screen.getByRole('dialog', { name: 'Product Designer' });
    expect(dialog.querySelector('.job-detail-description')?.textContent).toBe(description);
    expect(within(dialog).getByText('Source: Greenhouse')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: /original listing/i })).toHaveAttribute('href', 'https://jobs.example/full');
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

  it('shows the saved profile without a sample chooser and refreshes recommendations after save', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    expect(screen.queryByText('Try a sample profile')).not.toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText('e.g. Alex Tan'));
    await user.type(screen.getByPlaceholderText('e.g. Alex Tan'), 'Alex Tan');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(mockApi.putProfile).toHaveBeenCalledWith(expect.objectContaining({ name: 'Alex Tan' }), 0));
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenCalledTimes(2));
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
    expect(screen.getByRole('button', { name: /download pdf/i })).toBeDisabled();
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

  it('saves a reviewed resume snapshot and manual cover letter without sending an application', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-1', job_id: 'role-1', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-1', title: 'Product Designer', company: 'Northstar', location: 'Singapore', source_url: 'https://jobs.example/role-1' } };
    const reviewed = { id: 'resume-ready', title: 'Product design resume', kind: 'resume' as const, revision: 3, template: 'classic' as const, content: { name: 'Alice Tan', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 3 };
    mockApi.applications.mockResolvedValue({ items: [application] }); mockApi.documents.mockResolvedValue({ items: [reviewed] });
    mockApi.putApplication.mockResolvedValue({ ...application, revision: 2, resume_packet: { export_id: 'export-1', document_id: reviewed.id, title: reviewed.title, revision: 3, download_url: '/v1/exports/export-1' }, cover_letter_text: 'Hello Northstar' });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: Product Designer' })[0]);
    expect(screen.getByRole('link', { name: /original job posting/i })).toHaveAttribute('href', 'https://jobs.example/role-1');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Attach reviewed resume' }), reviewed.id);
    await user.type(screen.getByLabelText(/Cover letter \(written by you\)/), 'Hello Northstar');
    await user.click(screen.getByRole('button', { name: 'Save application record' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-1', expect.objectContaining({ expected_revision: 1, resume_document_id: reviewed.id, expected_resume_revision: 3, cover_letter_text: 'Hello Northstar' })));
    expect(await screen.findByText(/stored locally; it has not been sent/i)).toBeInTheDocument();
  });

  it('preserves existing packet attachments when application details are edited without packet changes', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-2', job_id: 'role-2', status: 'saved', notes: '', applied_at: null, revision: 4, resume_packet: { export_id: 'export-keep', document_id: 'resume-keep', title: 'Existing resume', revision: 2, download_url: '/v1/exports/export-keep' }, cover_letter_text: 'Previously saved letter', job: { id: 'role-2', title: 'Data Analyst', company: 'Cedar', location: null } };
    mockApi.applications.mockResolvedValue({ items: [application] });
    mockApi.putApplication.mockResolvedValue({ ...application, status: 'preparing', revision: 5 });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: Data Analyst' })[0]);
    expect(screen.getByText('Reviewed revision 2 · PDF snapshot')).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'preparing');
    await user.click(screen.getByRole('button', { name: 'Save application record' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalled());
    const payload = mockApi.putApplication.mock.calls[0][1];
    expect(payload).toMatchObject({ expected_revision: 4, status: 'preparing' });
    expect(payload).not.toHaveProperty('resume_document_id'); expect(payload).not.toHaveProperty('resume_export_id'); expect(payload).not.toHaveProperty('cover_letter_text');
  });

  it('prepares a separate job-specific copy and attaches it only after review', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null } };
    const original = { id: 'resume-base', title: 'My resume', kind: 'resume' as const, revision: 2, template: 'modern' as const, content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 2 };
    const copy = { ...original, id: 'resume-role', job_id: 'role-3', title: 'My resume — UX Designer', revision: 1, reviewed_revision: null };
    mockApi.applications.mockResolvedValue({ items: [application] }); mockApi.documents.mockResolvedValue({ items: [original] });
    mockApi.duplicateDocument.mockResolvedValue(copy); mockApi.reviewDocument.mockResolvedValue({ ...copy, reviewed_revision: 1 });
    mockApi.putApplication.mockResolvedValue({ ...application, revision: 2, resume_packet: { export_id: 'export-role', document_id: copy.id, title: copy.title, revision: 1, download_url: '/v1/exports/export-role' } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a resume to tailor' }), original.id);
    await user.click(screen.getByRole('button', { name: 'Create tailored copy' }));
    await waitFor(() => expect(mockApi.duplicateDocument).toHaveBeenCalledWith(original.id, 'My resume — UX Designer', 'role-3'));
    await user.click(await screen.findByRole('button', { name: 'Mark as reviewed' }));
    await user.click(await screen.findByRole('button', { name: 'Attach reviewed revision' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-3', { resume_document_id: copy.id, expected_resume_revision: 1, expected_revision: 1 }));
    expect(await screen.findByRole('dialog', { name: 'UX Designer' })).toBeInTheDocument();
  });
  it('reopens the selected application resume and returns to that application, even with identical job titles', async () => {
    const user = userEvent.setup();
    const resume = { id: 'linked-resume', job_id: 'job-b', title: 'Resume for company B', kind: 'resume' as const, revision: 1, template: 'modern' as const, content: { name: 'Alex', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 1 };
    const applications = ['a', 'b'].map((suffix) => ({ id: 'app-' + suffix, job_id: 'job-' + suffix, status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'job-' + suffix, title: 'Engineer', location: null, company: 'Company ' + suffix }, resume_packet: suffix === 'b' ? { document_id: resume.id, export_id: 'export-b', title: resume.title, revision: 1, download_url: '/v1/exports/export-b' } : null }));
    mockApi.applications.mockResolvedValue({ items: applications });
    mockApi.documents.mockResolvedValue({ items: [resume] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation')).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: Engineer' })[1]);
    expect(within(screen.getByRole('dialog')).getByText('Company b')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toHaveValue(resume.title);
    expect(mockApi.duplicateDocument).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Return to tracker' }));
    expect(within(await screen.findByRole('dialog')).getByText('Company b')).toBeInTheDocument();
  });

});
