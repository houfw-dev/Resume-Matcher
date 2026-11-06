import { describe, expect, it } from 'vitest';

import { canonicalizeDatePeriod } from '@/lib/utils/date-period';
import { formatDateRange } from '@/lib/utils';
import { normalizeResumeForSave } from '@/lib/utils/resume-normalization';
import type { ResumeData } from '@/components/dashboard/resume-component';

describe('canonicalizeDatePeriod', () => {
  it.each([
    // Numeric / Chinese numeric forms, every connector style.
    ['2020.06 - 2023.09', '2020.06~2023.09'],
    ['2020/06 – 2023/09', '2020.06~2023.09'],
    ['2020-06~2023-09', '2020.06~2023.09'],
    ['2017.9~2021.7', '2017.09~2021.07'],
    ['2020 年 06 月 - 2023 年 09 月', '2020.06~2023.09'],
    ['2020年5月 至 2023年8月', '2020.05~2023.08'],
    // Open-ended markers all become Chinese 至今 with a tilde.
    ['2025.07 - 至今', '2025.07~至今'],
    ['2025.07～至今', '2025.07~至今'],
    ['May 2021 - Present', '2021.05~至今'],
    ['January 2020 - Current', '2020.01~至今'],
    ['2024.03 - Now', '2024.03~至今'],
    // English month names become numeric on every resume.
    ['Jan 2020 - Dec 2023', '2020.01~2023.12'],
    ['Jun 2023', '2023.06'],
    ['Jan 2020 to Mar 2021', '2020.01~2021.03'],
    // Year-only precision is kept — months must never be invented.
    ['2020 - 2021', '2020~2021'],
    ['2020', '2020'],
    // One trailing parenthesized note survives.
    ['2019.07 - 2021.12（实习）', '2019.07~2021.12（实习）'],
  ])('canonicalizes %s -> %s', (raw, expected) => {
    expect(canonicalizeDatePeriod(raw)).toBe(expected);
  });

  it.each([
    '',
    '   ',
    '三年经验',
    '2020年入职',
    '至今',
    '2020.06~2023.09 备注文字',
    '2020.06~至今~2023.09',
    '2020-06-2023-09', // glued, no real connector: do not guess
  ])('passes unparseable values through unchanged: %j', (raw) => {
    expect(canonicalizeDatePeriod(raw)).toBe(raw);
  });

  it('is idempotent', () => {
    const once = canonicalizeDatePeriod('Jan 2020 - Dec 2023');
    expect(once).toBe('2020.01~2023.12');
    expect(canonicalizeDatePeriod(once)).toBe(once);
  });
});

describe('formatDateRange', () => {
  it('returns empty string for empty input and canonical form otherwise', () => {
    expect(formatDateRange(undefined)).toBe('');
    expect(formatDateRange(null)).toBe('');
    expect(formatDateRange('2020.06 - 至今')).toBe('2020.06~至今');
  });
});

describe('normalizeResumeForSave years canonicalization', () => {
  const baseResume = {
    personalInfo: {},
    summary: '',
    workExperience: [],
    education: [],
    personalProjects: [],
    additional: {},
    sectionMeta: [],
    customSections: {},
  } as unknown as ResumeData;

  it('canonicalizes years on work, project, education and custom items', () => {
    const state: ResumeData = {
      ...baseResume,
      workExperience: [
        { id: 1, company: '甲', title: '工程师', years: '2020.06 - 至今', description: [] },
      ],
      education: [{ id: 1, institution: '乙大学', degree: '本科', years: '2016 - 2020' }],
      personalProjects: [{ id: 1, name: '丙项目', years: 'Mar 2021 - Present', description: [] }],
      customSections: {
        pubs: {
          sectionType: 'itemList',
          items: [{ id: 1, title: '论文', years: '2019.05 - 2020.02' }],
        } as never,
      },
    };

    const saved = normalizeResumeForSave(state);
    expect(saved.workExperience?.[0].years).toBe('2020.06~至今');
    expect(saved.education?.[0].years).toBe('2016~2020');
    expect(saved.personalProjects?.[0].years).toBe('2021.03~至今');
    const savedCustom = saved.customSections as
      Record<string, { items: { years: string }[] }> | undefined;
    expect(savedCustom?.pubs.items[0].years).toBe('2019.05~2020.02');
  });
});
