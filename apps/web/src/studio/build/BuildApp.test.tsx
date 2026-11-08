import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../../App';
import { api } from '../../api';
import { createFromBank, suggestPlan } from './buildApi';
import { bank, resume } from './testData';

vi.mock('../../api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api')>();
  return { ...original, api: Object.fromEntries(Object.keys(original.api).map((key) => [key, vi.fn()])) };
});
vi.mock('./buildApi', () => ({ suggestPlan: vi.fn(), createFromBank: vi.fn() }));
const mockApi = vi.mocked(api), mockSuggest = vi.mocked(suggestPlan), mockCreate = vi.mocked(createFromBank);
const application = { id: 'app-1', job_id: 'job-1', status: 'saved', notes: '', applied_at: null, revision: 3, job: { id: 'job-1', title: 'Backend Engineer', company: 'Stripe', location: 'Singapore' } };
const built = resume({ id: 'built-1', job_id: 'job-1', title: 'Backend Engineer – Stripe', revision: 1 });

beforeEach(() => {
  vi.resetAllMocks();
  mockApi.fitSummaries.mockResolvedValue({ items: [] });
  mockApi.me.mockResolvedValue({ user_id: '1', display_name: 'Alice Tan', plan: 'free', allowance: { limit: 5, used: 0, remaining: 5, period: '2026-10' }, ai_available: false });
  mockApi.getProfile.mockResolvedValue({ draft: { name: 'Alice Tan', email: 'alice@example.com', phone: '', location: 'Singapore', summary: '', skills: [] }, revision: 0, confirmed_revision: null });
  mockApi.getBank.mockImplementation(async () => bank());
  mockApi.getPreferences.mockResolvedValue({ roles: [], locations: [], work_modes: [], seniority: '', salary_min: null, salary_currency: 'SGD', salary_period: 'year', revision: 0 });
  mockApi.recommendations.mockResolvedValue({ items: [], total: 0, next_offset: null, degraded_mode: true });
  mockApi.applications.mockResolvedValue({ items: [application] });
  mockApi.documents.mockResolvedValue({ items: [] });
  mockApi.getSettings.mockResolvedValue({ revision: 2, resume_defaults: { build: { points_per_item: 2 } } });
  mockSuggest.mockResolvedValue({ strategy: 'keyword-v1', plan: { sections: [{ kind: 'experience', items: [{ item_id: 'exp-1', picks: [{ bullet_id: 'b1' }, { bullet_id: 'b3', alternative_id: 'v1' }] }] }] }, reasons: { 'exp-1': ['matches PostgreSQL'] }, coverage: { covered: ['PostgreSQL'], missing: ['Kubernetes'] } });
  mockCreate.mockResolvedValue(built);
});
afterEach(() => cleanup());
const goTo = async (user: ReturnType<typeof userEvent.setup>, name: string) => user.click(within(await screen.findByRole('navigation', { name: 'Main navigation' })).getByRole('button', { name }));

describe('build flow inside the app', () => {
  it('builds a resume for a saved job from the chooser and opens it in the editor with the attach banner', async () => {
    const user = userEvent.setup(); render(<App />);
    await goTo(user, 'My documents');
    await user.click(await screen.findByRole('button', { name: /create your first resume/i }));
    expect(screen.getAllByRole('button').filter((button) => button.classList.contains('start-card'))).toHaveLength(4);
    await user.click(screen.getByRole('button', { name: /^For a job/ }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a saved job' }), 'job-1');
    await user.click(screen.getByRole('button', { name: 'Match my profile' }));
    expect(await screen.findByText('matches PostgreSQL')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toHaveValue('Backend Engineer – Stripe');
    expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'job-1', title: 'Backend Engineer – Stripe' }));
    expect(screen.getByText('Preparing for', { exact: false })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Attach reviewed revision' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Return to tracker' })).toBeInTheDocument();
    expect(mockApi.createDocument).not.toHaveBeenCalled();
  });

  it('builds from the tracker\'s Prepare resume with the job fixed', async () => {
    const user = userEvent.setup(); render(<App />);
    await goTo(user, 'Application tracker');
    await user.click((await screen.findAllByRole('button', { name: 'Edit application: Backend Engineer' }))[0]);
    await user.click(screen.getByRole('button', { name: 'Prepare resume' }));
    expect(screen.getByRole('button', { name: 'Create tailored copy' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Build from my profile' }));
    expect(await screen.findByText('matches PostgreSQL')).toBeInTheDocument();
    expect(mockSuggest).toHaveBeenCalledWith('job-1', 2);
    expect(screen.queryByRole('combobox', { name: 'Choose a saved job' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toHaveValue('Backend Engineer – Stripe');
    expect(screen.getByRole('button', { name: 'Return to tracker' })).toBeInTheDocument();
  });

  it('creates a free-build resume with no job and no attach banner', async () => {
    const user = userEvent.setup(); render(<App />);
    mockCreate.mockResolvedValue(resume({ id: 'general', title: 'Resume from my profile', job_id: null }));
    await goTo(user, 'My documents');
    await user.click(await screen.findByRole('button', { name: /create your first resume/i }));
    await user.click(screen.getByRole('button', { name: /^From my profile/ }));
    await user.click(await screen.findByRole('button', { name: 'Create resume' }));
    expect(await screen.findByRole('textbox', { name: 'Resume title' })).toHaveValue('Resume from my profile');
    expect(mockCreate.mock.calls[0][0].job_id).toBeNull();
    expect(screen.queryByRole('button', { name: 'Attach reviewed revision' })).not.toBeInTheDocument();
  });

  it('starts a blank resume from the user defaults', async () => {
    const user = userEvent.setup(); render(<App />);
    mockApi.getSettings.mockResolvedValue({ revision: 2, resume_defaults: { template: 'modern', layout: { accent_color: 'teal' }, sections: [{ kind: 'skills' }, { kind: 'experience' }] } });
    mockApi.createDocument.mockImplementation(async (values) => ({ ...resume({ id: 'blank' }), ...values } as ReturnType<typeof resume>));
    await goTo(user, 'My documents');
    await user.click(await screen.findByRole('button', { name: /create your first resume/i }));
    await user.click(screen.getByRole('button', { name: /^Blank/ }));
    await screen.findByRole('textbox', { name: 'Resume title' });
    const request = mockApi.createDocument.mock.calls[0][0] as { template: string; layout: Record<string, unknown>; content: { sections: { title: string }[] } };
    expect(request.template).toBe('modern');
    expect(request.layout).toMatchObject({ font_size: 11, accent_color: 'teal' });
    expect(request.content.sections.map((section) => section.title)).toEqual(['Skills', 'Experience', 'Education', 'Projects']);
  });

  describe('style settings in the editor', () => {
    const openEditor = async (user: ReturnType<typeof userEvent.setup>) => {
      mockApi.documents.mockResolvedValue({ items: [resume({ reviewed_revision: 2 })] });
      render(<App />);
      await goTo(user, 'My documents');
      await user.click(await screen.findByRole('button', { name: 'Open Backend Engineer – Stripe' }));
      await screen.findByRole('textbox', { name: 'Resume title' });
    };

    it('applies my defaults as an ordinary edit that autosaves with the new layout and section order', async () => {
      const user = userEvent.setup();
      mockApi.getSettings.mockResolvedValue({ revision: 2, resume_defaults: { layout: { heading_style: 'small-caps', bullet_char: '–' }, sections: [{ kind: 'skills' }, { kind: 'experience' }, { kind: 'custom', title: 'Fun facts', hidden: true }] } });
      mockApi.patchDocument.mockImplementation(async (id, values) => ({ ...resume(), ...values, id, revision: 3, reviewed_revision: null } as ReturnType<typeof resume>));
      await openEditor(user);
      await user.click(screen.getByRole('button', { name: 'Apply my defaults' }));
      const article = document.querySelector('article.resume-paper')!;
      await waitFor(() => expect(article.className).toContain('heading-small-caps'));
      expect(article.className).toContain('bullet-dash');
      expect([...article.querySelectorAll('h2')].map((heading) => heading.textContent)).toEqual(['Skills', 'Experience']);
      await waitFor(() => expect(mockApi.patchDocument).toHaveBeenCalled(), { timeout: 3000 });
      const [id, patch] = mockApi.patchDocument.mock.calls[0];
      expect(id).toBe('r1');
      expect(patch.layout).toMatchObject({ heading_style: 'small-caps', bullet_char: '–' });
      expect(patch.expected_revision).toBe(2);
      expect(patch.content!.sections.map((section) => [section.title, section.hidden])).toEqual([['Skills', undefined], ['Experience', undefined], ['Fun facts', true]]);
      await user.click(screen.getByRole('button', { name: 'Undo' }));
      await waitFor(() => expect([...document.querySelectorAll('article.resume-paper h2')].map((heading) => heading.textContent)).toEqual(['Experience', 'Skills', 'Fun facts']));
    });

    it('saves my default with expected_revision and changes a style key in the live preview', async () => {
      const user = userEvent.setup();
      mockApi.putSettings.mockResolvedValue({ revision: 3, resume_defaults: {} });
      await openEditor(user);
      await user.selectOptions(screen.getByRole('combobox', { name: 'Accent colour' }), 'navy');
      expect(document.querySelector('article.resume-paper')!.className).toContain('accent-navy');
      await user.click(screen.getByRole('button', { name: 'Save as my default' }));
      await waitFor(() => expect(mockApi.putSettings).toHaveBeenCalled());
      expect(mockApi.putSettings.mock.calls[0][0]).toMatchObject({ expected_revision: 2, resume_defaults: { build: { points_per_item: 2 }, template: 'classic', layout: { accent_color: 'navy' } } });
    });
  });
});
