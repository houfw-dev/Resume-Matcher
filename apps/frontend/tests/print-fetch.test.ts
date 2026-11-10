import { afterEach, describe, expect, it, vi } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { PRINT_DATA_FETCH_TIMEOUT_MS, fetchPrintResource } from '@/lib/print/fetch';

/**
 * The print/* server components render inside headless Chromium for the PDF
 * pipeline. Their data fetches must be bounded (AbortSignal.timeout) so a hung
 * internal API call cannot consume the whole 60s Playwright navigation budget,
 * and every print route must load through the shared helper.
 */

const PRINT_DIR = join(process.cwd(), 'app', 'print');

function collectPrintPages(dir: string): string[] {
  const pages: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      pages.push(...collectPrintPages(full));
    } else if (entry === 'page.tsx') {
      pages.push(full);
    }
  }
  return pages;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('fetchPrintResource', () => {
  it('composes the API base URL with no-store and a 15s abort signal', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    const timeoutSpy = vi.spyOn(AbortSignal, 'timeout');

    await fetchPrintResource('/resumes?resume_id=abc');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes?resume_id=abc');
    expect(init.cache).toBe('no-store');
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(timeoutSpy).toHaveBeenCalledWith(PRINT_DATA_FETCH_TIMEOUT_MS);
    expect(PRINT_DATA_FETCH_TIMEOUT_MS).toBe(15_000);
  });

  it('rejects a request that never settles once the abort deadline fires', async () => {
    let capturedSignal: AbortSignal | undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            capturedSignal = init?.signal ?? undefined;
            capturedSignal?.addEventListener('abort', () => {
              const reason = capturedSignal?.reason;
              reject(reason instanceof Error ? reason : new Error('aborted'));
            });
          })
      )
    );

    await expect(fetchPrintResource('/resumes?resume_id=hang', 30)).rejects.toThrow();
    expect(capturedSignal).toBeDefined();
    expect(capturedSignal?.aborted).toBe(true);
  });

  it('returns the response untouched when the fetch settles in time', async () => {
    const response = new Response(JSON.stringify({ ok: true }), { status: 200 });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

    const result = await fetchPrintResource('/resumes?resume_id=fast', 5_000);

    expect(result).toBe(response);
    expect(result.status).toBe(200);
  });
});

describe('print route call sites', () => {
  it('every print page loads data through fetchPrintResource (no raw fetch, no API_BASE)', () => {
    const pages = collectPrintPages(PRINT_DIR);
    expect(pages.length).toBeGreaterThanOrEqual(5);
    const offenders: string[] = [];
    for (const page of pages) {
      const source = readFileSync(page, 'utf8');
      if (/[^.\w]fetch\s*\(/.test(source) || source.includes('API_BASE')) {
        offenders.push(page);
      }
    }
    expect(offenders).toEqual([]);
  });
});
