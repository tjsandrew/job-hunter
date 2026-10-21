import { apiRequest } from '../../api';
import type { Resume, Template } from '../../types';

// Use the same identity, session handling and errors as every other private API call.
const post = <T>(path: string, body: unknown) =>
  apiRequest<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

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
