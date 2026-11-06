import { describe, expect, it } from 'vitest';
import {
  getStartDateKey,
  orderTimelineSectionsNewestFirst,
  sortTimelineNewestFirst,
} from '@/lib/utils/timeline-sort';
import type { ResumeData } from '@/components/dashboard/resume-component';

describe('getStartDateKey', () => {
  it('parses dotted and dashed numeric starts', () => {
    expect(getStartDateKey('2018.05 - 2020.11')).toEqual([2018, 5]);
    expect(getStartDateKey('2010.09-2014.06')).toEqual([2010, 9]);
  });

  it('parses English month prefixes', () => {
    expect(getStartDateKey('Jun 2020 - Aug 2021')).toEqual([2020, 6]);
    expect(getStartDateKey('May 2021 - Present')).toEqual([2021, 5]);
  });

  it('parses Chinese month format and plain years', () => {
    expect(getStartDateKey('2020年12月 - 至今')).toEqual([2020, 12]);
    expect(getStartDateKey('2020 - 2022')).toEqual([2020, 0]);
  });

  it('sinks undated values', () => {
    expect(getStartDateKey('')).toEqual([0, 0]);
    expect(getStartDateKey(undefined)).toEqual([0, 0]);
    expect(getStartDateKey('no date here')).toEqual([0, 0]);
  });
});

describe('sortTimelineNewestFirst', () => {
  it('orders newest start date first', () => {
    const entries = [
      { id: 1, years: '2018.05 - 2020.11' },
      { id: 2, years: '2020.12 - 2026.04' },
    ];
    expect(sortTimelineNewestFirst(entries)?.map((e) => e.id)).toEqual([2, 1]);
  });

  it('keeps undated entries stable at the end', () => {
    const entries = [
      { id: 'a', years: '2010 - 2012' },
      { id: 'u1', years: '' },
      { id: 'b', years: '2020 - 2022' },
      { id: 'u2' },
    ];
    expect(sortTimelineNewestFirst(entries)?.map((e) => e.id)).toEqual(['b', 'a', 'u1', 'u2']);
  });

  it('does not mutate the input', () => {
    const entries = [
      { id: 1, years: '2018 - 2020' },
      { id: 2, years: '2020 - 2022' },
    ];
    const snapshot = [...entries];
    sortTimelineNewestFirst(entries);
    expect(entries).toEqual(snapshot);
  });

  it('returns undefined for undefined input', () => {
    expect(sortTimelineNewestFirst(undefined)).toBeUndefined();
  });
});

describe('orderTimelineSectionsNewestFirst', () => {
  it('sorts work and education but leaves projects untouched', () => {
    const data = {
      personalInfo: { name: 'X' },
      workExperience: [
        { company: 'Old', years: '2018.05 - 2020.11', description: [] },
        { company: 'New', years: '2020.12 - 2026.04', description: [] },
      ],
      education: [
        { institution: 'Bachelor', years: '2010.09 - 2014.06' },
        { institution: 'Master', years: '2014.09 - 2017.06' },
      ],
      personalProjects: [
        { name: 'P1', years: '2009 - 2010' },
        { name: 'P2', years: '2022 - 2023' },
      ],
    } as unknown as ResumeData;

    const result = orderTimelineSectionsNewestFirst(data);
    expect(result.workExperience!.map((e) => e.company)).toEqual(['New', 'Old']);
    expect(result.education!.map((e) => e.institution)).toEqual(['Master', 'Bachelor']);
    expect(result.personalProjects!.map((e) => e.name)).toEqual(['P1', 'P2']);
  });
});
