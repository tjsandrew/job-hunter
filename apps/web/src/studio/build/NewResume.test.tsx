import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../../api';
import { createFromBank, suggestPlan } from './buildApi';
import type { Suggestion } from './buildApi';
import { NewResume } from './NewResume';
import type { NewResumeStep } from './NewResume';
import { bank, resume } from './testData';

vi.mock('../../api', async (importOriginal) => ({ ...await importOriginal<typeof import('../../api')>(), api: { getBank: vi.fn(), getSettings: vi.fn(), createItem: vi.fn() } }));
vi.mock('./buildApi', () => ({ suggestPlan: vi.fn(), createFromBank: vi.fn() }));
const mockApi = vi.mocked(api), mockSuggest = vi.mocked(suggestPlan), mockCreate = vi.mocked(createFromBank);
const jobs = [{ id: 'job-1', title: 'Backend Engineer', company: 'Stripe', location: 'Singapore', work_mode: 'Hybrid' }, { id: 'job-2', title: 'Data Engineer', company: 'Grab' }];
const handlers = { onBlank: vi.fn(), onCopy: vi.fn(), onBuilt: vi.fn(), onClose: vi.fn() };
const suggestion = (): Suggestion => ({ strategy: 'keyword-v1', plan: { sections: [
  { kind: 'experience', items: [{ item_id: 'exp-1', picks: [{ bullet_id: 'b1' }, { bullet_id: 'b3', alternative_id: 'v1' }] }] },
  { kind: 'skills', skill_ids: ['skill-sql'] }] },
  reasons: { 'exp-1': ['matches FastAPI, PostgreSQL'], 'exp-1:b1': ['matches FastAPI'] }, coverage: { covered: ['PostgreSQL', 'FastAPI'], missing: ['Kubernetes'] } });

function open(props: { initial?: NewResumeStep; attachTarget?: { job_id: string; title: string } | null; resumes?: ReturnType<typeof resume>[] } = {}) {
  return render(<NewResume resumes={props.resumes || []} jobs={jobs} attachTarget={props.attachTarget || null} initial={props.initial} busy={false} {...handlers} />);
}
beforeEach(() => {
  vi.resetAllMocks();
  mockApi.getBank.mockImplementation(async () => bank());
  mockApi.getSettings.mockResolvedValue({ revision: 3, resume_defaults: { template: 'modern', build: { points_per_item: 2 } } });
  mockSuggest.mockImplementation(async () => suggestion());
  mockCreate.mockImplementation(async (plan) => resume({ title: plan.title }));
});
afterEach(() => cleanup());
const checked = (name: string | RegExp) => (screen.getByRole('checkbox', { name }) as HTMLInputElement).checked;

describe('new resume chooser', () => {
  it('offers four ways to start', () => {
    open();
    const group = screen.getByRole('group', { name: 'How to start' });
    expect(within(group).getAllByRole('button').map((button) => button.querySelector('b')!.textContent)).toEqual(['Blank', 'From my profile', 'For a job', 'Copy a resume']);
  });

  it('starts blank straight away', async () => {
    open(); await userEvent.click(screen.getByRole('button', { name: /^Blank/ }));
    expect(handlers.onBlank).toHaveBeenCalledTimes(1);
  });

  it('copies a chosen resume', async () => {
    const user = userEvent.setup(); const source = resume();
    open({ resumes: [source] });
    await user.click(screen.getByRole('button', { name: /^Copy a resume/ }));
    expect(screen.getByRole('button', { name: 'Create copy' })).toBeDisabled();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a resume to copy' }), source.id);
    await user.click(screen.getByRole('button', { name: 'Create copy' }));
    expect(handlers.onCopy).toHaveBeenCalledWith(source);
  });

  it('goes back to the library from the first screen', async () => {
    open(); await userEvent.click(screen.getByRole('button', { name: /Library/ }));
    expect(handlers.onClose).toHaveBeenCalled();
  });
});

describe('free build from my profile', () => {
  it('pre-selects everything newest first and caps points per item from settings', async () => {
    open({ initial: 'free' });
    await screen.findByRole('heading', { name: 'Experience' });
    expect(checked(/^Backend Engineer/)).toBe(true);
    expect(checked(/^Data Analyst/)).toBe(true);
    expect(checked(/^Booking app/)).toBe(true);
    expect(checked('Built FastAPI services on PostgreSQL.')).toBe(true);
    expect(checked('Made analytics dashboards 4x faster.')).toBe(true);
    expect(checked('Cut p95 query time by 40%.')).toBe(false);
    expect(screen.getByRole('combobox', { name: 'Template' })).toHaveValue('modern');
    expect(mockSuggest).not.toHaveBeenCalled();
  });

  it('re-selects by focus', async () => {
    const user = userEvent.setup(); open({ initial: 'free' });
    await user.click(await screen.findByRole('button', { name: 'backend' }));
    expect(screen.getByRole('button', { name: 'backend' })).toHaveAttribute('aria-pressed', 'true');
    expect(checked('Built FastAPI services on PostgreSQL.')).toBe(true);
    expect(checked('Cut p95 query time by 40%.')).toBe(true);
    expect(checked('Made analytics dashboards 4x faster.')).toBe(false);
    expect(screen.getByRole('checkbox', { name: /Data Analyst/ })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: /BSc Computer Science/ })).toBeChecked();
  });

  it('creates the resume from the exact plan with a general (null) job and reports it', async () => {
    const user = userEvent.setup(); open({ initial: 'free' });
    await user.click(await screen.findByRole('button', { name: 'backend' }));
    await user.selectOptions(screen.getByRole('combobox', { name: /^Wording for: Cut p95/ }), 'v1');
    await user.clear(screen.getByRole('textbox', { name: 'Resume title' })); await user.type(screen.getByRole('textbox', { name: 'Resume title' }), 'General');
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    await waitFor(() => expect(handlers.onBuilt).toHaveBeenCalled());
    expect(mockCreate).toHaveBeenCalledWith({ title: 'General', template: 'modern', job_id: null, summary: { mode: 'profile' }, sections: [
      { kind: 'experience', items: [{ item_id: 'exp-1', picks: [{ bullet_id: 'b1' }, { bullet_id: 'b3', alternative_id: 'v1' }] }] },
      { kind: 'education', items: [{ item_id: 'edu-1', picks: [] }] },
      { kind: 'skills', skill_ids: ['skill-py', 'skill-sql'] },
    ] });
    expect(handlers.onBuilt.mock.calls[0][0].title).toBe('General');
  });

  it('sends a custom empty summary when the profile summary is unticked, and shows API errors', async () => {
    const user = userEvent.setup(); open({ initial: 'free' });
    await user.click(await screen.findByRole('checkbox', { name: 'Use my profile summary' }));
    mockCreate.mockRejectedValueOnce(new Error('Profile changed.'));
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Profile changed.');
    expect(mockCreate.mock.calls[0][0].summary).toEqual({ mode: 'custom', text: '' });
    expect(handlers.onBuilt).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Create resume' })).toBeEnabled();
  });

  it('falls back to 4 points per item when settings cannot be read, and reorders items', async () => {
    mockApi.getSettings.mockRejectedValue(new Error('no settings'));
    const user = userEvent.setup(); open({ initial: 'free' });
    await screen.findByRole('heading', { name: 'Experience' });
    expect(checked('Added REST endpoints with integration tests.')).toBe(true);
    expect(checked('Mentored two interns.')).toBe(false);
    expect(screen.getByRole('combobox', { name: 'Template' })).toHaveValue('classic');
    await user.click(screen.getByRole('button', { name: 'Move Backend Engineer down' }));
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    expect(mockCreate.mock.calls[0][0].sections[0]).toMatchObject({ kind: 'experience', items: [{ item_id: 'exp-2' }, { item_id: 'exp-1' }] });
  });
});

describe('build for a job', () => {
  const pickJob = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: /^For a job/ }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a saved job' }), 'job-1');
    await user.click(screen.getByRole('button', { name: 'Match my profile' }));
  };

  it('suggests a plan with reasons and coverage', async () => {
    const user = userEvent.setup(); open(); await pickJob(user);
    expect(await screen.findByText('matches FastAPI, PostgreSQL')).toBeInTheDocument();
    expect(mockSuggest).toHaveBeenCalledWith('job-1', 2);
    expect(screen.getByText('matches FastAPI')).toBeInTheDocument();
    expect(screen.getByText('keyword-v1')).toBeInTheDocument();
    expect(screen.getByText('Stripe · Singapore · Hybrid')).toBeInTheDocument();
    expect(screen.getByText('2 of 3')).toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'Skills coverage' })).toHaveAttribute('aria-valuenow', '2');
    const covered = screen.getByRole('heading', { name: 'Covered' }).parentElement!;
    expect(within(covered).getByText('PostgreSQL')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add to profile: Kubernetes/ })).toBeInTheDocument();
    expect(checked('Built FastAPI services on PostgreSQL.')).toBe(true);
    expect(checked('Reduced p95 query latency by 40% across reporting.')).toBe(true);
    expect(checked('Made analytics dashboards 4x faster.')).toBe(false);
    expect(checked(/Data Analyst/)).toBe(false);
    expect(screen.getByRole('combobox', { name: /^Wording for: Cut p95/ })).toHaveValue('v1');
  });

  it('adds a missing skill to the profile and asks for new suggestions', async () => {
    const user = userEvent.setup(); open(); await pickJob(user);
    await screen.findByText('matches FastAPI, PostgreSQL');
    mockApi.createItem.mockResolvedValue({ ...bank().items[4], id: 'skill-k8s', data: { name: 'Kubernetes', category: 'tool', bullets: [] } });
    mockSuggest.mockImplementation(async () => ({ ...suggestion(), coverage: { covered: ['PostgreSQL', 'FastAPI', 'Kubernetes'], missing: [] } }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Category for Kubernetes' }), 'tool');
    await user.click(screen.getByRole('button', { name: /add to profile: Kubernetes/ }));
    await waitFor(() => expect(mockApi.createItem).toHaveBeenCalledWith({ kind: 'skill', data: { name: 'Kubernetes', category: 'tool', bullets: [] } }));
    await waitFor(() => expect(mockSuggest).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('3 of 3')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add to profile: Kubernetes/ })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Kubernetes added to your profile');
  });

  it('creates with the job id, the picked points and chosen versions after unticking and reordering', async () => {
    const user = userEvent.setup(); open(); await pickJob(user);
    await screen.findByText('matches FastAPI, PostgreSQL');
    await user.click(screen.getByRole('checkbox', { name: 'Built FastAPI services on PostgreSQL.' }));
    await user.click(screen.getByRole('checkbox', { name: /BSc Computer Science/ }));
    await user.click(screen.getByRole('checkbox', { name: 'Python' }));
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    await waitFor(() => expect(handlers.onBuilt).toHaveBeenCalled());
    expect(mockCreate).toHaveBeenCalledWith({ title: 'Backend Engineer – Stripe', template: 'modern', job_id: 'job-1', summary: { mode: 'profile' }, sections: [
      { kind: 'experience', items: [{ item_id: 'exp-1', picks: [{ bullet_id: 'b3', alternative_id: 'v1' }] }] },
      { kind: 'education', items: [{ item_id: 'edu-1', picks: [] }] },
      { kind: 'skills', skill_ids: ['skill-py', 'skill-sql'] },
    ] });
  });

  it('goes straight to the job from the tracker and keeps the job fixed', async () => {
    open({ initial: 'job', attachTarget: { job_id: 'job-2', title: 'Data Engineer' } });
    expect(await screen.findByText('matches FastAPI, PostgreSQL')).toBeInTheDocument();
    expect(mockSuggest).toHaveBeenCalledWith('job-2', 2);
    expect(screen.queryByRole('combobox', { name: 'Choose a saved job' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Create resume' }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    expect(mockCreate.mock.calls[0][0]).toMatchObject({ job_id: 'job-2', title: 'Data Engineer – Grab' });
  });

  it('says so when no job is saved, and surfaces suggest errors with a retry', async () => {
    cleanup();
    render(<NewResume resumes={[]} jobs={[]} attachTarget={null} initial="job" busy={false} {...handlers} />);
    expect(screen.getByText(/Save a job from Discover first/)).toBeInTheDocument();
    cleanup();
    mockSuggest.mockRejectedValueOnce(new Error('Job not found.'));
    open({ initial: 'job', attachTarget: { job_id: 'job-1', title: 'Backend Engineer' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Job not found.');
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('matches FastAPI, PostgreSQL')).toBeInTheDocument();
  });
});
