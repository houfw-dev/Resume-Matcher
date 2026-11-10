import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ApplicationCard } from '@/components/tracker/application-card';
import type { Application } from '@/lib/api/tracker';

const push = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

// dnd-kit sensors need DOM APIs irrelevant to date rendering; stub the hook.
const sortableState = vi.hoisted(() => ({ calls: [] as unknown[] }));
vi.mock('@dnd-kit/sortable', () => ({
  useSortable: (options: unknown) => {
    sortableState.calls.push(options);
    return {
      attributes: {},
      listeners: {},
      setNodeRef: vi.fn(),
      transform: null,
      transition: null,
      isDragging: false,
    };
  },
}));
vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: () => '' } },
}));

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'zh' }),
}));

function application(overrides: Partial<Application> = {}): Application {
  return {
    application_id: 'app-1',
    job_id: 'job-1',
    resume_id: 'res-1',
    master_resume_id: null,
    status: 'applied',
    company: 'Acme',
    role: 'Engineer',
    applied_at: '2026-03-05T12:00:00Z',
    notes: null,
    position: 0,
    created_at: '2026-03-05T12:00:00Z',
    updated_at: '2026-03-05T12:00:00Z',
    ...overrides,
  };
}

describe('ApplicationCard date localization', () => {
  it('renders applied_at in the active UI locale rather than hardcoded en-US', () => {
    render(
      <ApplicationCard
        application={application()}
        selected={false}
        sharedResume={false}
        onToggleSelect={vi.fn()}
        onOpen={vi.fn()}
      />
    );

    // zh formatting localizes the month; the old no-arg/en-US call rendered
    // "Mar 05, 2026" regardless of UI language.
    const dateLine = screen.getByText(/2026/);
    expect(dateLine).toHaveTextContent('3月');
    expect(dateLine).not.toHaveTextContent('Mar');
  });

  it('omits the date line entirely when applied_at is null', () => {
    render(
      <ApplicationCard
        application={application({ applied_at: null })}
        selected={false}
        sharedResume={false}
        onToggleSelect={vi.fn()}
        onOpen={vi.fn()}
      />
    );

    expect(screen.queryByText(/2026/)).not.toBeInTheDocument();
  });
});

describe('ApplicationCard resume reverse link', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sortableState.calls.length = 0;
  });

  it('routes to the resume viewer with an encoded id without opening the card', () => {
    const onOpen = vi.fn();
    render(
      <ApplicationCard
        application={application({ resume_id: 'res/1 2' })}
        selected={false}
        sharedResume={false}
        onToggleSelect={vi.fn()}
        onOpen={onOpen}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'tracker.card.viewResume' }));
    expect(push).toHaveBeenCalledWith('/resumes/res%2F1%202');
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('disables the drag handle when dragDisabled', () => {
    render(
      <ApplicationCard
        application={application()}
        selected={false}
        sharedResume={false}
        onToggleSelect={vi.fn()}
        onOpen={vi.fn()}
        dragDisabled
      />
    );

    expect(screen.getByRole('button', { name: 'tracker.card.dragAria' })).toBeDisabled();
    expect(sortableState.calls.at(-1)).toEqual(
      expect.objectContaining({ id: 'app-1', disabled: true })
    );
  });

  it('keeps the drag handle enabled on the regular board', () => {
    render(
      <ApplicationCard
        application={application()}
        selected={false}
        sharedResume={false}
        onToggleSelect={vi.fn()}
        onOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: 'tracker.card.dragAria' })).toBeEnabled();
    expect(sortableState.calls.at(-1)).toEqual(
      expect.objectContaining({ id: 'app-1', disabled: false })
    );
  });
});
