import type { Application, Me, ProfileDraft, Recommendation, Resume, ProfileResponse, ProfileBank, ProfileItem, ItemKind, ItemData, ItemChanges, PointWrite, PointUpdate, UserSettings, UploadedResume, ProfileExport, ProfileImport, ImportSource, ImportDecision, ImportResult } from './types';
import { accessToken, cloudAuth } from './auth';

const base = (import.meta.env.VITE_API_BASE_URL || '/v1').replace(/\/$/, '');
export const devUserStorageKey = 'jh-dev-user';
export function getDevUser(): 'alice' | 'casey' {
  return (localStorage.getItem(devUserStorageKey) === 'casey' ? 'casey' : 'alice');
}
export function setDevUser(user: 'alice' | 'casey') { localStorage.setItem(devUserStorageKey, user); }

export class HttpError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) { super(message); this.status = status; this.code = code; }
}

// Share concurrent reads only. Keys include identity, and writes invalidate the
// pool so a read after saving cannot reuse a request started before that save.
const pendingReads = new Map<string, Promise<Response>>();
async function fetchApi(url: string, init: RequestInit): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase();
  if (method !== 'GET') {
    pendingReads.clear();
    return fetch(url, init);
  }
  // A caller with cancellation owns its request independently.
  if (init.signal) return fetch(url, init);
  const key = JSON.stringify([url, [...new Headers(init.headers).entries()]]);
  let task = pendingReads.get(key);
  if (!task) {
    task = fetch(url, init);
    pendingReads.set(key, task);
    const clear = () => { if (pendingReads.get(key) === task) pendingReads.delete(key); };
    void task.then(clear, clear);
  }
  return (await task).clone();
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (cloudAuth) headers.set('Authorization', `Bearer ${await accessToken()}`);
  else headers.set('X-Dev-User', getDevUser());
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  let response: Response;
  try { response = await fetchApi(`${base}${path}`, { ...init, headers }); }
  catch (cause) {
    if (init.signal?.aborted) throw cause;
    throw new HttpError(cloudAuth ? 'Could not reach Job Hunter. Please try again.' : 'Could not reach the Job Hunter API. Check that the local services are running.', 0);
  }
  if (!response.ok) {
    let body: any = {};
    try { body = await response.json(); } catch { /* response may not contain JSON */ }
    throw new HttpError(body?.error?.message || body?.detail?.message || (typeof body?.detail === 'string' ? body.detail : undefined) || (response.status === 401 ? 'Your session expired. Please sign in again.' : response.status === 429 ? 'Too many requests. Please wait a moment and try again.' : `Request failed (${response.status}).`), response.status, body?.error?.code);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) return response.json() as Promise<T>;
  return (await response.blob()) as T;
}
// Shared by feature clients so cloud authentication and error handling stay consistent.
export { request as apiRequest };

// The browser's MIME type for .docx is sometimes empty, so the type sent follows the extension (the server re-checks the bytes).
export const resumeContentType = (file: { name: string }) => file.name.toLowerCase().endsWith('.docx') ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : file.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : '';
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  me: (signal?: AbortSignal) => request<Me>('/me', {signal}),
  uploadResume: async (file: File) => {
    const created = await request<{ upload_id: string; upload_url: string; finalize_url?: string }>('/uploads', json('POST', { filename: file.name, content_type: resumeContentType(file), size_bytes: file.size }));
    if (created.finalize_url) {
      const response = await fetch(created.upload_url, { method: 'PUT', headers: { 'Content-Type': resumeContentType(file) }, body: file });
      if (!response.ok) throw new HttpError('Resume upload failed. Please try again.', response.status);
      const uploaded = await request<{ upload_id: string; status: string; page_count: number | null; error_code: string | null; message: string; ai_available: boolean }>(`/uploads/${encodeURIComponent(created.upload_id)}/finalize`, json('POST'));
      const extracted = await request<{ filename: string; extracted_text: string | null }>(`/uploads/${encodeURIComponent(created.upload_id)}`);
      return { ...uploaded, ...extracted };
    }
    const path = created.upload_url.startsWith(base) ? created.upload_url.slice(base.length) : created.upload_url.replace(/^\/v1/, '');
    const uploaded = await request<{ upload_id: string; status: string; page_count: number | null; error_code: string | null; message: string; ai_available: boolean }>(path, { method: 'PUT', headers: { 'Content-Type': resumeContentType(file) }, body: file });
    const extracted = await request<{ upload_id: string; filename: string; status: string; page_count: number | null; extracted_text: string | null; error_code: string | null }>(`/uploads/${encodeURIComponent(created.upload_id)}`);
    return { ...uploaded, extracted_text: extracted.extracted_text, filename: extracted.filename };
  },
  getProfile: () => request<ProfileResponse>('/profile'),
  putProfile: (draft: ProfileDraft, expected_revision: number) => request<ProfileResponse>('/profile', json('PUT', { draft, expected_revision })),
  confirmProfile: (expected_bank_revision: number) => request<{revision: number; bank_revision: number; profile_version_id: string}>('/profile/confirm', json('POST', { expected_bank_revision })),
  startImport: (values: ImportSource) => request<ProfileImport>('/profile/imports', json('POST', values)),
  getImport: (id: string) => request<ProfileImport>(`/profile/imports/${encodeURIComponent(id)}`),
  imports: () => request<{items: ProfileImport[]; next_cursor: null}>('/profile/imports'),
  applyImport: (id: string, decisions: ImportDecision[], expected_profile_epoch: number) => request<ImportResult>(`/profile/imports/${encodeURIComponent(id)}/apply`, json('POST', {decisions, expected_profile_epoch})),
  discardImport: (id: string) => request<ProfileImport>(`/profile/imports/${encodeURIComponent(id)}/discard`, json('POST')),
  retryImport: (id: string) => request<ProfileImport>(`/profile/imports/${encodeURIComponent(id)}/retry`, json('POST')),
  getBank: () => request<ProfileBank>('/profile/bank'),
  getItem: (id: string) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}`),
  createItem: (values: {kind: ItemKind; data: ItemData; tags?: string[]; parent_id?: string | null}) => request<ProfileItem>('/profile/items', json('POST', values)),
  patchItem: (id: string, values: ItemChanges) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}`, json('PATCH', values)),
  archiveItem: (id: string, expected_revision: number) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}?expected_revision=${expected_revision}`, json('DELETE')),
  reorderItems: (values: {kind: ItemKind; item_ids: string[]; expected_bank_revision: number}) => request<ProfileBank>('/profile/items/order', json('PUT', values)),
  addPoint: (id: string, values: PointWrite) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}/bullets`, json('POST', values)),
  updatePoint: (id: string, pointId: string, values: PointUpdate) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}/bullets/${encodeURIComponent(pointId)}`, json('PUT', values)),
  addAlternative: (id: string, pointId: string, values: PointWrite) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}/bullets/${encodeURIComponent(pointId)}/alternatives`, json('POST', values)),
  revertItem: (id: string, values: ItemChanges) => request<ProfileItem>(`/profile/items/${encodeURIComponent(id)}/revert`, json('POST', values)),
  getSettings: () => request<UserSettings>('/settings'),
  putSettings: (values: Omit<UserSettings, 'revision'> & {expected_revision: number}) => request<UserSettings>('/settings', json('PUT', {resume_defaults: values.resume_defaults, expected_revision: values.expected_revision})),
  deleteProfile: (values: {confirmation: 'DELETE'; delete_settings: boolean}) => request<{deleted: boolean; bank_revision: number; profile_epoch: number}>('/profile/data', json('DELETE', values)),
  exportProfile: () => request<ProfileExport>('/profile/export.json'),
  deleteUpload: (id: string) => request<void>(`/uploads/${encodeURIComponent(id)}`, json('DELETE')),
  uploads: () => request<{items: UploadedResume[]; next_cursor: null}>('/uploads'),
  downloadUpload: (id: string) => request<Blob | {url: string}>(`/uploads/${encodeURIComponent(id)}/download`),
  getPreferences: () => request<any>('/preferences'),
  getSeniorityOptions: () => request<{items: {value: string; label: string}[]}>('/preferences/seniority-options'),
  putPreferences: (values: unknown) => request('/preferences', json('PUT', values)),
  recommendations: (q = '', offset = 0, limit = 20) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (q.trim()) params.set('q', q.trim());
    return request<{ items: Recommendation[]; total: number; next_offset: number | null; degraded_mode?: boolean; ranking_status?: string; ranking_mode?: string }>(`/recommendations?${params}`);
  },
  recommendationsForYou: (q = '', offset = 0, limit = 20) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (q.trim()) params.set('q', q.trim());
    return request<{ items: Recommendation[]; total: number; next_offset: number | null; degraded_mode?: boolean; ranking_status?: string; ranking_mode?: 'semantic' | 'keyword_fallback'; fallback_reason?: string | null; fallback_code?: 'no_profile' | 'profile_embedding_pending' | null; blocked_by_checks?: number }>(`/recommendations/for-you?${params}`);
  },
  reviewJob: (id: string, decision: 'saved' | 'dismissed' | 'none') => request(`/jobs/${encodeURIComponent(id)}/review`, json('PUT', { decision })),
  applications: () => request<{ items: Application[] }>('/applications'),
  putApplication: (jobId: string, values: Partial<Application> & { expected_revision?: number; resume_document_id?: string; expected_resume_revision?: number; resume_export_id?: string | null; cover_letter_text?: string | null }) => request<Application>(`/applications/${encodeURIComponent(jobId)}`, json('PUT', values)),
  documents: () => request<{ items: Resume[] }>('/documents?kind=resume'),
  createDocument: (values: { title: string; template: string; content: unknown; layout: unknown; job_id?: string }) => request<Resume>('/documents', json('POST', values)),
  patchDocument: (id: string, values: Partial<Resume> & { expected_revision: number }) => request<Resume>(`/documents/${encodeURIComponent(id)}`, json('PATCH', values)),
  archiveDocument: (id: string) => request<void>(`/documents/${encodeURIComponent(id)}`, json('DELETE')),
  restoreDocument: (id: string) => request<Resume>(`/documents/${encodeURIComponent(id)}/restore`, json('POST')),
  duplicateDocument: (id: string, title?: string, job_id?: string) => request<Resume>(`/documents/${encodeURIComponent(id)}/duplicate`, json('POST', { title, job_id })),
  tailorDocument: (id: string, job_id: string, title?: string, mode: 'rules' | 'ai' = 'rules') => request<{ document: Resume; matched: string[]; missing: string[]; ai: { status: 'off' | 'applied' | 'unchanged' | 'fallback'; changed: number; reason: string | null } }>(`/documents/${encodeURIComponent(id)}/tailor`, json('POST', { job_id, title, mode })),
  reviewDocument: (id: string, expected_revision: number) => request<Resume>(`/documents/${encodeURIComponent(id)}/review`, json('POST', { expected_revision })),
  exportDocument: (id: string) => request<{ export_id: string; revision: number; download_url: string }>(`/documents/${encodeURIComponent(id)}/exports`, json('POST')),
  previewDocument: (id: string) => request<Blob>(`/documents/${encodeURIComponent(id)}/preview.pdf`),
  downloadExport: (id: string) => request<Blob | {url: string}>(`/exports/${encodeURIComponent(id)}`),
};
