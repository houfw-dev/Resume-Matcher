import { describe, expect, it } from 'vitest';

import type { ResumeData } from '@/components/dashboard/resume-component';
import { cleanTextBlock, normalizeTextHygiene } from '@/lib/utils/text-hygiene';

const baseResume = (): ResumeData =>
  ({
    personalInfo: {},
    summary: '',
    workExperience: [],
    education: [],
    personalProjects: [],
    additional: {},
    customSections: {},
    sectionMeta: [],
  }) as unknown as ResumeData;

describe('normalizeTextHygiene', () => {
  it('drops blank description rows and their styles in lockstep', () => {
    const resume = baseResume();
    resume.workExperience = [
      {
        company: '  某公司  ',
        description: ['负责架构', '  ', '推进微服务', ''],
        descriptionStyles: ['bullet', 'plain', 'bullet', 'bullet'],
      },
    ] as ResumeData['workExperience'];

    const result = normalizeTextHygiene(resume);
    const entry = result.workExperience?.[0] as unknown as Record<string, unknown>;
    expect(entry.description).toEqual(['负责架构', '推进微服务']);
    expect(entry.descriptionStyles).toEqual(['bullet', 'bullet']);
    expect(entry.company).toBe('某公司');
  });

  it('strips bullet endings but keeps plain prose and label colons', () => {
    const resume = baseResume();
    resume.personalProjects = [
      {
        name: 'P',
        description: [
          '项目背景：',
          '这是一段散文描述。',
          '完成性能优化；',
          '可用性提升至 99.99%。',
        ],
        descriptionStyles: ['label', 'plain', 'bullet', 'bullet'],
      },
    ] as ResumeData['personalProjects'];

    const result = normalizeTextHygiene(resume);
    expect(result.personalProjects?.[0].description).toEqual([
      '项目背景：',
      '这是一段散文描述。',
      '完成性能优化',
      '可用性提升至 99.99%',
    ]);
  });

  it('collapses whitespace runs inside rows', () => {
    const resume = baseResume();
    resume.workExperience = [
      {
        description: ['Java\t\t并发   与  JVM', ' 带不间断空格 '],
        descriptionStyles: ['bullet', 'plain'],
      },
    ] as ResumeData['workExperience'];

    const rows = normalizeTextHygiene(resume).workExperience?.[0].description;
    expect(rows).toEqual(['Java 并发 与 JVM', '带不间断空格']);
  });

  it('trims summary lines, drops blank lines and strips endings', () => {
    const resume = baseResume();
    resume.summary = '  10 年研发管理经验。\n\n  \n主导过多个大型平台；\n带过 200 人技术团队。';

    expect(normalizeTextHygiene(resume).summary).toBe(
      '10 年研发管理经验\n主导过多个大型平台\n带过 200 人技术团队'
    );
  });

  it('cleans rendered string lists', () => {
    const resume = baseResume();
    resume.additional = {
      technicalSkills: ['  Java / Spring 生态。', '', '  ', 'Python；'],
      languages: ['英语六级 '],
      certificationsTraining: ['PMP。'],
      awards: ['优秀员工。'],
    } as ResumeData['additional'];

    const additional = normalizeTextHygiene(resume).additional as Record<string, unknown>;
    expect(additional.technicalSkills).toEqual(['Java / Spring 生态', 'Python']);
    expect(additional.languages).toEqual(['英语六级']);
    expect(additional.certificationsTraining).toEqual(['PMP']);
    expect(additional.awards).toEqual(['优秀员工']);
  });

  it('strips self-evaluation text endings but keeps ordinary prose text', () => {
    const resume = baseResume();
    resume.customSections = {
      self_evaluation: {
        sectionType: 'text',
        text: '踏实肯干。\n\n持续学习。',
      },
      hobbies: { sectionType: 'text', text: '阅读。\n\n跑步。' },
    } as ResumeData['customSections'];

    const sections = normalizeTextHygiene(resume).customSections as Record<
      string,
      { text: string }
    >;
    expect(sections.self_evaluation.text).toBe('踏实肯干\n持续学习');
    expect(sections.hobbies.text).toBe('阅读。\n跑步。');
  });

  it('cleans custom itemList titles and descriptions', () => {
    const resume = baseResume();
    resume.customSections = {
      papers: {
        sectionType: 'itemList',
        items: [
          {
            title: '  某核心期刊论文  ',
            subtitle: '第一作者 ',
            description: ['提出一种新架构。', ' '],
            descriptionStyles: ['bullet', 'plain'],
          },
        ],
      },
    } as unknown as ResumeData['customSections'];

    const item = (
      normalizeTextHygiene(resume).customSections as unknown as {
        papers: {
          items: Array<{
            title: string;
            subtitle: string;
            description: string[];
            descriptionStyles: string[];
          }>;
        };
      }
    ).papers.items[0];
    expect(item.title).toBe('某核心期刊论文');
    expect(item.subtitle).toBe('第一作者');
    expect(item.description).toEqual(['提出一种新架构']);
    expect(item.descriptionStyles).toEqual(['bullet']);
  });

  it('trims personalInfo headers but preserves workYears content', () => {
    const resume = baseResume();
    resume.personalInfo = {
      name: '  李勇 ',
      title: ' 架构师 ',
      workYears: '15年+ 5年大型医院项目 ',
    } as ResumeData['personalInfo'];

    const info = normalizeTextHygiene(resume).personalInfo!;
    expect(info.name).toBe('李勇');
    expect(info.title).toBe('架构师');
    expect(info.workYears).toBe('15年+ 5年大型医院项目');
  });

  it('is idempotent', () => {
    const resume = baseResume();
    resume.summary = ' 10 年经验。\n\n\n主导架构演进。\n';
    resume.workExperience = [
      {
        company: ' 某公司 ',
        description: ['负责架构。', ' ', '推进微服务。'],
        descriptionStyles: ['bullet', 'plain', 'bullet'],
      },
    ] as ResumeData['workExperience'];
    resume.additional = {
      technicalSkills: [' Java。', '', 'Python；'],
    } as ResumeData['additional'];
    resume.customSections = {
      self_evaluation: {
        sectionType: 'text',
        text: '踏实肯干。\n\n持续学习。',
      },
    } as ResumeData['customSections'];

    const once = normalizeTextHygiene(resume);
    const twice = normalizeTextHygiene(once);
    expect(twice).toEqual(once);
  });

  it('does not mutate the input object', () => {
    const resume = baseResume();
    resume.summary = ' 点一。\n ';
    const snapshot = JSON.stringify(resume);
    normalizeTextHygiene(resume);
    expect(JSON.stringify(resume)).toBe(snapshot);
  });
});

describe('cleanTextBlock', () => {
  it('leaves non-string values untouched', () => {
    expect(cleanTextBlock(undefined, { stripEndings: true })).toBeUndefined();
    expect(cleanTextBlock(null, { stripEndings: true })).toBeNull();
  });
});
