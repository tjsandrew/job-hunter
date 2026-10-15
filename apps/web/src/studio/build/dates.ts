import type { ResumeLayout } from '../../types';

export type DateRange = { start?: string | null; end?: string | null; current?: boolean };
export type DateFormat = NonNullable<ResumeLayout['date_format']>;
export type PresentLabel = NonNullable<ResumeLayout['present_label']>;

export const dateFormats: DateFormat[] = ['Jul 2023', 'July 2023', '07/2023', '2023'];
export const presentLabels: PresentLabel[] = ['Present', 'Current', 'Now'];

const shortMonths = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const longMonths = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

// Profile dates are "2023" or "2023-07". Anything else is unknown and is shown as typed.
function formatPart(value: string | null | undefined, format: DateFormat): string {
  const text = (value ?? '').trim();
  if (!text) return '';
  const match = /^(\d{4})(?:-(\d{2}))?$/.exec(text);
  if (!match) return text;
  const [, year, rawMonth] = match;
  const month = rawMonth ? Number(rawMonth) : 0;
  if (rawMonth && (month < 1 || month > 12)) return text;
  if (!month || format === '2023') return year;
  if (format === 'July 2023') return `${longMonths[month - 1]} ${year}`;
  if (format === '07/2023') return `${rawMonth}/${year}`;
  return `${shortMonths[month - 1]} ${year}`;
}

/** Renders a structured date range, such as "Jul 2023 – Present". Pure. */
export function formatDateRange(range: DateRange | null | undefined, format: DateFormat = 'Jul 2023', presentLabel: PresentLabel = 'Present'): string {
  if (!range) return '';
  const start = formatPart(range.start, format);
  const end = range.current ? presentLabel : formatPart(range.end, format);
  if (start && end) return start === end ? start : `${start} – ${end}`;
  return start || end;
}
