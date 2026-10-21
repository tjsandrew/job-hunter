import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { BuildPlan } from './buildApi';
const auth = vi.hoisted(() => ({ accessToken: vi.fn() }));
vi.mock('../../auth', () => ({ cloudAuth: true, accessToken: auth.accessToken }));
const fetchMock = vi.fn();
beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks();
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.invalid/v1');
  vi.stubGlobal('fetch', fetchMock);
  auth.accessToken.mockResolvedValue('test-access-token');
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
const plan: BuildPlan = {title: 'Example', template: 'classic', job_id: null, summary: {mode: 'profile'}, sections: []};

it('authenticates both cloud resume-build endpoints without a development header', async () => {
  fetchMock.mockImplementation(async () => new Response('{}', {headers: {'Content-Type': 'application/json'}}));
  const { createFromBank, suggestPlan } = await import('./buildApi');
  await createFromBank(plan);
  await suggestPlan('job-1');
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    'https://api.example.invalid/v1/documents/from-bank',
    'https://api.example.invalid/v1/resume-builds/suggest',
  ]);
  for (const [, init] of fetchMock.mock.calls) {
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer test-access-token');
    expect(headers.has('X-Dev-User')).toBe(false);
    expect(headers.get('Content-Type')).toBe('application/json');
  }
});

it('shows a cloud network error without local-services instructions', async () => {
  fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
  const { createFromBank } = await import('./buildApi');
  await expect(createFromBank(plan)).rejects.toMatchObject({status: 0, message: 'Could not reach Job Hunter. Please try again.'});
});

it('preserves sign-in errors and does not send an unauthenticated request', async () => {
  auth.accessToken.mockRejectedValue(new Error('Your session expired. Please sign in again.'));
  const { createFromBank } = await import('./buildApi');
  await expect(createFromBank(plan)).rejects.toThrow('Your session expired');
  expect(fetchMock).not.toHaveBeenCalled();
});
