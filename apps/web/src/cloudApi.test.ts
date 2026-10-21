import { afterEach, beforeEach, expect, test, vi } from 'vitest';
vi.mock('./auth', () => ({ cloudAuth: true, accessToken: async () => 'test-access-token' }));
import { api } from './api';

const reply = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
beforeEach(() => { vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => { vi.unstubAllGlobals(); });

test('cloud API uses the access token and never sends the development identity', async () => {
  vi.mocked(fetch).mockResolvedValue(reply({ user_id: 'test' }));
  await api.me();
  const headers = new Headers(vi.mocked(fetch).mock.calls[0][1]?.headers);
  expect(headers.get('Authorization')).toBe('Bearer test-access-token');
  expect(headers.has('X-Dev-User')).toBe(false);
});

test('direct S3 upload receives no API credentials; finalization is authenticated', async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(reply({ upload_id: 'upload-1', upload_url: 'https://documents.example.test/signed-put', finalize_url: '/v1/uploads/upload-1/finalize' }))
    .mockResolvedValueOnce(new Response('', { status: 200 }))
    .mockResolvedValueOnce(reply({ upload_id: 'upload-1', status: 'ready_for_review' }))
    .mockResolvedValueOnce(reply({ filename: 'resume.pdf', extracted_text: 'Fictional resume' }));
  const result = await api.uploadResume(new File(['%PDF-test'], 'resume.pdf', { type: 'application/pdf' }));
  const calls = vi.mocked(fetch).mock.calls;
  expect(calls[1][0]).toBe('https://documents.example.test/signed-put');
  expect(new Headers(calls[1][1]?.headers).has('Authorization')).toBe(false);
  expect(new Headers(calls[1][1]?.headers).has('X-Dev-User')).toBe(false);
  expect(String(calls[2][0])).toContain('/uploads/upload-1/finalize');
  expect(new Headers(calls[2][1]?.headers).get('Authorization')).toBe('Bearer test-access-token');
  expect(result.extracted_text).toBe('Fictional resume');
});

test('a failed S3 upload never finalizes or imports missing bytes', async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(reply({ upload_id: 'upload-1', upload_url: 'https://documents.example.test/signed-put', finalize_url: '/v1/uploads/upload-1/finalize' }))
    .mockResolvedValueOnce(new Response('', { status: 403 }));
  await expect(api.uploadResume(new File(['data'], 'resume.pdf'))).rejects.toThrow('Resume upload failed');
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('cloud downloads return signed URLs without following a storage redirect', async () => {
  vi.mocked(fetch).mockImplementation(async () => reply({url: 'https://documents.example.test/signed-download'}));
  expect(await api.downloadExport('export-1')).toEqual({url: 'https://documents.example.test/signed-download'});
  expect(await api.downloadUpload('upload-1')).toEqual({url: 'https://documents.example.test/signed-download'});
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).startsWith('https://documents.'))).toBe(true);
});

test.each([[401, 'sign in again'], [429, 'Too many requests']])('gateway %s has a useful message', async (status, message) => {
  vi.mocked(fetch).mockResolvedValue(new Response('{"message":"gateway error"}', {status}));
  await expect(api.me()).rejects.toThrow(message);
});
