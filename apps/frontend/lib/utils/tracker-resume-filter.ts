import {
  APPLICATION_STATUS_ORDER,
  type Application,
  type ApplicationColumns,
} from '@/lib/api/tracker';

/**
 * A card belongs to a resume when the resume was applied directly
 * (`resume_id`) or when it is the master/base of a tailored application
 * (`master_resume_id`). Mirrors the backend `OR` filter on
 * `GET /applications?resume_id=...` — keep the two predicates in sync.
 */
export function applicationMatchesResume(application: Application, resumeId: string): boolean {
  return application.resume_id === resumeId || application.master_resume_id === resumeId;
}

/**
 * Narrow every board column to cards linked to `resumeId`. A null id returns
 * the columns unchanged (the unfiltered board). All seven keys are preserved
 * so consumers can keep rendering the fixed column layout.
 */
export function filterColumnsByResume(
  columns: ApplicationColumns,
  resumeId: string | null
): ApplicationColumns {
  const next = {} as ApplicationColumns;
  for (const status of APPLICATION_STATUS_ORDER) {
    next[status] = resumeId
      ? columns[status].filter((card) => applicationMatchesResume(card, resumeId))
      : columns[status];
  }
  return next;
}

/** Total card count across all seven columns. */
export function countApplications(columns: ApplicationColumns): number {
  return APPLICATION_STATUS_ORDER.reduce((total, status) => total + columns[status].length, 0);
}
