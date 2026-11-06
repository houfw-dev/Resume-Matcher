/**
 * Pure helpers for the rendered-layout snapshot.
 *
 * Two sides meet here:
 *  - {@link enumerateExpectedPoints} walks the structured ResumeData exactly
 *    like the backend `_iter_text_blocks` (summary, work/project description
 *    lines, custom text/item sections), producing stable locators.
 *  - The DOM measurement walks rendered rows (same content, visual order);
 *    {@link alignPoints} joins the two so each measured visual-line count can
 *    be attributed back to a structured point.
 *
 * Everything in this file is free of DOM APIs so it runs under jsdom tests.
 */
import type { ResumeData } from '@/components/dashboard/resume-component';
import { stripPointMarker } from '@/components/resume/list-format';
import { getCanonicalSections } from '@/lib/utils/section-order';
import { dedupeResumeLists, stripMarkdownEmphasisDeep } from '@/lib/utils/markdown-strip';
import { LAYOUT_LIMITS, type LayoutLocator } from '@/lib/types/rendered-layout';
import type { LayoutPageMirror, LayoutPoint, RenderedLayout } from '@/lib/types/rendered-layout';

export interface ExpectedPoint {
  locator: LayoutLocator;
  /** Canonical data key of the owning section (summary/workExperience/…). */
  sectionKey: string;
  /** Rendered section title used as the secondary matching key. */
  sectionTitle: string;
  /** Text as rendered (source numbering markers stripped). */
  text: string;
  /** Whitespace-free form for robust cross-renderer comparison. */
  norm: string;
}

export interface ObservedRow {
  sectionKey?: string;
  sectionTitle: string;
  text: string;
  norm: string;
  top: number;
  left: number;
  height: number;
  visualLines: number;
  page: number;
  column: number;
  /** Human location prefix, e.g. 工作经历 / 某公司. */
  location: string;
}

export interface AlignedPoint {
  expected: ExpectedPoint;
  observed: ObservedRow;
}

type EntrySection = 'workExperience' | 'personalProjects';

function nonEmptyLines(block: unknown): string[] {
  if (typeof block !== 'string') return [];
  return block
    .split('\n')
    .map((line) => stripPointMarker(line.trim()))
    .filter((line) => line.length > 0);
}

/** Strip ALL whitespace for comparison (CJK has none; English spacing varies). */
function normText(text: string): string {
  return text.replace(/\s+/g, '');
}

function sectionTitleMap(data: ResumeData): Map<string, string> {
  const map = new Map<string, string>();
  for (const meta of getCanonicalSections(data)) {
    map.set(meta.key, meta.displayName ?? '');
  }
  return map;
}

/**
 * Enumerate the same text points the backend paragraph check inspects.
 * Input must be the display-state data (localized/reordered), since points
 * are matched to rows rendered from that same object.
 */
export function enumerateExpectedPoints(resumeData: ResumeData): ExpectedPoint[] {
  const data = dedupeResumeLists(stripMarkdownEmphasisDeep(resumeData)) as ResumeData;
  const titles = sectionTitleMap(data);
  const points: ExpectedPoint[] = [];

  const pushLines = (
    lines: string[],
    sectionKey: string,
    makeLocator: (pointIndex: number) => LayoutLocator
  ): void => {
    lines.forEach((text, pointIndex) => {
      points.push({
        locator: makeLocator(pointIndex),
        sectionKey,
        sectionTitle: titles.get(sectionKey) ?? '',
        text,
        norm: normText(text),
      });
    });
  };

  if (typeof data.summary === 'string') {
    pushLines(nonEmptyLines(data.summary), 'summary', (pointIndex) => ({
      kind: 'summary',
      point_index: pointIndex,
    }));
  }

  const entrySections: EntrySection[] = ['workExperience', 'personalProjects'];
  for (const section of entrySections) {
    const entries = data[section];
    if (!Array.isArray(entries)) continue;
    entries.forEach((entry, entryIndex) => {
      if (!entry || !Array.isArray(entry.description)) return;
      const lines = entry.description.flatMap((block) => nonEmptyLines(block));
      pushLines(lines, section, (pointIndex) => ({
        kind: 'entry',
        section,
        entry_index: entryIndex,
        point_index: pointIndex,
      }));
    });
  }

  const customSections = data.customSections;
  if (customSections && typeof customSections === 'object') {
    for (const [key, section] of Object.entries(customSections)) {
      if (!section || typeof section !== 'object') continue;
      if (section.sectionType === 'text') {
        pushLines(nonEmptyLines(section.text), key, (pointIndex) => ({
          kind: 'custom_text',
          key,
          point_index: pointIndex,
        }));
      } else if (section.sectionType === 'itemList' && Array.isArray(section.items)) {
        section.items.forEach((item, entryIndex) => {
          if (!item || !Array.isArray(item.description)) return;
          const lines = item.description.flatMap((block) => nonEmptyLines(block));
          pushLines(lines, key, (pointIndex) => ({
            kind: 'custom_item',
            key,
            entry_index: entryIndex,
            point_index: pointIndex,
          }));
        });
      }
      // stringList rows render as an ordered string list that the backend
      // paragraph check does not cover — intentionally excluded.
    }
  }

  return points;
}

function sameSection(expected: ExpectedPoint, observed: ObservedRow): boolean {
  if (expected.sectionKey && observed.sectionKey === expected.sectionKey) return true;
  if (!expected.sectionTitle || !observed.sectionTitle) return false;
  return normText(expected.sectionTitle) === normText(observed.sectionTitle);
}

function includesEither(a: string, b: string): boolean {
  if (a.length < 4 || b.length < 4) return false;
  return a.includes(b) || b.includes(a);
}

/**
 * Match expected points to observed rendered rows, per section, preserving
 * order. Exact normalized equality first (greedy two-pointer), then a
 * bidirectional-substring pass for punctuation/emphasis residue. Unmatched
 * expected points are dropped: the backend falls back to char estimates.
 */
export function alignPoints(expected: ExpectedPoint[], observed: ObservedRow[]): AlignedPoint[] {
  const usedObserved = new Set<ObservedRow>();
  const pairs: AlignedPoint[] = [];

  const matchInSection = (candidate: ExpectedPoint, allowIncludes: boolean): ObservedRow | null => {
    for (const row of observed) {
      if (usedObserved.has(row) || !sameSection(candidate, row)) continue;
      if (candidate.norm && row.norm === candidate.norm) return row;
    }
    if (!allowIncludes) return null;
    for (const row of observed) {
      if (usedObserved.has(row) || !sameSection(candidate, row)) continue;
      if (includesEither(candidate.norm, row.norm)) return row;
    }
    return null;
  };

  for (const point of expected) {
    const exact = matchInSection(point, false);
    if (exact) {
      usedObserved.add(exact);
      pairs.push({ expected: point, observed: exact });
    }
  }
  for (const point of expected) {
    if (pairs.some((pair) => pair.expected === point)) continue;
    const fuzzy = matchInSection(point, true);
    if (fuzzy) {
      usedObserved.add(fuzzy);
      pairs.push({ expected: point, observed: fuzzy });
    }
  }

  pairs.sort((a, b) => a.observed.top - b.observed.top);
  return pairs;
}

/**
 * Cluster block left-edge coordinates into one or two reading columns by the
 * largest gap. Returns a 0/1 column index per input coordinate.
 */
export function clusterColumns(lefts: number[], gapThresholdPx = 40): number[] {
  if (lefts.length === 0) return [];
  const sorted = [...new Set(lefts)].sort((a, b) => a - b);
  let splitAt = -1;
  let largestGap = 0;
  for (let i = 1; i < sorted.length; i += 1) {
    const gap = sorted[i] - sorted[i - 1];
    if (gap > largestGap) {
      largestGap = gap;
      splitAt = i;
    }
  }
  if (splitAt < 0 || largestGap < gapThresholdPx) {
    return lefts.map(() => 0);
  }
  const rightColumnStart = sorted[splitAt];
  return lefts.map((left) => (left >= rightColumnStart ? 1 : 0));
}

export interface HeaderRect {
  top: number;
  bottom: number;
  left: number;
}

/** Group header cell rectangles into visual rows by top-coordinate proximity. */
export function groupHeaderRows(
  rects: HeaderRect[],
  tolerancePx = 6
): { top: number; bottom: number; cells: number }[] {
  const sorted = [...rects].sort((a, b) => a.top - b.top || a.left - b.left);
  const rows: { top: number; bottom: number; cells: number }[] = [];
  for (const rect of sorted) {
    const current = rows[rows.length - 1];
    if (current && rect.top - current.top <= tolerancePx) {
      current.cells += 1;
      current.bottom = Math.max(current.bottom, rect.bottom);
    } else {
      rows.push({ top: rect.top, bottom: rect.bottom, cells: 1 });
    }
  }
  return rows;
}

export interface MeasuredPage {
  pageNumber: number;
  contentOffset: number;
  contentEnd: number;
}

/** 1-based page whose vertical band contains y; clamps at both ends. */
export function assignPage(y: number, pages: MeasuredPage[]): number {
  for (const page of pages) {
    if (y >= page.contentOffset && y < page.contentEnd) return page.pageNumber;
  }
  const last = pages[pages.length - 1];
  if (last && y >= last.contentEnd) return last.pageNumber;
  return 1;
}

export type MirrorBlockKind = 'fact' | 'section' | 'heading' | 'label' | 'line';

export interface MirrorBlock {
  page: number;
  column: number;
  top: number;
  text: string;
  kind: MirrorBlockKind;
  visualLines?: number;
}

function formatMirrorBlock(block: MirrorBlock): string {
  const text = block.text.trim();
  if (!text) return '';
  switch (block.kind) {
    case 'section':
      return `【${text}】`;
    case 'heading':
      return `- ${text}`;
    case 'fact':
      return text;
    case 'label':
      return text;
    case 'line': {
      const suffix =
        typeof block.visualLines === 'number' && block.visualLines > 3
          ? `（实测 ${block.visualLines} 行）`
          : '';
      return `• ${text}${suffix}`;
    }
  }
}

const PAGE_TRUNCATION_MARKER = ' […]';

export interface BuiltPageMirror {
  mirror: LayoutPageMirror[];
  warnings: string[];
}

/**
 * Render the per-page plain-text mirror in reading order (column then top for
 * two-column templates). Each page is capped at pageText characters.
 */
export function buildPageMirror(
  blocks: MirrorBlock[],
  pageCount: number,
  perPageCharLimit = LAYOUT_LIMITS.pageText
): BuiltPageMirror {
  const warnings: string[] = [];
  const ordered = [...blocks].sort((a, b) => {
    if (a.page !== b.page) return a.page - b.page;
    if (a.column !== b.column) return a.column - b.column;
    return a.top - b.top;
  });

  const mirror: LayoutPageMirror[] = [];
  for (let page = 1; page <= pageCount; page += 1) {
    const lines: string[] = [];
    for (const block of ordered) {
      if (block.page !== page) continue;
      const line = formatMirrorBlock(block);
      if (line) lines.push(line);
    }
    let text = lines.join('\n');
    if (text.length > perPageCharLimit) {
      text = text.slice(0, Math.max(0, perPageCharLimit - PAGE_TRUNCATION_MARKER.length));
      text += PAGE_TRUNCATION_MARKER;
      warnings.push(`page_mirror_page_${page}_truncated`);
    }
    mirror.push({ page, text });
  }
  return { mirror, warnings };
}

function payloadBytes(layout: RenderedLayout): number {
  return new TextEncoder().encode(JSON.stringify(layout)).length;
}

function truncateField(value: string, max: number, marker: string): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - marker.length))}${marker}`;
}

/**
 * Enforce {@link LAYOUT_LIMITS} so the uploaded snapshot stays small. Mirrors
 * shrink first (LLM context), then point text, then point count; every cut is
 * recorded as a machine-readable warning.
 */
export function clampRenderedLayout(input: RenderedLayout): RenderedLayout {
  const warnings = [...input.warnings];
  const layout: RenderedLayout = {
    ...input,
    sections: input.sections.slice(0, LAYOUT_LIMITS.maxSections),
    points: input.points.slice(0, LAYOUT_LIMITS.maxPoints),
    page_mirror: input.page_mirror.slice(0, LAYOUT_LIMITS.maxPages),
    warnings,
  };
  if (input.sections.length > layout.sections.length) warnings.push('sections_truncated');
  if (input.points.length > layout.points.length) warnings.push('points_truncated');
  if (input.page_mirror.length > layout.page_mirror.length) warnings.push('pages_truncated');

  const note = (message: string): void => {
    if (!warnings.includes(message)) warnings.push(message);
  };

  if (payloadBytes(layout) > LAYOUT_LIMITS.payloadBytes) {
    const mirrorBudgets = [4000, 2000, 1000, 500];
    for (const budget of mirrorBudgets) {
      if (payloadBytes(layout) <= LAYOUT_LIMITS.payloadBytes) break;
      layout.page_mirror = layout.page_mirror.map((page) =>
        page.text.length > budget
          ? { ...page, text: truncateField(page.text, budget, PAGE_TRUNCATION_MARKER) }
          : page
      );
    }
    note('page_mirror_truncated');
  }

  const pointTextBudgets = [LAYOUT_LIMITS.pointText, 80, 40];
  for (const budget of pointTextBudgets) {
    if (payloadBytes(layout) <= LAYOUT_LIMITS.payloadBytes) break;
    layout.points = layout.points.map((point) =>
      point.text.length > budget
        ? { ...point, text: truncateField(point.text, budget, '…') }
        : point
    );
    note('point_text_truncated');
  }

  while (payloadBytes(layout) > LAYOUT_LIMITS.payloadBytes && layout.points.length > 0) {
    layout.points = layout.points.slice(0, Math.max(0, Math.floor(layout.points.length / 2)));
    note('points_dropped_for_size');
  }

  while (payloadBytes(layout) > LAYOUT_LIMITS.payloadBytes && layout.page_mirror.length > 1) {
    layout.page_mirror = layout.page_mirror.slice(0, -1);
    note('pages_dropped_for_size');
  }

  layout.warnings = warnings.slice(0, LAYOUT_LIMITS.maxWarnings);
  return layout;
}

/** Build LayoutPoint records from aligned pairs + character counts. */
export function toLayoutPoints(pairs: AlignedPoint[]): LayoutPoint[] {
  return pairs.map(({ expected, observed }) => ({
    locator: expected.locator,
    location: observed.location
      ? `${observed.location} / ${expected.sectionTitle}`.replace(/\s*\/\s*$/, '')
      : expected.sectionTitle,
    text: expected.text.slice(0, LAYOUT_LIMITS.pointText),
    chars: expected.norm.length,
    visual_lines: Math.max(1, Math.round(observed.visualLines)),
    height_px: Math.round(observed.height),
    page: observed.page,
  }));
}
