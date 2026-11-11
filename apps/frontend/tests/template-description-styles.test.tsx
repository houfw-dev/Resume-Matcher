import { describe, expect, it, vi } from 'vitest';
import { render, within } from '@testing-library/react';
import React from 'react';
import type { ResumeData } from '@/components/dashboard/resume-component';

import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeLatex } from '@/components/resume/resume-latex';
import { ResumeModern } from '@/components/resume/resume-modern';
import { ResumeModernTwoColumn } from '@/components/resume/resume-modern-two-column';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';
import { ResumeTwoColumn } from '@/components/resume/resume-two-column';
import { ResumeVivid } from '@/components/resume/resume-vivid';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * T-03: every template threads `styles={exp.descriptionStyles}` into
 * DescriptionList, but nothing asserted it. Deleting that prop from any of the
 * seven files left the suite green while the template silently reverted to
 * all-bullets — the highest-risk regression in a 7-file copy-paste refactor.
 *
 * Markers are rendered in an aria-hidden span, so they are asserted through
 * textContent rather than by role.
 */

const buildData = (): ResumeData =>
  ({
    personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
    workExperience: [
      {
        id: 1,
        title: 'Engineer',
        company: 'Analytical Engines',
        location: 'London',
        years: '2024-Present',
        description: ['PLAIN ROW should have no marker', 'BULLET ROW should have one'],
        descriptionStyles: ['plain', 'bullet'],
      },
    ],
    additional: { technicalSkills: ['Ada'] },
  }) as ResumeData;

const TEMPLATES: [string, React.ComponentType<{ data: ResumeData }>][] = [
  ['ResumeClean', ResumeClean],
  ['ResumeLatex', ResumeLatex],
  ['ResumeModern', ResumeModern],
  ['ResumeModernTwoColumn', ResumeModernTwoColumn],
  ['ResumeSingleColumn', ResumeSingleColumn],
  ['ResumeTwoColumn', ResumeTwoColumn],
  ['ResumeVivid', ResumeVivid],
];

const rowFor = (container: HTMLElement, text: string): HTMLElement => {
  const node = within(container).getByText(text);
  const li = node.closest('li');
  if (!li) throw new Error(`no <li> ancestor for "${text}"`);
  return li as HTMLElement;
};

describe.each(TEMPLATES)('%s honours descriptionStyles', (_name, Template) => {
  it('renders a marker for bullet rows and none for plain rows', () => {
    const { container } = render(<Template data={buildData()} />);

    const plainRow = rowFor(container, 'PLAIN ROW should have no marker');
    const bulletRow = rowFor(container, 'BULLET ROW should have one');

    const markerIn = (li: HTMLElement) =>
      Array.from(li.querySelectorAll('[aria-hidden="true"]'))
        .map((n) => (n.textContent ?? '').trim())
        .filter(Boolean);

    // The bullet row carries a visible marker glyph; the plain row does not.
    expect(markerIn(bulletRow).length).toBeGreaterThan(0);
    expect(markerIn(plainRow)).toHaveLength(0);
  });

  it('defaults to bullets when descriptionStyles is absent (old resumes)', () => {
    const legacy = buildData();
    delete (legacy.workExperience![0] as { descriptionStyles?: unknown }).descriptionStyles;

    const { container } = render(<Template data={legacy} />);
    const row = rowFor(container, 'PLAIN ROW should have no marker');

    const markers = Array.from(row.querySelectorAll('[aria-hidden="true"]'))
      .map((n) => (n.textContent ?? '').trim())
      .filter(Boolean);

    expect(markers.length).toBeGreaterThan(0);
  });
});

// Project items canonicalize their sub-module names (工作职责/负责内容/… →
// 项目职责， 项目成果/技术亮点/… → 项目亮点）; work items must NOT. Deleting
// canonicalizeLabels at a project render site turns this red.
describe.each(TEMPLATES)('%s canonicalizes project sub-labels only', (_name, Template) => {
  const buildProjectData = (): ResumeData =>
    ({
      personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
      workExperience: [
        {
          id: 1,
          title: 'Engineer',
          company: 'Analytical Engines',
          years: '2024-Present',
          description: ['工作职责：', 'Did the work'],
          descriptionStyles: ['label', 'bullet'],
        },
      ],
      personalProjects: [
        {
          id: 1,
          name: 'Project X',
          description: [
            '项目简介：Glued intro prose.',
            '技术列表：SpringAI、RAG。',
            '项目成果：',
            'Shipped it',
            '负责内容：',
            'Built it',
          ],
          descriptionStyles: ['bullet', 'bullet', 'label', 'bullet', 'label', 'bullet'],
        },
      ],
      additional: { technicalSkills: ['Ada'] },
    }) as ResumeData;

  it('renames project aliases but leaves work labels verbatim', () => {
    const { container } = render(<Template data={buildProjectData()} />);

    expect(within(container).getByText('项目亮点：')).toBeInTheDocument();
    expect(within(container).getByText('项目职责：')).toBeInTheDocument();
    expect(within(container).queryByText('项目成果：')).not.toBeInTheDocument();
    expect(within(container).queryByText('负责内容：')).not.toBeInTheDocument();
    expect(within(container).getByText('工作职责：')).toBeInTheDocument();
  });

  it('splits glued intro/tech-list rows into bold labels and aligned bodies', () => {
    const { container } = render(<Template data={buildProjectData()} />);

    const markerIn = (el: HTMLElement) =>
      Array.from(el.querySelectorAll('[aria-hidden="true"]'))
        .map((n) => (n.textContent ?? '').trim())
        .filter(Boolean);

    // Glued descriptive rows are split display-only into a canonical bold
    // label plus its content on the next line.
    const bgLabel = within(container).getByText('项目背景：').closest('[data-sub-label]');
    const techLabel = within(container).getByText('技术栈：').closest('[data-sub-label]');
    expect(bgLabel).not.toBeNull();
    expect(techLabel).not.toBeNull();
    expect(bgLabel?.hasAttribute('data-descriptive')).toBe(true);
    expect(within(container).queryByText('项目简介：Glued intro prose.')).toBeNull();

    const introRow = within(container).getByText('Glued intro prose.').closest('[data-body-row]');
    const techRow = within(container).getByText('SpringAI、RAG。').closest('[data-body-row]');
    expect(introRow).not.toBeNull();
    expect(techRow).not.toBeNull();
    // Body content carries no number marker and sits in the flush body block
    // aligned to the project label / project name edge (padding-left 0, not
    // the 3.5ch indented duty list).
    expect(markerIn(introRow as HTMLElement)).toHaveLength(0);
    expect(markerIn(techRow as HTMLElement)).toHaveLength(0);
    expect(introRow?.parentElement?.className).toContain('resume-sub-body');
    expect(introRow?.parentElement?.className).toContain('resume-sub-body-flush');

    // Duty points under the renamed canonical labels still carry a marker.
    expect(markerIn(rowFor(container, 'Shipped it')).length).toBeGreaterThan(0);
    expect(markerIn(rowFor(container, 'Built it')).length).toBeGreaterThan(0);
  });

  it('aligns project sub-labels with the project name edge while work labels keep their number gutter', () => {
    const { container } = render(<Template data={buildProjectData()} />);

    const spacerIn = (label: HTMLElement | null) =>
      label?.querySelector('span[aria-hidden="true"]') ?? null;

    // Project labels （项目背景/技术栈/项目亮点/项目职责） reserve no number
    // gutter, so they start at the same left edge as the project name.
    ['项目背景：', '技术栈：', '项目亮点：', '项目职责：'].forEach((text) => {
      const label = within(container).getByText(text).closest('[data-sub-label]');
      expect(label).not.toBeNull();
      expect(spacerIn(label as HTMLElement)).toBeNull();
    });

    // Work-experience labels keep the 3ch gutter (and their verbatim name).
    const workLabel = within(container).getByText('工作职责：').closest('[data-sub-label]');
    expect(spacerIn(workLabel as HTMLElement)).not.toBeNull();

    // Project duty numbers start at the label edge (no extra list indent),
    // whereas the work list stays indented one number gutter.
    const projectList = rowFor(container, 'Built it').closest('ol');
    expect(projectList?.className).not.toContain('resume-list-indented');
    const workList = rowFor(container, 'Did the work').closest('ol');
    expect(workList?.className).toContain('resume-list-indented');
  });
});

// Technical skills render one entry per line in EVERY template: the group-head
// planner (list-format.ts) may insert bold head lines, but individual skills
// must never be comma/bullet-joined onto one text line or flow side-by-side as
// wrapping pills. Reverting any template to `.join(', ')` / `.join(' • ')` /
// flex-wrap pills makes these exact-text lookups throw, because a joined
// element's text no longer equals the bare skill name.
describe.each(TEMPLATES)('%s renders technical skills one entry per line', (_name, Template) => {
  const flatSkills: ResumeData = {
    personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
    additional: { technicalSkills: ['Python', 'TypeScript'] },
  } as ResumeData;

  it('never joins a flat skill list onto one line', () => {
    const { container } = render(<Template data={flatSkills} />);
    expect(within(container).getByText('Python')).toBeInTheDocument();
    expect(within(container).getByText('TypeScript')).toBeInTheDocument();
    expect(container.textContent).not.toContain('Python, TypeScript');
    expect(container.textContent).not.toContain('Python • TypeScript');
  });

  // Two short punctuation-free heads, each followed by a long detail-shaped
  // successor: planSkillGroupHeaders qualifies both (>= SKILL_GROUP_MIN_HEADS).
  const groupedSkills: ResumeData = {
    personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
    additional: {
      technicalSkills: [
        '后端开发',
        '熟悉 Java 与 Spring Boot 生态，具备高并发系统设计经验',
        '数据存储',
        '熟悉 MySQL、Redis 与消息队列的选型和调优',
      ],
    },
  } as ResumeData;

  it('keeps each group head on its own line with every detail entry on a separate line', () => {
    const { container } = render(<Template data={groupedSkills} />);
    expect(within(container).getByText('后端开发')).toBeInTheDocument();
    expect(within(container).getByText('数据存储')).toBeInTheDocument();
    expect(
      within(container).getByText('熟悉 Java 与 Spring Boot 生态，具备高并发系统设计经验')
    ).toBeInTheDocument();
    expect(
      within(container).getByText('熟悉 MySQL、Redis 与消息队列的选型和调优')
    ).toBeInTheDocument();
  });
});

// jsdom performs no layout, so the one-pill-per-row contract of the two
// sidebar templates is locked at the container's flex direction: each skill
// was already its own element under the old flex-wrap design, so text
// assertions alone cannot catch a visual side-by-side reflow. A revert to
// flex-wrap must turn this red.
const PILL_TEMPLATES: [string, React.ComponentType<{ data: ResumeData }>][] = [
  ['ResumeTwoColumn', ResumeTwoColumn],
  ['ResumeModernTwoColumn', ResumeModernTwoColumn],
];

describe.each(PILL_TEMPLATES)('%s stacks skill pills one per row', (_name, Template) => {
  it('uses a column flex container, never flex-wrap side-by-side pills', () => {
    const data: ResumeData = {
      personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
      additional: { technicalSkills: ['Python', 'TypeScript', 'Go'] },
    } as ResumeData;
    const { container } = render(<Template data={data} />);
    const skillsContainer = within(container).getByText('Python').parentElement!;
    expect(skillsContainer.className).toContain('flex-col');
    expect(skillsContainer.className).not.toContain('flex-wrap');
  });
});
