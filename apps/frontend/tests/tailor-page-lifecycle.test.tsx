import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TailorPage from '@/app/(default)/tailor/page';

const api = vi.hoisted(() => ({
  upload: vi.fn(),
  preview: vi.fn(),
  confirm: vi.fn(),
  push: vi.fn(),
  back: vi.fn(),
  setPreview: vi.fn(),
  jobs: vi.fn(),
  improvements: vi.fn(),
  resumes: vi.fn(),
  fetchList: vi.fn(),
}));
const router = { push: api.push, back: api.back };
const t = (key: string) => key;
vi.mock('next/navigation', () => {
  // Stable reference across renders: a new object per call would make the
  // page's [router, searchParams] effect loop forever.
  const searchParams = { get: () => null };
  return {
    useRouter: () => router,
    useSearchParams: () => searchParams,
  };
});
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t }) }));
vi.mock('@/lib/api/resume', () => ({
  uploadJobDescriptions: api.upload,
  previewImproveResume: api.preview,
  confirmImproveResume: api.confirm,
  fetchResumeList: api.fetchList,
}));
vi.mock('@/lib/api/config', () => ({
  fetchPromptConfig: async () => ({ prompt_options: [], default_prompt_id: 'keywords' }),
}));
vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ setImprovedData: api.setPreview }),
}));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({
    status: { llm_configured: true },
    isLoading: false,
    incrementJobs: api.jobs,
    incrementImprovements: api.improvements,
    incrementResumes: api.resumes,
  }),
}));
vi.mock('@/components/tailor/diff-preview-modal', () => ({
  DiffPreviewModal: ({
    onConfirm,
    onReject,
    onClose,
    isConfirming,
    errorMessage,
  }: {
    onConfirm: () => void;
    onReject: () => void;
    onClose: () => void;
    isConfirming: boolean;
    errorMessage?: string;
  }) => (
    <div role="dialog">
      <button onClick={onConfirm} disabled={isConfirming}>
        Confirm preview
      </button>
      <button onClick={onReject}>Reject preview</button>
      <button onClick={onClose}>Close preview</button>
      {errorMessage && <span>{errorMessage}</span>}
    </div>
  ),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

const preview = {
  request_id: 'preview-request',
  data: {
    job_id: 'job',
    preview_id: 'preview',
    resume_id: null,
    resume_preview: { personalInfo: { name: 'Ada' } },
    improvements: [],
    diff_summary: { total_changes: 1 },
    detailed_changes: [],
  },
};
const confirmed = {
  request_id: 'confirmed-request',
  data: { job_id: 'job', resume_id: 'tailored' },
};

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  localStorage.setItem('master_resume_id', 'master');
  api.upload.mockResolvedValue('job');
  api.preview.mockResolvedValue(preview);
  api.confirm.mockResolvedValue(confirmed);
  // One eligible master whose id matches the cached localStorage master.
  api.fetchList.mockResolvedValue([
    {
      resume_id: 'master',
      filename: 'master.pdf',
      is_master: true,
      parent_id: null,
      processing_status: 'ready',
      created_at: '',
      updated_at: '',
    },
  ]);
});

async function generate() {
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: 'A software engineer role building useful tools with Python and SQL.' },
  });
  await act(async () => screen.getByRole('button', { name: 'tailor.generateTailored' }).click());
}

describe('actual tailor page transaction boundaries', () => {
  it('clears the missing-diff confirmation state after successful save', async () => {
    api.preview.mockResolvedValue({ ...preview, data: { ...preview.data, diff_summary: null } });
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    await act(async () =>
      screen.getByRole('button', { name: 'tailor.missingDiffDialog.confirmLabel' }).click()
    );
    expect(api.confirm).toHaveBeenCalledTimes(1);
    expect(api.push).toHaveBeenLastCalledWith('/resumes/tailored');
    expect(screen.queryByText('tailor.missingDiffDialog.description')).toBeNull();
    expect(screen.getByRole('button', { name: 'tailor.generateTailored' })).toBeEnabled();
  });

  it('keeps a failed preview retry distinct from confirmation and records the created job', async () => {
    api.preview.mockRejectedValueOnce(new Error('Preview offline')).mockResolvedValue(preview);
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    expect(api.jobs).toHaveBeenCalledTimes(1);
    expect(api.confirm).not.toHaveBeenCalled();
    await generate();
    expect(api.upload).toHaveBeenCalledTimes(2);
    expect(api.preview).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Confirm preview' })).toBeVisible();
  });

  it('retries confirmation with the same preview and no new job or preview call', async () => {
    api.confirm.mockRejectedValueOnce(new Error('Lost response')).mockResolvedValue(confirmed);
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    await act(async () => screen.getByRole('button', { name: 'Confirm preview' }).click());
    await act(async () => screen.getByRole('button', { name: 'Confirm preview' }).click());
    expect(api.upload).toHaveBeenCalledTimes(1);
    expect(api.preview).toHaveBeenCalledTimes(1);
    expect(api.confirm).toHaveBeenCalledTimes(2);
    expect(api.confirm.mock.calls[0]).toEqual(api.confirm.mock.calls[1]);
    expect(api.confirm.mock.calls[0][0].preview_id).toBe('preview');
    expect(api.resumes).toHaveBeenCalledTimes(1);
    expect(api.push).toHaveBeenLastCalledWith('/resumes/tailored');
  });

  it('requires explicit regeneration after rejecting a preview', async () => {
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    fireEvent.click(screen.getByRole('button', { name: 'Reject preview' }));
    expect(api.preview).toHaveBeenCalledTimes(1);
    await act(async () =>
      screen.getByRole('button', { name: 'tailor.regenerateDialog.confirmLabel' }).click()
    );
    expect(api.preview).toHaveBeenCalledTimes(2);
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('lets the user decline a preview with missing diff data without saving', async () => {
    api.preview.mockResolvedValue({ ...preview, data: { ...preview.data, diff_summary: null } });
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    expect(screen.getByText('tailor.missingDiffDialog.description')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }));
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('ignores confirmation completion after leaving the page', async () => {
    const pending = deferred<typeof confirmed>();
    api.confirm.mockReturnValue(pending.promise);
    const view = render(<TailorPage />);
    await act(async () => {});
    await generate();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm preview' }));
    view.unmount();
    await act(async () => pending.resolve(confirmed));
    expect(api.push).not.toHaveBeenCalled();
    expect(api.setPreview).not.toHaveBeenCalled();
    expect(api.resumes).not.toHaveBeenCalled();
  });

  it('retries navigation after an acknowledged confirmation without another save or counter increment', async () => {
    api.push.mockImplementationOnce(() => {
      throw new Error('Navigation unavailable');
    });
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    await act(async () => screen.getByRole('button', { name: 'Confirm preview' }).click());
    await act(async () => screen.getByRole('button', { name: 'Confirm preview' }).click());
    expect(api.confirm).toHaveBeenCalledTimes(1);
    expect(api.resumes).toHaveBeenCalledTimes(1);
    expect(api.improvements).toHaveBeenCalledTimes(1);
    expect(api.push).toHaveBeenLastCalledWith('/resumes/tailored');
  });
});

it('keeps missing-diff confirmation open while its durable request is pending', async () => {
  const pending = deferred<typeof confirmed>();
  api.confirm.mockReturnValueOnce(pending.promise);
  api.preview.mockResolvedValue({ ...preview, data: { ...preview.data, diff_summary: null } });
  render(<TailorPage />);
  await act(async () => {});
  await generate();
  fireEvent.click(screen.getByRole('button', { name: 'tailor.missingDiffDialog.confirmLabel' }));
  const cancel = screen.getByRole('button', { name: 'common.cancel' });
  expect(cancel).toBeDisabled();
  fireEvent.click(cancel);
  await act(async () => pending.resolve(confirmed));
  expect(api.resumes).toHaveBeenCalledTimes(1);
  expect(api.push).toHaveBeenLastCalledWith('/resumes/tailored');
});

it('cancels an in-flight generation and returns to the form without an error', async () => {
  // Never settles on its own: only the AbortSignal can end this call.
  api.upload.mockImplementation(
    (_descriptions: string[], _resumeId: string, signal?: AbortSignal) =>
      new Promise<never>((_resolve, reject) => {
        signal?.addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        });
      })
  );
  render(<TailorPage />);
  await act(async () => {});
  await generate();

  const cancelButton = screen.getByRole('button', { name: 'common.cancel' });
  const signal = api.upload.mock.calls[0][2] as AbortSignal;
  expect(signal).toBeInstanceOf(AbortSignal);
  expect(signal.aborted).toBe(false);

  await act(async () => cancelButton.click());

  expect(signal.aborted).toBe(true);
  expect(screen.getByRole('button', { name: 'tailor.generateTailored' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'common.cancel' })).toBeNull();
  // Let the aborted continuation flush: it must not render an error banner.
  await act(async () => {});
  expect(document.body.textContent).not.toMatch(/tailor\.errors/);

  // A fresh run is possible and gets its own, unaborted signal.
  api.upload.mockResolvedValue('job-2');
  await generate();
  expect(api.upload).toHaveBeenCalledTimes(2);
  const nextSignal = api.upload.mock.calls[1][2] as AbortSignal;
  expect(nextSignal).not.toBe(signal);
  expect(nextSignal.aborted).toBe(false);
  expect(screen.getByRole('button', { name: 'Confirm preview' })).toBeVisible();
});

it.each(['expired locally', 'rejected by server'])(
  'offers a fresh preview when confirmation is %s',
  async (mode) => {
    api.preview.mockResolvedValue({
      ...preview,
      data: {
        ...preview.data,
        preview_expires_at: mode === 'expired locally' ? '2000-01-01T00:00:00Z' : null,
      },
    });
    if (mode === 'rejected by server')
      api.confirm.mockRejectedValueOnce(
        new Error('Improve failed with status 409: Preview expired')
      );
    render(<TailorPage />);
    await act(async () => {});
    await generate();
    await act(async () => screen.getByRole('button', { name: 'Confirm preview' }).click());
    expect(screen.getByText('tailor.errors.previewUnavailable')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'tailor.regenerateDialog.confirmLabel' })
    ).toBeVisible();
    if (mode === 'expired locally') expect(api.confirm).not.toHaveBeenCalled();
    api.preview.mockResolvedValue(preview);
    await act(async () =>
      screen.getByRole('button', { name: 'tailor.regenerateDialog.confirmLabel' }).click()
    );
    expect(api.preview).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Confirm preview' })).toBeEnabled();
  }
);
