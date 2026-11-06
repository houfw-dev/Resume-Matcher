/**
 * Reverse-chronological ordering for work experience and education.
 *
 * Entries are sorted by the START date of their `years` string, newest first.
 * The rule mirrors the backend parser post-processing
 * (`sort_timeline_sections_newest_first`) so stored data, the on-screen
 * viewer and the Chromium PDF export all agree. Projects and custom sections
 * are intentionally untouched.
 */

import type { ResumeData } from '@/components/dashboard/resume-component';

interface DatedEntry {
  years?: string;
}

const EN_MONTH_BY_NAME: Readonly<Record<string, number>> = Object.freeze({
  jan: 1,
  january: 1,
  feb: 2,
  february: 2,
  mar: 3,
  march: 3,
  apr: 4,
  april: 4,
  may: 5,
  jun: 6,
  june: 6,
  jul: 7,
  july: 7,
  aug: 8,
  august: 8,
  sep: 9,
  sept: 9,
  september: 9,
  oct: 10,
  october: 10,
  nov: 11,
  november: 11,
  dec: 12,
  december: 12,
});

/**
 * Return `[year, month]` of the FIRST date token in a years string.
 *
 * Understands "2018.05 - 2020.11", "2010.09-2014.06", "Jun 2020 - Aug 2021",
 * "2020年5月" and plain years. A value without a parseable date returns
 * `[0, 0]` so the entry sinks below every dated entry.
 */
export function getStartDateKey(value?: string | null): [number, number] {
  if (typeof value !== 'string' || !value.trim()) {
    return [0, 0];
  }

  const english = value.match(/([A-Za-z]+)\s*(\d{4})/);
  if (english) {
    const month = EN_MONTH_BY_NAME[english[1].toLowerCase()];
    if (month) {
      return [Number(english[2]), month];
    }
  }

  const numeric = value.match(/(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*月?/);
  if (numeric) {
    const month = Number(numeric[2]);
    return [Number(numeric[1]), month >= 1 && month <= 12 ? month : 0];
  }

  const yearOnly = value.match(/(\d{4})/);
  return yearOnly ? [Number(yearOnly[1]), 0] : [0, 0];
}

/**
 * Stable newest-first sort of dated entries. Entries with no parseable date
 * keep their relative order and sink to the end.
 */
export function sortTimelineNewestFirst<T extends DatedEntry>(
  entries: readonly T[] | null | undefined
): T[] | undefined {
  if (entries == null) {
    return undefined;
  }
  if (entries.length < 2) {
    return [...entries];
  }
  return [...entries].sort((a, b) => {
    const [yearA, monthA] = getStartDateKey(a?.years);
    const [yearB, monthB] = getStartDateKey(b?.years);
    if (yearA !== yearB) return yearB - yearA;
    return monthB - monthA;
  });
}

/**
 * Return a ResumeData copy with workExperience and education ordered
 * newest-first; every other section is left untouched.
 */
export function orderTimelineSectionsNewestFirst(resumeData: ResumeData): ResumeData {
  return {
    ...resumeData,
    workExperience: sortTimelineNewestFirst(resumeData.workExperience) ?? [],
    education: sortTimelineNewestFirst(resumeData.education) ?? [],
  };
}
