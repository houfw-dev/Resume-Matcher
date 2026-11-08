import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ResumeViewerPage from '@/app/(default)/resumes/[id]/page';
import { fetchResume } from '@/lib/api/resume';

const route = vi.hoisted(() => ({ resumeId: 'resume-a' }));
const push = vi.fn();

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
vi.mock('@/components/enrichment/enrichment-modal', () => ({
  EnrichmentModal: () => null,
}));
vi.mock('@/components/diagnosis/diagnosis-modal', () => ({
  DiagnosisModal: () => null,
}));

const mockedFetchResume = vi.mocked(fetchResume);

beforeEach(() => {
  vi.clearAllMocks();
  mockedFetchResume.mockResolvedValue({
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
      processing_status: 'ready',
    },
  });
});

describe('resume viewer removed AI entry points', () => {
  it('no longer renders the cover-letter studio entry', async () => {
    render(<ResumeViewerPage />);

    await screen.findByTestId('resume-name');
    expect(screen.queryByRole('button', { name: 'coverLetter.generate' })).not.toBeInTheDocument();
  });

  it('no longer renders the interview-prep entry for tailored resumes', async () => {
    mockedFetchResume.mockResolvedValueOnce({
      resume_id: route.resumeId,
      title: 'Tailored child',
      parent_id: 'master-resume',
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
        processing_status: 'ready',
      },
    });

    render(<ResumeViewerPage />);

    await screen.findByTestId('resume-name');
    expect(screen.queryByRole('button', { name: 'interviewPrep.title' })).not.toBeInTheDocument();
  });
});

describe('resume viewer tailor-from-this entry', () => {
  it('offers tailoring for a standalone ready resume and carries the source id', async () => {
    render(<ResumeViewerPage />);

    const entry = await screen.findByRole('button', {
      name: 'resumeViewer.tailorFromThis',
    });
    expect(entry).toBeInTheDocument();

    fireEvent.click(entry);
    await waitFor(() => expect(push).toHaveBeenCalledWith(`/tailor?source=${route.resumeId}`));
  });

  it('hides the entry for an already-tailored resume', async () => {
    mockedFetchResume.mockResolvedValueOnce({
      resume_id: route.resumeId,
      title: 'Tailored child',
      parent_id: 'master-resume',
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
        processing_status: 'ready',
      },
    });

    render(<ResumeViewerPage />);

    await screen.findByTestId('resume-name');
    expect(
      screen.queryByRole('button', { name: 'resumeViewer.tailorFromThis' })
    ).not.toBeInTheDocument();
  });

  it('hides the entry while the resume is still processing', async () => {
    mockedFetchResume.mockResolvedValueOnce({
      resume_id: route.resumeId,
      title: 'Still processing',
      processed_resume: null,
      raw_resume: {
        id: null,
        content: '',
        content_type: 'text/markdown',
        created_at: '2026-09-05T00:00:00Z',
        processing_status: 'processing',
      },
    });

    render(<ResumeViewerPage />);

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'resumeViewer.tailorFromThis' })
      ).not.toBeInTheDocument()
    );
  });
});
