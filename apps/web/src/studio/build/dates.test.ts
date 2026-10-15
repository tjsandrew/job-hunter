import { describe, expect, it } from 'vitest';
import { formatDateRange } from './dates';

describe('formatDateRange', () => {
  const range = { start: '2023-07', end: '2024-02', current: false };
  it.each([
    ['Jul 2023', 'Jul 2023 – Feb 2024'],
    ['July 2023', 'July 2023 – February 2024'],
    ['07/2023', '07/2023 – 02/2024'],
    ['2023', '2023 – 2024'],
  ] as const)('formats %s', (format, expected) => expect(formatDateRange(range, format, 'Present')).toBe(expected));

  it.each([['Present'], ['Current'], ['Now']] as const)('uses the %s label for ongoing roles', (label) => {
    expect(formatDateRange({ start: '2023-07', end: null, current: true }, 'Jul 2023', label)).toBe(`Jul 2023 – ${label}`);
    expect(formatDateRange({ start: '2023-07', end: '2024-01', current: true }, '07/2023', label)).toBe(`07/2023 – ${label}`);
  });

  it('shows year-only dates as years in every format', () => {
    for (const format of ['Jul 2023', 'July 2023', '07/2023', '2023'] as const) expect(formatDateRange({ start: '2021', end: '2022', current: false }, format)).toBe('2021 – 2022');
  });
  it('shows only the start when the end is unknown', () => {
    expect(formatDateRange({ start: '2023-07', end: null, current: false }, 'July 2023')).toBe('July 2023');
  });
  it('collapses an identical start and end', () => {
    expect(formatDateRange({ start: '2021-05', end: '2021-05' }, 'Jul 2023')).toBe('May 2021');
    expect(formatDateRange({ start: '2023-01', end: '2023-09' }, '2023')).toBe('2023');
  });
  it('keeps values it cannot read as typed, and renders empty ranges as nothing', () => {
    expect(formatDateRange({ start: 'Summer 2020', end: '2021-13', current: false }, 'Jul 2023')).toBe('Summer 2020 – 2021-13');
    expect(formatDateRange({ start: null, end: null, current: false })).toBe('');
    expect(formatDateRange(null, 'Jul 2023')).toBe('');
    expect(formatDateRange(undefined)).toBe('');
  });
  it('defaults to "Jul 2023" and "Present"', () => {
    expect(formatDateRange({ start: '2023-07', current: true })).toBe('Jul 2023 – Present');
  });
  it('shows just the label when an ongoing range has no start', () => {
    expect(formatDateRange({ start: null, end: null, current: true }, 'Jul 2023', 'Now')).toBe('Now');
  });
});
