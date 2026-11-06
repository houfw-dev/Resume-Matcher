import { describe, expect, it } from 'vitest';
import { computePageBreaks, type PageBreak } from '@/components/preview/use-pagination';

/**
 * The greedy pagination model shared by the live preview and the diagnosis
 * offscreen measurement. Bounds carry an Element only to satisfy the type;
 * geometry alone drives the algorithm.
 */
function bound(top: number, bottom: number): { top: number; bottom: number; element: Element } {
  return { top, bottom, element: document.createElement('div') };
}

function offsets(pages: PageBreak[]): [number, number][] {
  return pages.map((page) => [page.contentOffset, page.contentEnd]);
}

describe('computePageBreaks', () => {
  it('returns one page when content fits', () => {
    expect(offsets(computePageBreaks(800, 1000, []))).toEqual([[0, 800]]);
  });

  it('splits equal pages without bounds', () => {
    expect(offsets(computePageBreaks(2000, 1000, []))).toEqual([
      [0, 1000],
      [1000, 2000],
    ]);
  });

  it('moves a straddling break to the zone top past the 50% mark', () => {
    // Zone 700–1200 straddles the 1000 cut and starts past half a page, so the
    // break retreats to 700 instead of slicing the zone.
    const pages = computePageBreaks(1800, 1000, [bound(700, 1200)]);
    // First page ends at the zone top (700); page two then fills a full page
    // because the zone no longer straddles the 1700 cut.
    expect(offsets(pages)).toEqual([
      [0, 700],
      [700, 1700],
      [1700, 1800],
    ]);
  });

  it('keeps the hard cut when the zone starts in the top half', () => {
    // Zone 200–1600: retreating to 200 would waste > half the page, so the
    // cut stays at 1000; the giant zone is allowed to span pages.
    const pages = computePageBreaks(1800, 1000, [bound(200, 1600)]);
    expect(offsets(pages)).toEqual([
      [0, 1000],
      [1000, 1800],
    ]);
  });

  it('fills at least three pages for long content with retreating zones', () => {
    // Each page break retreats to a zone top, but always makes progress.
    const zones = [bound(700, 1100), bound(1700, 2100), bound(2700, 3100)];
    const pages = computePageBreaks(3600, 1000, zones);
    expect(pages.length).toBeGreaterThanOrEqual(3);
    expect(pages[0].contentOffset).toBe(0);
    // Pages advance in order and the last page ends at content height.
    for (let i = 1; i < pages.length; i += 1) {
      expect(pages[i].contentOffset).toBe(pages[i - 1].contentEnd);
      expect(pages[i].contentOffset).toBeGreaterThan(pages[i - 1].contentOffset);
    }
    expect(pages[pages.length - 1].contentEnd).toBe(3600);
  });
});
