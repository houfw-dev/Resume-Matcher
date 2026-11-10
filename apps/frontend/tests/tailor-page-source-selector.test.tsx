import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TailorPage from '@/app/(default)/tailor/page';
import { fetchResumeList } from '@/lib/api/resume';
import type { ResumeListItem } from '@/lib/api/resume';

const push = vi.fn();
let sourceParam: string | null = null;
const searchParams = {
  get: (key: string) => (key === 'source' ? sourceParam : null),
};

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, back: vi.fn() }),
  useSearchParams: () => searchParams,
}));
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({
    status: { llm_configured: true },
    isLoading: false,
    incrementJobs: vi.fn(),
    incrementImprovements: vi.fn(),
    incrementResumes: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-operation-owner', () => ({
  useOperationOwner: () => ({
    begin: () => 1,
    isCurrent: () => true,
    invalidate: vi.fn(),
  }),
}));
vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ setImprovedData: vi.fn() }),
}));
vi.mock('@/components/tailor/diff-preview-modal', () => ({
  DiffPreviewModal: () => null,
}));
vi.mock('@/components/tailor/ats-score-card', () => ({ ATSScoreCard: () => null }));
vi.mock('@/components/ui/confirm-dialog', () => ({ ConfirmDialog: () => null }));
vi.mock('@/lib/api/config', () => ({
  fetchPromptConfig: vi.fn().mockResolvedValue({
    prompt_options: [],
    default_prompt_id: 'keywords',
  }),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResumeList: vi.fn(),
  uploadJobDescriptions: vi.fn(),
  previewImproveResume: vi.fn(),
  confirmImproveResume: vi.fn(),
}));

const RESUMES: ResumeListItem[] = [
  {
    resume_id: 'master-1',
    filename: 'master.pdf',
    is_master: true,
    parent_id: null,
    processing_status: 'ready',
    created_at: '',
    updated_at: '',
    title: 'Master Title',
  },
  {
    resume_id: 'standalone-1',
    filename: 'standalone.pdf',
    is_master: false,
    parent_id: null,
    processing_status: 'ready',
    created_at: '',
    updated_at: '',
    title: 'Standalone Title',
  },
  {
    resume_id: 'tailored-1',
    filename: 'tailored.pdf',
    is_master: false,
    parent_id: 'master-1',
    processing_status: 'ready',
    created_at: '',
    updated_at: '',
    title: 'Tailored Title',
  },
  {
    resume_id: 'processing-1',
    filename: 'processing.pdf',
    is_master: false,
    parent_id: null,
    processing_status: 'processing',
    created_at: '',
    updated_at: '',
    title: 'Processing Title',
  },
];

const mockedFetchResumeList = vi.mocked(fetchResumeList);

async function openSourceMenu() {
  const trigger = screen.getByRole('button', { name: 'tailor.selectResume' });
  fireEvent.click(trigger);
  return screen.getByRole('menu', { name: 'tailor.selectResume' });
}

describe('tailor page source selector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sourceParam = null;
    mockedFetchResumeList.mockResolvedValue(RESUMES);
  });

  it('lists only eligible sources and selects the master by default', async () => {
    render(<TailorPage />);

    await waitFor(() => expect(mockedFetchResumeList).toHaveBeenCalledWith(true));
    const trigger = screen.getByRole('button', { name: 'tailor.selectResume' });
    await waitFor(() => expect(trigger).toHaveTextContent('Master Title'));
    expect(trigger).toHaveTextContent('tailor.sourceMaster');

    const menu = await openSourceMenu();
    const options = within(menu).getAllByRole('menuitemradio');
    expect(options).toHaveLength(2);
    expect(menu).toHaveTextContent('Master Title');
    expect(menu).toHaveTextContent('Standalone Title');
    // Tailored and still-processing resumes are not eligible sources.
    expect(menu).not.toHaveTextContent('Tailored Title');
    expect(menu).not.toHaveTextContent('Processing Title');
  });

  it('selects the resume requested via ?source= when it is eligible', async () => {
    sourceParam = 'standalone-1';
    render(<TailorPage />);

    const trigger = await screen.findByRole('button', {
      name: 'tailor.selectResume',
    });
    await waitFor(() => expect(trigger).toHaveTextContent('Standalone Title'));
    expect(trigger).toHaveTextContent('tailor.sourceStandalone');
  });

  it('falls back to the master when ?source= points at an ineligible resume', async () => {
    sourceParam = 'tailored-1';
    render(<TailorPage />);

    const trigger = await screen.findByRole('button', {
      name: 'tailor.selectResume',
    });
    await waitFor(() => expect(trigger).toHaveTextContent('Master Title'));
  });

  it('redirects to the dashboard when no resume is eligible', async () => {
    mockedFetchResumeList.mockResolvedValue([RESUMES[2], RESUMES[3]]);
    render(<TailorPage />);

    await waitFor(() => expect(push).toHaveBeenCalledWith('/dashboard'));
  });
});
