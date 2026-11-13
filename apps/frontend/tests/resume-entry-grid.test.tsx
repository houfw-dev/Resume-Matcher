import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import React from 'react';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeLatex } from '@/components/resume/resume-latex';
import { ResumeModern } from '@/components/resume/resume-modern';
import cleanStyles from '@/components/resume/styles/clean.module.css';
import latexStyles from '@/components/resume/styles/latex.module.css';
import modernStyles from '@/components/resume/styles/modern.module.css';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * Work and education entry headers in Modern / LaTeX / Clean render as ONE
 * time-first justified row — work: time | company · location | department |
 * role; education: time | university | major | degree — mirroring the
 * swiss-single contract. The SECTION grid (.entryGridSection) owns the fixed
 * minmax(0, …) tracks once; every item and header row nests as a subgrid, so
 * column edges align across every entry (行列对齐） even though the role track
 * is `auto` — per-row grids used to size it independently and let a long
 * title shift the department column left. The date is flush left and
 * role/degree flush right （两端对齐）, and a long value wraps inside its own
 * cell instead of pushing another field onto a second line. A work entry
 * without a department uses a three-cell row whose role spans the last two
 * tracks; a legacy plain department description line is promoted into the
 * department column. jsdom performs no layout, so the contract is locked at
 * class token + cell structure plus a stylesheet content lock.
 */
const data: ResumeData = {
  personalInfo: { name: '李勇', email: 'li@example.com' },
  workExperience: [
    {
      id: 1,
      title: '高级工程师',
      company: '甲科技有限公司',
      department: '研发中心',
      location: '上海',
      years: '2020.01 - 2023.05',
      description: ['负责平台架构'],
      descriptionStyles: ['bullet'],
    },
    {
      id: 2,
      title: '前端工程师',
      company: '乙网络公司',
      location: '北京',
      years: '2023.06 - 至今',
      description: ['负责页面开发'],
    },
    {
      // Legacy storage: a standalone org-unit line filed as the first "plain"
      // description row must be lifted into the department column.
      id: 3,
      title: '测试经理',
      company: '丙集团',
      years: '2018 - 2020',
      description: ['质量保障部', '负责测试体系建设'],
      descriptionStyles: ['plain', 'bullet'],
    },
  ],
  education: [
    {
      id: 1,
      institution: '某某大学',
      degree: '本科',
      years: '2016.09 - 2020.06',
      // education.description doubles as the major column.
      description: '计算机科学与技术',
    },
    {
      id: 2,
      institution: '另一个学院',
      degree: '大专',
      years: '2013 - 2016',
    },
  ],
  additional: { technicalSkills: ['Java'] },
} as ResumeData;

const rowOf = (text: string): HTMLElement => screen.getByText(text).parentElement!;

// CSS modules arrive as generic string-index maps; every module below defines
// the same entry* class names used in the assertions.
const TEMPLATES: [string, React.ComponentType<{ data: ResumeData }>, Record<string, string>][] = [
  ['ResumeClean', ResumeClean, cleanStyles],
  ['ResumeLatex', ResumeLatex, latexStyles],
  ['ResumeModern', ResumeModern, modernStyles],
];

describe.each(TEMPLATES)('%s work entries on time-first justified rows', (_name, Template, css) => {
  it('renders a department entry as one four-track row: time | company · location | department | role', () => {
    render(<Template data={data} />);

    const roleCell = screen.getByText('高级工程师');
    const row = roleCell.parentElement!;
    expect(row).toHaveClass(css.entryGrid);
    expect(row.className).not.toContain('justify-between');
    expect(row.children).toHaveLength(4);

    expect(row.children[0]).toHaveClass(css.entryDate);
    expect(row.children[0].textContent).toContain('2020');

    // Location is merged into the company cell with a middot, never its own
    // grid track, so all four requested fields stay on the single row.
    expect(row.children[1].textContent).toContain('甲科技有限公司');
    expect(row.children[1].textContent).toContain('上海');

    expect(row.children[2]).toHaveClass(css.entryDepartment);
    expect(row.children[2].textContent).toBe('研发中心');

    expect(row.children[3]).toBe(roleCell);
    expect(roleCell).toHaveClass(css.entryRoleEnd);
    expect(roleCell.textContent).toBe('高级工程师');
  });

  it('renders an entry without a department on a three-track row, role still flush right', () => {
    render(<Template data={data} />);

    const roleCell = screen.getByText('前端工程师');
    const row = roleCell.parentElement!;
    expect(row).toHaveClass(css.entryGridThree);
    expect(row.children).toHaveLength(3);
    expect(row.children[0]).toHaveClass(css.entryDate);
    expect(row.children[0].textContent).toContain('2023');
    expect(row.children[1].textContent).toContain('乙网络公司');
    expect(row.children[1].textContent).toContain('北京');
    expect(row.children[2]).toBe(roleCell);
    expect(roleCell).toHaveClass(css.entryRoleEnd);
  });

  it('promotes a legacy plain department description row into the department column', () => {
    render(<Template data={data} />);

    const departmentCell = screen.getByText('质量保障部');
    const row = departmentCell.parentElement!;
    expect(row).toHaveClass(css.entryGrid);
    expect(row.children[2]).toBe(departmentCell);

    // The promoted line no longer renders inside the bullet list; the
    // remaining description row still does.
    const entryItem = row.parentElement!;
    const bulletList = entryItem.querySelector('ol');
    expect(bulletList).not.toBeNull();
    expect(bulletList!.textContent).not.toContain('质量保障部');
    expect(within(entryItem).getByText('负责测试体系建设')).toBeInTheDocument();
  });
});

describe.each(TEMPLATES)(
  '%s education entries on time-first justified rows',
  (_name, Template, css) => {
    it('renders time | university | major | degree on one four-track row', () => {
      render(<Template data={data} />);

      const row = rowOf('某某大学');
      expect(row).toHaveClass(css.entryGrid);
      expect(row.children).toHaveLength(4);
      expect(row.children[0]).toHaveClass(css.entryDate);
      expect(row.children[0].textContent).toContain('2016');
      expect(row.children[1].textContent).toContain('某某大学');
      expect(row.children[2]).toHaveClass(css.entryDepartment);
      expect(row.children[2].textContent).toBe('计算机科学与技术');
      expect(row.children[3]).toHaveClass(css.entryRoleEnd);
      expect(row.children[3].textContent).toBe('本科');

      // The major (education.description) renders in its cell, never again as a
      // standalone paragraph under the header.
      expect(row.parentElement!.querySelector('p')).toBeNull();
      expect(screen.queryByText('计算机科学与技术')).toBe(row.children[2]);
    });

    it('keeps four reserved tracks when the major cell is empty', () => {
      render(<Template data={data} />);

      const row = rowOf('另一个学院');
      expect(row).toHaveClass(css.entryGrid);
      expect(row.children).toHaveLength(4);
      expect(row.children[2].textContent).toBe('');
      expect(row.children[3].textContent).toBe('大专');
    });
  }
);

describe('entry grid stylesheet lock', () => {
  const readCss = (file: string): string =>
    readFileSync(resolve(process.cwd(), 'components/resume/styles', file), 'utf8');

  it.each([['clean.module.css'], ['latex.module.css'], ['modern.module.css']])(
    '%s pins the shared section tracks with nested subgrid rows',
    (file) => {
      const css = readCss(file);
      // The SECTION owns the 4-track template. The role track is `auto` but
      // is shared across every row of the section: independent per-row grids
      // sized it per row, so a long title shrank the fr tracks and shifted
      // the department column left (alignment regression, 2026-11).
      const section = css.slice(css.indexOf('.entryGridSection'));
      expect(section).toContain('display: grid');
      expect(section).toContain(
        'grid-template-columns: minmax(0, 10.5rem) minmax(0, 1.35fr) minmax(0, 1fr) auto'
      );

      // Entries and their header rows nest as subgrids, inheriting the
      // section's column tracks instead of defining their own.
      const item = css.slice(css.indexOf('.entryGridItem {'));
      expect(item).toContain('display: grid');
      expect(item).toContain('grid-template-columns: subgrid');

      const fourTrack = css.slice(css.indexOf('.entryGrid {'));
      expect(fourTrack).toContain('display: grid');
      expect(fourTrack).toContain('grid-template-columns: subgrid');

      // No-department rows inherit the same four tracks and span the role
      // across the department+role bands so it stays flush right.
      const threeTrack = css.slice(css.indexOf('.entryGridThree'));
      expect(threeTrack).toContain('grid-template-columns: subgrid');
      expect(threeTrack).toContain('grid-column: 3 / -1');

      // Print media trap: _base.module.css forces .resume-items to
      // `display: block !important` in print, and the section element carries
      // resume-items too. As a block it stops being a grid container, the
      // subgrid rows compute to one implicit column and every cell stacks
      // vertically. Each module must restore grid display inside the print
      // block with a higher-specificity selector.
      const printBlock = css.slice(css.indexOf('@media print'));
      expect(printBlock).toContain(':global(.resume-print) .entryGridSection');
      expect(printBlock).toContain('display: grid !important');
    }
  );

  it('clean.module.css keeps the company-first item grid for dynamic custom sections', () => {
    const css = readCss('clean.module.css');
    const block = css.slice(css.indexOf('.entryItemGrid'));
    expect(block).toContain('display: grid');
    expect(block).toContain(
      'grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 0.9fr) auto'
    );
  });

  it.each([['latex.module.css'], ['modern.module.css']])(
    '%s keeps the two-track line grid for dynamic custom sections',
    (file) => {
      const css = readCss(file);
      const block = css.slice(css.indexOf('.entryLineGrid'));
      expect(block).toContain('display: grid');
      expect(block).toContain('grid-template-columns: minmax(0, 1fr) auto');
    }
  );
});

describe('template-specific header cell semantics', () => {
  it('keeps the modern work role an h4 heading inside the flush-right cell', () => {
    render(<ResumeModern data={data} />);
    const roleCell = screen.getByText('高级工程师');
    expect(roleCell.tagName).toBe('H4');
    expect(roleCell).toHaveClass(modernStyles.entryRoleEnd);
  });

  it('renders the clean work role as a non-heading span in the flush-right cell', () => {
    render(<ResumeClean data={data} />);
    const roleCell = screen.getByText('高级工程师');
    expect(roleCell.tagName).toBe('SPAN');
    expect(roleCell).toHaveClass(cleanStyles.entryRoleEnd);
  });

  it('renders the latex work role as a non-heading span in the flush-right cell', () => {
    render(<ResumeLatex data={data} />);
    const roleCell = screen.getByText('测试经理');
    expect(roleCell.tagName).toBe('SPAN');
    expect(roleCell).toHaveClass(latexStyles.entryRoleEnd);
  });
});
