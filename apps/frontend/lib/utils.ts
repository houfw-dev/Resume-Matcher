import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

import { canonicalizeDatePeriod } from '@/lib/utils/date-period';

/**
 * Combines multiple class names or class name objects into a single string.
 * Uses clsx for conditional class logic.
 *
 * @param inputs - Class values to be combined (strings, objects, arrays)
 * @returns A string of combined class names
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Formats a date range into the canonical resume presentation.
 *
 * Canonical form uses numeric months, a tilde connector and Chinese 至今
 * for open-ended ranges: "2020.06~2023.09", "2024.03~至今". English month
 * names are converted on every resume; values carrying non-date prose pass
 * through unchanged. The implementation mirrors the backend canonicalizer
 * in `lib/utils/date-period.ts`.
 *
 * @param dateString - The date range string to format
 * @returns Formatted date string, or "" for empty input
 */
export function formatDateRange(dateString: string | undefined | null): string {
  if (!dateString) return '';
  return canonicalizeDatePeriod(dateString);
}
