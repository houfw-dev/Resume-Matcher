import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ResumeData } from '@/components/dashboard/resume-component';
import type { PersonalInfoLabels } from '@/lib/utils/resume-headings';
import { DEFAULT_PERSONAL_INFO_LABELS } from '@/lib/utils/resume-headings';
import { buildHeaderFactCells } from '@/components/resume/header-fact-grid';
import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeLatex } from '@/components/resume/resume-latex';
import { ResumeModern } from '@/components/resume/resume-modern';
import baseStyles from '@/components/resume/styles/_base.module.css';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * Modern / LaTeX / Clean surface the basic-info facts （性别/年龄/学历/工作
 * 年限/求职意向/意向城市/电话/邮箱/外语水平） in a centered header fact grid
 * with the SAME order and fallback rules as swiss-single's info grid and the
 * resume-parsing-rules 基本信息 spec. The old standalone title/location and
 * pipe/middot/comma contact lines are absorbed into labeled cells; social
 * links stay on their own row outside the grid; languages render ONLY here,
 * never in the skills section. jsdom performs no layout, so the contract is
 * locked via data-header-fact* tokens, cell structure and class tokens.
 */
const zhLabels: PersonalInfoLabels = {
  gender: '性别',
  age: '年龄',
  educationLevel: '学历',
  workYears: '工作年限',
  jobIntention: '求职意向',
  desiredCity: '意向城市',
  phone: '电话',
  email: '邮箱',
  foreignLanguage: '外语水平',
  website: '个人网站',
  linkedin: '领英',
  github: 'GitHub',
};

const fullData: ResumeData = {
  personalInfo: {
    name: '王浩',
    gender: '男',
    age: '28岁',
    educationLevel: '硕士',
    workYears: '5年',
    title: 'Java 开发工程师',
    location: '深圳',
    phone: '13800000000',
    email: 'wanghao@example.com',
    website: 'wanghao.dev',
    linkedin: 'in/wanghao',
    github: 'wanghao',
  },
  education: [{ id: 1, institution: '某大学', degree: '本科', years: '2016 - 2020' }],
  additional: {
    technicalSkills: ['Java 并发'],
    languages: ['英语 CET-6', '日语 N2'],
  },
} as ResumeData;

type TemplateProps = {
  data: ResumeData;
  personalInfoLabels?: Partial<PersonalInfoLabels>;
};

const TEMPLATES: [string, React.ComponentType<TemplateProps>][] = [
  ['ResumeClean', ResumeClean],
  ['ResumeLatex', ResumeLatex],
  ['ResumeModern', ResumeModern],
];

describe('buildHeaderFactCells pure contract', () => {
  it('emits the nine facts in the fixed Chinese-resume order', () => {
    const cells = buildHeaderFactCells({
      personalInfo: fullData.personalInfo,
      education: fullData.education,
      languages: fullData.additional?.languages,
      labels: DEFAULT_PERSONAL_INFO_LABELS,
    });

    expect(cells.map((cell) => cell.key)).toEqual([
      'gender',
      'age',
      'educationLevel',
      'workYears',
      'jobIntention',
      'desiredCity',
      'phone',
      'email',
      'foreignLanguage',
    ]);
    expect(cells.map((cell) => cell.label)).toEqual([
      'Gender',
      'Age',
      'Education',
      'Years of Experience',
      'Job Objective',
      'Desired City',
      'Phone',
      'Email',
      'Foreign Languages',
    ]);
  });

  it('keeps the phone a plain string fact while email becomes a mailto anchor', () => {
    const cells = buildHeaderFactCells({
      personalInfo: fullData.personalInfo,
      labels: DEFAULT_PERSONAL_INFO_LABELS,
    });

    const phone = cells.find((cell) => cell.key === 'phone')!;
    expect(phone.value).toBe('13800000000');

    const email = cells.find((cell) => cell.key === 'email')!;
    expect(React.isValidElement(email.value)).toBe(true);
    const emailAnchor = email.value as React.ReactElement<{ href: string }>;
    expect(emailAnchor.props.href).toBe('mailto:wanghao@example.com');
  });

  it('omits blank/whitespace facts and joins languages with the ideographic comma', () => {
    const cells = buildHeaderFactCells({
      personalInfo: { name: '王浩', gender: '  ', age: '', phone: '13800000000' },
      languages: ['英语 CET-6', '   ', '日语 N2'],
      labels: DEFAULT_PERSONAL_INFO_LABELS,
    });

    expect(cells.map((cell) => cell.key)).toEqual(['phone', 'foreignLanguage']);
    expect(cells[1].value).toBe('英语 CET-6、日语 N2');
  });

  it('falls back to the first education degree, while an explicit educationLevel wins', () => {
    const fallback = buildHeaderFactCells({
      personalInfo: { name: '王浩' },
      education: [
        { id: 1, institution: '另一个学院', degree: '大专' },
        { id: 2, institution: '某大学', degree: '统招本科' },
      ],
      labels: DEFAULT_PERSONAL_INFO_LABELS,
    });
    expect(fallback.find((cell) => cell.key === 'educationLevel')?.value).toBe('大专');

    const explicit = buildHeaderFactCells({
      personalInfo: { name: '王浩', educationLevel: '硕士' },
      education: [{ id: 1, degree: '本科' }],
      labels: DEFAULT_PERSONAL_INFO_LABELS,
    });
    expect(explicit.find((cell) => cell.key === 'educationLevel')?.value).toBe('硕士');
  });
});

describe.each(TEMPLATES)('%s header fact grid', (_name, Template) => {
  it('renders the nine labeled facts as three rows of three in the fixed order', () => {
    const { container } = render(<Template data={fullData} personalInfoLabels={zhLabels} />);

    const grid = container.querySelector('[data-header-fact-grid]')!;
    expect(grid).toBeTruthy();
    // The centered variant centers the grid block (swiss-single's grid is
    // left-aligned) while keeping the shared row/cell structure.
    expect(grid.className).toContain('items-center');

    const rows = Array.from(grid.querySelectorAll('[data-header-fact-row]'));
    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.children.length)).toEqual([3, 3, 3]);

    const cells = rows.flatMap((row) => Array.from(row.children));
    expect(cells.map((cell) => cell.getAttribute('data-header-fact'))).toEqual([
      'gender',
      'age',
      'educationLevel',
      'workYears',
      'jobIntention',
      'desiredCity',
      'phone',
      'email',
      'foreignLanguage',
    ]);
    expect(cells.map((cell) => cell.textContent)).toEqual([
      '性别男',
      '年龄28岁',
      '学历硕士',
      '工作年限5年',
      '求职意向Java 开发工程师',
      '意向城市深圳',
      '电话13800000000',
      '邮箱wanghao@example.com',
      '外语水平英语 CET-6、日语 N2',
    ]);

    // Labels use the muted 0.75× meta face, values the 0.92× face — the same
    // sizes as swiss-single's infoLabel / infoValue.
    for (const cell of cells) {
      expect(cell.children[0]).toHaveClass(baseStyles['resume-meta-sm']);
      expect(cell.children[1]).toHaveClass(baseStyles['resume-text-sm']);
    }
  });

  it('keeps the phone a plain non-link fact and email a mailto anchor', () => {
    const { container } = render(<Template data={fullData} personalInfoLabels={zhLabels} />);

    expect(screen.getByText('13800000000')).toBeInTheDocument();
    expect(container.querySelector('a[href^="tel:"]')).toBeNull();
    const phoneCell = container.querySelector('[data-header-fact="phone"]')!;
    expect(phoneCell.querySelector('a')).toBeNull();

    const emailAnchor = screen.getByRole('link', { name: 'wanghao@example.com' });
    expect(emailAnchor.getAttribute('href')).toBe('mailto:wanghao@example.com');
    expect(emailAnchor.closest('[data-header-fact]')?.getAttribute('data-header-fact')).toBe(
      'email'
    );
  });

  it('absorbs title/location into cells: no standalone tagline or h2 remains', () => {
    const { container } = render(<Template data={fullData} personalInfoLabels={zhLabels} />);

    // Modern previously rendered the title as an uppercase h2; all three
    // templates now expose it only as the 求职意向 fact cell.
    expect(container.querySelector('h2')).toBeNull();
    const intention = container.querySelector('[data-header-fact="jobIntention"]')!;
    expect(intention.textContent).toBe('求职意向Java 开发工程师');
    const city = container.querySelector('[data-header-fact="desiredCity"]')!;
    expect(city.textContent).toBe('意向城市深圳');
  });

  it('keeps social links on their own row outside the fact grid', () => {
    const { container } = render(<Template data={fullData} personalInfoLabels={zhLabels} />);

    const grid = container.querySelector('[data-header-fact-grid]')!;
    expect(grid.textContent).not.toContain('wanghao.dev');
    for (const name of ['wanghao.dev', 'in/wanghao', 'wanghao']) {
      const anchor = screen.getByRole('link', { name });
      expect(anchor.closest('[data-header-fact-grid]')).toBeNull();
    }
  });

  it('falls back to the first education degree when educationLevel is blank', () => {
    const fallbackData: ResumeData = {
      personalInfo: { name: '王浩', title: '架构师' },
      education: [{ id: 1, institution: '某大学', degree: '统招本科', years: '2016 - 2020' }],
    } as ResumeData;

    const { container } = render(<Template data={fallbackData} personalInfoLabels={zhLabels} />);

    const level = container.querySelector('[data-header-fact="educationLevel"]')!;
    expect(level.textContent).toBe('学历统招本科');
    const intention = container.querySelector('[data-header-fact="jobIntention"]')!;
    expect(intention.textContent).toBe('求职意向架构师');
  });

  it('omits blank facts and chunks the survivors into rows of at most three', () => {
    const sparseData: ResumeData = {
      personalInfo: { name: '王浩', phone: '13800000000' },
    } as ResumeData;

    const { container } = render(<Template data={sparseData} personalInfoLabels={zhLabels} />);

    const rows = container.querySelectorAll('[data-header-fact-row]');
    expect(rows).toHaveLength(1);
    expect(rows[0].children).toHaveLength(1);
    expect(rows[0].children[0].getAttribute('data-header-fact')).toBe('phone');
  });

  it('renders languages only in the header: no skills block when technical skills are absent', () => {
    const languageOnly: ResumeData = {
      personalInfo: { name: '王浩' },
      additional: { languages: ['英语 CET-6'] },
    } as ResumeData;

    render(<Template data={languageOnly} personalInfoLabels={zhLabels} />);

    // The skills section disappears entirely (it no longer hosts languages).
    expect(screen.queryByRole('heading', { level: 3, name: 'Skills & Awards' })).toBeNull();
    const cell = screen.getByText('英语 CET-6').closest('[data-header-fact]')!;
    expect(cell.getAttribute('data-header-fact')).toBe('foreignLanguage');
    expect(cell.textContent).toContain('外语水平');
  });
});
