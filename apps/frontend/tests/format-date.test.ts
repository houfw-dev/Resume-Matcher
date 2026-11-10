import { describe, expect, it } from 'vitest';
import { formatLocaleDate, formatLocaleMonthYear } from '@/lib/utils/format-date';

// Noon UTC so no inhabited timezone can roll the date onto another day.
const MOMENT = '2026-03-05T12:00:00Z';

describe('formatLocaleDate', () => {
  it('formats the same instant differently per locale', () => {
    expect(formatLocaleDate(MOMENT, 'en-US')).toBe('Mar 05, 2026');
    // Chinese and Japanese localizations must not fall back to US month names.
    const zh = formatLocaleDate(MOMENT, 'zh');
    expect(zh).toContain('2026');
    expect(zh).toContain('3月');
    expect(zh).not.toContain('Mar');
    const ja = formatLocaleDate(MOMENT, 'ja');
    expect(ja).toContain('2026');
    expect(ja).not.toContain('Mar');
  });

  it('accepts Date objects and numeric timestamps', () => {
    expect(formatLocaleDate(new Date(MOMENT), 'en-US')).toBe('Mar 05, 2026');
    expect(formatLocaleDate(Date.parse(MOMENT), 'en-US')).toBe('Mar 05, 2026');
  });

  it('returns the fallback for empty or unparseable input', () => {
    expect(formatLocaleDate(null, 'en-US')).toBe('');
    expect(formatLocaleDate(undefined, 'en-US')).toBe('');
    expect(formatLocaleDate('', 'en-US')).toBe('');
    expect(formatLocaleDate('not-a-date', 'en-US', undefined, '—')).toBe('—');
  });
});

describe('formatLocaleMonthYear', () => {
  it('renders month and year in the active locale', () => {
    expect(formatLocaleMonthYear(MOMENT, 'en-US')).toBe('Mar 2026');
    const zh = formatLocaleMonthYear(MOMENT, 'zh');
    expect(zh).toContain('2026');
    expect(zh).toContain('3月');
  });

  it('honors the fallback for missing dates', () => {
    expect(formatLocaleMonthYear(null, 'en-US')).toBe('');
    expect(formatLocaleMonthYear('garbage', 'ja', '?')).toBe('?');
  });
});
