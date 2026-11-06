import { describe, expect, it } from 'vitest';

/**
 * Pure logic for the rendered-layout snapshot: point enumeration (must mirror
 * the backend `_iter_located_blocks` traversal), expected↔observed alignment,
 * column/header clustering, page assignment, per-page mirror rendering and the
 * 48 KB payload clamp.
 */
import {
  alignPoints,
  assignPage,
  buildPageMirror,
  clampRenderedLayout,
  clusterColumns,
  enumerateExpectedPoints,
  groupHeaderRows,
  toLayoutPoints,
  type ExpectedPoint,
  type MirrorBlock,
  type ObservedRow,
} from '@/lib/utils/layout-snapshot';
import { LAYOUT_LIMITS, type RenderedLayout } from '@/lib/types/rendered-layout';
import type { ResumeData } from '@/components/dashboard/resume-component';

function dataFixture(overrides: Record<string, unknown> = {}): ResumeData {
  return {
    personalInfo: { name: '王浩' },
    summary: '',
    workExperience: [],
    education: [],
    personalProjects: [],
    additional: {},
    ...overrides,
  } as unknown as ResumeData;
}

// --- enumerateExpectedPoints -----------------------------------------------

describe('enumerateExpectedPoints', () => {
  it('splits summary on newlines and strips source markers', () => {
    const data = dataFixture({ summary: '个人优势第一条\n1. 个人优势第二条' });
    const points = enumerateExpectedPoints(data);
    expect(points).toHaveLength(2);
    expect(points.map((p) => p.text)).toEqual(['个人优势第一条', '个人优势第二条']);
    expect(points[0].locator).toEqual({ kind: 'summary', point_index: 0 });
    expect(points[1].locator).toEqual({ kind: 'summary', point_index: 1 });
  });

  it('flattens description bullets per entry with continuous point_index', () => {
    const data = dataFixture({
      workExperience: [
        {
          company: '甲公司',
          title: '工程师',
          description: ['第一行\n第二行', '第三行'],
        },
      ],
      personalProjects: [{ name: '智能平台', description: ['项目第一点', '项目第二点'] }],
    });
    const points = enumerateExpectedPoints(data);

    const work = points.filter((p) => p.sectionKey === 'workExperience');
    expect(work.map((p) => p.text)).toEqual(['第一行', '第二行', '第三行']);
    expect(work.map((p) => (p.locator as { point_index: number }).point_index)).toEqual([0, 1, 2]);
    for (const point of work) {
      expect(point.locator.kind).toBe('entry');
    }

    const projects = points.filter((p) => p.sectionKey === 'personalProjects');
    expect(projects.map((p) => p.text)).toEqual(['项目第一点', '项目第二点']);
  });

  it('covers custom text and itemList sections but never stringList rows', () => {
    const data = dataFixture({
      customSections: {
        honors: { sectionType: 'text', text: '荣誉第一行\n荣誉第二行' },
        certs: {
          sectionType: 'itemList',
          items: [
            { title: '证书一', description: ['证书第一点'] },
            { title: '证书二', description: ['证书第二点'] },
          ],
        },
        tags: { sectionType: 'stringList', items: ['英语四级', '英语六级'] },
      },
    });
    const points = enumerateExpectedPoints(data);
    expect(points.map((p) => p.text)).toEqual([
      '荣誉第一行',
      '荣誉第二行',
      '证书第一点',
      '证书第二点',
    ]);
    expect(points[0].locator).toMatchObject({
      kind: 'custom_text',
      key: 'honors',
      point_index: 0,
    });
    expect(points[2].locator).toMatchObject({
      kind: 'custom_item',
      key: 'certs',
      entry_index: 0,
      point_index: 0,
    });
    expect(points[3].locator).toMatchObject({ entry_index: 1 });
    expect(points.some((p) => p.text.includes('英语'))).toBe(false);
  });

  it('strips markdown emphasis before enumerating points', () => {
    const data = dataFixture({
      workExperience: [
        {
          company: '乙公司',
          description: ['**负责**核心系统', '独特的第三条内容'],
        },
      ],
    });
    const texts = enumerateExpectedPoints(data).map((p) => p.text);
    expect(texts).toEqual(['负责核心系统', '独特的第三条内容']);
  });
});

// --- alignPoints ------------------------------------------------------------

function observed(
  partial: Partial<ObservedRow> & Pick<ObservedRow, 'sectionKey' | 'text' | 'top'>
): ObservedRow {
  return {
    sectionTitle: '',
    norm: partial.text.replace(/\s+/g, ''),
    left: 0,
    height: 20,
    visualLines: 1,
    page: 1,
    column: 0,
    location: '',
    ...partial,
  };
}

function expected(text: string, sectionKey: string): ExpectedPoint {
  return {
    locator: { kind: 'summary', point_index: 0 },
    sectionKey,
    sectionTitle: '',
    text,
    norm: text.replace(/\s+/g, ''),
  };
}

describe('alignPoints', () => {
  it('matches exact normalized text within the same section', () => {
    const exp = [expected('要点甲', 'summary')];
    const rows = [
      observed({ sectionKey: 'other', text: '要点甲', top: 5 }),
      observed({ sectionKey: 'summary', text: '要点甲', top: 10 }),
    ];
    const pairs = alignPoints(exp, rows);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].observed.top).toBe(10);
  });

  it('falls back to bidirectional substring matching', () => {
    const exp = [expected('非常非常长的独特要点内容ABC', 'workExperience')];
    const rows = [
      observed({ sectionKey: 'workExperience', text: '非常非常长的独特要点内容', top: 3 }),
    ];
    const pairs = alignPoints(exp, rows);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].observed.text).toBe('非常非常长的独特要点内容');
  });

  it('does not fuzzy-match strings shorter than 4 chars', () => {
    const exp = [expected('甲乙', 'summary')];
    const rows = [observed({ sectionKey: 'summary', text: '甲乙丙', top: 1 })];
    expect(alignPoints(exp, rows)).toHaveLength(0);
  });

  it('never reuses an observed row and drops unmatched points', () => {
    const exp = [expected('相同的要点内容甲', 'summary'), expected('相同的要点内容甲', 'summary')];
    const rows = [observed({ sectionKey: 'summary', text: '相同的要点内容甲', top: 2 })];
    const pairs = alignPoints(exp, rows);
    expect(pairs).toHaveLength(1);
  });

  it('returns pairs ordered by observed top', () => {
    const exp = [
      {
        ...expected('第二行内容', 'summary'),
        locator: { kind: 'summary' as const, point_index: 1 },
      },
      {
        ...expected('第一行内容', 'summary'),
        locator: { kind: 'summary' as const, point_index: 0 },
      },
    ];
    const rows = [
      observed({ sectionKey: 'summary', text: '第一行内容', top: 40 }),
      observed({ sectionKey: 'summary', text: '第二行内容', top: 10 }),
    ];
    const pairs = alignPoints(exp, rows);
    // Pairs leave the function sorted by observed top (ascending).
    expect(pairs.map((p) => p.observed.text)).toEqual(['第二行内容', '第一行内容']);
  });
});

// --- clustering helpers -----------------------------------------------------

describe('clusterColumns', () => {
  it('returns [] for empty input and one column for small gaps', () => {
    expect(clusterColumns([])).toEqual([]);
    // 3ch (~30px) indentation must not invent a second column.
    expect(clusterColumns([0, 30, 0, 28], 40)).toEqual([0, 0, 0, 0]);
  });

  it('splits at the largest gap once it exceeds the threshold', () => {
    expect(clusterColumns([0, 400, 0, 402, 400], 40)).toEqual([0, 1, 0, 1, 1]);
  });
});

describe('groupHeaderRows', () => {
  it('groups cells with similar tops into visual rows', () => {
    const rows = groupHeaderRows([
      { top: 0, bottom: 20, left: 0 },
      { top: 1, bottom: 21, left: 120 },
      { top: 1, bottom: 21, left: 240 },
      { top: 30, bottom: 50, left: 0 },
    ]);
    expect(rows.map((r) => r.cells)).toEqual([3, 1]);
    expect(rows[0].bottom).toBe(21);
  });
});

describe('assignPage', () => {
  const pages = [
    { pageNumber: 1, contentOffset: 0, contentEnd: 1000 },
    { pageNumber: 2, contentOffset: 1000, contentEnd: 1800 },
  ];
  it('maps y into the containing band, clamps after the end, defaults to 1', () => {
    expect(assignPage(500, pages)).toBe(1);
    expect(assignPage(1000, pages)).toBe(2);
    expect(assignPage(9999, pages)).toBe(2);
    expect(assignPage(-5, pages)).toBe(1);
  });
});

// --- page mirror ------------------------------------------------------------

describe('buildPageMirror', () => {
  it('formats blocks and orders by page, then column, then top', () => {
    const blocks: MirrorBlock[] = [
      { page: 2, column: 0, top: 10, kind: 'line', text: '第二页主栏' },
      { page: 1, column: 1, top: 5, kind: 'line', text: '第一页侧栏' },
      { page: 1, column: 0, top: 0, kind: 'section', text: '工作经历' },
      { page: 1, column: 0, top: 8, kind: 'heading', text: '甲公司 / 工程师' },
      { page: 1, column: 0, top: 20, kind: 'line', text: '长要点', visualLines: 7 },
      { page: 1, column: 0, top: 30, kind: 'fact', text: '王浩' },
    ];
    const { mirror } = buildPageMirror(blocks, 2);
    const page1 = mirror[0].text;
    expect(page1.split('\n')).toEqual([
      '【工作经历】',
      '- 甲公司 / 工程师',
      '• 长要点（实测 7 行）',
      '王浩',
      '• 第一页侧栏',
    ]);
    expect(mirror[1].text.trim()).toBe('• 第二页主栏');
  });

  it('annotates measured lines only past 3 visual lines', () => {
    const { mirror } = buildPageMirror(
      [
        { page: 1, column: 0, top: 0, kind: 'line', text: '三行', visualLines: 3 },
        { page: 1, column: 0, top: 10, kind: 'line', text: '四行', visualLines: 4 },
      ],
      1
    );
    expect(mirror[0].text).toBe('• 三行\n• 四行（实测 4 行）');
  });

  it('truncates per-page text at the cap and records a warning', () => {
    const { mirror, warnings } = buildPageMirror(
      [{ page: 1, column: 0, top: 0, kind: 'line', text: '字'.repeat(7000) }],
      1
    );
    expect(mirror[0].text.length).toBe(LAYOUT_LIMITS.pageText);
    expect(mirror[0].text.endsWith(' […]')).toBe(true);
    expect(warnings).toContain('page_mirror_page_1_truncated');
  });
});

// --- clamp ------------------------------------------------------------------

function makeLayout(overrides: Partial<RenderedLayout> = {}): RenderedLayout {
  return {
    schema_version: 1,
    measured_at: '',
    template: 'swiss-single',
    page_size: 'A4',
    margins: { top: 10, bottom: 10, left: 10, right: 10 },
    content_width_px: 718,
    content_height_px: 1047,
    page_count: 1,
    total_height_px: 1000,
    two_column: false,
    header: { height_px: 100, cell_count: 1, rows: [{ cells: 1 }] },
    sections: [],
    points: [],
    page_mirror: [],
    warnings: [],
    ...overrides,
  };
}

describe('clampRenderedLayout', () => {
  it('leaves a small snapshot untouched', () => {
    const layout = makeLayout({
      page_mirror: [{ page: 1, text: '短镜像' }],
    });
    const clamped = clampRenderedLayout(layout);
    expect(clamped.page_mirror[0].text).toBe('短镜像');
    expect(clamped.warnings).toEqual([]);
  });

  it('forces the JSON payload under the byte cap with explicit warnings', () => {
    const layout = makeLayout({
      page_count: LAYOUT_LIMITS.maxPages,
      page_mirror: Array.from({ length: LAYOUT_LIMITS.maxPages }, (_, i) => ({
        page: i + 1,
        text: '镜'.repeat(5_900),
      })),
    });
    const clamped = clampRenderedLayout(layout);
    const bytes = new TextEncoder().encode(JSON.stringify(clamped)).length;
    expect(bytes).toBeLessThanOrEqual(LAYOUT_LIMITS.payloadBytes);
    expect(clamped.warnings).toContain('page_mirror_truncated');
  });

  it('truncates over-long section/point arrays at the hard caps', () => {
    const layout = makeLayout({
      sections: Array.from({ length: 60 }, (_, i) => ({
        key: `s${i}`,
        title: `S${i}`,
        visible: true,
        index: i,
        height_px: 10,
        pages: [1],
      })),
      points: Array.from({ length: 400 }, (_, i) => ({
        locator: { kind: 'summary' as const, point_index: i },
        location: '',
        text: '点',
        chars: 1,
        visual_lines: 1,
        height_px: 20,
        page: 1,
      })),
    });
    const clamped = clampRenderedLayout(layout);
    expect(clamped.sections).toHaveLength(LAYOUT_LIMITS.maxSections);
    expect(clamped.points).toHaveLength(LAYOUT_LIMITS.maxPoints);
    expect(clamped.warnings).toContain('sections_truncated');
    expect(clamped.warnings).toContain('points_truncated');
  });
});

describe('toLayoutPoints', () => {
  it('projects aligned pairs into capped LayoutPoint records', () => {
    const exp = { ...expected('要点内容甲', 'workExperience'), sectionTitle: '工作经历' };
    const pairs = alignPoints(
      [exp],
      [
        observed({
          sectionKey: 'workExperience',
          sectionTitle: '工作经历',
          text: '要点内容甲',
          top: 12,
          height: 140,
          visualLines: 7,
          page: 2,
          location: '甲公司 / 工程师',
        }),
      ]
    );
    const [point] = toLayoutPoints(pairs);
    expect(point.visual_lines).toBe(7);
    expect(point.page).toBe(2);
    expect(point.location).toBe('甲公司 / 工程师 / 工作经历');
  });
});
