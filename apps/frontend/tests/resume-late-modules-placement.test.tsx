import { describe, expect, it, vi } from 'vitest';
import type { FC } from 'react';
import { render } from '@testing-library/react';
import type {
  AdditionalSectionLabels,
  ResumeData,
  ResumeSectionHeadings,
  SectionMeta,
} from '@/components/dashboard/resume-component';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';
import { ResumeModern } from '@/components/resume/resume-modern';
import { ResumeLatex } from '@/components/resume/resume-latex';
import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeTwoColumn } from '@/components/resume/resume-two-column';
import { ResumeModernTwoColumn } from '@/components/resume/resume-modern-two-column';
import { ResumeVivid } from '@/components/resume/resume-vivid';
import swissTwoStyles from '@/components/resume/styles/swiss-two-column.module.css';
import modernTwoStyles from '@/components/resume/styles/modern-two-column.module.css';
import vividStyles from '@/components/resume/styles/vivid.module.css';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * 培训与证书 / 荣誉奖项 stay independent modules but render at the BACK of the
 * resume. Single-column (meta-driven) templates project them via
 * getRenderSections; the hardcoded two-column templates place the same JSX in
 * the main column after every custom section.
 */

function meta(overrides: Partial<SectionMeta>): SectionMeta {
  return {
    id: 'x',
    key: 'x',
    displayName: 'X',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 0,
    ...overrides,
  };
}

const zhHeadings: Partial<ResumeSectionHeadings> = {
  summary: '个人优势',
  experience: '工作经历',
  education: '教育背景',
  projects: '项目经验',
  certifications: '培训与证书',
  skills: '专业技能',
  languages: '外语水平',
  awards: '荣誉奖项',
  links: '链接',
};

const zhLabels: Partial<AdditionalSectionLabels> = {
  technicalSkills: '专业技能：',
  languages: '外语水平：',
  certifications: '培训与证书：',
  awards: '荣誉奖项：',
};

const fixture: ResumeData = {
  personalInfo: { name: '李勇', title: '架构师' },
  summary: '十余年研发管理经验。',
  education: [{ id: 1, years: '2006 - 2010', institution: '某大学', degree: '统招本科' }],
  workExperience: [
    {
      id: 1,
      years: '2020 - 至今',
      company: '某科技公司',
      title: '架构师',
      description: ['负责平台演进'],
      descriptionStyles: ['bullet'],
    },
  ],
  personalProjects: [
    { id: 1, name: '医院信息平台', years: '2018 - 2020', role: '核心开发', description: [] },
  ],
  additional: {
    technicalSkills: ['Java / Spring 生态', 'Python'],
    certificationsTraining: ['信息系统项目管理师（高项）证书'],
    awards: ['上海市优秀工程师（2022）'],
  },
  customSections: {
    custom_hobby: { sectionType: 'text', text: '阅读、跑步。' },
    custom_honors: { sectionType: 'stringList', strings: ['国家科技进步二等奖'] },
    custom_eval: { sectionType: 'text', text: '踏实肯干，持续学习。' },
  },
  sectionMeta: [
    meta({
      id: 'personalInfo',
      key: 'personalInfo',
      displayName: '基本信息',
      sectionType: 'personalInfo',
      isDefault: true,
      order: 0,
    }),
    meta({
      id: 'education',
      key: 'education',
      displayName: '教育背景',
      sectionType: 'itemList',
      isDefault: true,
      order: 1,
    }),
    meta({ id: 'summary', key: 'summary', displayName: '个人优势', isDefault: true, order: 2 }),
    meta({
      id: 'additional',
      key: 'additional',
      displayName: '专业技能',
      sectionType: 'stringList',
      isDefault: true,
      order: 3,
    }),
    meta({
      id: 'workExperience',
      key: 'workExperience',
      displayName: '工作经历',
      sectionType: 'itemList',
      isDefault: true,
      order: 4,
    }),
    meta({
      id: 'personalProjects',
      key: 'personalProjects',
      displayName: '项目经验',
      sectionType: 'itemList',
      isDefault: true,
      order: 5,
    }),
    meta({ id: 'custom_hobby', key: 'custom_hobby', displayName: '兴趣爱好', order: 6 }),
    meta({
      id: 'custom_honors',
      key: 'custom_honors',
      displayName: '荣誉证书',
      sectionType: 'stringList',
      order: 7,
    }),
    meta({ id: 'custom_eval', key: 'custom_eval', displayName: '自我评价', order: 8 }),
  ],
} as ResumeData;

type TemplateProps = {
  data: ResumeData;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
};

const singleColumnTemplates: Array<{
  name: string;
  Component: FC<TemplateProps>;
  singleEntryPlain?: boolean;
}> = [
  {
    name: 'swiss-single',
    Component: ResumeSingleColumn as FC<TemplateProps>,
    singleEntryPlain: true,
  },
  { name: 'modern', Component: ResumeModern as FC<TemplateProps> },
  { name: 'latex', Component: ResumeLatex as FC<TemplateProps> },
  { name: 'clean', Component: ResumeClean as FC<TemplateProps> },
];

const expectedOrder = ['项目经验', '兴趣爱好', '荣誉证书', '培训与证书', '荣誉奖项', '自我评价'];

describe('late additional modules placement — single-column templates', () => {
  for (const { name, Component, singleEntryPlain } of singleColumnTemplates) {
    it(`${name}: legacy honors custom block rides the cluster; cert/award modules anchor before selfeval`, () => {
      const { container } = render(
        <Component data={fixture} sectionHeadings={zhHeadings} additionalSectionLabels={zhLabels} />
      );

      const titles = Array.from(container.querySelectorAll('h3')).map((el) => el.textContent);
      const indices = expectedOrder.map((title) => titles.indexOf(title));
      for (const index of indices) expect(index).toBeGreaterThanOrEqual(0);
      expect(indices).toEqual([...indices].sort((a, b) => a - b));

      // The cert entry lives in its own module, never inside the skills block.
      const skillsTitle = Array.from(container.querySelectorAll('h3')).find(
        (el) => el.textContent === '专业技能'
      )!;
      expect(skillsTitle.parentElement!.textContent).not.toContain('信息系统项目管理师');

      const certsTitle = Array.from(container.querySelectorAll('h3')).find(
        (el) => el.textContent === '培训与证书'
      )!;
      const certsBlock = certsTitle.parentElement!;
      expect(certsBlock.textContent).toContain('信息系统项目管理师（高项）证书');
      if (singleEntryPlain) {
        // swiss-single: a lone entry is a plain paragraph, no ordered list.
        expect(certsBlock.querySelector('ol')).toBeNull();
      }
    });
  }
});

const twoColumnTemplates: Array<{
  name: string;
  Component: FC<TemplateProps>;
  styles: { readonly [key: string]: string };
}> = [
  {
    name: 'swiss-two-column',
    Component: ResumeTwoColumn as FC<TemplateProps>,
    styles: swissTwoStyles,
  },
  {
    name: 'modern-two-column',
    Component: ResumeModernTwoColumn as FC<TemplateProps>,
    styles: modernTwoStyles,
  },
  {
    name: 'vivid',
    Component: ResumeVivid as FC<TemplateProps>,
    styles: vividStyles,
  },
];

describe('late additional modules placement — two-column templates', () => {
  for (const { name, Component, styles: columnStyles } of twoColumnTemplates) {
    it(`${name}: both modules sit in the main column after custom sections, never the sidebar`, () => {
      const { container } = render(<Component data={fixture} sectionHeadings={zhHeadings} />);

      const main = container.querySelector(`.${columnStyles.mainColumn}`)!;
      const sidebar = container.querySelector(`.${columnStyles.sidebarColumn}`)!;
      expect(main).not.toBeNull();
      expect(sidebar).not.toBeNull();

      // Main column: every custom block comes first, then the two modules.
      const mainTitles = Array.from(main.querySelectorAll('h3')).map((el) => el.textContent);
      const iLastCustom = mainTitles.lastIndexOf('自我评价');
      const iCerts = mainTitles.indexOf('培训与证书');
      const iAwards = mainTitles.indexOf('荣誉奖项');
      expect(iLastCustom).toBeGreaterThanOrEqual(0);
      expect(iCerts).toBeGreaterThan(iLastCustom);
      expect(iAwards).toBeGreaterThan(iCerts);
      expect(main.textContent).toContain('信息系统项目管理师（高项）证书');

      // The sidebar keeps education/skills/languages but no cert/award module.
      const sidebarTitles = Array.from(sidebar.querySelectorAll('h3')).map((el) => el.textContent);
      expect(sidebarTitles).not.toContain('培训与证书');
      expect(sidebarTitles).not.toContain('荣誉奖项');
      expect(sidebar.textContent).not.toContain('信息系统项目管理师');
      expect(sidebarTitles).toContain('教育背景');
    });
  }
});
