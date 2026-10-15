import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../../api';
import { createFromBank, suggestPlan } from './buildApi';
import type { Suggestion } from './buildApi';
import { NewResume } from './NewResume';
import type { NewResumeStep } from './NewResume';
import { applyFocus, applyOverrides, bankToDraft, draftToPlan, moveDraftItem, noOverrides, recordOverrides } from './buildPlan';
import { bank, bankWithExtras, resume } from './testData';

vi.mock('../../api', async (importOriginal) => ({ ...await importOriginal<typeof import('../../api')>(), api: { getBank: vi.fn(), getSettings: vi.fn(), createItem: vi.fn() } }));
vi.mock('./buildApi', () => ({ suggestPlan: vi.fn(), createFromBank: vi.fn() }));
const mockApi = vi.mocked(api), mockSuggest = vi.mocked(suggestPlan), mockCreate = vi.mocked(createFromBank);
const jobs = [{ id: 'job-1', title: 'Backend Engineer', company: 'Stripe' }];
const handlers = { onBlank: vi.fn(), onCopy: vi.fn(), onBuilt: vi.fn(), onClose: vi.fn() };
const open = (initial?: NewResumeStep) => render(<NewResume resumes={[]} jobs={jobs} attachTarget={null} initial={initial} busy={false} {...handlers} />);
const checked = (name: string | RegExp) => (screen.getByRole('checkbox', { name }) as HTMLInputElement).checked;
const suggestion = (extra: Suggestion['plan']['sections'] = []): Suggestion => ({ strategy: 'keyword-v1', plan: { sections: [
  { kind: 'experience', items: [{ item_id: 'exp-1', picks: [{ bullet_id: 'b1' }, { bullet_id: 'b3', alternative_id: 'v1' }] }, ...(extra.length ? [{ item_id: 'exp-2', picks: [{ bullet_id: 'd1' }] }] : [])] },
  ...extra, { kind: 'skills', skill_ids: ['skill-sql'] }] },
  reasons: {}, coverage: { covered: ['PostgreSQL'], missing: ['Kubernetes'] } });

beforeEach(() => {
  vi.resetAllMocks();
  mockApi.getBank.mockImplementation(async () => bankWithExtras());
  mockApi.getSettings.mockResolvedValue({ revision: 1, resume_defaults: { build: { points_per_item: 2 } } });
  mockSuggest.mockImplementation(async () => suggestion());
  mockCreate.mockImplementation(async (plan) => resume({ title: plan.title }));
});
afterEach(() => cleanup());

describe('certifications, awards and volunteering in the build plan', () => {
  it('lists them as their own groups with issuer and awarder', async () => {
    open('free');
    expect(await screen.findByRole('heading', { name: 'Certifications' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /AWS Developer Associate.*Amazon/ })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Hackathon winner.*City Council/ })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Mentor.*Code Club/ })).toBeInTheDocument();
  });

  it('ticks certifications but leaves awards and volunteering for the user until a focus asks for them', async () => {
    const user = userEvent.setup(); open('free');
    await screen.findByRole('heading', { name: 'Certifications' });
    expect(checked(/AWS Developer Associate/)).toBe(true);
    expect(checked(/Hackathon winner/)).toBe(false);
    expect(checked(/^Mentor(?!ed)/)).toBe(false);
    await user.click(screen.getByRole('button', { name: 'backend' }));
    expect(checked(/Hackathon winner/)).toBe(true);   // tagged backend
    expect(checked(/^Mentor(?!ed)/)).toBe(false);
    await user.click(screen.getByRole('button', { name: 'education' }));
    expect(checked(/^Mentor(?!ed)/)).toBe(true);             // a point tagged education
    expect(checked('Taught Python to teenagers.')).toBe(true);
  });

  it('sends the new kinds to the server after the section they belong in', async () => {
    const user = userEvent.setup(); open('free');
    await user.click(await screen.findByRole('checkbox', { name: /Hackathon winner/ }));
    await user.click(screen.getByRole('checkbox', { name: /^Mentor(?!ed)/ }));
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const sections = mockCreate.mock.calls[0][0].sections;
    expect(sections.map((section) => section.kind)).toEqual(['experience', 'education', 'projects', 'skills', 'certifications', 'volunteering', 'awards']);
    expect(sections[4]).toEqual({ kind: 'certifications', items: [{ item_id: 'cert-1', picks: [] }] });
    expect(sections[5]).toEqual({ kind: 'volunteering', items: [{ item_id: 'vol-1', picks: [{ bullet_id: 'v-b1' }] }] });
    expect(sections[6]).toEqual({ kind: 'awards', items: [{ item_id: 'award-1', picks: [] }] });
  });

  it('shows a suggested certification ticked', async () => {
    const user = userEvent.setup(); open();
    mockSuggest.mockImplementation(async () => suggestion([{ kind: 'certifications', items: [{ item_id: 'cert-1', picks: [] }] }]));
    await user.click(screen.getByRole('button', { name: /^For a job/ }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a saved job' }), 'job-1');
    await user.click(screen.getByRole('button', { name: 'Match my profile' }));
    await screen.findByRole('heading', { name: 'Certifications' });
    expect(checked(/AWS Developer Associate/)).toBe(true);
    expect(checked(/Hackathon winner/)).toBe(false);
  });
});

describe('manual choices survive new suggestions', () => {
  const pickJob = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: /^For a job/ }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Choose a saved job' }), 'job-1');
    await user.click(screen.getByRole('button', { name: 'Match my profile' }));
    await screen.findByText('keyword-v1');
  };

  it('keeps ticks, unticks, order and wording after "I have this · add to profile", and gives new items the new defaults', async () => {
    const user = userEvent.setup(); open(); await pickJob(user);
    await user.click(screen.getByRole('checkbox', { name: 'Built FastAPI services on PostgreSQL.' }));   // manual untick
    await user.click(screen.getByRole('checkbox', { name: 'Made analytics dashboards 4x faster.' }));    // manual tick
    await user.selectOptions(screen.getByRole('combobox', { name: /^Wording for: Cut p95/ }), '');       // back to the main wording
    await user.click(screen.getByRole('button', { name: 'Move point down: Made analytics dashboards 4x faster.' }));
    await user.click(screen.getByRole('button', { name: 'Move Data Analyst up' }));

    mockApi.createItem.mockResolvedValue({ ...bank().items[4], id: 'skill-k8s' });
    mockSuggest.mockImplementation(async () => suggestion([{ kind: 'certifications', items: [{ item_id: 'cert-1', picks: [] }] }]));  // now also picks exp-2 and a certification
    await user.click(screen.getByRole('button', { name: /add to profile: Kubernetes/ }));
    await waitFor(() => expect(mockSuggest).toHaveBeenCalledTimes(2));
    await screen.findByRole('heading', { name: 'Certifications' });

    expect(checked('Built FastAPI services on PostgreSQL.')).toBe(false);
    expect(checked('Made analytics dashboards 4x faster.')).toBe(true);
    expect(screen.getByRole('combobox', { name: /^Wording for: Cut p95/ })).toHaveValue('');
    const order = screen.getAllByRole('checkbox', { name: /^(Backend Engineer|Data Analyst)/ }).map((box) => box.closest('label')!.textContent || '');
    expect(order[0]).toMatch(/Data Analyst/); expect(order[1]).toMatch(/Backend Engineer/);
    expect(checked(/^Data Analyst/)).toBe(true);           // newly suggested: takes the suggestion
    expect(checked('Automated weekly reports.')).toBe(true);
    expect(checked(/AWS Developer Associate/)).toBe(true);
  });

  it('keeps manual choices when the free-build focus changes', async () => {
    const user = userEvent.setup(); open('free');
    await user.click(await screen.findByRole('button', { name: 'backend' }));
    expect(checked(/^Data Analyst/)).toBe(false);
    await user.click(screen.getByRole('checkbox', { name: /^Data Analyst/ }));                       // manual tick (focus would leave it out)
    await user.click(screen.getByRole('checkbox', { name: 'Built FastAPI services on PostgreSQL.' })); // manual untick
    await user.click(screen.getByRole('button', { name: 'backend' }));     // focus off: everything is the default again
    await user.click(screen.getByRole('button', { name: 'leadership' }));
    expect(checked(/^Data Analyst/)).toBe(true);
    expect(checked('Built FastAPI services on PostgreSQL.')).toBe(false);
    expect(checked('Mentored two interns.')).toBe(true);                                              // untouched: follows the new focus
    expect(checked('Cut p95 query time by 40%.')).toBe(false);
  });
});

describe('projects under their job', () => {
  it('lists a project of a job under that job, indented, and not again under Projects', async () => {
    open('free');
    const experience = await screen.findByRole('region', { name: 'Experience' });
    const nested = within(experience).getByRole('checkbox', { name: /Billing rewrite/ });
    expect(nested.closest('.plan-item')).toHaveClass('nested');
    expect(within(nested.closest('.plan-item') as HTMLElement).getByText('Project in this role')).toBeInTheDocument();
    const projects = screen.getByRole('region', { name: 'Projects' });
    expect(within(projects).queryByRole('checkbox', { name: /Billing rewrite/ })).toBeNull();
    expect(within(projects).getByRole('checkbox', { name: /Booking app/ })).toBeInTheDocument();
  });

  it('still lists a project without a job under Projects, and the plan stays flat', async () => {
    const user = userEvent.setup(); open('free');
    await screen.findByRole('checkbox', { name: /Billing rewrite/ });
    await user.click(screen.getByRole('button', { name: 'Create resume' }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const projects = mockCreate.mock.calls[0][0].sections.find((section) => section.kind === 'projects');
    expect(projects && 'items' in projects ? projects.items.map((entry) => entry.item_id) : []).toEqual(['proj-job', 'proj-1']);
    expect(mockCreate.mock.calls[0][0].sections.some((section) => section.kind === 'experience' && section.items.some((entry) => entry.item_id === 'proj-job'))).toBe(false);
  });

  it('moves a nested project only among the projects of its own job', () => {
    const data = bankWithExtras();
    data.items.push({ ...data.items.find((row) => row.id === 'proj-job')!, id: 'proj-job-2', data: { name: 'Second', bullets: [] } });
    const draft = bankToDraft(data);
    const ids = (value: typeof draft) => value.items.filter((row) => row.kind === 'projects').map((row) => row.id);
    const before = ids(draft);
    const moved = moveDraftItem(draft, 'proj-job-2', -1);
    expect(ids(moved)).not.toEqual(before);
    expect(moveDraftItem(draft, 'proj-1', -1)).toBe(draft);   // the only project without a job
  });
});

describe('overrides', () => {
  it('records an edit and lays it over fresh defaults, ignoring items that disappeared', () => {
    const base = applyFocus(bankToDraft(bank()), [], 4);
    const edited = { ...base, items: base.items.map((item) => item.id === 'exp-2' ? { ...item, on: false } : item) };
    const recorded = recordOverrides(base, edited, noOverrides());
    expect(recorded.items).toEqual({ 'exp-2': false });
    const fresh = applyFocus(bankToDraft(bank()), ['backend'], 4);
    expect(applyOverrides(fresh, recorded).items.find((item) => item.id === 'exp-2')!.on).toBe(false);
    const smaller = { ...fresh, items: fresh.items.filter((item) => item.id !== 'exp-2') };
    expect(applyOverrides(smaller, recorded).items.some((item) => item.id === 'exp-2')).toBe(false);
    const plan = draftToPlan(applyOverrides(fresh, recorded), { title: 'T', template: 'classic', job_id: null, summary: { mode: 'profile' } });
    expect(JSON.stringify(plan)).not.toContain('exp-2');
  });
});
