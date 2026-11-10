import { API_BASE } from '@/lib/api/client';

/**
 * Timeout for print-page server-side data fetches.
 *
 * The backend PDF pipeline renders these pages in headless Chromium with a
 * 60s per-stage navigation budget (`_NAV_TIMEOUT_MS` in apps/backend/app/pdf.py).
 * A hung internal API call must reject fast enough to leave the render,
 * selector and font stages their share of that budget instead of silently
 * consuming all of it. A single-row local read normally returns in
 * milliseconds; 15s is a generous ceiling.
 */
export const PRINT_DATA_FETCH_TIMEOUT_MS = 15_000;

/**
 * Server-side fetch for the `app/print/*` routes: `no-store` plus a hard
 * `AbortSignal.timeout`. Print pages are React Server Components rendered
 * inside the PDF pipeline, so a request that never settles must reject rather
 * than hang the whole document render. All print data loading goes through
 * this helper so no route can regress to an unbounded raw `fetch`.
 *
 * @param path Path relative to `/api/v1` (must start with `/`).
 * @param timeoutMs Override for the abort deadline (tests only; production
 *   call sites use the 15s default).
 */
export async function fetchPrintResource(
  path: string,
  timeoutMs: number = PRINT_DATA_FETCH_TIMEOUT_MS
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(timeoutMs),
  });
}
