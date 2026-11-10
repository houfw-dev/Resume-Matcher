import { describe, expect, it, vi } from 'vitest';

import type { ResumeData } from '@/components/dashboard/resume-component';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';
import { LayoutMeasurementError, measureResumeLayout } from '@/lib/utils/measure-resume-layout';
import type { ResumeHeadingProps } from '@/lib/utils/resume-headings';

const resumeData = {
  personalInfo: { name: '王浩', title: '工程师', email: 'a@b.c', phone: '13800000000' },
  summary: '具备多年开发经验',
  workExperience: [
    {
      company: '甲公司',
      title: '工程师',
      years: '2023.01 至今',
      description: ['负责系统开发'],
    },
  ],
  education: [],
  personalProjects: [],
  additional: { technicalSkills: ['Java'] },
} as unknown as ResumeData;

const headingProps = {
  personalInfoLabels: {
    gender: '性别',
    age: '年龄',
    educationLevel: '学历',
    workYears: '年限',
    jobIntention: '求职意向',
    desiredCity: '城市',
    phone: '电话',
    email: '邮箱',
    foreignLanguage: '外语',
    website: '个人网站',
    linkedin: '领英',
    github: 'GitHub',
  },
  additionalSectionLabels: {
    technicalSkills: '专业技能',
    languages: '语言能力',
    certifications: '证书',
    awards: '奖项',
  },
  sectionHeadings: {
    summary: '个人优势',
    experience: '工作经历',
    education: '教育经历',
    projects: '项目经验',
    certifications: '培训与证书',
    skills: '专业技能',
    languages: '语言能力',
    awards: '荣誉奖项',
    links: '链接',
  },
  fallbackLabels: { name: '姓名' },
} as ResumeHeadingProps;

describe('measureResumeLayout self-check gate', () => {
  it('throws LayoutMeasurementError under jsdom (zero layout height)', async () => {
    // jsdom performs no layout: every scrollHeight is 0. The offscreen render
    // still succeeds (so this also proves <Resume> mounts offscreen), but the
    // zero-height self-check must reject the snapshot rather than upload
    // measurements that are all zeros.
    await expect(
      measureResumeLayout({
        resumeData,
        settings: DEFAULT_TEMPLATE_SETTINGS,
        headingProps,
        // Short timeout so a stuck render fails the test instead of hanging.
        timeoutMs: 2000,
      })
    ).rejects.toBeInstanceOf(LayoutMeasurementError);

    // The hidden host is removed again after the attempt.
    await expect(
      measureResumeLayout({
        resumeData,
        settings: DEFAULT_TEMPLATE_SETTINGS,
        headingProps,
        timeoutMs: 2000,
      })
    ).rejects.toThrow('zero height');
  });

  it('throws on SSR (no DOM)', async () => {
    const originalDocument = globalThis.document;
    const originalWindow = globalThis.window;
    vi.stubGlobal('document', undefined);
    vi.stubGlobal('window', undefined);
    try {
      await expect(
        measureResumeLayout({
          resumeData,
          settings: DEFAULT_TEMPLATE_SETTINGS,
          headingProps,
        })
      ).rejects.toBeInstanceOf(LayoutMeasurementError);
    } finally {
      vi.unstubAllGlobals();
      expect(globalThis.document).toBe(originalDocument);
      expect(globalThis.window).toBe(originalWindow);
    }
  });
});
