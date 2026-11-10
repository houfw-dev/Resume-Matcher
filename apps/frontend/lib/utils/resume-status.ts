/**
 * Backend resume processing status -> i18n label key.
 *
 * The backend (`processing_status` on every resume document) emits exactly
 * these four values. The dashboard additionally has a frontend-only
 * 'loading' state while the first status poll is in flight; it is mapped at
 * the call site, not here.
 *
 * Centralizing the map keeps the master card and the tailored-card grid
 * translating the same enum identically — a raw enum string on a tailored
 * card otherwise leaks English (e.g. "ready") into every localized UI.
 */
export type ResumeProcessingStatus = 'pending' | 'processing' | 'ready' | 'failed';

const STATUS_LABEL_KEYS: Readonly<Record<ResumeProcessingStatus, string>> = Object.freeze({
  pending: 'dashboard.status.pending',
  processing: 'dashboard.status.processing',
  ready: 'dashboard.status.ready',
  failed: 'dashboard.status.failed',
});

/**
 * Resolve a raw processing status to its translation key. Unknown values
 * (a newer backend enum the UI does not know yet) fall back to 'pending'
 * rather than rendering the raw enum to end users.
 */
export function getProcessingStatusLabelKey(status: string | null | undefined): string {
  if (status && status in STATUS_LABEL_KEYS) {
    return STATUS_LABEL_KEYS[status as ResumeProcessingStatus];
  }
  return STATUS_LABEL_KEYS.pending;
}
