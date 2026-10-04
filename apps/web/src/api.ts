import type { Application, Me, ProfileDraft, Recommendation, Resume } from './types';

const base = (import.meta.env.VITE_API_BASE_URL || '/v1').replace(/\/$/, '');
export const devUserStorageKey = 'jh-dev-user';
export function getDevUser(): 'alice' | 'bob' {
  return (localStorage.getItem(devUserStorageKey) === 'bob' ? 'bob' : 'alice');
}
export function setDevUser(user: 'alice' | 'bob') { localStorage.setItem(devUserStorageKey, user); }

export class HttpError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) { super(message); this.status = status; this.code = code; }
}
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('X-Dev-User', getDevUser());
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  let response: Response;
  try { response = await fetch(`${base}${path}`, { ...init, headers }); }
  catch { throw new HttpError('Could not reach the Job Hunter API. Check that the local services are running.', 0); }
  if (!response.ok) {
    let body: any = {};
    try { body = await response.json(); } catch { /* response may not contain JSON */ }
    throw new HttpError(body?.error?.message || body?.detail || `Request failed (${response.status}).`, response.status, body?.error?.code);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/pdf')) return (await response.blob()) as T;
  return response.json() as Promise<T>;
}
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  me: () => request<Me>('/me'),
  uploadResume: async (file: File) => {
    const created = await request<{ upload_id: string; upload_url: string }>('/uploads', json('POST', { filename: file.name, content_type: file.type, size_bytes: file.size }));
    const path = created.upload_url.startsWith(base) ? created.upload_url.slice(base.length) : created.upload_url.replace(/^\/v1/, '');
    const uploaded = await request<{ upload_id: string; status: string; page_count: number | null; error_code: string | null; message: string; ai_available: boolean }>(path, { method: 'PUT', headers: { 'Content-Type': 'application/pdf' }, body: file });
    const extracted = await request<{ upload_id: string; filename: string; status: string; page_count: number | null; extracted_text: string | null; error_code: string | null }>(`/uploads/${encodeURIComponent(created.upload_id)}`);
    return { ...uploaded, extracted_text: extracted.extracted_text, filename: extracted.filename };
  },
  getProfile: () => request<{ draft: ProfileDraft; revision: number; confirmed_revision: number | null }>('/profile'),
  putProfile: (draft: ProfileDraft, expected_revision: number) => request('/profile', json('PUT', { draft, expected_revision })),
  confirmProfile: (expected_revision: number) => request('/profile/confirm', json('POST', { expected_revision })),
  getPreferences: () => request<any>('/preferences'),
  putPreferences: (values: unknown) => request('/preferences', json('PUT', values)),
  recommendations: (q = '', offset = 0, limit = 20) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (q.trim()) params.set('q', q.trim());
    return request<{ items: Recommendation[]; total: number; next_offset: number | null; degraded_mode?: boolean; ranking_status?: string; ranking_mode?: string }>(`/recommendations?${params}`);
  },
  reviewJob: (id: string, decision: 'saved' | 'dismissed' | 'none') => request(`/jobs/${encodeURIComponent(id)}/review`, json('PUT', { decision })),
  applications: () => request<{ items: Application[] }>('/applications'),
  putApplication: (jobId: string, values: Partial<Application> & { expected_revision?: number; resume_document_id?: string; expected_resume_revision?: number; resume_export_id?: string | null; cover_letter_text?: string | null }) => request<Application>(`/applications/${encodeURIComponent(jobId)}`, json('PUT', values)),
  documents: () => request<{ items: Resume[] }>('/documents?kind=resume'),
  createDocument: (values: { title: string; template: string; content: unknown; layout: unknown; job_id?: string }) => request<Resume>('/documents', json('POST', values)),
  patchDocument: (id: string, values: Partial<Resume> & { expected_revision: number }) => request<Resume>(`/documents/${encodeURIComponent(id)}`, json('PATCH', values)),
  duplicateDocument: (id: string, title?: string, job_id?: string) => request<Resume>(`/documents/${encodeURIComponent(id)}/duplicate`, json('POST', { title, job_id })),
  reviewDocument: (id: string, expected_revision: number) => request<Resume>(`/documents/${encodeURIComponent(id)}/review`, json('POST', { expected_revision })),
  exportDocument: (id: string) => request<{ export_id: string; revision: number; download_url: string }>(`/documents/${encodeURIComponent(id)}/exports`, json('POST')),
  previewDocument: (id: string) => request<Blob>(`/documents/${encodeURIComponent(id)}/preview.pdf`),
  downloadExport: (id: string) => request<Blob>(`/exports/${encodeURIComponent(id)}`),
};
