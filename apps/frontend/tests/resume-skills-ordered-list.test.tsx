import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import type { AdditionalSectionLabels, ResumeData } from '@/components/dashboard/resume-component';
import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeLatex } from '@/components/resume/resume-latex';
import { ResumeModern } from '@/components/resume/resume-modern';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * Modern / LaTeX / Clean render technical skills as an ORDERED numbered list
 * (the same contract as swiss-single and the DOCX exporter): one number per
 * skill line, bold unnumbered group heads with per-group restarting numbers,
 * and no inline "Technical Skills:" label — the section heading already names
 * the block. Reverting any template to unnumbered divs, re-adding the label or
 * joining lines makes these assertions red.
 */
type TemplateProps = {
  data: ResumeData;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
};

const TEMPLATES: [string, React.ComponentType<TemplateProps>][] = [
  ['ResumeClean', ResumeClean],
  ['ResumeLatex', ResumeLatex],
  ['ResumeModern', ResumeModern],
];

const baseData = (additional: ResumeData['additional']): ResumeData =>
  ({
    personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
    additional,
  }) as ResumeData;

const skillsSection = (): HTMLElement =>
  screen.getByRole('heading', { level: 3, name: 'Skills & Awards' }).parentElement!;

describe.each(TEMPLATES)('%s technical skills as an ordered list', (_name, Template) => {
  it('numbers a flat skill list 1..n in one <ol>, one skill per line', () => {
    render(<Template data={baseData({ technicalSkills: ['Python', 'TypeScript', 'Go'] })} />);

    const section = skillsSection();
    const lists = section.querySelectorAll('ol');
    expect(lists).toHaveLength(1);
    const items = lists[0].querySelectorAll('li');
    expect(items).toHaveLength(3);
    // Number and text sit in separate spans (CSS gap), so textContent starts
    // with the marker with no whitespace.
    expect(items[0].textContent).toMatch(/^1\./);
    expect(items[1].textContent).toMatch(/^2\./);
    expect(items[2].textContent).toMatch(/^3\./);
    expect(within(section).getByText('Python')).toBeInTheDocument();
    expect(within(section).getByText('TypeScript')).toBeInTheDocument();
    expect(within(section).getByText('Go')).toBeInTheDocument();
    // Never joined onto one line.
    expect(section.textContent).not.toContain('Python, TypeScript');
  });

  it('renders a lone skill as plain text, never a singleton numbered list', () => {
    render(<Template data={baseData({ technicalSkills: ['Rust'] })} />);

    const section = skillsSection();
    expect(section.querySelector('ol')).toBeNull();
    expect(within(section).getByText('Rust')).toBeInTheDocument();
  });

  it('renders bold unnumbered group heads with per-group restarting numbers', () => {
    const grouped = baseData({
      technicalSkills: [
        '后端开发',
        '熟悉 Java 与 Spring Boot 生态，具备高并发系统设计经验',
        '熟悉高并发场景下的缓存设计与限流降级方案',
        '数据存储',
        '熟悉 MySQL、Redis 与消息队列的选型和调优',
        '熟悉数据库分库分表与慢查询治理的落地经验',
      ],
    });
    render(<Template data={grouped} />);

    const section = skillsSection();
    const heads = section.querySelectorAll('[data-skill-group]');
    expect(heads).toHaveLength(2);
    expect(within(section).getByText('后端开发')).toBeInTheDocument();
    expect(within(section).getByText('数据存储')).toBeInTheDocument();
    // Trailing colons are trimmed and heads are never list items.
    expect(section.textContent).not.toContain('后端开发：');
    heads.forEach((head) => expect(head.closest('li')).toBeNull());

    const lists = section.querySelectorAll('ol');
    expect(lists).toHaveLength(2);
    const firstItems = lists[0].querySelectorAll('li');
    const secondItems = lists[1].querySelectorAll('li');
    expect(firstItems).toHaveLength(2);
    expect(secondItems).toHaveLength(2);
    expect(firstItems[0].textContent).toMatch(/^1\./);
    expect(firstItems[1].textContent).toMatch(/^2\./);
    // Numbering restarts at 1 for the second group.
    expect(secondItems[0].textContent).toMatch(/^1\./);
    expect(secondItems[1].textContent).toMatch(/^2\./);
  });

  it('never emits the inline technical-skills label, while languages keep theirs', () => {
    render(
      <Template
        data={baseData({
          technicalSkills: ['Python', 'Go'],
          languages: ['英语 CET-6'],
        })}
        additionalSectionLabels={{ technicalSkills: '技术技能：', languages: '外语：' }}
      />
    );

    const section = skillsSection();
    // The localized inline label must not render anywhere (the section title
    // is the only heading the block needs).
    expect(screen.queryByText('技术技能：')).toBeNull();
    expect(section.textContent).not.toContain('技术技能：');
    expect(screen.queryByText('Technical Skills:')).toBeNull();
    // The skills themselves still render, numbered.
    expect(section.querySelector('ol')?.querySelectorAll('li')).toHaveLength(2);
    // Languages are untouched: bold inline label + joined line.
    expect(within(section).getByText('外语：')).toBeInTheDocument();
    expect(within(section).getByText('英语 CET-6')).toBeInTheDocument();
  });
});
