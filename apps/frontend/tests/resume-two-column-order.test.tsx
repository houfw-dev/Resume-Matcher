import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { ResumeTwoColumn } from '@/components/resume/resume-two-column';
import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';

// Two-column templates are EXEMPT from the fixed-order rule: their main/sidebar
// split is hardcoded layout, and custom sections keep raw meta order. This
// suite guards that getCanonicalSections never leaks into them.
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

function meta(over: Partial<SectionMeta>): SectionMeta {
  return {
    id: 'x',
    key: 'x',
    displayName: 'X',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 0,
    ...over,
  };
}

describe('ResumeTwoColumn order exemption', () => {
  it('keeps custom sections in raw meta order and keeps education in the sidebar', () => {
    // Deliberately non-formal degree (would move education to the end under
    // the canonical rule) with a selfeval-titled custom stored FIRST: the
    // canonical resolver would sort it last; this template must not.
    const data: ResumeData = {
      personalInfo: { name: '王二' },
      summary: '',
      education: [{ id: 1, institution: '乙大专', degree: '大专' }],
      workExperience: [],
      personalProjects: [],
      additional: {},
      customSections: {
        custom_eval: { sectionType: 'text', text: '踏实稳重。' },
        custom_hobby: { sectionType: 'text', text: '热爱开源。' },
      },
      sectionMeta: [
        meta({ id: 'custom_eval', key: 'custom_eval', displayName: '自我评价', order: 0 }),
        meta({ id: 'custom_hobby', key: 'custom_hobby', displayName: '志愿者', order: 1 }),
        meta({
          id: 'personalInfo',
          key: 'personalInfo',
          displayName: '基本信息',
          sectionType: 'personalInfo',
          isDefault: true,
          order: 2,
        }),
        meta({ id: 'summary', key: 'summary', displayName: '个人优势', isDefault: true, order: 3 }),
        meta({
          id: 'workExperience',
          key: 'workExperience',
          displayName: '工作经历',
          sectionType: 'itemList',
          isDefault: true,
          order: 4,
        }),
        meta({
          id: 'education',
          key: 'education',
          displayName: '教育背景',
          sectionType: 'itemList',
          isDefault: true,
          order: 5,
        }),
        meta({
          id: 'personalProjects',
          key: 'personalProjects',
          displayName: '项目经验',
          sectionType: 'itemList',
          isDefault: true,
          order: 6,
        }),
        meta({
          id: 'additional',
          key: 'additional',
          displayName: '专业技能',
          sectionType: 'stringList',
          isDefault: true,
          order: 7,
        }),
      ],
    } as ResumeData;

    const { container } = render(<ResumeTwoColumn data={data} />);
    const titles = Array.from(container.querySelectorAll('h3')).map((el) => el.textContent);

    // Raw stored custom order: 自我评价 (order 0) before 志愿者 (order 1).
    // Canonical formal/other placement would have produced the reverse.
    expect(titles.indexOf('自我评价')).toBeGreaterThanOrEqual(0);
    expect(titles.indexOf('自我评价')).toBeLessThan(titles.indexOf('志愿者'));
    // Education is still rendered (hardcoded sidebar placement, unmoved by
    // the non-formal degree branch).
    expect(titles).toContain('教育背景');
  });
});
