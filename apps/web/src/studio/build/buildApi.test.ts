import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createFromBank, suggestPlan } from './buildApi';
import type { BuildPlan } from './buildApi';

const fetchMock = vi.fn();
beforeEach(() => { vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.unstubAllGlobals(); fetchMock.mockReset(); });
const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('build API', () => {
  it('posts the job to the suggest endpoint', async () => {
    fetchMock.mockImplementation(async () => reply(200, { plan: { sections: [] }, reasons: {}, coverage: { covered: [], missing: [] }, strategy: 'keyword-v1' }));
    const result = await suggestPlan('job-1', 3);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/v1/resume-builds/suggest');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ job_id: 'job-1', points_per_item: 3 });
    expect(new Headers(init.headers).get('X-Dev-User')).toBeTruthy();
    expect(result.strategy).toBe('keyword-v1');
    await suggestPlan('job-2');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ job_id: 'job-2' });
  });
  it('posts the exact plan to from-bank and returns the document', async () => {
    const plan: BuildPlan = { title: 'T', template: 'classic', job_id: null, summary: { mode: 'profile' }, sections: [{ kind: 'skills', skill_ids: ['s1'] }] };
    fetchMock.mockImplementation(async () => reply(201, { id: 'r1' }));
    await expect(createFromBank(plan)).resolves.toEqual({ id: 'r1' });
    expect(fetchMock.mock.calls[0][0]).toBe('/v1/documents/from-bank');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(plan);
  });
  it('turns API errors into HttpError messages', async () => {
    fetchMock.mockImplementation(async () => reply(404, { error: { code: 'not_found', message: 'Job not found.' } }));
    await expect(suggestPlan('x')).rejects.toMatchObject({ message: 'Job not found.', status: 404, code: 'not_found' });
    fetchMock.mockRejectedValue(new TypeError('offline'));
    await expect(suggestPlan('x')).rejects.toMatchObject({ status: 0 });
  });
});
