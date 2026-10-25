import type { DiscoverMode } from './types';

// Every page, list and opened listing has its own address, so a refresh, the back button and a pasted link all land where you were.
//   /discover  /discover/all  /discover/saved  /discover/passed     the job lists (For you is the default)
//   /jobs/<job id>                                                   one listing (the details window, over the Discover list)
//   /profile  /tracker  /resumes  /resumes/<resume id>               the other pages, and one resume in the editor
//   /resumes/letters  /resumes/letters/<letter id>                   the cover letters beside the resumes, and one letter in the editor
// The hosting already answers every path without a dot with the app (Amplify rewrite rule, Vite dev server), so nothing there changes.
export type Page = 'discover' | 'profile' | 'tracker' | 'studio';
export type DocumentTab = 'resumes' | 'letters';
export type Route = { page: Page; mode: DiscoverMode; jobId: string | null; resumeId: string | null; tab: DocumentTab; letterId: string | null };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// The local demo data uses short ids such as "role-1", so a listing id only has to be a plain token, not a UUID.
const TOKEN = /^[A-Za-z0-9_-]{1,80}$/;
const MODE_SEGMENT: Record<string, DiscoverMode> = { all: 'all', saved: 'saved', passed: 'passed' };
const SEGMENT_OF: Record<DiscoverMode, string> = { 'for-you': '', all: '/all', saved: '/saved', passed: '/passed' };

export const DEFAULT_ROUTE: Route = { page: 'discover', mode: 'for-you', jobId: null, resumeId: null, tab: 'resumes', letterId: null };

/** Reads an address; anything unknown becomes the default page rather than an error page. */
export function parseRoute(pathname: string): Route {
  const parts = pathname.split('/').filter(Boolean).map((part) => { try { return decodeURIComponent(part); } catch { return ''; } });
  const [first, second] = parts;
  if (parts.length === 0 || first === 'discover') {
    if (parts.length <= 1) return { ...DEFAULT_ROUTE };
    const mode = MODE_SEGMENT[second ?? ''];
    return parts.length === 2 && mode ? { ...DEFAULT_ROUTE, mode } : { ...DEFAULT_ROUTE };
  }
  if (first === 'jobs' && parts.length === 2 && second && (UUID.test(second) || TOKEN.test(second))) return { ...DEFAULT_ROUTE, jobId: second };
  if (first === 'profile' && parts.length === 1) return { ...DEFAULT_ROUTE, page: 'profile' };
  if (first === 'tracker' && parts.length === 1) return { ...DEFAULT_ROUTE, page: 'tracker' };
  if (first === 'resumes' && parts.length === 1) return { ...DEFAULT_ROUTE, page: 'studio' };
  if (first === 'resumes' && second === 'letters' && parts.length === 2) return { ...DEFAULT_ROUTE, page: 'studio', tab: 'letters' };
  if (first === 'resumes' && second === 'letters' && parts.length === 3 && parts[2] && (UUID.test(parts[2]) || TOKEN.test(parts[2]))) return { ...DEFAULT_ROUTE, page: 'studio', tab: 'letters', letterId: parts[2] };
  if (first === 'resumes' && parts.length === 2 && second && (UUID.test(second) || TOKEN.test(second))) return { ...DEFAULT_ROUTE, page: 'studio', resumeId: second };
  return { ...DEFAULT_ROUTE };
}

/** The address of a route; an opened listing wins over the list behind it, an open resume over the resume library. */
export function routePath(route: Route): string {
  if (route.jobId) return `/jobs/${encodeURIComponent(route.jobId)}`;
  if (route.page === 'profile') return '/profile';
  if (route.page === 'tracker') return '/tracker';
  if (route.page === 'studio' && route.tab === 'letters') return route.letterId ? `/resumes/letters/${encodeURIComponent(route.letterId)}` : '/resumes/letters';
  if (route.page === 'studio') return route.resumeId ? `/resumes/${encodeURIComponent(route.resumeId)}` : '/resumes';
  return `/discover${SEGMENT_OF[route.mode]}`;
}

/** A path that is safe to return to after signing in: this app's own, never the sign-in callback, never another site. */
export function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/';
  if (value === '/auth/callback' || value.startsWith('/auth/')) return '/';
  return value;
}
