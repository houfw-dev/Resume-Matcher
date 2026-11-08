import type { ResumeListItem } from '@/lib/api/resume';

/**
 * Eligible tailoring sources are master/standalone resumes (no parent
 * lineage) that finished processing. Already-tailored resumes are excluded so
 * the lineage cannot grow nested grandchild chains — the same rule the backend
 * enforces in `_validate_tailor_source`.
 */
export function isEligibleTailorSource(item: ResumeListItem): boolean {
  return item.parent_id === null && item.processing_status === 'ready';
}

export interface TailorSourceSelection {
  eligible: ResumeListItem[];
  selectedId: string | null;
}

/**
 * Pick the source resume for the tailor page.
 *
 * Priority: an eligible `?source=` query param → the master resume → the
 * locally cached master id → the first eligible resume. With no eligible
 * resume the caller should redirect back to the dashboard.
 */
export function selectTailorSource(
  list: ResumeListItem[],
  requestedSource: string | null,
  storedMasterId: string | null
): TailorSourceSelection {
  const eligible = list.filter(isEligibleTailorSource);
  if (eligible.length === 0) {
    return { eligible, selectedId: null };
  }
  const fromQuery = eligible.find((item) => item.resume_id === requestedSource);
  const master = eligible.find((item) => item.is_master);
  const fromStorage = eligible.find((item) => item.resume_id === storedMasterId);
  const selected = fromQuery ?? master ?? fromStorage ?? eligible[0];
  return { eligible, selectedId: selected.resume_id };
}
