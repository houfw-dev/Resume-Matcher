import { describe, expect, it, vi } from 'vitest';
import { render, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import React from 'react';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * Work entry headers render one justified column row with the role in
 * regular weight: four columns (time | company | department | role) when a
 * department exists, THREE columns (time | company | role) when it does not.
 * A standalone org-unit line legacy parsers filed as a plain description row
 * is lifted into the department column instead of rendering as an indented
 * body line under the date.
 */
const buildData = (entry: Record<string, unknown>): ResumeData =>
  ({
    personalInfo: { name: '王浩', email: 'wang@example.com' },
    sectionMeta: [
      {
        id: 'workExperience',
        key: 'workExperience',
        displayName: '工作经历',
        sectionType: 'itemList',
        isDefault: true,
        isVisible: true,
        order: 1,
      },
    ],
    workExperience: [
      {
        id: 1,
        title: 'Java高级开发',
        company: '武汉软通动力',
        years: '2023.09 - 2026.04',
        ...entry,
      },
    ],
  }) as ResumeData;

// CSS modules are identity in some runs and hashed (_resume-item_<hash>) in
// others; match the entry wrapper either way without also hitting resume-items.
const closestEntry = (el: HTMLElement): HTMLElement | null => {
  let cur: HTMLElement | null = el;
  while (cur && !/(?:^|\s)_?resume-item(?:_|$|\s)/.test(cur.className)) {
    cur = cur.parentElement;
  }
  return cur;
};

describe('ResumeSingleColumn work entry row', () => {
  it('lifts a legacy plain department line into its own column', () => {
    const data = buildData({
      department: null,
      description: ['全球资金部'],
      descriptionStyles: ['plain'],
    });
    const { container } = render(<ResumeSingleColumn data={data} />);

    const item = closestEntry(within(container).getByText('全球资金部'));
    expect(item).not.toBeNull();
    // The promoted line no longer renders as a description list/body row.
    expect(item!.querySelector('ol')).toBeNull();
    expect(item!.querySelector('[data-sub-body]')).toBeNull();

    const grid = item!.querySelector('[class*="entryColumnsWork"]');
    expect(grid).not.toBeNull();
    expect(grid!.textContent).toContain('2023.09~2026.04');
    expect(grid!.textContent).toContain('武汉软通动力');
    expect(grid!.textContent).toContain('全球资金部');
    expect(grid!.textContent).toContain('Java高级开发');
  });

  it('renders three columns (time | company | role) when there is no department', () => {
    const data = buildData({ department: '', description: [] });
    const { container } = render(<ResumeSingleColumn data={data} />);

    const role = within(container).getByText('Java高级开发');
    const item = closestEntry(role);
    const grid = item!.querySelector('[class*="entryColumnsWork"]');
    expect(grid).not.toBeNull();
    // The three-column variant, not the four-column one (exact class token).
    expect(grid!.className.split(/\s+/).some((c) => c.includes('Three'))).toBe(true);

    const cells = Array.from(grid!.children);
    expect(cells).toHaveLength(3);
    expect(cells[0].textContent).toContain('2023.09~2026.04');
    expect(cells[1].textContent).toContain('武汉软通动力');
    expect(cells[2].textContent).toContain('Java高级开发');

    // The role stays flush with the right content edge (两端对齐) inside the
    // freed department+role band. jsdom cannot measure CSS alignment, so the
    // right-align rule is locked by the entryRoleThree class token (substring
    // checks survive both identity and hashed CSS-module class names).
    expect(role).toBe(cells[2]);
    expect(role.tagName).toBe('H4');
    expect(role.className).toContain('entryRoleThree');
    expect(role.className).toContain('entryRole');
  });

  it('renders four columns (time | company | department | role) with a department', () => {
    const data = buildData({ department: '研发部', description: [] });
    const { container } = render(<ResumeSingleColumn data={data} />);

    const role = within(container).getByText('Java高级开发');
    const item = closestEntry(role);
    const grid = item!.querySelector('[class*="entryColumnsWork"]');
    expect(grid).not.toBeNull();
    expect(grid!.className.split(/\s+/).some((c) => c.includes('Three'))).toBe(false);

    const cells = Array.from(grid!.children);
    expect(cells).toHaveLength(4);
    expect(cells[2].textContent).toContain('研发部');
    // The role stays flush right in its own auto track (no left-align class).
    expect(cells[3].className).not.toContain('entryRoleThree');
  });

  it('renders the parsed department field in its own column', () => {
    const data = buildData({
      department: '云计算集成部',
      description: ['负责平台架构升级'],
      descriptionStyles: ['bullet'],
    });
    const { container } = render(<ResumeSingleColumn data={data} />);

    const item = closestEntry(within(container).getByText('云计算集成部'));
    expect(item).not.toBeNull();
    expect(item!.querySelector('[class*="entryColumnsWork"]')).not.toBeNull();
    expect(within(item as HTMLElement).getByText('负责平台架构升级')).toBeTruthy();
  });

  it('renders the role without bold weight, flush right', () => {
    const data = buildData({ department: '研发部' });
    const { container } = render(<ResumeSingleColumn data={data} />);

    const role = within(container).getByText('Java高级开发');
    expect(role.tagName).toBe('H4');
    expect(role.className).toContain('entryRole');
    expect(role.className).not.toContain('resume-item-title');
  });

  it('starts the company/school column a little right of the date glyphs', () => {
    // jsdom cannot measure grid geometry; pin the track widths in the CSS
    // source so the date-first grids (work 4/3 columns and education) stay
    // aligned across sections and the DOCX 3.3cm first track has a mirror.
    const stylesPath = path.resolve(
      path.dirname(new URL(import.meta.url).pathname),
      '../components/resume/styles/swiss-single.module.css'
    );
    const css = readFileSync(stylesPath, 'utf8');
    expect(css.match(/minmax\(0, 10\.5rem\)/g)).toHaveLength(3);
    // The project row keeps its time column where it was (name-first grid).
    expect(css).toContain('minmax(0, 2fr) minmax(0, 9.5rem)');
  });

  it('keeps a bullet-styled department-like line in the description', () => {
    const data = buildData({
      department: null,
      description: ['研发部'],
      descriptionStyles: ['bullet'],
    });
    const { container } = render(<ResumeSingleColumn data={data} />);

    const item = closestEntry(within(container).getByText('研发部'));
    expect(item).not.toBeNull();
    expect(item!.querySelector('ol')).not.toBeNull();
  });
});
