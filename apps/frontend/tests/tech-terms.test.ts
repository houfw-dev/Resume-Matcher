import { describe, expect, it } from 'vitest';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { canonicalizeTechTerms, canonicalizeTermsInText } from '@/lib/utils/tech-terms';

describe('canonicalizeTermsInText', () => {
  it('canonicalizes lowercase terms', () => {
    expect(canonicalizeTermsInText('熟悉 java 和 python')).toBe('熟悉 Java 和 Python');
  });

  it('canonicalizes all-caps compounds and acronyms', () => {
    expect(canonicalizeTermsInText('SPRING BOOT')).toBe('Spring Boot');
    expect(canonicalizeTermsInText('Devops ci/cd')).toBe('DevOps CI/CD');
    expect(canonicalizeTermsInText('svn, git, aws')).toBe('SVN, Git, AWS');
  });

  it('matches terms adjacent to CJK', () => {
    expect(canonicalizeTermsInText('mysql集群')).toBe('MySQL集群');
    expect(canonicalizeTermsInText('使用redis缓存')).toBe('使用Redis缓存');
  });

  it('lets the longest term win over its prefix', () => {
    expect(canonicalizeTermsInText('javascript')).toBe('JavaScript');
    expect(canonicalizeTermsInText('JAVASCRIPT and JAVA')).toBe('JavaScript and Java');
  });

  it('does not match inside other ASCII words', () => {
    expect(canonicalizeTermsInText('Vue.jsx')).toBe('Vue.jsx');
    expect(canonicalizeTermsInText('Javanese tea')).toBe('Javanese tea');
  });

  it('leaves dates and non-strings untouched', () => {
    expect(canonicalizeTermsInText('2020.06~2023.09')).toBe('2020.06~2023.09');
    expect(canonicalizeTermsInText(null)).toBeNull();
    expect(canonicalizeTermsInText(123)).toBe(123);
    expect(canonicalizeTermsInText('')).toBe('');
  });
});

describe('canonicalizeTechTerms', () => {
  const resume = {
    personalInfo: { name: 'java 张三', email: 'java@example.com' },
    summary: '五年 java 经验，熟悉 spring boot。',
    workExperience: [
      {
        id: 1,
        title: 'java 开发',
        company: 'Acme java Corp',
        years: '2020.06~2023.09',
        description: ['spring cloud 改造', 'mysql 与 redis'],
        descriptionStyles: ['bullet', 'bullet'],
      },
    ],
    personalProjects: [
      {
        id: 1,
        name: 'vue.js 组件库',
        role: '前端',
        description: ['typescript 开发'],
      },
    ],
    additional: {
      technicalSkills: ['java', 'Spring Boot', 'mysql集群'],
      languages: ['英语 CET-6'],
      certificationsTraining: ['aws 架构师'],
      awards: [],
    },
    customSections: {
      stack: {
        sectionType: 'itemList',
        items: [
          {
            title: 'docker',
            subtitle: 'devops',
            description: ['ci/cd 流水线'],
          },
        ],
      },
      hobbies: { sectionType: 'stringList', strings: ['linux 内核'] },
      self_evaluation: { sectionType: 'text', text: '熟悉 nginx' },
    },
  } as unknown as ResumeData;

  it('canonicalizes every content field', () => {
    const result = canonicalizeTechTerms(resume);

    expect(result.summary).toBe('五年 Java 经验，熟悉 Spring Boot。');
    expect(result.workExperience?.[0].title).toBe('Java 开发');
    expect(result.workExperience?.[0].description).toEqual(['Spring Cloud 改造', 'MySQL 与 Redis']);
    expect(result.personalProjects?.[0].name).toBe('Vue.js 组件库');
    expect(result.personalProjects?.[0].description).toEqual(['TypeScript 开发']);
    expect(result.additional?.technicalSkills).toEqual(['Java', 'Spring Boot', 'MySQL集群']);
    expect(result.additional?.certificationsTraining).toEqual(['AWS 架构师']);
    const sections = result.customSections as unknown as {
      stack: { items: { title: string; subtitle: string; description: string[] }[] };
      hobbies: { strings: string[] };
      self_evaluation: { text: string };
    };
    expect(sections.stack.items[0].title).toBe('Docker');
    expect(sections.stack.items[0].subtitle).toBe('DevOps');
    expect(sections.stack.items[0].description).toEqual(['CI/CD 流水线']);
    expect(sections.hobbies.strings).toEqual(['Linux 内核']);
    expect(sections.self_evaluation.text).toBe('熟悉 Nginx');
  });

  it('skips personalInfo, years and company fields', () => {
    const result = canonicalizeTechTerms(resume);

    expect(result.personalInfo?.name).toBe('java 张三');
    expect(result.personalInfo?.email).toBe('java@example.com');
    expect(result.workExperience?.[0].company).toBe('Acme java Corp');
    expect(result.workExperience?.[0].years).toBe('2020.06~2023.09');
  });

  it('does not mutate the input', () => {
    const snapshot = JSON.parse(JSON.stringify(resume));
    canonicalizeTechTerms(resume);
    expect(resume).toEqual(snapshot);
  });
});
