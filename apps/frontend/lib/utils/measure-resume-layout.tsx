/**
 * Offscreen, real-browser measurement of a resume rendered with the builder's
 * chosen template/typography settings.
 *
 * Splits cleanly into:
 *  - measure stage (this file): render <Resume> in a hidden host, wait for
 *    fonts, read geometry from the real DOM (page count via the same
 *    {@link computePageBreaks} model the preview uses, per-row visual line
 *    counts via Range client rects, section/header geometry, column assignment
 *    for two-column templates), then delegate the rest to pure helpers.
 * stage 2 (layout-snapshot.ts): enumerate/align/mirror/clamp — all jsdom
 *    testable without browsers.
 *
 * jsdom cannot lay text out (every scrollHeight stays 0): the zero-height
 * self-check throws {@link LayoutMeasurementError} so callers skip the
 * snapshot rather than upload zeros.
 */
import { createRoot } from 'react-dom/client';
import Resume, { type ResumeData } from '@/components/dashboard/resume-component';
import type { TemplateSettings, TemplateType } from '@/lib/types/template-settings';
import { getContentAreaPx } from '@/lib/constants/page-dimensions';
import {
  collectUnbreakableBounds,
  computePageBreaks,
  type PageBreak,
} from '@/components/preview/use-pagination';
import { getCanonicalSections } from '@/lib/utils/section-order';
import { closestLocalClass, findLocalClass, queryLocalClass } from '@/lib/utils/css-modules-dom';
import {
  LAYOUT_LIMITS,
  RENDERED_LAYOUT_SCHEMA_VERSION,
  type LayoutSection,
  type RenderedLayout,
} from '@/lib/types/rendered-layout';
import type { ResumeHeadingProps } from '@/lib/utils/resume-headings';
import {
  alignPoints,
  assignPage,
  buildPageMirror,
  clampRenderedLayout,
  clusterColumns,
  enumerateExpectedPoints,
  groupHeaderRows,
  toLayoutPoints,
  type MirrorBlock,
  type ObservedRow,
} from '@/lib/utils/layout-snapshot';

export class LayoutMeasurementError extends Error {}

export interface MeasureLayoutOptions {
  /** Display-state data (localized/reordered) — exactly what is on screen. */
  resumeData: ResumeData;
  settings: TemplateSettings;
  headingProps: ResumeHeadingProps;
  /** Content locale ("zh"|"ja"|…) — mirrors the visible render's CJK stack. */
  locale?: string;
  timeoutMs?: number;
}

const TWO_COLUMN_TEMPLATES: ReadonlySet<TemplateType> = new Set([
  'swiss-two-column',
  'modern-two-column',
  'vivid',
]);

const FONT_RACE_MS = 3000;

interface RawRecord {
  kind: MirrorBlock['kind'];
  text: string;
  top: number;
  left: number;
  height: number;
  visualLines: number;
  /** Present only for records that correspond to an enumerated text point. */ observed: boolean;
  sectionKey?: string;
  sectionTitle: string;
  location: string;
}

function nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame !== 'function') {
      setTimeout(resolve, 0);
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

function collapseSpaces(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

function normText(text: string): string {
  return text.replace(/\s+/g, '');
}

function itemTitleOf(item: Element | null): string {
  if (!item) return '';
  const parts = [
    findLocalClass<HTMLElement>(item, 'resume-item-title') ??
      findLocalClass<HTMLElement>(item, 'resume-item-title-sm'),
    findLocalClass<HTMLElement>(item, 'resume-item-subtitle') ??
      findLocalClass<HTMLElement>(item, 'resume-item-subtitle-sm'),
  ]
    .map((element) => collapseSpaces(element?.textContent ?? ''))
    .filter(Boolean);
  return parts.join(' / ');
}

/** Distinct visual lines of an element by clustering Range client-rect tops. */
function measureVisualLines(element: HTMLElement): number {
  const range = document.createRange();
  range.selectNodeContents(element);
  const rects = Array.from(range.getClientRects()).filter((rect) => rect.height > 0);
  if (rects.length > 0) {
    const lineHeight = rects[0].height || 0;
    const tolerance = Math.max(2, lineHeight * 0.5);
    const tops = rects.map((rect) => rect.top).sort((a, b) => a - b);
    let lines = 0;
    let currentTop: number | null = null;
    for (const top of tops) {
      if (currentTop === null || top - currentTop > tolerance) {
        lines += 1;
        currentTop = top;
      }
    }
    if (lines > 0) return lines;
  }
  // Fallback (jsdom / degenerate render): box height ÷ computed line-height.
  const computed = Number.parseFloat(getComputedStyle(element).lineHeight || '0');
  if (Number.isFinite(computed) && computed > 0) {
    return Math.max(1, Math.round(element.offsetHeight / computed));
  }
  return 1;
}

function pagesTouched(top: number, bottom: number, pages: PageBreak[]): number[] {
  const touched: number[] = [];
  for (const page of pages) {
    if (bottom - page.contentOffset > 1 && page.contentEnd - top > 1) {
      touched.push(page.pageNumber);
    }
  }
  return touched;
}

/**
 * Render the resume offscreen and measure its layout. Always unmounts in
 * `finally`. Throws {@link LayoutMeasurementError} when real layout is
 * unavailable (SSR / jsdom / timeout).
 */
export async function measureResumeLayout(options: MeasureLayoutOptions): Promise<RenderedLayout> {
  const { resumeData, settings, headingProps, locale, timeoutMs = 5000 } = options;

  if (typeof document === 'undefined' || typeof window === 'undefined') {
    throw new LayoutMeasurementError('DOM is unavailable');
  }

  const contentArea = getContentAreaPx(settings.pageSize, settings.margins);
  const zeroMarginSettings: TemplateSettings = {
    ...settings,
    margins: { top: 0, bottom: 0, left: 0, right: 0 },
  };

  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.position = 'fixed';
  host.style.left = '-9999px';
  host.style.top = '0';
  host.style.width = `${contentArea.width}px`;
  host.style.opacity = '0';
  host.style.pointerEvents = 'none';
  host.style.zIndex = '-1';
  document.body.appendChild(host);

  const root = createRoot(host);
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    root.render(
      <Resume
        resumeData={resumeData}
        template={settings.template}
        settings={zeroMarginSettings}
        locale={locale}
        {...headingProps}
      />
    );

    await Promise.race([
      (async () => {
        const fonts = (document as Document & { fonts?: { ready?: Promise<unknown> } }).fonts;
        if (fonts?.ready) {
          await Promise.race([
            fonts.ready,
            new Promise((resolve) => setTimeout(resolve, FONT_RACE_MS)),
          ]);
        }
        await nextAnimationFrame();
        await nextAnimationFrame();
      })(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new LayoutMeasurementError('layout measurement timed out')),
          timeoutMs
        );
      }),
    ]);

    const bodyEl = findLocalClass<HTMLElement>(host, 'resume-body');
    if (!bodyEl || bodyEl.scrollHeight < 1) {
      throw new LayoutMeasurementError('resume rendered with zero height');
    }

    const totalHeight = bodyEl.scrollHeight;
    const bounds = collectUnbreakableBounds(bodyEl);
    const allPages = computePageBreaks(totalHeight, contentArea.height, bounds);
    const actualPageCount = allPages.length;
    const pageCount = Math.min(actualPageCount, LAYOUT_LIMITS.maxPages);
    const pages = allPages.slice(0, pageCount);

    const bodyRect = bodyEl.getBoundingClientRect();
    const baseLeft = bodyRect.left;
    const baseTop = bodyRect.top;
    const relRect = (element: Element): DOMRect => {
      const rect = element.getBoundingClientRect();
      return new DOMRect(rect.left - baseLeft, rect.top - baseTop, rect.width, rect.height);
    };

    const warnings: string[] = [];
    if (actualPageCount > pageCount) warnings.push('page_count_capped');

    const titleToKey = new Map<string, string>();
    for (const meta of getCanonicalSections(resumeData)) {
      titleToKey.set(normText(meta.displayName ?? ''), meta.key);
    }
    const sectionKeyForTitle = (title: string): string | undefined =>
      titleToKey.get(normText(title));

    // ---- Sections ---------------------------------------------------------
    const sectionElements = queryLocalClass<HTMLElement>(bodyEl, 'resume-section');
    const sectionData = sectionElements.map((element, index) => {
      const titleElement =
        findLocalClass<HTMLElement>(element, 'resume-section-title') ??
        findLocalClass<HTMLElement>(element, 'resume-section-title-sm');
      const title = collapseSpaces(titleElement?.textContent ?? '');
      return { element, rect: relRect(element), title, index };
    });

    // ---- Header facts -----------------------------------------------------
    const headerRecords: RawRecord[] = [];
    let headerHeight = 0;
    let headerCellCount = 0;
    let headerRows: { cells: number }[] = [];
    const headerEl = findLocalClass<HTMLElement>(bodyEl, 'resume-header');
    if (headerEl) {
      const headerRect = relRect(headerEl);
      headerHeight = Math.round(headerRect.height);

      const nameEl = findLocalClass<HTMLElement>(headerEl, 'resume-name');
      const name = collapseSpaces(nameEl?.textContent ?? '');
      if (name) {
        const nameRect = nameEl ? relRect(nameEl) : headerRect;
        headerRecords.push({
          kind: 'fact',
          text: name,
          top: nameRect.top,
          left: nameRect.left,
          height: nameRect.height,
          visualLines: 1,
          observed: false,
          sectionTitle: '',
          location: '',
        });
      }

      // swiss-single uses a labeled 3-cell grid (infoRow/infoCell). Other
      // templates fall back to grouping text leaves by visual row.
      const infoRows = queryLocalClass<HTMLElement>(headerEl, 'infoRow');
      const cellRects: { top: number; bottom: number; left: number }[] = [];
      if (infoRows.length > 0) {
        infoRows.forEach((row) => {
          const rowRect = relRect(row);
          const text = collapseSpaces(row.textContent ?? '');
          if (text) {
            headerRecords.push({
              kind: 'fact',
              text,
              top: rowRect.top,
              left: rowRect.left,
              height: rowRect.height,
              visualLines: 1,
              observed: false,
              sectionTitle: '',
              location: '',
            });
          }
          queryLocalClass<HTMLElement>(row, 'infoCell').forEach((cell) => {
            const cellRect = relRect(cell);
            cellRects.push({
              top: cellRect.top,
              bottom: cellRect.bottom,
              left: cellRect.left,
            });
          });
        });
      } else {
        const leaves = Array.from(headerEl.querySelectorAll<HTMLElement>('span, a, p, div')).filter(
          (element) =>
            Boolean(element.textContent?.trim()) &&
            !Array.from(element.children).some((child) => Boolean(child.textContent?.trim()))
        );
        leaves.forEach((leaf) => {
          const rect = relRect(leaf);
          const text = collapseSpaces(leaf.textContent ?? '');
          if (!text) return;
          headerRecords.push({
            kind: 'fact',
            text,
            top: rect.top,
            left: rect.left,
            height: rect.height,
            visualLines: 1,
            observed: false,
            sectionTitle: '',
            location: '',
          });
          cellRects.push({ top: rect.top, bottom: rect.bottom, left: rect.left });
        });
      }
      const groupedRows = groupHeaderRows(cellRects);
      headerRows = groupedRows.map((row) => ({ cells: row.cells }));
      headerCellCount = groupedRows.reduce((sum, row) => sum + row.cells, 0);
    }

    // ---- Content records (headings + text rows) --------------------------
    const records: RawRecord[] = [];
    for (const { element: sectionEl, rect: sectionRect, title } of sectionData) {
      const sectionKey = sectionKeyForTitle(title);
      records.push({
        kind: 'section',
        text: title,
        top: sectionRect.top,
        left: sectionRect.left,
        height: sectionRect.height,
        visualLines: 1,
        observed: false,
        sectionKey,
        sectionTitle: title,
        location: title,
      });

      queryLocalClass<HTMLElement>(sectionEl, 'resume-item').forEach((item) => {
        const heading = itemTitleOf(item);
        if (!heading) return;
        const itemRect = relRect(item);
        records.push({
          kind: 'heading',
          text: heading,
          top: itemRect.top,
          left: itemRect.left,
          height: itemRect.height,
          visualLines: 1,
          observed: false,
          sectionKey,
          sectionTitle: title,
          location: title ? `${title} / ${heading}` : heading,
        });
      });

      // List items, lone paragraphs (single-point summary), descriptive
      // body rows (项目背景/技术栈), and sub-module labels — one record each.
      const rowElements = Array.from(
        sectionEl.querySelectorAll<HTMLElement>('li, p, [data-body-row], [data-sub-label]')
      );
      const seen = new Set<HTMLElement>();
      for (const row of rowElements) {
        if (seen.has(row)) continue;
        seen.add(row);
        const isLabel = row.hasAttribute('data-sub-label');
        const textElement: HTMLElement | null = isLabel
          ? row
          : (row.querySelector<HTMLElement>('span.flex-1') ?? row);
        const text = collapseSpaces(textElement.textContent ?? '');
        if (!text) continue;
        const rect = relRect(textElement);
        if (rect.height <= 0) continue;
        const item = closestLocalClass<HTMLElement>(row, 'resume-item');
        const heading = itemTitleOf(item);
        const location = [title, heading].filter(Boolean).join(' / ');
        records.push({
          kind: isLabel ? 'label' : 'line',
          text,
          top: rect.top,
          left: rect.left,
          height: rect.height,
          visualLines: isLabel ? 1 : measureVisualLines(textElement),
          // Labels are description lines too (project sub-modules), so they
          // stay observable for point alignment; at 1 line they can never
          // trip the >6-lines density rule.
          observed: true,
          sectionKey,
          sectionTitle: title,
          location,
        });
      }
    }

    // ---- Column assignment (only known two-column templates) -------------
    // Cluster ALL record lefts at once (a single left value has no gap to
    // detect); single-column templates stay column 0 even when indented
    // sub-lists create a ~3ch left offset.
    const isTwoColumn = TWO_COLUMN_TEMPLATES.has(settings.template);
    const columns = isTwoColumn
      ? clusterColumns(
          records.map((record) => record.left),
          Math.max(40, contentArea.width * 0.12)
        )
      : records.map(() => 0);

    // ---- Emit mirror blocks + observed rows ------------------------------
    const mirrorBlocks: MirrorBlock[] = [];
    for (const record of headerRecords) {
      mirrorBlocks.push({
        page: 1,
        column: 0,
        top: record.top,
        text: record.text,
        kind: record.kind,
      });
    }
    const observed: ObservedRow[] = [];
    records.forEach((record, recordIndex) => {
      const page = assignPage(record.top, pages);
      const column = columns[recordIndex] ?? 0;
      mirrorBlocks.push({
        page,
        column,
        top: record.top,
        text: record.text,
        kind: record.kind,
        visualLines: record.kind === 'line' ? record.visualLines : undefined,
      });
      if (record.observed) {
        observed.push({
          sectionKey: record.sectionKey,
          sectionTitle: record.sectionTitle,
          text: record.text,
          norm: normText(record.text),
          top: record.top,
          left: record.left,
          height: record.height,
          visualLines: record.visualLines,
          page,
          column,
          location: record.location,
        });
      }
    });

    const sections: LayoutSection[] = sectionData.map(({ rect, title, index }) => ({
      key: sectionKeyForTitle(title) ?? `section_${index}`,
      title,
      visible: true,
      index,
      height_px: Math.round(rect.height),
      pages: pagesTouched(rect.top, rect.bottom, pages),
    }));

    const expected = enumerateExpectedPoints(resumeData);
    const pairs = alignPoints(expected, observed);
    const points = toLayoutPoints(pairs);

    const { mirror, warnings: mirrorWarnings } = buildPageMirror(mirrorBlocks, pageCount);
    warnings.push(...mirrorWarnings);

    const layout: RenderedLayout = {
      schema_version: RENDERED_LAYOUT_SCHEMA_VERSION,
      measured_at: new Date().toISOString(),
      template: settings.template,
      page_size: settings.pageSize,
      margins: { ...settings.margins },
      content_width_px: Math.round(contentArea.width),
      content_height_px: Math.round(contentArea.height),
      page_count: pageCount,
      total_height_px: Math.round(totalHeight),
      two_column: isTwoColumn,
      header: { height_px: headerHeight, cell_count: headerCellCount, rows: headerRows },
      sections,
      points,
      page_mirror: mirror,
      warnings,
    };

    return clampRenderedLayout(layout);
  } finally {
    if (timer) clearTimeout(timer);
    root.unmount();
    host.remove();
  }
}
