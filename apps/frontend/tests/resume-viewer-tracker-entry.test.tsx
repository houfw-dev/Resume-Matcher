import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ResumeViewerPage from '@/app/(default)/resumes/[id]/page';
import { fetchResume } from '@/lib/api/resume';
import {
  APPLICATION_STATUS_ORDER,
  type Application,
  type ApplicationColumns,
  type ApplicationStatus,
} from '@/lib/api/tracker';

const route = vi.hoisted(() => ({ resumeId: 'resume-a' }));
const push = vi.fn();
const tracker = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: route.resumeId }),
}));
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ decrementResumes: vi.fn(), setHasMasterResume: vi.fn() }),
}));
vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en' }),
}));
vi.mock('@/components/dashboard/resume-component', () => ({
  default: ({ resumeData }: { resumeData: { personalInfo?: { name?: string } } }) => (
    <div data-testid="resume-name">{resumeData.personalInfo?.name}</div>
  ),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  deleteResume: vi.fn(),
  retryProcessing: vi.fn(),
  renameResume: vi.fn(),
  downloadResumePdf: vi.fn(),
  getResumePdfUrl: vi.fn(),
  downloadResumeDocx: vi.fn(),
  getResumeDocxUrl: vi.fn(),
}));
vi.mock('@/lib/api/tracker', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/tracker')>()),
  listApplications: (...args: unknown[]) => tracker.list(...args),
}));
vi.mock('@/components/enrichment/enrichment-modal', () => ({
  EnrichmentModal: () => null,
}));
vi.mock('@/components/diagnosis/diagnosis-modal', () => ({
  DiagnosisModal: () => null,
}));

const mockedFetchResume = vi.mocked(fetchResume);

function readyResume() {
  return {
    resume_id: route.resumeId,
    title: 'Jane resume',
    processed_resume: {
      personalInfo: { name: 'Jane Doe' },
      workExperience: [],
      education: [],
      personalProjects: [],
      additional: {},
    },
    raw_resume: {
      id: null,
      content: '',
      content_type: 'application/json',
      created_at: '2026-09-05T00:00:00Z',
      processing_status: 'ready' as const,
    },
  };
}

function trackerResponse(counts: Partial<Record<string, number>>) {
  const columns = APPLICATION_STATUS_ORDER.reduce((acc, status) => {
    acc[status] = [];
    return acc;
  }, {} as ApplicationColumns);
  for (const [status, count] of Object.entries(counts)) {
    columns[status as ApplicationStatus] = Array.from(
      { length: count ?? 0 },
      (_, index): Application => ({
        application_id: `${status}-${index}`,
        job_id: `job-${status}-${index}`,
        resume_id: route.resumeId,
        master_resume_id: null,
        status: status as ApplicationStatus,
        company: null,
        role: null,
        applied_at: null,
        notes: null,
        position: index,
        created_at: '2026-03-05T12:00:00Z',
        updated_at: '2026-03-05T12:00:00Z',
      })
    );
  }
  return { columns };
}

beforeEach(() => {
  vi.clearAllMocks();
  route.resumeId = 'resume-a';
  mockedFetchResume.mockResolvedValue(readyResume());
});

describe('resume viewer tracker entry', () => {
  it('queries applications for this resume and deep-links with a count badge', async () => {
    tracker.list.mockResolvedValue(trackerResponse({ applied: 1, interview: 1 }));
    render(<ResumeViewerPage />);

    await screen.findByTestId('resume-name');
    await waitFor(() => expect(tracker.list).toHaveBeenCalledWith({ resumeId: 'resume-a' }));

    const entry = await screen.findByRole('button', {
      name: /resumeViewer.trackApplications/,
    });
    expect(screen.getByTestId('tracker-count')).toHaveTextContent('2');

    fireEvent.click(entry);
    expect(push).toHaveBeenCalledWith('/tracker?resume=resume-a');
  });

  it('omits the badge when no applications link to this resume', async () => {
    tracker.list.mockResolvedValue(trackerResponse({}));
    render(<ResumeViewerPage />);

    await screen.findByTestId('resume-name');
    expect(
      await screen.findByRole('button', { name: /resumeViewer.trackApplications/ })
    ).toBeInTheDocument();
    await waitFor(() => expect(tracker.list).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('tracker-count')).not.toBeInTheDocument();
  });

  it('keeps the entry usable without a badge when the count fetch fails', async () => {
    tracker.list.mockRejectedValue(new Error('network down'));
    render(<ResumeViewerPage />);

    const entry = await screen.findByRole('button', {
      name: /resumeViewer.trackApplications/,
    });
    expect(screen.queryByTestId('tracker-count')).not.toBeInTheDocument();

    fireEvent.click(entry);
    expect(push).toHaveBeenCalledWith('/tracker?resume=resume-a');
  });

  it('encodes special characters in the resume id for the deep link', async () => {
    route.resumeId = 'res/1 2';
    mockedFetchResume.mockResolvedValue(readyResume());
    tracker.list.mockResolvedValue(trackerResponse({ applied: 1 }));
    render(<ResumeViewerPage />);

    const entry = await screen.findByRole('button', {
      name: /resumeViewer.trackApplications/,
    });
    await waitFor(() => expect(tracker.list).toHaveBeenCalledWith({ resumeId: 'res/1 2' }));
    fireEvent.click(entry);
    expect(push).toHaveBeenCalledWith('/tracker?resume=res%2F1%202');
  });
});
