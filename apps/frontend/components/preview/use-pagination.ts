'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { type PageSize, type MarginSettings } from '@/lib/types/template-settings';
import { getContentAreaPx } from '@/lib/constants/page-dimensions';
import {
  closestLocalClass,
  findLocalClass,
  hasLocalClass,
  queryLocalClass,
} from '@/lib/utils/css-modules-dom';

export interface PageBreak {
  pageNumber: number;
  contentOffset: number; // Where this page starts in the content (px)
  contentEnd: number; // Where this page ends in the content (px)
}

interface UnbreakableBound {
  top: number;
  bottom: number;
  element: Element;
}

/**
 * Collect page-break-avoid zones, in coordinates relative to the container.
 *
 * Granularity mirrors the print CSS: sections always span pages. For
 * swiss-single (`resume-template-swiss-single` on the rendered root) a tall
 * work/project entry splits BETWEEN bullet rows — the entry header + first
 * bullet form one zone, each later bullet its own zone. Every other template
 * treats the whole entry as atomic. Section titles are bound to their first
 * piece of content so they are never orphaned at a page bottom.
 */
export function collectUnbreakableBounds(container: HTMLElement): UnbreakableBound[] {
  // `.resume-section > ol > li` covers the numbered rows of custom
  // text/stringList sections and the swiss-single skills list (rows stay
  // whole; the list itself may span pages, mirroring the print CSS).
  // Local class lookups accept both identity tokens (tests) and hashed
  // CSS-module tokens (real builds: `_base-module__xxxx__resume-item`).
  // An entry can carry both the local `resume-item` class and an explicit
  // `[data-no-break]`; dedupe so it yields one atomic zone, not two.
  const items: Element[] = [...queryLocalClass(container, 'resume-item')];
  container.querySelectorAll('[data-no-break]').forEach((el) => {
    if (!items.includes(el)) items.push(el);
  });
  container.querySelectorAll('ol > li').forEach((row) => {
    const list = row.parentElement;
    // Direct section child only (mirrors the original `.resume-section > ol > li`).
    if (list && list.parentElement && hasLocalClass(list.parentElement, 'resume-section')) {
      if (!items.includes(row)) items.push(row);
    }
  });
  const bounds: UnbreakableBound[] = [];
  const containerRect = container.getBoundingClientRect();

  const fineGrained = Boolean(
    container.matches?.('.resume-template-swiss-single') ||
    container.querySelector('.resume-template-swiss-single')
  );

  items.forEach((item) => {
    const rect = item.getBoundingClientRect();
    const itemTop = rect.top - containerRect.top;
    const itemBottom = rect.bottom - containerRect.top;

    if (!fineGrained || item.hasAttribute('data-no-break')) {
      bounds.push({ top: itemTop, bottom: itemBottom, element: item });
      return;
    }

    // `[data-sub-body] > [data-body-row]` covers 项目背景/技术栈 descriptive
    // content blocks, which paginate row-by-row just like list rows.
    const bullets = item.querySelectorAll(
      ':scope > :is(ul, ol) > li, :scope > [data-sub-body] > [data-body-row]'
    );
    if (bullets.length === 0) {
      // Header-only entry (e.g. an education row): keep the whole item.
      bounds.push({ top: itemTop, bottom: itemBottom, element: item });
      return;
    }

    // Entry header + first bullet as one atomic zone, then one bound per
    // remaining bullet so pages fill densely instead of pushing the whole
    // entry to the next page.
    const firstRect = bullets[0].getBoundingClientRect();
    bounds.push({
      top: itemTop,
      bottom: firstRect.bottom - containerRect.top,
      element: item,
    });
    const laterBulletBounds = new Map<Element, UnbreakableBound>();
    bullets.forEach((bullet, index) => {
      if (index === 0) return;
      const bulletRect = bullet.getBoundingClientRect();
      const bound = {
        top: bulletRect.top - containerRect.top,
        bottom: bulletRect.bottom - containerRect.top,
        element: bullet,
      };
      bounds.push(bound);
      laterBulletBounds.set(bullet, bound);
    });

    // A sub-module label (负责内容 / 难点与解决 / 项目背景 / …) must stay with
    // the first row of its own restart-numbered list or descriptive body
    // block, mirroring the print CSS `:has(+ :is(ul, ol, [data-sub-body]))`
    // binding.
    item.querySelectorAll(':scope > [data-sub-label]').forEach((label) => {
      const group = label.nextElementSibling;
      if (!group || !group.matches?.('ul, ol, [data-sub-body]')) return;
      const firstRow = group.matches('ul, ol')
        ? group.querySelector(':scope > li')
        : group.querySelector(':scope > [data-body-row]');
      if (!firstRow) return;
      const bound = laterBulletBounds.get(firstRow);
      if (!bound) return; // first group is already inside the header zone
      bound.top = Math.min(bound.top, label.getBoundingClientRect().top - containerRect.top);
    });
  });

  // Prevent section headers from being orphaned at page bottom: a section
  // header should stay with at least its first piece of content.
  const sectionTitles: Element[] = [
    ...queryLocalClass(container, 'resume-section-title'),
    ...queryLocalClass(container, 'resume-section-title-sm'),
  ];
  sectionTitles.forEach((title) => {
    const titleRect = title.getBoundingClientRect();
    const section = closestLocalClass(title, 'resume-section');
    if (!section) return;

    // swiss-single binds the title to the first bullet instead of the whole
    // entry (entries split between bullets).
    const firstItem = findLocalClass<HTMLElement>(section, 'resume-item');
    const firstFineGrainedBullet =
      fineGrained && firstItem ? firstItem.querySelector(':scope > :is(ul, ol) > li') : null;
    const itemsContainer = findLocalClass<HTMLElement>(section, 'resume-items');
    const firstContent =
      firstFineGrainedBullet ||
      firstItem ||
      itemsContainer?.firstElementChild ||
      title.nextElementSibling; // Fallback to immediate sibling (p, ul, etc.)

    if (firstContent && firstContent !== title) {
      const firstContentRect = firstContent.getBoundingClientRect();
      // Unbreakable zone from title top to first content bottom.
      bounds.push({
        top: titleRect.top - containerRect.top,
        bottom: firstContentRect.bottom - containerRect.top,
        element: title,
      });
    } else {
      // No content found; protect the title with a small buffer.
      bounds.push({
        top: titleRect.top - containerRect.top,
        bottom: titleRect.bottom - containerRect.top + 50,
        element: title,
      });
    }
  });

  bounds.sort((a, b) => a.top - b.top);
  return bounds;
}

/**
 * Pure pagination model shared by the live preview hook and the diagnosis
 * layout measurement (which renders the same <Resume> offscreen).
 *
 * Greedy fill: each page starts at the previous break and runs a full page
 * deep; when that cut would split an unbreakable zone (item/bullet/title),
 * the break moves to the zone top — but only past the 50%-full mark so a
 * giant zone never wastes most of a page. A 100px minimum-progress guard
 * prevents loops, and trailing near-empty pages are dropped.
 */
export function computePageBreaks(
  contentHeight: number,
  pageHeight: number,
  bounds: UnbreakableBound[]
): PageBreak[] {
  // If content fits on one page, we're done
  if (contentHeight <= pageHeight) {
    return [{ pageNumber: 1, contentOffset: 0, contentEnd: contentHeight }];
  }

  const breakPoints: number[] = [0]; // Start positions of each page
  let currentOffset = 0;

  while (currentOffset + pageHeight < contentHeight) {
    let nextBreak = currentOffset + pageHeight;

    // Check if this break would split an individual item
    for (const bound of bounds) {
      // If an item straddles the page break
      if (bound.top < nextBreak && bound.bottom > nextBreak) {
        // Move break to before this item starts, but only if it doesn't push
        // us back too far (at least 50% of page used) so pages stay dense.
        const proposedBreak = bound.top;
        if (proposedBreak > currentOffset + pageHeight * 0.5) {
          nextBreak = proposedBreak;
          break;
        }
      }
    }

    // Safety: ensure we make progress (at least 100px per page)
    if (nextBreak <= currentOffset + 100) {
      nextBreak = currentOffset + pageHeight;
    }

    currentOffset = nextBreak;

    // Only add break point if there's more content and it's not a duplicate
    if (currentOffset < contentHeight) {
      const lastBreak = breakPoints[breakPoints.length - 1];
      if (currentOffset - lastBreak > 1) {
        breakPoints.push(currentOffset);
      }
    }
  }

  // Convert break points to page objects with start and end
  const newPages: PageBreak[] = breakPoints.map((offset, index) => ({
    pageNumber: index + 1,
    contentOffset: offset,
    contentEnd: index < breakPoints.length - 1 ? breakPoints[index + 1] : contentHeight,
  }));

  const nonEmptyPages = newPages.filter(
    (page, index) => page.contentEnd - page.contentOffset > 1 || index === 0
  );
  return nonEmptyPages.length > 0 ? nonEmptyPages : newPages.slice(0, 1);
}

interface UsePaginationOptions {
  pageSize: PageSize;
  margins: MarginSettings;
  measurementRef: React.RefObject<HTMLDivElement | null>;
  debounceMs?: number;
}

interface UsePaginationResult {
  pages: PageBreak[];
  totalContentHeight: number;
  isCalculating: boolean;
}

/**
 * Custom hook for calculating page breaks based on content height.
 * Respects section boundaries to avoid splitting content mid-section.
 */
export function usePagination({
  pageSize,
  margins,
  measurementRef,
  debounceMs = 150,
}: UsePaginationOptions): UsePaginationResult {
  const [pages, setPages] = useState<PageBreak[]>([
    { pageNumber: 1, contentOffset: 0, contentEnd: 0 },
  ]);
  const [totalContentHeight, setTotalContentHeight] = useState(0);
  const [isCalculating, setIsCalculating] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const calculatePageBreaks = useCallback(() => {
    const container = measurementRef.current;
    if (!container) {
      setPages([{ pageNumber: 1, contentOffset: 0, contentEnd: 0 }]);
      return;
    }

    setIsCalculating(true);

    // Wait for fonts to load before measuring
    document.fonts.ready.then(() => {
      const contentArea = getContentAreaPx(pageSize, margins);
      const contentHeight = container.scrollHeight;

      setTotalContentHeight(contentHeight);

      // Page-break-avoid zones (individual items / bullets / title zones) —
      // never whole sections: sections are allowed to span pages.
      const itemBounds = collectUnbreakableBounds(container);

      setPages(computePageBreaks(contentHeight, contentArea.height, itemBounds));
      setIsCalculating(false);
    });
  }, [pageSize, margins, measurementRef]);

  // Debounced recalculation
  const debouncedCalculate = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      calculatePageBreaks();
    }, debounceMs);
  }, [calculatePageBreaks, debounceMs]);

  // Set up observers for content changes
  useEffect(() => {
    const container = measurementRef.current;
    if (!container) return;

    // Initial calculation
    calculatePageBreaks();

    // ResizeObserver for size changes
    const resizeObserver = new ResizeObserver(() => {
      debouncedCalculate();
    });
    resizeObserver.observe(container);

    // MutationObserver for content changes
    const mutationObserver = new MutationObserver(() => {
      debouncedCalculate();
    });
    mutationObserver.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
    });

    return () => {
      resizeObserver.disconnect();
      mutationObserver.disconnect();
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [calculatePageBreaks, debouncedCalculate, measurementRef]);

  // Recalculate when page size or margins change
  useEffect(() => {
    calculatePageBreaks();
  }, [pageSize, margins, calculatePageBreaks]);

  return { pages, totalContentHeight, isCalculating };
}
