import { afterEach, expect, it, vi } from 'vitest';
import { api, setDevUser } from './api';

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

it('sends confirmation with a bank revision on the HTTP contract', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({bank_revision:17}), {headers:{'Content-Type':'application/json'}}));
  vi.stubGlobal('fetch',fetch); setDevUser('alice');
  await api.confirmProfile(17);
  const [path, init] = fetch.mock.calls[0];
  expect(path).toMatch(/\/profile\/confirm$/);
  expect(JSON.parse(init.body)).toEqual({expected_bank_revision:17});
  expect(init.headers.get('X-Dev-User')).toBe('alice');
});

it('uses the selected local identity on private profile requests', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('{}', {headers:{'Content-Type':'application/json'}}));
  vi.stubGlobal('fetch',fetch); setDevUser('casey');
  await api.getBank();
  const [path, init] = fetch.mock.calls[0];
  expect(path).toMatch(/\/profile\/bank$/);
  expect(init.headers.get('X-Dev-User')).toBe('casey');
});

it('sends the right content type for Word resumes and surfaces server refusals', async () => {
  const docx = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const fetch = vi.fn()
    .mockResolvedValueOnce(reply({ upload_id: 'u1', upload_url: '/v1/uploads/u1/content' }, 201))
    .mockResolvedValueOnce(reply({ upload_id: 'u1', status: 'ready_for_review', page_count: null, error_code: null, message: 'ok', ai_available: false }))
    .mockResolvedValueOnce(reply({ upload_id: 'u1', filename: 'resume.docx', status: 'ready_for_review', page_count: null, extracted_text: 'Jordan', error_code: null }));
  vi.stubGlobal('fetch', fetch); setDevUser('alice');
  // An empty browser MIME type (common for .docx) must not leak through.
  await api.uploadResume(new File(['PK'], 'Resume.DOCX', { type: '' }));
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ filename: 'Resume.DOCX', content_type: docx });
  expect(fetch.mock.calls[1][1].headers.get('Content-Type')).toBe(docx);

  fetch.mockResolvedValueOnce(reply({ upload_id: 'u2', upload_url: '/v1/uploads/u2/content' }, 201))
    .mockResolvedValueOnce(reply({ error: { code: 'LEGACY_DOC', message: 'Save it as PDF or .docx and upload again.' } }, 422));
  await expect(api.uploadResume(new File(['x'], 'resume.pdf', { type: 'application/pdf' }))).rejects.toThrow('Save it as PDF or .docx and upload again.');
  expect(fetch.mock.calls[4][1].headers.get('Content-Type')).toBe('application/pdf');
});
