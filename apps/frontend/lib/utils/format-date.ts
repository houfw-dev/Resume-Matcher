/**
 * Locale-aware date formatting for UI surfaces.
 *
 * Every call site must pass the active UI locale from `useTranslations()`;
 * hardcoding 'en-US' (or omitting the locale and inheriting the jsdom/browser
 * default) froze tracker dates in US format for every other supported
 * language.
 */

export type LocaleDateInput = string | number | Date;

const DEFAULT_OPTIONS: Readonly<Intl.DateTimeFormatOptions> = Object.freeze({
  month: 'short',
  day: '2-digit',
  year: 'numeric',
});

/**
 * Format a date for the given locale. Empty/invalid input returns `fallback`
 * instead of "Invalid Date", so callers can render an explicit empty string.
 */
export function formatLocaleDate(
  value: LocaleDateInput | null | undefined,
  locale: string,
  options: Intl.DateTimeFormatOptions = DEFAULT_OPTIONS,
  fallback = ''
): string {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }
  return date.toLocaleDateString(locale, options);
}

/** Compact month+year label for card headers and detail modals. */
export function formatLocaleMonthYear(
  value: LocaleDateInput | null | undefined,
  locale: string,
  fallback = ''
): string {
  return formatLocaleDate(value, locale, { month: 'short', year: 'numeric' }, fallback);
}
