import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TailorPage from '@/app/(default)/tailor/page';

const push = vi.fn();
let sourceParam: string | null = 'standalone-1';
const searchParams = { get: (key: string) => (key === 'source' ? sourceParam : null) };

const api = vi.hoisted(() => ({
  upload: vi.fn(),
  preview: vi.fn(),
  confirm: vi.fn(),
  fetchList: vi.fn(),
}));

const router = { push, back: vi.fn() };
vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useSearchParams: () => searchParams,
}));
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));
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
  useOperationOwner: () => ({ begin: () => 1, isCurrent: () => true, invalidate: vi.fn() }),
}));
vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ setImprovedData: vi.fn() }),
}));
vi.mock('@/components/tailor/diff-preview-modal', () => ({
  DiffPreviewModal: ({ onConfirm }: { onConfirm: () => void }) => (
    <div role="dialog">
      <button onClick={onConfirm}>Confirm preview</button>
    </div>
  ),
}));
vi.mock('@/components/tailor/ats-score-card', () => ({ ATSScoreCard: () => null }));
vi.mock('@/components/ui/confirm-dialog', () => ({ ConfirmDialog: () => null }));
vi.mock('@/lib/api/config', () => ({
  fetchPromptConfig: vi
    .fn()
    .mockResolvedValue({ prompt_options: [], default_prompt_id: 'keywords' }),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResumeList: api.fetchList,
  uploadJobDescriptions: api.upload,
  previewImproveResume: api.preview,
  confirmImproveResume: api.confirm,
}));

const previewResult = {
  request_id: 'req',
  data: {
    job_id: 'job-1',
    preview_id: 'preview-1',
    preview_expires_at: '2099-01-01T00:00:00Z',
    resume_id: null,
    resume_preview: { personalInfo: { name: 'Ada' } },
    improvements: [],
    diff_summary: { total_changes: 1 },
    detailed_changes: [{ lineNumber: 1, suggestion: 'x' }],
  },
};

describe('tailor confirm payload with ?source=', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sourceParam = 'standalone-1';
    api.fetchList.mockResolvedValue([
      {
        resume_id: 'master-1',
        filename: 'm.pdf',
        is_master: true,
        parent_id: null,
        processing_status: 'ready',
        created_at: '',
        updated_at: '',
      },
      {
        resume_id: 'standalone-1',
        filename: 's.pdf',
        is_master: false,
        parent_id: null,
        processing_status: 'ready',
        created_at: '',
        updated_at: '',
      },
    ]);
    api.upload.mockResolvedValue('job-1');
    api.preview.mockResolvedValue(previewResult);
    api.confirm.mockResolvedValue({
      request_id: 'c',
      data: { job_id: 'job-1', resume_id: 'tailored-1' },
    });
  });

  it('confirms against the standalone source id from the query param', async () => {
    render(<TailorPage />);
    const trigger = await screen.findByRole('button', { name: 'tailor.selectResume' });
    await waitFor(() => expect(trigger).toHaveTextContent('s.pdf'));

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'A software engineer role building useful tools with Python and SQL.' },
    });
    await act(async () => screen.getByRole('button', { name: 'tailor.generateTailored' }).click());
    await screen.findByRole('dialog');
    await act(async () => screen.getByRole('button', { name: 'Confirm preview' }).click());

    await waitFor(() => expect(api.confirm).toHaveBeenCalledTimes(1));
    const payload = api.confirm.mock.calls[0][0];
    console.log(
      'CONFIRM PAYLOAD:',
      JSON.stringify({ ...payload, improved_data: '<...>' }, null, 2)
    );
    expect(payload.resume_id).toBe('standalone-1');
    expect(payload.job_id).toBe('job-1');
    expect(payload.preview_id).toBe('preview-1');
  });
});
