import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpError } from './api';
import { FitPanel } from './FitPanel';
import type { FitAnalysis } from './types';

const mockApi = vi.hoisted(() => ({ startFit: vi.fn(), jobFit: vi.fn(), fit: vi.fn() }));
vi.mock('./api', async (original) => ({ ...(await original<typeof import('./api')>()), api: mockApi }));

const ready = (overrides: Partial<FitAnalysis> = {}): FitAnalysis => ({
  id: 'a1', job_id: 'j1', status: 'ready', error_code: null, profile_revision: 1, stale: false, created_at: '2026-10-24T00:00:00Z', completed_at: '2026-10-24T00:00:30Z',
  result: {
    model: 'gemma4:26b',
    requirements: [{ text: '3 years of Python', importance: 'must' }, { text: 'Kubernetes', importance: 'must' }, { text: 'Degree in Computer Science', importance: 'must' }],
    verdicts: [{ verdict: 'met', evidence: ['b1'], note: 'Built pipelines.' }, { verdict: 'not_evidenced', evidence: [], note: '' }, { verdict: 'needs_judgement', evidence: [], note: '' }],
    suggestions: [{ kind: 'add', requirement: 1, bullet_id: null, text: 'Mention Kubernetes if you have used it.' }],
    coverage: { percent: 50, met: 1, partly: 0, considered: 2, needs_judgement: 1, unanswered: 0, basis: 'must-have requirements' },
    evidence: { b1: 'Designed incremental SQL pipelines.' },
  },
  ...overrides,
});

beforeEach(() => { vi.clearAllMocks(); mockApi.jobFit.mockRejectedValue(new HttpError('Not found', 404)); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

const panel = (props: Partial<{ available: boolean; remaining: number }> = {}, onUsed = vi.fn()) =>
  render(<FitPanel jobId="j1" available remaining={5} onUsed={onUsed} {...props} />);

describe('FitPanel', () => {
  it('shows a saved analysis with the percentage, its meaning, evidence and suggestions', async () => {
    mockApi.jobFit.mockResolvedValue(ready());
    panel();
    expect(await screen.findByText('50%')).toBeInTheDocument();
    expect(screen.getByText(/not a chance of being hired/i)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Your profile shows' })).toHaveTextContent('3 years of Python');
    expect(screen.getByText(/From your profile: Designed incremental SQL pipelines\./)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Not evidenced in your profile' })).toHaveTextContent('Kubernetes');
    expect(screen.getByRole('region', { name: 'Needs your judgement' })).toHaveTextContent('Degree in Computer Science');
    expect(screen.getByText(/Mention Kubernetes if you have used it/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run again' })).toBeEnabled();
  });

  it('starts an analysis, waits while it is pending, then shows the result', async () => {
    const onUsed = vi.fn();
    mockApi.startFit.mockResolvedValue(ready({ status: 'pending', result: null }));
    mockApi.fit.mockResolvedValue(ready());
    const user = userEvent.setup();
    panel({}, onUsed);
    await user.click(await screen.findByRole('button', { name: 'Check my fit' }));
    expect(await screen.findByText(/This takes about 30 seconds/)).toBeInTheDocument();
    expect(await screen.findByText('50%', undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(mockApi.fit).toHaveBeenCalledWith('a1');
    expect(onUsed).toHaveBeenCalledTimes(1);          // refreshes the monthly allowance exactly once
  });

  it('says so when the profile changed after the analysis', async () => {
    mockApi.jobFit.mockResolvedValue(ready({ stale: true }));
    panel();
    expect(await screen.findByText(/Your profile changed after this analysis/)).toBeInTheDocument();
  });

  it('shows no percentage when too little could be checked', async () => {
    const analysis = ready();
    analysis.result!.coverage = { ...analysis.result!.coverage, percent: null };
    mockApi.jobFit.mockResolvedValue(analysis);
    panel();
    expect(await screen.findByText('No score')).toBeInTheDocument();
  });

  it('explains a failed analysis in plain words', async () => {
    mockApi.jobFit.mockResolvedValue(ready({ status: 'failed', result: null, error_code: 'MODEL_UNAVAILABLE' }));
    panel();
    expect(await screen.findByRole('alert')).toHaveTextContent('The AI model could not be reached');
  });

  it('asks to confirm the profile when the server refuses with 409', async () => {
    mockApi.startFit.mockRejectedValue(new HttpError('Confirm your profile before analysing a job', 409, 'PROFILE_NOT_CONFIRMED'));
    const user = userEvent.setup();
    panel();
    await user.click(await screen.findByRole('button', { name: 'Check my fit' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Confirm your profile first');
  });

  it('disables the button when AI is off or the month is used up, but still shows an existing result', async () => {
    panel({ available: false });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Check my fit' })).toBeDisabled());
    expect(screen.getByText('AI is not available right now.')).toBeInTheDocument();
    cleanup();
    mockApi.jobFit.mockResolvedValue(ready());
    panel({ remaining: 0 });
    expect(await screen.findByText('50%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run again' })).toBeEnabled();   // this job already has its slot this month
  });

  it('blocks a new job when no uses are left', async () => {
    panel({ remaining: 0 });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Check my fit' })).toBeDisabled());
    expect(screen.getByText(/used all your AI uses for this month/)).toBeInTheDocument();
  });
});
