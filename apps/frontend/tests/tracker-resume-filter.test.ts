import { describe, expect, it } from 'vitest';
import {
  applicationMatchesResume,
  countApplications,
  filterColumnsByResume,
} from '@/lib/utils/tracker-resume-filter';
import {
  APPLICATION_STATUS_ORDER,
  type Application,
  type ApplicationColumns,
  type ApplicationStatus,
} from '@/lib/api/tracker';

function application(id: string, overrides: Partial<Application> = {}): Application {
  return {
    application_id: id,
    job_id: `job-${id}`,
    resume_id: 'res-direct',
    master_resume_id: null,
    status: 'applied',
    company: 'Acme',
    role: 'Engineer',
    applied_at: null,
    notes: null,
    position: 0,
    created_at: '2026-03-05T12:00:00Z',
    updated_at: '2026-03-05T12:00:00Z',
    ...overrides,
  };
}

function emptyColumns(): ApplicationColumns {
  return APPLICATION_STATUS_ORDER.reduce((acc, status) => {
    acc[status] = [];
    return acc;
  }, {} as ApplicationColumns);
}

function columnsWith(cards: Application[]): ApplicationColumns {
  const columns = emptyColumns();
  for (const card of cards) columns[card.status].push(card);
  return columns;
}

describe('applicationMatchesResume', () => {
  it('matches a card that applied the resume directly', () => {
    expect(applicationMatchesResume(application('a', { resume_id: 'r1' }), 'r1')).toBe(true);
  });

  it('matches a tailored card whose master/base resume is the given resume', () => {
    const card = application('a', { resume_id: 'r2', master_resume_id: 'r1' });
    expect(applicationMatchesResume(card, 'r1')).toBe(true);
  });

  it('rejects a card linked to neither id', () => {
    const card = application('a', { resume_id: 'r2', master_resume_id: 'r9' });
    expect(applicationMatchesResume(card, 'r1')).toBe(false);
  });

  it('never matches when master_resume_id is null and the direct id differs', () => {
    const card = application('a', { resume_id: 'r2', master_resume_id: null });
    expect(applicationMatchesResume(card, 'r1')).toBe(false);
  });
});

describe('filterColumnsByResume', () => {
  const cards: Application[] = [
    application('direct', { resume_id: 'r1', status: 'applied' }),
    application('child', { resume_id: 'r2', master_resume_id: 'r1', status: 'interview' }),
    application('other', { resume_id: 'r3', status: 'applied' }),
  ];

  it('keeps only direct and master-lineage cards across columns', () => {
    const filtered = filterColumnsByResume(columnsWith(cards), 'r1');
    const ids = APPLICATION_STATUS_ORDER.flatMap((status) =>
      filtered[status].map((card) => card.application_id)
    );
    expect(ids.sort()).toEqual(['child', 'direct']);
    expect(filtered.applied.map((card) => card.application_id)).toEqual(['direct']);
    expect(filtered.interview.map((card) => card.application_id)).toEqual(['child']);
  });

  it('preserves all seven column keys even when every column is empty', () => {
    const filtered = filterColumnsByResume(columnsWith(cards), 'ghost');
    expect(Object.keys(filtered).sort()).toEqual([...APPLICATION_STATUS_ORDER].sort());
    expect(countApplications(filtered)).toBe(0);
  });

  it('returns the columns unchanged for a null filter (unfiltered board)', () => {
    const source = columnsWith(cards);
    const filtered = filterColumnsByResume(source, null);
    expect(filtered).toEqual(source);
    expect(countApplications(filtered)).toBe(3);
  });

  it('does not mutate the source columns', () => {
    const source = columnsWith(cards);
    const snapshot = JSON.stringify(source);
    filterColumnsByResume(source, 'r1');
    expect(JSON.stringify(source)).toBe(snapshot);
  });
});

describe('countApplications', () => {
  it('sums cards across every status column', () => {
    const columns = emptyColumns();
    const statuses: ApplicationStatus[] = ['saved', 'accepted', 'rejected'];
    statuses.forEach((status, index) => {
      columns[status] = [application(`a${index}`, { status })];
    });
    expect(countApplications(columns)).toBe(3);
  });

  it('is zero for an empty board', () => {
    expect(countApplications(emptyColumns())).toBe(0);
  });
});
