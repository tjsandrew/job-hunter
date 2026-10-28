import { beforeEach, describe, expect, it } from 'vitest';
import { activeCount, activePreferences, cleanPreferences, emptyPreferences, filterQuery, loadChoice, preferenceMatches, samePreferences, storeChoice } from './filters';
import type { Job } from '../types';

const saved = cleanPreferences({ roles: ['Backend Engineer'], locations: ['Singapore'], work_modes: ['hybrid'], seniority: 'mid', salary_min: 6000, salary_currency: 'SGD', salary_period: 'month' });

describe('Discover filters', () => {
  beforeEach(() => sessionStorage.clear());

  it('sends nothing for the profile defaults, so the server reads the saved ones', () => {
    expect(filterQuery({ mode: 'profile', custom: saved })).toBeUndefined();
  });

  it('asks for no preferences when filters are cleared', () => {
    expect(filterQuery({ mode: 'none', custom: saved })).toEqual({ filters: 'none' });
  });

  it('sends every custom value, and the salary only when one is set', () => {
    expect(filterQuery({ mode: 'custom', custom: saved })).toEqual({ filters: 'custom', role: ['Backend Engineer'], location: ['Singapore'], work_mode: ['hybrid'], seniority: 'mid', salary_min: '6000', salary_currency: 'SGD', salary_period: 'month' });
    expect(filterQuery({ mode: 'custom', custom: { ...saved, salary_min: '' } })).not.toHaveProperty('salary_min');
  });

  it('shows the saved defaults, nothing, or the custom values', () => {
    const custom = { ...saved, work_modes: ['remote'] };
    expect(activePreferences({ mode: 'profile', custom }, saved)).toEqual(saved);
    expect(activePreferences({ mode: 'none', custom }, saved)).toEqual(emptyPreferences());
    expect(activePreferences({ mode: 'custom', custom }, saved).work_modes).toEqual(['remote']);
  });

  it('compares preferences by value and counts the ones that are set', () => {
    expect(samePreferences(saved, cleanPreferences({ ...saved, roles: [' Backend Engineer '] }))).toBe(true);
    expect(activeCount(saved)).toBe(5);
    expect(activeCount(emptyPreferences())).toBe(0);
  });

  it('remembers the choice per user for this session only', () => {
    storeChoice('alice', { mode: 'custom', custom: saved });
    expect(loadChoice('alice')).toEqual({ mode: 'custom', custom: saved });
    expect(loadChoice('casey')).toBeNull();
    sessionStorage.setItem('jh-discover-filters:alice', '{"mode":"broken"}');
    expect(loadChoice('alice')).toBeNull();
  });

  it('tags the work mode, location and salary a job matches', () => {
    const job = { id: 'j', title: 'Engineer', company: 'Acme', location: 'Singapore (Central)', work_mode: 'Hybrid', salary_min: 7000, salary_max: 9000, salary_currency: 'SGD', salary_period: 'Monthly' } as Job;
    expect(preferenceMatches(job, saved)).toEqual(['Hybrid', 'Singapore', 'Meets your salary']);
    expect(preferenceMatches({ ...job, salary_max: 5000, salary_min: 4000 }, saved)).toEqual(['Hybrid', 'Singapore']);
    expect(preferenceMatches({ ...job, work_mode: 'remote', location: 'London' }, saved)).toEqual(['Meets your salary']);
    expect(preferenceMatches(job, emptyPreferences())).toEqual([]);
  });
});
