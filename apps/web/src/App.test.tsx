import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { api, HttpError } from './api';
import { clearLists } from './listCache';

vi.mock('./api', async (importOriginal) => {
  const original = await importOriginal<typeof import('./api')>();
  return { ...original, api: {
    getBank: vi.fn(), uploads: vi.fn(), imports: vi.fn(), me: vi.fn(), getProfile: vi.fn(), getPreferences: vi.fn(), getSeniorityOptions: vi.fn(), recommendations: vi.fn(), recommendationsForYou: vi.fn(), applications: vi.fn(), documents: vi.fn(),
    uploadResume: vi.fn(), reviewJob: vi.fn(), putProfile: vi.fn(), confirmProfile: vi.fn(), putPreferences: vi.fn(), putApplication: vi.fn(), createDocument: vi.fn(), patchDocument: vi.fn(),
    job: vi.fn(), startFit: vi.fn(), jobFit: vi.fn(), fit: vi.fn(), fitSummaries: vi.fn(), reviewedJobs: vi.fn(), letters: vi.fn(), createLetter: vi.fn(), getSettings: vi.fn(),
    duplicateDocument: vi.fn(), tailorDocument: vi.fn(), reviewDocument: vi.fn(), exportDocument: vi.fn(), previewDocument: vi.fn(), downloadExport: vi.fn(),
  } };
});
const mockApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  clearLists();   // the Discover lists are remembered in memory between renders; each test starts without them
  sessionStorage.clear();   // and the Discover filter choice for this session, so every test starts from the profile defaults
  history.replaceState(null, '', '/');   // every test starts at the root address
  mockApi.jobFit.mockRejectedValue(new HttpError('Not found', 404));
  mockApi.me.mockResolvedValue({ user_id: '1', display_name: 'Alice Tan', plan: 'free', allowance: { limit: 5, used: 0, remaining: 5, period: '2026-10' }, ai_available: false });
  mockApi.getProfile.mockResolvedValue({ draft: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', skills: [] }, revision: 0, confirmed_revision: null });
  mockApi.getBank.mockResolvedValue({ basics: { name: 'Alice Tan' }, items: [], grouped: { experience: [], education: [], project: [], skill: [], certification: [], award: [], volunteering: [], custom: [] }, bank_revision: 7, confirmed_revision: null, profile_epoch: 0 });
  mockApi.uploads.mockResolvedValue({ items: [], next_cursor: null });
  mockApi.imports.mockResolvedValue({ items: [], next_cursor: null });
  mockApi.putProfile.mockImplementation(async (draft) => ({ draft, revision: 1, bank_revision: 8, confirmed_revision: null }));
  mockApi.getPreferences.mockResolvedValue({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: null, salary_currency: 'SGD', salary_period: 'year', revision: 0 });
  mockApi.getSeniorityOptions.mockResolvedValue({items:[{value:'intern',label:'Intern'},{value:'junior',label:'Junior / Entry-level'},{value:'mid',label:'Mid-level'},{value:'senior',label:'Senior'},{value:'lead',label:'Lead'},{value:'executive',label:'Executive'}]});
  mockApi.recommendations.mockResolvedValue({ items: [{ job: { id: 'role-1', title: 'Product Designer', company: 'Northstar', location: 'Singapore', description: 'Design clear tools for people.' }, score: 0.91, reasons: ['Product design experience'] }], total: 1, next_offset: null, degraded_mode: true });
  mockApi.recommendationsForYou.mockRejectedValue(new Error('for you unavailable in this test'));   // default: exercise the fallback
  mockApi.applications.mockResolvedValue({ items: [] }); mockApi.documents.mockResolvedValue({ items: [] });
  mockApi.fitSummaries.mockResolvedValue({ items: [] });
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
    expect(within(dialog).getByRole('region', { name: 'Fit analysis' })).toBeInTheDocument();   // AI is off in this test, so the button is disabled
    expect(await within(dialog).findByRole('button', { name: 'Check my fit' })).toBeDisabled();
  });

  it('shows a posting once and names the other sites that list it', async () => {
    const user = userEvent.setup();
    const seen = [{ job_id: 'dup-1', source: 'mycareersfuture', source_board: 'sg', source_url: 'https://www.mycareersfuture.gov.sg/job/x' }, { job_id: 'dup-2', source: 'adzuna', source_board: 'sg', source_url: 'javascript:alert(1)' }];
    mockApi.recommendations.mockResolvedValue({ items: [{ job: { id: 'role-seen', title: 'Data Engineer', company: 'Stripe', location: 'Singapore', source: 'greenhouse', source_board: 'stripe', source_url: 'https://boards.greenhouse.io/stripe/jobs/1', description: 'Build pipelines.', also_seen_on: seen }, reasons: [] }], total: 1, next_offset: null, degraded_mode: false });
    render(<App />); await screen.findByText('Data Engineer');
    expect(screen.getByText('Also on MyCareersFuture, Adzuna')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Read full description' }));
    const dialog = screen.getByRole('dialog', { name: 'Data Engineer' });
    expect(within(dialog).getByText('Also listed on MyCareersFuture, Adzuna')).toBeInTheDocument();
    expect(within(dialog).getByText('Source: Greenhouse · stripe')).toBeInTheDocument();   // the site name, then the employer board
    expect(within(dialog).getByRole('link', { name: /Also on MyCareersFuture/ })).toHaveAttribute('href', 'https://www.mycareersfuture.gov.sg/job/x');
    expect(within(dialog).queryByRole('link', { name: /Also on Adzuna/ })).not.toBeInTheDocument();   // an unsafe link is never rendered
  });

  it('names the site a job came from, not the generic board code', async () => {
    const user = userEvent.setup();
    mockApi.recommendations.mockResolvedValue({ items: [{ job: { id: 'role-mcf', title: 'Data Platform Engineer', company: 'Acme', location: 'Singapore', source: 'mycareersfuture', source_board: 'sg', source_url: 'https://www.mycareersfuture.gov.sg/job/x', description: 'Build pipelines.' }, reasons: [] }], total: 1, next_offset: null, degraded_mode: false });
    render(<App />); await screen.findByText('Data Platform Engineer');
    expect(screen.getByText('MyCareersFuture')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Read full description' }));
    expect(within(screen.getByRole('dialog', { name: 'Data Platform Engineer' })).getByText('Source: MyCareersFuture')).toBeInTheDocument();
  });

  it('gives each page its own address, keeps it on refresh and follows the Back button', async () => {
    const user = userEvent.setup();
    history.replaceState(null, '', '/tracker');                       // opened (or refreshed) on the tracker
    const first = render(<App />);
    expect(await screen.findByText('Keep the momentum.')).toBeInTheDocument();
    expect(location.pathname).toBe('/tracker');
    expect(document.title).toBe('Application tracker · Job Hunter');
    await user.click(screen.getByRole('button', { name: 'Profile' }));
    expect(location.pathname).toBe('/profile');
    await user.click(screen.getByRole('button', { name: 'Discover' }));
    expect(location.pathname).toBe('/discover');
    history.back();                                                   // Back goes to the profile
    await waitFor(() => expect(location.pathname).toBe('/profile'));
    expect(screen.getByRole('button', { name: 'Profile' })).toHaveClass('active');
    first.unmount();
    render(<App />);                                                  // a refresh on /profile stays on the profile
    expect(await screen.findByRole('button', { name: 'Profile' })).toHaveClass('active');
    expect(location.pathname).toBe('/profile');
  });

  it('opens the list named in the address and tidies the root address', async () => {
    history.replaceState(null, '', '/discover/saved');
    render(<App />);
    await waitFor(() => expect(mockApi.reviewedJobs).toHaveBeenCalled());
    expect(location.pathname).toBe('/discover/saved');
    cleanup();
    history.replaceState(null, '', '/');
    render(<App />);
    await screen.findByText('Product Designer');
    expect(location.pathname).toBe('/discover');
  });

  it('gives an opened listing its own link, loads it from a pasted link, and closing it returns to the list', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Product Designer');
    await user.click(screen.getByRole('button', { name: 'Read full description' }));
    expect(location.pathname).toBe('/jobs/role-1');
    await user.click(screen.getByRole('button', { name: 'Close job details' }));
    await waitFor(() => expect(location.pathname).toBe('/discover'));    // closing steps back instead of stacking another entry
    cleanup();
    mockApi.job.mockResolvedValue({ id: 'role-9', title: 'Data Engineer', company: 'Acme', location: 'Singapore', description: 'Build pipelines.' });
    history.replaceState(null, '', '/jobs/role-9');                   // a pasted or refreshed listing link
    render(<App />);
    expect(await screen.findByRole('dialog', { name: 'Data Engineer' })).toBeInTheDocument();
    expect(mockApi.job).toHaveBeenCalledWith('role-9');
    expect(location.pathname).toBe('/jobs/role-9');
  });

  it('says so and falls back to the list when a listing link no longer exists', async () => {
    mockApi.job.mockRejectedValue(new HttpError('Not found', 404));
    history.replaceState(null, '', '/jobs/gone-1');
    render(<App />);
    expect(await screen.findByText('That job is no longer listed.')).toBeInTheDocument();
    await waitFor(() => expect(location.pathname).toBe('/discover'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('searches the backend and loads later recommendation pages', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    mockApi.recommendations.mockResolvedValueOnce({ items: [{ job: { id: 'role-2', title: 'Data Engineer', company: 'Northstar', location: 'Singapore' }, reasons: [] }], total: 21, next_offset: 20, degraded_mode: true });
    const search = screen.getByRole('textbox', { name: 'Search jobs' });
    await user.type(search, 'engineer');
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenLastCalledWith('engineer', 0, { posted_within: '14' }), { timeout: 1500 });
    expect(await screen.findByText('Data Engineer')).toBeInTheDocument();
    mockApi.recommendations.mockResolvedValueOnce({ items: [{ job: { id: 'role-3', title: 'Platform Engineer', company: 'Northstar', location: 'Singapore' }, reasons: [] }], total: 21, next_offset: null, degraded_mode: true });
    await user.click(screen.getByRole('button', { name: 'Load more roles' }));
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenLastCalledWith('engineer', 20, { posted_within: '14' }));
    expect(await screen.findByText('Platform Engineer')).toBeInTheDocument();
  });

  it('shows extracted PDF text as a review candidate without changing profile facts', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    mockApi.uploadResume.mockResolvedValue({ upload_id: 'up-1', filename: 'resume.pdf', status: 'extracted', page_count: 1, error_code: null, message: 'Extracted text is a review candidate only.', ai_available: false, extracted_text: 'Jordan Tan\nProduct designer\nEmail: jordan@example.com' });
    const file = new File(['%PDF-1.4 sample'], 'resume.pdf', { type: 'application/pdf' });
    await user.upload(await screen.findByLabelText('Upload resume file'), file);
    expect(await screen.findByLabelText(/Extracted text candidate/)).toHaveValue('Jordan Tan\nProduct designer\nEmail: jordan@example.com');
    expect(screen.getByRole('heading', { name: 'Alice Tan' })).toBeInTheDocument();
  });

  it('uploads a Word resume, refuses legacy .doc on the client and shows server refusals', async () => {
    const user = userEvent.setup({ applyAccept: false }); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    const input = await screen.findByLabelText('Upload resume file');
    const docxType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    mockApi.uploadResume.mockResolvedValueOnce({ upload_id: 'up-2', filename: 'resume.docx', status: 'ready_for_review', page_count: null, error_code: null, message: 'Extracted text is a review candidate only.', ai_available: false, extracted_text: 'Jordan Tan\nBackend engineer' });
    await user.upload(input, new File(['PK'], 'resume.docx', { type: docxType }));
    expect(await screen.findByLabelText(/Extracted text candidate/)).toHaveValue('Jordan Tan\nBackend engineer');
    expect(mockApi.uploadResume).toHaveBeenCalledTimes(1);
    // The input's accept list is only a hint, so legacy files are also stopped (with guidance) before any upload.
    await user.upload(input, new File(['x'], 'old.doc', { type: 'application/msword' }));
    expect(await screen.findByText(/Save it as PDF or \.docx and upload again/)).toBeInTheDocument();
    expect(mockApi.uploadResume).toHaveBeenCalledTimes(1);
    mockApi.uploadResume.mockRejectedValueOnce(new HttpError('Macro-enabled Word files (.docm) are not supported.', 422, 'MACRO_ENABLED'));
    await user.upload(input, new File(['PK'], 'macro.docx', { type: docxType }));
    expect(await screen.findByText(/Macro-enabled Word files/)).toBeInTheDocument();
  });

  it('provides a manual resume path and communicates AI unavailability', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'My documents' }));
    expect(screen.getByText(/Your resume library is empty/)).toBeInTheDocument();
    mockApi.createDocument.mockResolvedValue({ id: 'resume-1', title: 'Untitled resume', kind: 'resume', revision: 1, template: 'classic', content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: null });
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    await user.click(screen.getByRole('button', { name: /^Blank/ }));
    await waitFor(() => expect(mockApi.createDocument).toHaveBeenCalled());
    const request = mockApi.createDocument.mock.calls[0][0];
    expect(request.content).toMatchObject({ name: 'Alice Tan', email: 'alice@example.com' });
    expect(request.template).toBe('classic');
  });

  it('allows profile edits and requires explicit save before confirmation', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    await user.click(await screen.findByRole('button', { name: 'Edit personal details' }));
    const headline = screen.getByPlaceholderText('Product designer · 6 years experience');
    await user.type(headline, 'Product designer');
    expect(screen.getByText('Unsaved profile changes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /update my matches/i })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(mockApi.putProfile).toHaveBeenCalled());
  });

  it('refreshes recommendations after saving only when returning to Discover', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Profile' }));
    expect(screen.queryByText('Try a sample profile')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Edit personal details' }));
    await user.clear(screen.getByPlaceholderText('e.g. Alex Tan'));
    await user.type(screen.getByPlaceholderText('e.g. Alex Tan'), 'Alex Tan');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(mockApi.putProfile).toHaveBeenCalledWith(expect.objectContaining({ name: 'Alex Tan' }), 0));
    expect(mockApi.recommendations).toHaveBeenCalledTimes(1);
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Discover' }));
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenCalledTimes(2));
  });

  it('keeps local resume edits on a revision conflict and blocks account switching while dirty', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'My documents' }));
    mockApi.createDocument.mockResolvedValue({ id: 'resume-2', title: 'Untitled resume', kind: 'resume', revision: 1, template: 'classic', content: { name: 'Alice Tan', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: null });
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    await user.click(screen.getByRole('button', { name: /^Blank/ }));
    const summary = await screen.findByRole('textbox', { name: 'Professional summary' });
    await user.type(summary, 'My latest local draft');
    const userSelect = screen.getAllByRole('combobox', { name: 'Development user' })[0];
    await user.selectOptions(userSelect, 'casey');
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
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'My documents' }));
    const baseResume = { id: 'resume-slow', title: 'Untitled resume', kind: 'resume' as const, revision: 1, template: 'classic' as const, content: { name: 'Alice Tan', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: null };
    mockApi.createDocument.mockResolvedValue(baseResume);
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    await user.click(screen.getByRole('button', { name: /^Blank/ }));
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

  it('saves a reviewed resume snapshot without sending an application, and has no second box for a cover letter', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-1', job_id: 'role-1', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-1', title: 'Product Designer', company: 'Northstar', location: 'Singapore', source_url: 'https://jobs.example/role-1' } };
    const reviewed = { id: 'resume-ready', title: 'Product design resume', kind: 'resume' as const, revision: 3, template: 'classic' as const, content: { name: 'Alice Tan', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 3 };
    mockApi.applications.mockResolvedValue({ items: [application] }); mockApi.documents.mockResolvedValue({ items: [reviewed] });
    mockApi.putApplication.mockResolvedValue({ ...application, revision: 2, resume_packet: { export_id: 'export-1', document_id: reviewed.id, title: reviewed.title, revision: 3, download_url: '/v1/exports/export-1' } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: Product Designer' })[0]);
    expect(screen.getByRole('link', { name: /original job posting/i })).toHaveAttribute('href', 'https://jobs.example/role-1');
    expect(screen.queryByLabelText(/Cover letter \(written by you\)/)).not.toBeInTheDocument();      // the letter is written or pasted in the editor, not here
    expect(screen.getByRole('button', { name: 'Prepare cover letter' })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Attach reviewed resume' }), reviewed.id);
    await user.click(screen.getByRole('button', { name: 'Save application record' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-1', expect.objectContaining({ expected_revision: 1, resume_document_id: reviewed.id, expected_resume_revision: 3 })));
    expect(mockApi.putApplication.mock.calls[0][1]).not.toHaveProperty('cover_letter_text');
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
    mockApi.tailorDocument.mockResolvedValue({ document: copy, matched: ['SQL'], missing: ['Figma'], ai: { status: 'off', changed: 0, reason: null } }); mockApi.reviewDocument.mockResolvedValue({ ...copy, reviewed_revision: 1 });
    mockApi.putApplication.mockResolvedValue({ ...application, revision: 2, resume_packet: { export_id: 'export-role', document_id: copy.id, title: copy.title, revision: 1, download_url: '/v1/exports/export-role' } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a resume to tailor' }), original.id);
    await user.click(screen.getByRole('button', { name: 'Create tailored copy' }));
    await waitFor(() => expect(mockApi.tailorDocument).toHaveBeenCalledWith(original.id, 'role-3', 'My resume — UX Designer', 'rules'));
    expect(await screen.findByText(/A tailored draft was created for this application\. Review it before attaching\./)).toBeInTheDocument();
    expect(screen.queryByText(/Matched:|Missing:/)).not.toBeInTheDocument();      // the matched and missing lists are no longer shown
    await user.click(await screen.findByRole('button', { name: 'Mark as reviewed' }));
    await user.click(await screen.findByRole('button', { name: 'Attach reviewed revision' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-3', { resume_document_id: copy.id, expected_resume_revision: 1, expected_revision: 1 }));
    expect(await screen.findByRole('dialog', { name: 'UX Designer' })).toBeInTheDocument();
  });
  it('never shows Matched: none and Missing: none, even for a job with no skills', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null } };
    const original = { id: 'resume-base', title: 'My resume', kind: 'resume' as const, revision: 2, template: 'modern' as const, content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 2 };
    const copy = { ...original, id: 'resume-role', job_id: 'role-3', title: 'My resume — UX Designer', revision: 1, reviewed_revision: null };
    mockApi.applications.mockResolvedValue({ items: [application] }); mockApi.documents.mockResolvedValue({ items: [original] });
    mockApi.tailorDocument.mockResolvedValue({ document: copy, matched: [], missing: [], ai: { status: 'off', changed: 0, reason: null } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a resume to tailor' }), original.id);
    await user.click(screen.getByRole('button', { name: 'Create tailored copy' }));
    expect(await screen.findByText(/A tailored draft was created for this application\./)).toBeInTheDocument();
    expect(screen.queryByText(/Matched: none|Missing: none|nothing was compared/)).not.toBeInTheDocument();
  });
  it('explains what each tailoring button does', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null } };
    mockApi.applications.mockResolvedValue({ items: [application] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    expect(await screen.findByText(/puts the bullets that match this job first/)).toBeInTheDocument();
    expect(screen.getByText(/uses 1 AI use this month/i)).toBeInTheDocument();
  });
  it('tailors with AI from the application, showing the allowance left', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null } };
    const original = { id: 'resume-base', title: 'My resume', kind: 'resume' as const, revision: 2, template: 'modern' as const, content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 2 };
    const copy = { ...original, id: 'resume-role', job_id: 'role-3', title: 'My resume — UX Designer', revision: 1, reviewed_revision: null };
    mockApi.me.mockResolvedValue({ user_id: '1', display_name: 'Alice Tan', plan: 'free', allowance: { limit: 5, used: 2, remaining: 3, period: 'lifetime' }, ai_available: true });
    mockApi.applications.mockResolvedValue({ items: [application] }); mockApi.documents.mockResolvedValue({ items: [original] });
    mockApi.tailorDocument.mockResolvedValue({ document: copy, matched: [], missing: [], ai: { status: 'applied', changed: 2, reason: null } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a resume to tailor' }), original.id);
    await user.click(screen.getByRole('button', { name: 'Tailor with AI (3 of 5 left)' }));
    await waitFor(() => expect(mockApi.tailorDocument).toHaveBeenCalledWith(original.id, 'role-3', 'My resume — UX Designer', 'ai'));
    expect(await screen.findByText(/AI reworded some bullets/)).toBeInTheDocument();
  });
  it('disables Tailor with AI when no model is configured', async () => {
    const user = userEvent.setup();
    const application = { id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null } };
    const original = { id: 'resume-base', title: 'My resume', kind: 'resume' as const, revision: 2, template: 'modern' as const, content: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 2 };
    mockApi.applications.mockResolvedValue({ items: [application] }); mockApi.documents.mockResolvedValue({ items: [original] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a resume to tailor' }), original.id);
    expect(screen.getByRole('button', { name: /Tailor with AI/ })).toBeDisabled();
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

describe('Discover: For you and All jobs', () => {
  const semantic = (extra: object = {}) => ({ items: [{ job: { id: 'fy-1', title: 'Backend Engineer', company: 'Northstar', location: 'Singapore', description: 'Build APIs.' }, score: null, reasons: ['Python appears in the listing', 'Same kind of role as your target role'] }], total: 1, next_offset: null, degraded_mode: false, ranking_mode: 'semantic' as const, fallback_reason: null, ...extra });

  it('starts on For you, shows its reasons and does not call the keyword list', async () => {
    mockApi.recommendationsForYou.mockResolvedValue(semantic());
    mockApi.getPreferences.mockResolvedValue({ roles: ['Backend Engineer'], locations: [], work_modes: [], seniority: 'Junior', salary_min: null, salary_currency: 'SGD', salary_period: 'year', revision: 1 });
    render(<App />);
    expect(await screen.findByText('Python appears in the listing')).toBeInTheDocument();   // the Role filter pill also says Backend Engineer
    expect(screen.getByRole('button', { name: 'Backend Engineer' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'For you' })).toHaveAttribute('aria-pressed', 'true');
    expect(mockApi.recommendations).not.toHaveBeenCalled();
    expect(mockApi.recommendationsForYou).toHaveBeenCalledWith('', 0, { posted_within: '14' });   // the saved defaults: only the Posted filter is sent
    expect(screen.queryByText(/is unavailable right now/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sharpen these matches/i)).not.toBeInTheDocument();
  });

  it('switches to All jobs with one click and back again', async () => {
    const user = userEvent.setup();
    mockApi.recommendationsForYou.mockResolvedValue(semantic());
    render(<App />);
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'All jobs' }));
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'All jobs' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'For you' }));
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
  });

  it('shows a list it fetched a moment ago when you switch back, without asking the server again', async () => {
    const user = userEvent.setup();
    mockApi.recommendationsForYou.mockResolvedValue(semantic());
    render(<App />);
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'All jobs' }));
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'For you' }));
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();   // at once, nothing to wait for
    await user.click(screen.getByRole('button', { name: 'All jobs' }));
    expect(screen.getByText('Product Designer')).toBeInTheDocument();
    expect(mockApi.recommendationsForYou).toHaveBeenCalledTimes(1);
    expect(mockApi.recommendations).toHaveBeenCalledTimes(1);
  });

  it('shows an older list at once and replaces it when a newer one arrives', async () => {
    const user = userEvent.setup();
    mockApi.recommendationsForYou.mockResolvedValue(semantic());
    render(<App />);
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'All jobs' }));
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    const clock = vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 2 * 60_000);   // two minutes later: remembered, but no longer fresh
    try {
      let release: (value: ReturnType<typeof semantic>) => void = () => undefined;
      mockApi.recommendationsForYou.mockReturnValue(new Promise((resolve) => { release = resolve; }));   // the newer list is still on its way
      await user.click(screen.getByRole('button', { name: 'For you' }));
      expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
      act(() => release(semantic({ items: [{ job: { id: 'fy-2', title: 'Data Engineer', company: 'Northstar', location: 'Singapore', description: 'Build pipelines.' }, score: null, reasons: [] }] })));
      expect(await screen.findByText('Data Engineer')).toBeInTheDocument();
      expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument();
      expect(mockApi.recommendationsForYou).toHaveBeenCalledTimes(2);
    } finally { clock.mockRestore(); }
  });

  it('asks again for the lists after a save, because they changed', async () => {
    const user = userEvent.setup();
    mockApi.recommendationsForYou.mockResolvedValue(semantic());
    mockApi.reviewJob.mockResolvedValue({ job_id: 'fy-1', decision: 'dismissed' });
    render(<App />);
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Pass' }));
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenCalledTimes(2));
  });

  it('falls back to the all-jobs list with a plain note when For you fails', async () => {
    render(<App />);   // the default mock rejects For you
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    expect(screen.getByText(/For you is unavailable right now, so all jobs are shown/i)).toBeInTheDocument();
    expect(mockApi.recommendations).toHaveBeenCalled();
  });

  it('when the server has For you switched off, shows the plain list with no toggle and no note, and asks only once', async () => {
    const user = userEvent.setup();
    mockApi.recommendationsForYou.mockRejectedValue(new HttpError('Semantic recommendations are not enabled', 404, 'FOR_YOU_DISABLED'));
    render(<App />);
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    expect(screen.queryByText(/is unavailable right now/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'For you' })).not.toBeInTheDocument();      // the plain list stays, with Saved and Passed beside it
    expect(screen.getByRole('button', { name: 'All jobs' })).toBeInTheDocument();
    expect(mockApi.recommendationsForYou).toHaveBeenCalledTimes(1);
    await user.type(screen.getByLabelText('Search jobs'), 'design');
    await waitFor(() => expect(mockApi.recommendations).toHaveBeenLastCalledWith('design', 0, { posted_within: '14' }), { timeout: 1500 });
    expect(mockApi.recommendationsForYou).toHaveBeenCalledTimes(1);          // never asked again this session
  });

  it('marks jobs the user already ran a fit check on, with the score', async () => {
    mockApi.fitSummaries.mockResolvedValue({ items: [{ job_id: 'role-1', percent: 75, stale: false }] });
    render(<App />);
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    expect(await screen.findByText(/Fit checked · 75%/)).toBeInTheDocument();
  });

  it('says a fit check is out of date when the profile changed after it', async () => {
    mockApi.fitSummaries.mockResolvedValue({ items: [{ job_id: 'role-1', percent: 40, stale: true }] });
    render(<App />);
    expect(await screen.findByText(/Fit checked · 40% · out of date/)).toBeInTheDocument();
  });

  it('shows the saved fit score in the tracker and opens the job from it', async () => {
    const user = userEvent.setup();
    const job = { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null };
    mockApi.fitSummaries.mockResolvedValue({ items: [{ job_id: 'role-3', percent: 62, stale: false }] });
    mockApi.applications.mockResolvedValue({ items: [{ id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job }] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    expect(screen.getByRole('columnheader', { name: 'FIT' })).toBeInTheDocument();
    await user.click((await screen.findAllByRole('button', { name: /Fit with your profile for UX Designer: 62%/ }))[0]);
    expect(await screen.findByRole('dialog', { name: /UX Designer/ })).toBeInTheDocument();
    expect(mockApi.jobFit).toHaveBeenCalledWith('role-3');          // the job window holds the full breakdown
  });

  it('offers Check fit in the tracker for a job never checked, and opens the job to run it', async () => {
    const job = { id: 'role-4', title: 'Data Analyst', company: 'Cedar', location: null };
    mockApi.fitSummaries.mockResolvedValue({ items: [{ job_id: 'role-1', percent: 75, stale: false }], running: [] });     // a different job
    mockApi.applications.mockResolvedValue({ items: [{ id: 'app-4', job_id: 'role-4', status: 'saved', notes: '', applied_at: null, revision: 1, job }] });
    const user = userEvent.setup();
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    const notRun = (await screen.findAllByRole('button', { name: /Fit not run for Data Analyst/ }))[0];
    expect(notRun).toHaveTextContent('Check fit');
    await user.click(notRun);
    expect(await screen.findByRole('button', { name: 'Check my fit' })).toBeInTheDocument();       // the same window as on Discover
  });

  it('says In progress in the tracker while a fit check is running', async () => {
    const job = { id: 'role-5', title: 'Data Engineer', company: 'Birch', location: null };
    mockApi.fitSummaries.mockResolvedValue({ items: [], running: ['role-5'] });
    mockApi.applications.mockResolvedValue({ items: [{ id: 'app-5', job_id: 'role-5', status: 'saved', notes: '', applied_at: null, revision: 1, job }] });
    const user = userEvent.setup();
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    expect((await screen.findAllByRole('button', { name: /Fit check for Data Engineer is in progress/ }))[0]).toHaveTextContent('In progress');
    expect(screen.queryByRole('button', { name: /Fit not run for Data Engineer/ })).not.toBeInTheDocument();
  });

  it('lists saved jobs on the Saved tab', async () => {
    const user = userEvent.setup();
    mockApi.reviewedJobs.mockResolvedValue({ items: [{ job: { id: 's1', title: 'Saved Analyst', company: 'Acme', location: 'Singapore', description: 'Analyse things carefully.' }, reasons: [], review: 'saved' }], total: 1, next_offset: null });
    render(<App />);
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Saved' }));
    expect(await screen.findByText('Saved Analyst')).toBeInTheDocument();
    expect(mockApi.reviewedJobs).toHaveBeenLastCalledWith('saved', '', 0);
    expect(screen.getAllByRole('button', { name: 'Saved' }).filter((button) => button.hasAttribute('disabled'))).toHaveLength(1);   // the card's own button; nothing more to do
    expect(screen.queryByRole('button', { name: 'Pass' })).not.toBeInTheDocument();
  });

  it('lists passed jobs on the Passed tab and lets the user restore one', async () => {
    const user = userEvent.setup();
    mockApi.reviewedJobs.mockResolvedValue({ items: [{ job: { id: 'p1', title: 'Passed Analyst', company: 'Acme', location: 'Singapore', description: 'Analyse things carefully.' }, reasons: [], review: 'dismissed' }], total: 1, next_offset: null });
    mockApi.reviewJob.mockResolvedValue({});
    render(<App />);
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Passed' }));
    expect(await screen.findByText('Passed Analyst')).toBeInTheDocument();
    expect(mockApi.reviewedJobs).toHaveBeenLastCalledWith('dismissed', '', 0);
    await user.click(screen.getByRole('button', { name: /Restore/ }));
    await waitFor(() => expect(mockApi.reviewJob).toHaveBeenCalledWith('p1', 'none'));
  });

  it('keeps the toggle and the plain note for any other For you failure', async () => {
    mockApi.recommendationsForYou.mockRejectedValue(new HttpError('Request failed (500).', 500, 'INTERNAL'));
    render(<App />);
    expect(await screen.findByText('Product Designer')).toBeInTheDocument();
    expect(screen.getByText(/For you is unavailable right now, so all jobs are shown/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'For you' })).toBeInTheDocument();
  });

  it('shows the server reason when For you itself fell back, and hints at thin preferences', async () => {
    mockApi.recommendationsForYou.mockResolvedValue({ ...semantic(), ranking_mode: 'keyword_fallback' as const, fallback_reason: 'No confirmed profile yet, so the keyword ranker was used.', degraded_mode: true });
    render(<App />);
    expect(await screen.findByText('No confirmed profile yet, so the keyword ranker was used.')).toBeInTheDocument();
  });

  it('while the profile is still being prepared, says so and offers Check again, which asks For you once more', async () => {
    const user = userEvent.setup();
    const preparing = "We're still preparing your matches. This usually takes under a minute after you update your profile, so you're seeing all jobs for now. Refresh in a moment.";
    mockApi.recommendationsForYou.mockResolvedValueOnce({ ...semantic(), ranking_mode: 'keyword_fallback' as const, fallback_reason: preparing, fallback_code: 'profile_embedding_pending' as const, degraded_mode: true, ranking_status: 'Keyword text similarity and skill matching' })
      .mockResolvedValue(semantic());
    render(<App />);
    expect(await screen.findByText(preparing)).toBeInTheDocument();
    expect(screen.queryByText(/Keyword text similarity/i)).not.toBeInTheDocument();   // one banner, not two
    const calls = mockApi.recommendationsForYou.mock.calls.length;
    await user.click(screen.getByRole('button', { name: 'Check again' }));
    await waitFor(() => expect(mockApi.recommendationsForYou.mock.calls.length).toBe(calls + 1), { timeout: 1500 });
    await waitFor(() => expect(screen.queryByText(preparing)).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument();
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
  });

  it('offers no Check again when the fallback is only that there is no confirmed profile', async () => {
    mockApi.recommendationsForYou.mockResolvedValue({ ...semantic(), ranking_mode: 'keyword_fallback' as const, fallback_reason: 'No confirmed profile yet, so the keyword ranker was used.', fallback_code: 'no_profile' as const, degraded_mode: true });
    render(<App />);
    expect(await screen.findByText('No confirmed profile yet, so the keyword ranker was used.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument();
  });

  it('hints at adding roles and seniority when the profile is thin, and sends typed search to For you', async () => {
    const user = userEvent.setup();
    mockApi.recommendationsForYou.mockResolvedValue(semantic());
    render(<App />);   // default preferences: no roles, no seniority
    expect(await screen.findByText(/sharpen these matches/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search jobs'), 'backend');
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('backend', 0, { posted_within: '14' }), { timeout: 1500 });
  });
});

describe('Plan and cover letters in the app', () => {
  const used = { user_id: '1', display_name: 'Alice Tan', plan: 'free', allowance: { limit: 5, used: 2, remaining: 3, period: '2026-10' }, ai_available: true, letter_available: true };
  const saved = { id: 'app-3', job_id: 'role-3', status: 'saved', notes: '', applied_at: null, revision: 1, job: { id: 'role-3', title: 'UX Designer', company: 'Harbor', location: null } };

  it('reads the resume defaults once for several new resumes within a minute', async () => {
    const user = userEvent.setup();
    mockApi.getSettings.mockResolvedValue({ revision: 1, resume_defaults: { template: 'modern' } });
    let count = 0;
    mockApi.createDocument.mockImplementation(async (values: any) => ({ id: `r${++count}`, title: values.title, kind: 'resume', revision: 1, template: values.template, content: values.content, layout: values.layout, reviewed_revision: null }));
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'My documents' }));
    await user.click(screen.getByRole('button', { name: /create your first resume/i }));
    await user.click(screen.getByRole('button', { name: /^Blank/ }));
    await waitFor(() => expect(mockApi.createDocument).toHaveBeenCalledTimes(1));
    expect(mockApi.createDocument.mock.calls[0][0].template).toBe('modern');
    await user.click(await screen.findByRole('button', { name: /Library/ }));
    await user.click(screen.getByRole('button', { name: /Create resume/ }));
    await user.click(screen.getByRole('button', { name: /^Blank/ }));
    await waitFor(() => expect(mockApi.createDocument).toHaveBeenCalledTimes(2));
    expect(mockApi.createDocument.mock.calls[1][0].template).toBe('modern');
    expect(mockApi.getSettings).toHaveBeenCalledTimes(1);
  });

  it('shows the plan and the AI uses left in the sidebar and opens the plan panel from it', async () => {
    const user = userEvent.setup();
    mockApi.me.mockResolvedValue(used);
    render(<App />); await screen.findByText('Product Designer');
    const pill = await screen.findByRole('button', { name: /Free plan, 3 of 5 AI uses left/ });
    await user.click(pill);
    const panel = screen.getByRole('dialog', { name: 'Your plan' });
    expect(panel).toHaveTextContent('2 used, 3 left');
    expect(panel).toHaveTextContent('Resets on 1 November');
    await user.click(within(panel).getByRole('button', { name: 'Upgrade to Premium' }));
    await user.click(screen.getByRole('button', { name: 'Upgrade (demo)' }));
    expect(await screen.findByText(/Demo only: no payment was taken and your plan did not change/)).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Your plan' })).not.toBeInTheDocument();
    expect(mockApi.me).toHaveBeenCalled();                     // nothing was sent to change the plan
  });

  it('shows both the resume and the cover letter of an application in the tracker packet column', async () => {
    const user = userEvent.setup();
    const packet = (title: string) => ({ export_id: 'e', document_id: 'd', title, revision: 2, download_url: '/v1/exports/e' });
    const job = (id: string, title: string) => ({ id, title, company: 'Northstar', location: null });
    mockApi.applications.mockResolvedValue({ items: [
      { id: 'a1', job_id: 'j1', status: 'saved', notes: '', applied_at: null, revision: 1, job: job('j1', 'Both Role'), resume_packet: packet('R'), cover_letter_packet: packet('C') },
      { id: 'a2', job_id: 'j2', status: 'saved', notes: '', applied_at: null, revision: 1, job: job('j2', 'Letter Only Role'), cover_letter_packet: packet('C') },
      { id: 'a3', job_id: 'j3', status: 'saved', notes: '', applied_at: null, revision: 1, job: job('j3', 'Old Text Role'), cover_letter_text: 'Dear team' },
      { id: 'a4', job_id: 'j4', status: 'saved', notes: '', applied_at: null, revision: 1, job: job('j4', 'Nothing Role') },
    ] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    const rowOf = (title: string) => screen.getAllByText(title)[0].closest('tr') as HTMLElement;
    expect(within(rowOf('Both Role')).getByText('Resume · rev 2')).toBeInTheDocument();
    expect(within(rowOf('Both Role')).getByText('Cover letter · rev 2')).toBeInTheDocument();
    expect(within(rowOf('Letter Only Role')).getByText('No resume')).toBeInTheDocument();
    expect(within(rowOf('Letter Only Role')).getByText('Cover letter · rev 2')).toBeInTheDocument();
    expect(within(rowOf('Old Text Role')).getByText('Cover letter (text)')).toBeInTheDocument();
    expect(within(rowOf('Nothing Role')).getByText('No cover letter')).toBeInTheDocument();
  });

  const letterDoc = (over: object = {}) => ({ id: 'l1', title: 'Cover letter — UX Designer', kind: 'cover_letter' as const, revision: 2, template: 'classic' as const, content: { name: 'Alice', email: '', phone: '', location: '', date: '', recipient: '', greeting: '', paragraphs: ['Hello.'], closing: '', signature: '' }, layout: { font_size: 11, margin: 22 }, reviewed_revision: 2, updated_at: '2026-10-25T00:00:00Z', job_id: 'role-3', ...over });

  it('attaches a reviewed cover letter from the application window, like a resume, and lists only reviewed letters', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letterDoc({ id: 'l2', title: 'Draft letter', reviewed_revision: null }), letterDoc({ id: 'other', title: 'Letter for another job', job_id: 'role-9' }), letterDoc()] });
    mockApi.applications.mockResolvedValue({ items: [saved] });
    mockApi.putApplication.mockResolvedValue({ ...saved, revision: 2, cover_letter_packet: { export_id: 'e1', document_id: 'l1', title: 'Cover letter — UX Designer', revision: 2, download_url: '/v1/exports/e1' } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    const select = await screen.findByRole('combobox', { name: 'Attach reviewed cover letter' });
    await waitFor(() => expect(within(select).getByRole('option', { name: 'Cover letter — UX Designer · revision 2' })).toBeInTheDocument());
    expect(within(select).queryByRole('option', { name: /Draft letter/ })).not.toBeInTheDocument();                // not reviewed yet
    expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual(['No cover letter selected', 'Cover letter — UX Designer · revision 2', 'Letter for another job · revision 2']);   // this job's letter first
    await user.selectOptions(select, 'l1');
    await user.click(screen.getByRole('button', { name: 'Save application record' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-3', expect.objectContaining({ expected_revision: 1, cover_letter_document_id: 'l1', expected_cover_letter_revision: 2 })));
    expect(mockApi.putApplication.mock.calls[0][1]).not.toHaveProperty('resume_document_id');
  });

  it('can replace or remove an attached cover letter, and says when no letter is reviewed yet', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [letterDoc({ reviewed_revision: null })] });
    mockApi.applications.mockResolvedValue({ items: [{ ...saved, cover_letter_packet: { export_id: 'e1', document_id: 'l1', title: 'Cover letter — UX Designer', revision: 1, download_url: '/v1/exports/e1' } }] });
    mockApi.putApplication.mockResolvedValue({ ...saved, revision: 2, cover_letter_packet: null });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    expect(screen.getByText('Replace cover letter snapshot')).toBeInTheDocument();
    expect(await screen.findByText(/Review a cover letter in the letter editor before attaching it/)).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Attach reviewed cover letter' }), '__clear');
    await user.click(screen.getByRole('button', { name: 'Save application record' }));
    await waitFor(() => expect(mockApi.putApplication).toHaveBeenCalledWith('role-3', expect.objectContaining({ cover_letter_document_id: null })));
  });

  it('Prepare resume opens the resumes, even after the Cover letters tab was used', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [] });
    mockApi.applications.mockResolvedValue({ items: [saved] });
    render(<App />); await screen.findByText('Product Designer');
    const nav = within(screen.getByRole('navigation', { name: 'Main navigation' }));
    await user.click(nav.getByRole('button', { name: 'My documents' }));
    await user.click(screen.getByRole('tab', { name: /Cover letters/ }));
    expect(await screen.findByText('No cover letters yet.')).toBeInTheDocument();
    await user.click(nav.getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    // an application with no draft yet gets the window, and the page does not change
    expect(await screen.findByRole('dialog', { name: 'Prepare a resume' })).toBeInTheDocument();
    expect(location.pathname).toBe('/tracker');
    expect(screen.queryByText('No cover letters yet.')).not.toBeInTheDocument();
  });

  it('opens an existing draft for the job in the resume editor, not the cover letters tab, after the Cover letters tab was used', async () => {
    const user = userEvent.setup();
    const draft = { ...letterDoc(), id: 'draft-1', kind: 'resume' as const, title: 'Draft for UX Designer', content: { name: 'Alice', email: '', phone: '', location: '', summary: '', sections: [] }, reviewed_revision: null, job_id: 'role-3' };
    mockApi.letters.mockResolvedValue({ items: [] });
    mockApi.applications.mockResolvedValue({ items: [saved] });
    mockApi.documents.mockResolvedValue({ items: [draft] });
    render(<App />); await screen.findByText('Product Designer');
    const nav = within(screen.getByRole('navigation', { name: 'Main navigation' }));
    await user.click(nav.getByRole('button', { name: 'My documents' }));
    await user.click(screen.getByRole('tab', { name: /Cover letters/ }));
    await user.click(nav.getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toHaveValue('Draft for UX Designer');
    expect(screen.queryByRole('dialog', { name: 'Prepare a resume' })).not.toBeInTheDocument();
    expect(location.pathname).toBe('/resumes/draft-1');
  });

  it('creates the tailored copy from the Prepare a resume window and opens it in the editor', async () => {
    const user = userEvent.setup();
    const original = { id: 'resume-base', title: 'My resume', kind: 'resume' as const, revision: 2, template: 'classic' as const, content: { name: 'Alice', email: '', phone: '', location: '', summary: '', sections: [] }, layout: { font_size: 11, margin: 18 }, reviewed_revision: 2 };
    const copy = { ...original, id: 'resume-copy', title: 'My resume — UX Designer', revision: 1, reviewed_revision: null, job_id: 'role-3' };
    mockApi.applications.mockResolvedValue({ items: [saved] });
    mockApi.documents.mockResolvedValue({ items: [original] });
    mockApi.tailorDocument.mockResolvedValue({ document: copy, matched: [], missing: [], ai: { status: 'off', changed: 0, reason: null } });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Prepare a resume' }));
    expect(dialog.getByRole('button', { name: 'Create tailored copy' })).toBeDisabled();           // pick a resume first
    expect(dialog.getByRole('button', { name: 'Build from my profile' })).toBeEnabled();
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Choose a resume to tailor' }), original.id);
    await user.click(dialog.getByRole('button', { name: 'Create tailored copy' }));
    await waitFor(() => expect(mockApi.tailorDocument).toHaveBeenCalledWith(original.id, 'role-3', 'My resume — UX Designer', 'rules'));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toHaveValue('My resume — UX Designer');
    expect(screen.queryByRole('dialog', { name: 'Prepare a resume' })).not.toBeInTheDocument();
  });

  it('closes the Prepare a resume window with Cancel and stays on the tracker', async () => {
    const user = userEvent.setup();
    mockApi.applications.mockResolvedValue({ items: [saved] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    const dialog = await screen.findByRole('dialog', { name: 'Prepare a resume' });
    expect(within(dialog).getByRole('combobox', { name: 'Choose a resume to tailor' })).toBeDisabled();       // no resumes yet
    expect(dialog).toHaveTextContent('You have no resumes yet');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog', { name: 'Prepare a resume' })).not.toBeInTheDocument();
    expect(location.pathname).toBe('/tracker');
  });

  it('opens the same panel from the account block at the bottom of the sidebar', async () => {
    const user = userEvent.setup();
    mockApi.me.mockResolvedValue(used);
    render(<App />); await screen.findByText('Product Designer');
    await user.click(await screen.findByRole('button', { name: 'Your plan and account' }));
    expect(screen.getByRole('dialog', { name: 'Your plan' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Your plan' })).not.toBeInTheDocument();
  });

  it('switches My documents between resumes and cover letters, each at its own address', async () => {
    const user = userEvent.setup();
    mockApi.letters.mockResolvedValue({ items: [{ id: 'l1', title: 'Cover letter — UX Designer', kind: 'cover_letter', revision: 1, template: 'classic', content: { name: 'Alice', email: '', phone: '', location: '', date: '', recipient: '', greeting: '', paragraphs: ['Hello.'], closing: '', signature: '' }, layout: { font_size: 11, margin: 22 }, reviewed_revision: null, updated_at: '2026-10-25T00:00:00Z', job_id: 'role-3' }] });
    mockApi.applications.mockResolvedValue({ items: [saved] });
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'My documents' }));
    expect(location.pathname).toBe('/resumes');
    expect(screen.getByRole('tab', { name: /Resumes/ })).toHaveAttribute('aria-selected', 'true');
    await user.click(screen.getByRole('tab', { name: /Cover letters/ }));
    expect(await screen.findByText('Cover letter — UX Designer')).toBeInTheDocument();
    expect(location.pathname).toBe('/resumes/letters');
    await user.click(screen.getByRole('button', { name: 'Open Cover letter — UX Designer' }));
    expect(await screen.findByRole('textbox', { name: 'Letter title' })).toHaveValue('Cover letter — UX Designer');
    expect(location.pathname).toBe('/resumes/letters/l1');
    await user.click(screen.getByRole('button', { name: /Cover letters/ }));
    expect(location.pathname).toBe('/resumes/letters');
    await user.click(screen.getByRole('tab', { name: /Resumes/ }));
    expect(location.pathname).toBe('/resumes');
  });

  it('opens a letter from its address after a refresh or a pasted link', async () => {
    history.replaceState(null, '', '/resumes/letters');
    mockApi.letters.mockResolvedValue({ items: [] });
    render(<App />);
    expect(await screen.findByText('No cover letters yet.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Cover letters/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('starts a cover letter from an application in the tracker', async () => {
    const user = userEvent.setup();
    mockApi.applications.mockResolvedValue({ items: [saved] });
    mockApi.letters.mockResolvedValue({ items: [] });
    mockApi.me.mockResolvedValue(used);
    render(<App />); await screen.findByText('Product Designer');
    await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name: 'Application tracker' }));
    await user.click(screen.getAllByRole('button', { name: 'Edit application: UX Designer' })[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare cover letter' }));
    const dialog = await screen.findByRole('dialog', { name: 'Write a cover letter' });
    expect(within(dialog).getByRole('combobox', { name: 'Job for this letter' })).toHaveValue('role-3');
    expect(location.pathname).toBe('/resumes/letters');
  });
});

describe('Discover filters', () => {
  const defaults = { roles: ['Backend Engineer'], locations: ['Singapore'], work_modes: ['hybrid'], seniority: 'mid', salary_min: null, salary_currency: 'SGD', salary_period: 'year', revision: 3 };
  const list = { items: [{ job: { id: 'f-1', title: 'Platform Engineer', company: 'Northstar', location: 'Singapore', work_mode: 'Hybrid' }, score: null, reasons: ['Same kind of role'], review: null }], total: 1, next_offset: null, degraded_mode: false, ranking_mode: 'semantic' as const };
  beforeEach(() => {
    mockApi.getPreferences.mockResolvedValue(defaults);
    mockApi.recommendationsForYou.mockResolvedValue(list);
  });

  it('starts from the profile preferences, shows them as pills and tags what a job matches', async () => {
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Work mode: Hybrid' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Role: Backend Engineer' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'My preferences' })).toBeInTheDocument();
    expect(await screen.findByText('Platform Engineer')).toBeInTheDocument();
    const card = screen.getByText('Platform Engineer').closest('article')!;
    expect(within(card).getByText('Hybrid', { selector: '.preference-match' })).toBeInTheDocument();
    expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, { posted_within: '14' });
  });

  it('changing a pill filters this session only, and Reset goes back to the defaults', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Work mode: Hybrid' }));
    await user.click(within(screen.getByRole('dialog', { name: 'Work mode filter' })).getByRole('button', { name: 'Remote' }));
    expect(screen.getByRole('button', { name: 'Custom' })).toBeInTheDocument();
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, expect.objectContaining({ filters: 'custom', work_mode: ['hybrid', 'remote'], role: ['Backend Engineer'] })));
    expect(mockApi.putPreferences).not.toHaveBeenCalled();
    expect(JSON.parse(sessionStorage.getItem('jh-discover-filters:alice')!).mode).toBe('custom');
    await user.click(screen.getByRole('button', { name: 'Reset to my preferences' }));
    expect(screen.getByRole('button', { name: 'My preferences' })).toBeInTheDocument();
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, { posted_within: '14' }));
  });

  it('can show every job without preferences', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'My preferences' }));
    await user.click(screen.getByRole('menuitemradio', { name: /No filters/ }));
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, { filters: 'none', posted_within: '14' }));
    expect(screen.getByRole('button', { name: 'Work mode: Any work mode' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Use my preferences' }));
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, { posted_within: '14' }));
  });

  it('shows jobs from the last 14 days by default, and the Posted pill widens it to the past year', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Posted: Last 14 days' }));
    await user.click(screen.getByRole('menuitemradio', { name: /Past year/ }));
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, { posted_within: '365' }));
    expect(screen.getByRole('button', { name: 'My preferences' })).toBeInTheDocument();      // not a preference change
    expect(JSON.parse(sessionStorage.getItem('jh-discover-filters:alice')!).posted).toBe(365);
    expect(mockApi.putPreferences).not.toHaveBeenCalled();
  });

  it('hides expired listings by default, and unticking the box asks for them', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Posted: Last 14 days' }));
    const box = screen.getByRole('menuitemcheckbox', { name: /Hide expired listings/ });
    expect(box).toHaveAttribute('aria-checked', 'true');
    await user.click(box);
    await waitFor(() => expect(mockApi.recommendationsForYou).toHaveBeenLastCalledWith('', 0, { posted_within: '14', include_expired: 'true' }));
    expect(screen.getByRole('button', { name: 'Posted: Last 14 days + expired' })).toBeInTheDocument();
  });

  it('saves the current filters as the new profile default on request', async () => {
    const user = userEvent.setup();
    mockApi.putPreferences.mockImplementation(async (values: any) => ({ ...values, revision: 4 }));
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Work mode: Hybrid' }));
    await user.click(within(screen.getByRole('dialog', { name: 'Work mode filter' })).getByRole('button', { name: 'Remote' }));
    await user.click(screen.getByRole('button', { name: 'Save to profile' }));
    await waitFor(() => expect(mockApi.putPreferences).toHaveBeenCalledWith(expect.objectContaining({ work_modes: ['hybrid', 'remote'], roles: ['Backend Engineer'], expected_revision: 3 })));
    expect(await screen.findByRole('button', { name: 'My preferences' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Work mode: Hybrid, Remote' })).toBeInTheDocument();
  });
});
