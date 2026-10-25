import { describe, expect, it } from 'vitest';
import { DEFAULT_ROUTE, parseRoute, routePath, safeReturnPath } from './routes';

const JOB = '3f2b8c1e-5a47-4d0e-9b61-2c7d8e9f0a1b';

describe('routes', () => {
  it('gives every page, list, listing and resume its own address and reads it back', () => {
    const cases: [string, ReturnType<typeof parseRoute>][] = [
      ['/discover', { ...DEFAULT_ROUTE }],
      ['/discover/all', { ...DEFAULT_ROUTE, mode: 'all' }],
      ['/discover/saved', { ...DEFAULT_ROUTE, mode: 'saved' }],
      ['/discover/passed', { ...DEFAULT_ROUTE, mode: 'passed' }],
      ['/profile', { ...DEFAULT_ROUTE, page: 'profile' }],
      ['/tracker', { ...DEFAULT_ROUTE, page: 'tracker' }],
      ['/resumes', { ...DEFAULT_ROUTE, page: 'studio' }],
      [`/resumes/${JOB}`, { ...DEFAULT_ROUTE, page: 'studio', resumeId: JOB }],
      [`/jobs/${JOB}`, { ...DEFAULT_ROUTE, jobId: JOB }],
      ['/resumes/letters', { ...DEFAULT_ROUTE, page: 'studio', tab: 'letters' }],
      [`/resumes/letters/${JOB}`, { ...DEFAULT_ROUTE, page: 'studio', tab: 'letters', letterId: JOB }],
    ];
    for (const [path, route] of cases) {
      expect(parseRoute(path)).toEqual(route);
      expect(routePath(route)).toBe(path);
    }
  });

  it('opens the default page for the root and for anything unknown or malformed', () => {
    for (const path of ['/', '', '/nowhere', '/discover/bogus', '/discover/all/extra', '/jobs', '/jobs/', '/jobs/a/b', '/jobs/has space', '/resumes/%E0%A4%A', '/profile/x', '/resumes/letters/a/b', '/resumes/letters/has space']) {
      expect(parseRoute(path)).toEqual(DEFAULT_ROUTE);
    }
  });

  it('shows an opened listing at its own address, over whatever list is behind it', () => {
    expect(routePath({ ...DEFAULT_ROUTE, mode: 'saved', jobId: JOB })).toBe(`/jobs/${JOB}`);
    expect(routePath({ ...DEFAULT_ROUTE, page: 'profile', resumeId: JOB })).toBe('/profile');
  });

  it('only returns to this app\'s own pages after sign-in', () => {
    expect(safeReturnPath('/tracker')).toBe('/tracker');
    expect(safeReturnPath(`/jobs/${JOB}`)).toBe(`/jobs/${JOB}`);
    for (const bad of [undefined, null, 5, '', 'tracker', '//evil.example', 'https://evil.example', '/\\evil', '/auth/callback', '/auth/callback?code=1']) {
      expect(safeReturnPath(bad)).toBe('/');
    }
  });
});
