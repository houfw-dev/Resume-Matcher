import { describe, expect, it } from 'vitest';
import type { ResumeListItem } from '@/lib/api/resume';
import { isEligibleTailorSource, selectTailorSource } from '@/lib/utils/tailor-source';

function item(overrides: Partial<ResumeListItem>): ResumeListItem {
  return {
    resume_id: overrides.resume_id ?? 'id',
    filename: 'resume.pdf',
    is_master: false,
    parent_id: null,
    processing_status: 'ready',
    created_at: '',
    updated_at: '',
    ...overrides,
  };
}

const master = item({ resume_id: 'master', is_master: true });
const standalone = item({ resume_id: 'standalone' });
const tailored = item({ resume_id: 'tailored', parent_id: 'master' });
const processing = item({ resume_id: 'processing', processing_status: 'processing' });
const failed = item({ resume_id: 'failed', processing_status: 'failed' });

describe('isEligibleTailorSource', () => {
  it('accepts the master and standalone ready resumes', () => {
    expect(isEligibleTailorSource(master)).toBe(true);
    expect(isEligibleTailorSource(standalone)).toBe(true);
  });

  it('rejects tailored resumes regardless of status', () => {
    expect(isEligibleTailorSource(tailored)).toBe(false);
  });

  it('rejects resumes that are not ready yet', () => {
    expect(isEligibleTailorSource(processing)).toBe(false);
    expect(isEligibleTailorSource(failed)).toBe(false);
  });
});

describe('selectTailorSource', () => {
  const list = [master, standalone, tailored, processing];

  it('filters out tailored and non-ready resumes', () => {
    const { eligible } = selectTailorSource(list, null, null);
    expect(eligible.map((r) => r.resume_id)).toEqual(['master', 'standalone']);
  });

  it('prefers an eligible ?source= query param over the master', () => {
    const { selectedId } = selectTailorSource(list, 'standalone', 'master');
    expect(selectedId).toBe('standalone');
  });

  it('falls back to the master when the query param is absent', () => {
    const { selectedId } = selectTailorSource(list, null, null);
    expect(selectedId).toBe('master');
  });

  it('ignores an ineligible query param and falls back to the master', () => {
    const { selectedId } = selectTailorSource(list, 'tailored', null);
    expect(selectedId).toBe('master');
  });

  it('uses the cached master id when no master flag and no query param', () => {
    const noMaster = [standalone, tailored];
    const { selectedId } = selectTailorSource(noMaster, null, 'standalone');
    expect(selectedId).toBe('standalone');
  });

  it('picks the first eligible resume as the last resort', () => {
    const another = item({ resume_id: 'another-standalone' });
    const { selectedId } = selectTailorSource([standalone, another], null, null);
    expect(selectedId).toBe('standalone');
  });

  it('returns no selection when nothing is eligible', () => {
    const { eligible, selectedId } = selectTailorSource([tailored, processing], null, null);
    expect(eligible).toEqual([]);
    expect(selectedId).toBeNull();
  });
});
