import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { KanbanBoard } from '@/components/tracker/kanban-board';
import {
  APPLICATION_STATUS_ORDER,
  type Application,
  type ApplicationColumns,
  type ApplicationStatus,
} from '@/lib/api/tracker';

const nav = vi.hoisted(() => ({ push: vi.fn(), resumeParam: null as string | null }));
const api = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: nav.push }),
  useSearchParams: () => ({
    get: (key: string) => (key === 'resume' ? nav.resumeParam : null),
  }),
}));

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'en' }),
}));

vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PointerSensor: class PointerSensor {},
  KeyboardSensor: class KeyboardSensor {},
  closestCorners: vi.fn(),
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
}));

vi.mock('@/components/tracker/kanban-column', () => ({
  KanbanColumn: ({
    status,
    applications,
    dragDisabled,
  }: {
    status: ApplicationStatus;
    applications: Application[];
    dragDisabled?: boolean;
  }) => (
    <div data-testid={`col-${status}`} data-drag-disabled={dragDisabled ? 'true' : 'false'}>
      {applications.map((card) => (
        <span key={card.application_id}>{card.application_id}</span>
      ))}
    </div>
  ),
}));

vi.mock('@/components/tracker/card-detail-modal', () => ({
  CardDetailModal: () => null,
}));
vi.mock('@/components/tracker/manage-columns-dialog', () => ({
  ManageColumnsDialog: () => null,
}));
vi.mock('@/components/tracker/manual-add-application-dialog', () => ({
  ManualAddApplicationDialog: ({ open }: { open: boolean }) => (
    <div data-testid="manual-dialog" data-open={open ? 'true' : 'false'} />
  ),
}));

vi.mock('@/lib/api/tracker', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/tracker')>()),
  listApplications: (...args: unknown[]) => api.list(...args),
  updateApplication: vi.fn(),
  bulkUpdateStatus: vi.fn(),
  bulkDeleteApplications: vi.fn(),
}));

function card(
  application_id: string,
  status: ApplicationStatus,
  overrides: Partial<Application> = {}
): Application {
  return {
    application_id,
    job_id: `job-${application_id}`,
    resume_id: 'res-other',
    master_resume_id: null,
    status,
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

function boardResponse(cards: Application[]): { columns: ApplicationColumns } {
  const columns = APPLICATION_STATUS_ORDER.reduce((acc, status) => {
    acc[status] = [];
    return acc;
  }, {} as ApplicationColumns);
  for (const item of cards) columns[item.status].push(item);
  return { columns };
}

const sampleCards = [
  card('direct', 'applied', { resume_id: 'r1' }),
  card('child', 'interview', { resume_id: 'r2', master_resume_id: 'r1' }),
  card('unrelated', 'saved', { resume_id: 'r3' }),
];

beforeEach(() => {
  vi.clearAllMocks();
  nav.resumeParam = null;
});

afterEach(() => {
  localStorage.clear();
});

describe('KanbanBoard empty state CTAs', () => {
  it('renders add and dashboard CTAs on an empty board and wires both', async () => {
    api.list.mockResolvedValue(boardResponse([]));
    render(<KanbanBoard />);

    // Scope to the empty-state panel — the header always has its own Add button.
    const emptyPanel = (await screen.findByText('tracker.empty.title')).closest('div')!;
    fireEvent.click(within(emptyPanel).getByRole('button', { name: /tracker.addApplication/ }));
    expect(screen.getByTestId('manual-dialog').dataset.open).toBe('true');

    fireEvent.click(within(emptyPanel).getByRole('button', { name: 'tracker.empty.goDashboard' }));
    expect(nav.push).toHaveBeenCalledWith('/dashboard');
  });
});

describe('KanbanBoard resume filter (?resume=)', () => {
  it('renders the full board without a filter banner when no param is present', async () => {
    api.list.mockResolvedValue(boardResponse(sampleCards));
    render(<KanbanBoard />);

    await screen.findByText('direct');
    expect(screen.queryByText('tracker.filter.banner')).not.toBeInTheDocument();
    expect(screen.getByText('child')).toBeInTheDocument();
    expect(screen.getByText('unrelated')).toBeInTheDocument();
    expect(screen.getByTestId('col-applied').dataset.dragDisabled).toBe('false');
  });

  it('narrows columns to direct and master-lineage cards and disables drag', async () => {
    nav.resumeParam = 'r1';
    api.list.mockResolvedValue(boardResponse(sampleCards));
    render(<KanbanBoard />);

    expect(await screen.findByText('tracker.filter.banner')).toBeInTheDocument();
    expect(screen.getByText('direct')).toBeInTheDocument();
    expect(screen.getByText('child')).toBeInTheDocument();
    expect(screen.queryByText('unrelated')).not.toBeInTheDocument();
    // Every rendered column signals drag-off while the filter is active.
    for (const status of APPLICATION_STATUS_ORDER) {
      expect(screen.getByTestId(`col-${status}`).dataset.dragDisabled).toBe('true');
    }

    fireEvent.click(screen.getByRole('button', { name: 'tracker.filter.clear' }));
    expect(nav.push).toHaveBeenCalledWith('/tracker');
  });

  it('shows the filtered-empty message with an add CTA when nothing matches', async () => {
    nav.resumeParam = 'ghost';
    api.list.mockResolvedValue(boardResponse(sampleCards));
    render(<KanbanBoard />);

    const emptyPanel = (await screen.findByText('tracker.filter.emptyTitle')).closest('div')!;
    expect(screen.queryByText('direct')).not.toBeInTheDocument();
    fireEvent.click(within(emptyPanel).getByRole('button', { name: /tracker.addApplication/ }));
    expect(screen.getByTestId('manual-dialog').dataset.open).toBe('true');
  });

  it('treats an empty ?resume= as absent (unfiltered board)', async () => {
    nav.resumeParam = '';
    api.list.mockResolvedValue(boardResponse(sampleCards));
    render(<KanbanBoard />);

    await screen.findByText('unrelated');
    expect(screen.queryByText('tracker.filter.banner')).not.toBeInTheDocument();
  });

  it('loads the board through the unfiltered list endpoint (no server filter param)', async () => {
    api.list.mockResolvedValue(boardResponse(sampleCards));
    render(<KanbanBoard />);

    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1));
    expect(api.list).toHaveBeenCalledWith();
  });
});
