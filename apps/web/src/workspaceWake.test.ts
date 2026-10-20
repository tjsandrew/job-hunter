import { afterEach, beforeEach, expect, test, vi } from 'vitest';
vi.mock('./api', async importOriginal => {
  const original = await importOriginal<typeof import('./api')>();
  return {...original, api: {...original.api, me: vi.fn()}};
});
import { api, HttpError } from './api';
import { waitForWorkspace } from './workspaceWake';

beforeEach(() => { vi.useFakeTimers(); vi.mocked(api.me).mockReset(); });
afterEach(() => vi.useRealTimers());

test('retries temporary wake failures sequentially, then stops after success', async () => {
  vi.mocked(api.me).mockRejectedValueOnce(new HttpError('unavailable', 503))
    .mockRejectedValueOnce(new HttpError('throttled', 429)).mockResolvedValueOnce({} as never);
  const pending = waitForWorkspace(new AbortController().signal);
  await vi.advanceTimersByTimeAsync(4000);
  await pending;
  expect(api.me).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(600_000);
  expect(api.me).toHaveBeenCalledTimes(3);
});

test('authentication failures are not retried', async () => {
  vi.mocked(api.me).mockRejectedValue(new HttpError('sign in', 401));
  await expect(waitForWorkspace(new AbortController().signal)).rejects.toThrow('sign in');
  expect(api.me).toHaveBeenCalledTimes(1);
});

test('gives up after 45 seconds instead of creating an endless keep-alive', async () => {
  vi.mocked(api.me).mockRejectedValue(new HttpError('unavailable', 503));
  const pending = waitForWorkspace(new AbortController().signal);
  const rejected = expect(pending).rejects.toThrow('taking longer');
  await vi.advanceTimersByTimeAsync(45_000);
  await rejected;
  const calls = vi.mocked(api.me).mock.calls.length;
  await vi.advanceTimersByTimeAsync(600_000);
  expect(api.me).toHaveBeenCalledTimes(calls);
});

test('leaving the screen cancels a pending request and stops retries', async () => {
  vi.mocked(api.me).mockImplementation(signal => new Promise((_, reject) => {
    signal!.addEventListener('abort', () => reject(signal!.reason), {once: true});
  }));
  const controller = new AbortController();
  const pending = waitForWorkspace(controller.signal);
  const rejected = expect(pending).rejects.toMatchObject({name: 'AbortError'});
  controller.abort();
  await rejected;
  await vi.advanceTimersByTimeAsync(60_000);
  expect(api.me).toHaveBeenCalledTimes(1);
});
