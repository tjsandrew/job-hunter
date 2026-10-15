import { getDevUser, HttpError } from '../../api';
import type { Resume, Template } from '../../types';

// Calls for building a resume from the profile bank. api.ts keeps its request helper private, so this repeats the small pattern.
const base = (import.meta.env.VITE_API_BASE_URL || '/v1').replace(/\/$/, '');
async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try { response = await fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-User': getDevUser() }, body: JSON.stringify(body) }); }
  catch { throw new HttpError('Could not reach the Job Hunter API. Check that the local services are running.', 0); }
  if (!response.ok) {
    let data: any = {};
    try { data = await response.json(); } catch { /* response may not contain JSON */ }
    throw new HttpError(data?.error?.message || data?.detail || `Request failed (${response.status}).`, response.status, data?.error?.code);
  }
  return response.json() as Promise<T>;
}

export type PlanKind = 'experience' | 'education' | 'projects' | 'custom' | 'certifications' | 'awards' | 'volunteering';
export type PlanPick = { bullet_id: string; alternative_id?: string };
export type PlanItem = { item_id: string; picks: PlanPick[] };
export type PlanSection = { kind: PlanKind; items: PlanItem[] } | { kind: 'skills'; skill_ids: string[] };
export type BuildSummary = { mode: 'profile' } | { mode: 'custom'; text: string };
export type BuildPlan = { title: string; template: Template; job_id: string | null; summary: BuildSummary; sections: PlanSection[] };
export type Suggestion = { plan: { sections: PlanSection[] } & Partial<BuildPlan>; reasons: Record<string, string[]>; coverage: { covered: string[]; missing: string[] }; strategy: string };

export const suggestPlan = (jobId: string, pointsPerItem?: number) =>
  post<Suggestion>('/resume-builds/suggest', pointsPerItem === undefined ? { job_id: jobId } : { job_id: jobId, points_per_item: pointsPerItem });
export const createFromBank = (plan: BuildPlan) => post<Resume>('/documents/from-bank', plan);
