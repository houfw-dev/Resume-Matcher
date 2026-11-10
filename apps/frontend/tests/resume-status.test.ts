import { describe, expect, it } from 'vitest';
import { getProcessingStatusLabelKey } from '@/lib/utils/resume-status';

describe('getProcessingStatusLabelKey', () => {
  it.each([
    ['pending', 'dashboard.status.pending'],
    ['processing', 'dashboard.status.processing'],
    ['ready', 'dashboard.status.ready'],
    ['failed', 'dashboard.status.failed'],
  ])('maps backend status %s to its localized label key', (status, expectedKey) => {
    expect(getProcessingStatusLabelKey(status)).toBe(expectedKey);
  });

  it('falls back to the pending label for unknown or missing statuses', () => {
    // A newer backend enum must never render as a raw English string.
    expect(getProcessingStatusLabelKey('archived')).toBe('dashboard.status.pending');
    expect(getProcessingStatusLabelKey(null)).toBe('dashboard.status.pending');
    expect(getProcessingStatusLabelKey(undefined)).toBe('dashboard.status.pending');
  });
});
