import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResumeData } from '@/components/dashboard/resume-component';

const fetchResume = vi.fn();
const updateResume = vi.fn();
const updateCoverLetter = vi.fn();
const updateOutreachMessage = vi.fn();
const downloadCoverLetterPdf = vi.fn();
const generateCoverLetter = vi.fn();
const generateOutreachMessage = vi.fn();
const generateInterviewPrep = vi.fn();
const fetchJobDescription = vi.fn();
const push = vi.fn();

let currentSearch = 'id=a&tab=cover-letter';

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(currentSearch),
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/api/resume', () => ({
  fetchResume: (...args: unknown[]) => fetchResume(...args),
  updateResume: (...args: unknown[]) => updateResume(...args),
  updateCoverLetter: (...args: unknown[]) => updateCoverLetter(...args),
  updateOutreachMessage: (...args: unknown[]) => updateOutreachMessage(...args),
  downloadCoverLetterPdf: (...args: unknown[]) => downloadCoverLetterPdf(...args),
  downloadResumePdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => ''),
  getCoverLetterPdfUrl: vi.fn(() => ''),
  generateCoverLetter: (...args: unknown[]) => generateCoverLetter(...args),
  generateOutreachMessage: (...args: unknown[]) => generateOutreachMessage(...args),
  generateInterviewPrep: (...args: unknown[]) => generateInterviewPrep(...args),
  fetchJobDescription: (...args: unknown[]) => fetchJobDescription(...args),
}));

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en', contentLanguage: 'en' }),
}));

vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ improvedData: null }),
}));

vi.mock('@/components/preview', () => ({ PaginatedPreview: () => null }));
vi.mock('@/components/builder/resume-form', () => ({ ResumeForm: () => null }));
vi.mock('@/components/builder/formatting-controls', () => ({ FormattingControls: () => null }));
vi.mock('@/components/builder/cover-letter-preview', () => ({ CoverLetterPreview: () => null }));
vi.mock('@/components/builder/outreach-preview', () => ({ OutreachPreview: () => null }));
vi.mock('@/components/builder/jd-comparison-view', () => ({ JDComparisonView: () => null }));
vi.mock('@/components/builder/regenerate-wizard', () => ({ RegenerateWizard: () => null }));
vi.mock('@/hooks/use-regenerate-wizard', () => ({
  useRegenerateWizard: () => ({ step: 'idle', reset: vi.fn(), startRegenerate: vi.fn() }),
}));
vi.mock('@/components/builder/generate-prompt', () => ({
  GeneratePrompt: ({
    type,
    onGenerate,
    showJobDescription,
    jobDescription,
    onJobDescriptionChange,
    onGenerateWithJobDescription,
  }: {
    type: string;
    onGenerate: () => void;
    showJobDescription?: boolean;
    jobDescription?: string;
    onJobDescriptionChange?: (value: string) => void;
    onGenerateWithJobDescription?: () => void;
  }) => (
    <div>
      <button onClick={onGenerate}>generate-{type}</button>
      {showJobDescription && (
        <>
          <textarea
            aria-label={`${type}-job-description`}
            value={jobDescription}
            onChange={(event) => onJobDescriptionChange?.(event.target.value)}
          />
          <button onClick={onGenerateWithJobDescription}>generate-{type}-with-jd</button>
        </>
      )}
    </div>
  ),
}));
vi.mock('@/components/builder/interview-prep-view', () => ({
  InterviewPrepView: ({
    interviewPrep,
    onGenerate,
    showJobDescription,
    jobDescription,
    onJobDescriptionChange,
    onGenerateWithJobDescription,
  }: {
    interviewPrep: unknown;
    onGenerate: () => void;
    showJobDescription?: boolean;
    jobDescription?: string;
    onJobDescriptionChange?: (value: string) => void;
    onGenerateWithJobDescription?: () => void;
  }) => (
    <div>
      <output data-testid="interview-prep">{interviewPrep ? 'present' : 'empty'}</output>
      <button onClick={onGenerate}>generate-interview-prep</button>
      {showJobDescription && (
        <>
          <textarea
            aria-label="interview-prep-job-description"
            value={jobDescription}
            onChange={(event) => onJobDescriptionChange?.(event.target.value)}
          />
          <button onClick={onGenerateWithJobDescription}>generate-interview-prep-with-jd</button>
        </>
      )}
    </div>
  ),
}));
vi.mock('@/lib/utils/download', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils/download')>();
  return {
    ...actual,
    downloadBlobAsFile: vi.fn(),
    openUrlInNewTab: vi.fn(() => false),
  };
});

const RESUME = {
  personalInfo: { name: 'Ada', email: 'ada@example.com' },
  summary: 'Synthetic resume',
  workExperience: [],
  education: [],
  personalProjects: [],
  additional: {},
} satisfies ResumeData;

const response = (
  attachments: {
    cover_letter?: string | null;
    outreach_message?: string | null;
    interview_prep?: unknown;
  } = {}
) => ({
  processed_resume: RESUME,
  raw_resume: { processing_status: 'ready' },
  parent_id: 'master',
  title: 'Synthetic @ Example',
  ...attachments,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const importBuilder = async () => {
  // Mirror the real (default) layout, which wraps the app in ToastProvider.
  // Both modules must come from the SAME registry instance: afterEach calls
  // vi.resetModules(), so a statically imported ToastProvider would hold a
  // different React context object than the useToast() inside the
  // dynamically re-imported builder.
  const [{ ResumeBuilder }, { ToastProvider }] = await Promise.all([
    import('@/components/builder/resume-builder'),
    import('@/components/ui/toast'),
  ]);
  return function BuilderWithToast() {
    return (
      <ToastProvider>
        <ResumeBuilder />
      </ToastProvider>
    );
  };
};

beforeEach(() => {
  currentSearch = 'id=a&tab=cover-letter';
  localStorage.clear();
  vi.clearAllMocks();
  updateResume.mockResolvedValue({ processed_resume: RESUME });
  updateCoverLetter.mockResolvedValue(undefined);
  updateOutreachMessage.mockResolvedValue(undefined);
  downloadCoverLetterPdf.mockResolvedValue(new Blob(['pdf']));
  fetchJobDescription.mockResolvedValue({ job_id: 'job', content: 'Synthetic job' });
});

afterEach(() => {
  cleanup();
  vi.resetModules();
});

describe('builder attachment ownership', () => {
  it.each([
    ['cover-letter', 'cover_letter', 'ALICE COVER'],
    ['outreach', 'outreach_message', 'ALICE OUTREACH'],
  ] as const)('clears %s when the next document has no value', async (tab, field, oldValue) => {
    fetchResume.mockImplementation((id: string) =>
      Promise.resolve(id === 'a' ? response({ [field]: oldValue }) : response({ [field]: null }))
    );
    currentSearch = `id=a&tab=${tab}`;
    const Builder = await importBuilder();
    const view = render(<Builder />);
    expect(await screen.findByDisplayValue(oldValue)).toBeInTheDocument();

    currentSearch = `id=b&tab=${tab}`;
    view.rerender(<Builder />);

    await waitFor(() => expect(screen.queryByDisplayValue(oldValue)).not.toBeInTheDocument());
    expect(screen.getAllByRole('button', { name: `generate-${tab}` })).not.toHaveLength(0);
  });

  it.each(['cover-letter', 'outreach', 'interview-prep'] as const)(
    'ignores a late %s generation result after changing documents',
    async (kind) => {
      const pending = deferred<unknown>();
      fetchResume.mockResolvedValue(response());
      const generate =
        kind === 'cover-letter'
          ? generateCoverLetter
          : kind === 'outreach'
            ? generateOutreachMessage
            : generateInterviewPrep;
      generate.mockReturnValue(pending.promise);
      currentSearch = `id=a&tab=${kind}`;
      const Builder = await importBuilder();
      const view = render(<Builder />);
      const buttons = await screen.findAllByRole('button', { name: `generate-${kind}` });
      if (kind === 'interview-prep') {
        await waitFor(() => expect(fetchJobDescription).toHaveBeenCalledWith('a'));
      }
      await act(async () => buttons.at(-1)?.click());
      expect(generate).toHaveBeenCalledWith('a', '');

      currentSearch = `id=b&tab=${kind}`;
      view.rerender(<Builder />);
      await act(async () => {
        pending.resolve(kind === 'interview-prep' ? { questions: [] } : 'GENERATED FOR A');
      });

      if (kind === 'interview-prep') {
        expect(
          (await screen.findAllByTestId('interview-prep')).every(
            (item) => item.textContent === 'empty'
          )
        ).toBe(true);
      } else {
        expect(screen.queryByDisplayValue('GENERATED FOR A')).not.toBeInTheDocument();
      }
    }
  );

  it('ignores a late generation error after changing documents', async () => {
    const pending = deferred<string>();
    fetchResume.mockResolvedValue(response());
    generateCoverLetter.mockReturnValue(pending.promise);
    const Builder = await importBuilder();
    const view = render(<Builder />);
    const button = (await screen.findAllByRole('button', { name: 'generate-cover-letter' }))[0];
    await act(async () => button.click());

    currentSearch = 'id=b&tab=cover-letter';
    view.rerender(<Builder />);
    await act(async () => pending.reject(new Error('late failure for A')));

    expect(screen.queryByText('builder.alerts.coverLetterGenerateFailed')).toBeNull();
    expect(screen.getAllByRole('button', { name: 'generate-cover-letter' })).not.toHaveLength(0);
  });
});

describe('builder attachment persistence', () => {
  it('ignores a late save completion after changing documents', async () => {
    const save = deferred<void>();
    fetchResume.mockImplementation((id: string) =>
      Promise.resolve(response({ cover_letter: id === 'a' ? 'A COVER' : 'B COVER' }))
    );
    updateCoverLetter.mockReturnValue(save.promise);
    const Builder = await importBuilder();
    const view = render(<Builder />);
    fireEvent.change(await screen.findByDisplayValue('A COVER'), {
      target: { value: 'A EDIT' },
    });
    await act(async () => screen.getByRole('button', { name: 'common.save' }).click());

    currentSearch = 'id=b&tab=cover-letter';
    view.rerender(<Builder />);
    expect(await screen.findByDisplayValue('B COVER')).toBeInTheDocument();
    await act(async () => save.resolve());

    expect(screen.getByDisplayValue('B COVER')).toBeInTheDocument();
    expect(screen.queryByText('builder.alerts.coverLetterSaveSuccess')).toBeNull();
  });

  it('saves edited cover content before requesting its PDF', async () => {
    const save = deferred<void>();
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
    updateCoverLetter.mockReturnValue(save.promise);
    const Builder = await importBuilder();
    render(<Builder />);
    fireEvent.change(await screen.findByDisplayValue('SERVER COVER'), {
      target: { value: 'EDITED COVER' },
    });

    await act(async () => screen.getByRole('button', { name: 'common.download' }).click());
    expect(updateCoverLetter).toHaveBeenCalledWith('a', 'EDITED COVER');
    expect(downloadCoverLetterPdf).not.toHaveBeenCalled();

    await act(async () => save.resolve());
    expect(downloadCoverLetterPdf).toHaveBeenCalledWith('a', 'A4', 'en');
  });

  it('aborts cover export and retains its draft when the save fails', async () => {
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
    updateCoverLetter.mockRejectedValue(new Error('save unavailable'));
    const Builder = await importBuilder();
    render(<Builder />);
    fireEvent.change(await screen.findByDisplayValue('SERVER COVER'), {
      target: { value: 'RECOVERABLE COVER' },
    });

    await act(async () => screen.getByRole('button', { name: 'common.download' }).click());

    expect(downloadCoverLetterPdf).not.toHaveBeenCalled();
    expect(screen.getByText('builder.alerts.coverLetterSaveFailed')).toBeInTheDocument();
    expect(localStorage.getItem('resume_builder_attachment_draft:a')).toContain(
      'RECOVERABLE COVER'
    );
  });

  it('keeps a newer same-document edit dirty when an older cover save completes', async () => {
    const save = deferred<void>();
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
    updateCoverLetter.mockReturnValue(save.promise);
    const Builder = await importBuilder();
    render(<Builder />);
    const editor = await screen.findByDisplayValue('SERVER COVER');
    fireEvent.change(editor, { target: { value: 'FIRST EDIT' } });
    await act(async () => screen.getByRole('button', { name: 'common.save' }).click());
    fireEvent.change(editor, { target: { value: 'NEWER EDIT' } });
    await act(async () => save.resolve());

    expect(localStorage.getItem('resume_builder_attachment_draft:a')).toContain('NEWER EDIT');
    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
  });

  it('saves the latest cover revision before exporting when editing continues during save', async () => {
    const firstSave = deferred<void>();
    const latestSave = deferred<void>();
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
    updateCoverLetter
      .mockReturnValueOnce(firstSave.promise)
      .mockReturnValueOnce(latestSave.promise);
    const Builder = await importBuilder();
    render(<Builder />);
    const editor = await screen.findByDisplayValue('SERVER COVER');
    fireEvent.change(editor, { target: { value: 'FIRST EDIT' } });

    await act(async () => screen.getByRole('button', { name: 'common.download' }).click());
    fireEvent.change(editor, { target: { value: 'NEWER EDIT' } });
    await act(async () => firstSave.resolve());

    expect(updateCoverLetter).toHaveBeenNthCalledWith(1, 'a', 'FIRST EDIT');
    expect(updateCoverLetter).toHaveBeenNthCalledWith(2, 'a', 'NEWER EDIT');
    expect(downloadCoverLetterPdf).not.toHaveBeenCalled();

    await act(async () => latestSave.resolve());
    expect(downloadCoverLetterPdf).toHaveBeenCalledWith('a', 'A4', 'en');
  });

  it('serializes an existing cover save ahead of the export flush', async () => {
    const firstSave = deferred<void>();
    const latestSave = deferred<void>();
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
    updateCoverLetter
      .mockReturnValueOnce(firstSave.promise)
      .mockReturnValueOnce(latestSave.promise);
    const Builder = await importBuilder();
    render(<Builder />);
    const editor = await screen.findByDisplayValue('SERVER COVER');
    fireEvent.change(editor, { target: { value: 'FIRST EDIT' } });
    await act(async () => screen.getByRole('button', { name: 'common.save' }).click());
    fireEvent.change(editor, { target: { value: 'NEWER EDIT' } });
    await act(async () => screen.getByRole('button', { name: 'common.download' }).click());

    expect(updateCoverLetter).toHaveBeenCalledTimes(1);
    await act(async () => firstSave.resolve());
    expect(updateCoverLetter).toHaveBeenNthCalledWith(2, 'a', 'NEWER EDIT');
    expect(downloadCoverLetterPdf).not.toHaveBeenCalled();

    await act(async () => latestSave.resolve());
    expect(downloadCoverLetterPdf).toHaveBeenCalledWith('a', 'A4', 'en');
  });

  it('flushes outreach before Back and offers local-draft leave when it fails', async () => {
    currentSearch = 'id=a&tab=outreach';
    fetchResume.mockResolvedValue(response({ outreach_message: 'SERVER OUTREACH' }));
    updateOutreachMessage.mockRejectedValue(new Error('offline'));
    const Builder = await importBuilder();
    render(<Builder />);
    fireEvent.change(await screen.findByDisplayValue('SERVER OUTREACH'), {
      target: { value: 'RECOVERABLE OUTREACH' },
    });

    await act(async () => screen.getByRole('button', { name: 'nav.backToDashboard' }).click());

    expect(updateOutreachMessage).toHaveBeenCalledWith('a', 'RECOVERABLE OUTREACH');
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByText('builder.leaveWithLocalDraft.description')).toBeInTheDocument();
    expect(localStorage.getItem('resume_builder_attachment_draft:a')).toContain(
      'RECOVERABLE OUTREACH'
    );
  });

  it('warns that attachment edits have no backup when browser storage and save both fail', async () => {
    currentSearch = 'id=a&tab=outreach';
    fetchResume.mockResolvedValue(response({ outreach_message: 'SERVER OUTREACH' }));
    updateOutreachMessage.mockRejectedValue(new Error('offline'));
    const Builder = await importBuilder();
    render(<Builder />);
    const input = await screen.findByDisplayValue('SERVER OUTREACH');
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Quota exceeded', 'QuotaExceededError');
    });
    try {
      fireEvent.change(input, { target: { value: 'UNSAVED OUTREACH' } });
      await act(async () => screen.getByRole('button', { name: 'nav.backToDashboard' }).click());
      expect(screen.getByText('builder.leaveWithoutDraft.description')).toBeInTheDocument();
      expect(screen.getByDisplayValue('UNSAVED OUTREACH')).toBeInTheDocument();
      expect(screen.queryByText('builder.leaveWithLocalDraft.description')).not.toBeInTheDocument();
      expect(push).not.toHaveBeenCalled();
    } finally {
      storage.mockRestore();
    }
  });

  it('requires consent before restoring a resume-scoped attachment draft', async () => {
    localStorage.setItem(
      'resume_builder_attachment_draft:a',
      JSON.stringify({
        resumeId: 'a',
        updatedAt: Date.now(),
        coverLetter: 'LOCAL COVER',
        outreachMessage: '',
      })
    );
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
    const Builder = await importBuilder();
    render(<Builder />);

    expect(await screen.findByDisplayValue('SERVER COVER')).toBeInTheDocument();
    await act(async () =>
      screen.getByRole('button', { name: 'builder.draftRecovery.restoreDraft' }).click()
    );

    expect(screen.getByDisplayValue('LOCAL COVER')).toBeInTheDocument();
    expect(localStorage.getItem('resume_builder_attachment_draft:a')).toContain('LOCAL COVER');
  });
});

it('does not expose attachment state from an unusable resume response', async () => {
  fetchResume.mockResolvedValue({
    ...response({ cover_letter: 'UNUSABLE COVER' }),
    processed_resume: null,
    raw_resume: { processing_status: 'processing' },
  });
  const Builder = await importBuilder();
  render(<Builder />);
  await waitFor(() => expect(fetchResume).toHaveBeenCalled());
  expect(screen.queryByDisplayValue('UNUSABLE COVER')).not.toBeInTheDocument();
});

it('waits for an earlier cover save even after reverting to the acknowledged baseline', async () => {
  const first = deferred<void>();
  const latest = deferred<void>();
  fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER COVER' }));
  updateCoverLetter.mockReturnValueOnce(first.promise).mockReturnValueOnce(latest.promise);
  const Builder = await importBuilder();
  render(<Builder />);
  const editor = await screen.findByDisplayValue('SERVER COVER');
  fireEvent.change(editor, { target: { value: 'INTERMEDIATE' } });
  await act(async () => screen.getByRole('button', { name: 'common.save' }).click());
  fireEvent.change(editor, { target: { value: 'SERVER COVER' } });
  await act(async () => screen.getByRole('button', { name: 'common.download' }).click());
  expect(downloadCoverLetterPdf).not.toHaveBeenCalled();
  await act(async () => first.resolve());
  expect(updateCoverLetter).toHaveBeenNthCalledWith(2, 'a', 'SERVER COVER');
  expect(downloadCoverLetterPdf).not.toHaveBeenCalled();
  await act(async () => latest.resolve());
  expect(downloadCoverLetterPdf).toHaveBeenCalledOnce();
});

it.each(['cover-letter', 'outreach'])(
  'serializes and converges %s edits before Back',
  async (tab) => {
    const first = deferred<void>();
    const second = deferred<void>();
    const third = deferred<void>();
    const save = tab === 'cover-letter' ? updateCoverLetter : updateOutreachMessage;
    currentSearch = `id=a&tab=${tab}`;
    fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER', outreach_message: 'SERVER' }));
    save
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(third.promise);
    const Builder = await importBuilder();
    render(<Builder />);
    const editor = await screen.findByDisplayValue('SERVER');
    fireEvent.change(editor, { target: { value: 'FIRST' } });
    await act(async () => screen.getByRole('button', { name: 'common.save' }).click());
    fireEvent.change(editor, { target: { value: 'SECOND' } });
    await act(async () => screen.getByRole('button', { name: 'nav.backToDashboard' }).click());
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve());
    expect(save).toHaveBeenNthCalledWith(2, 'a', 'SECOND');
    fireEvent.change(editor, { target: { value: 'FINAL' } });
    await act(async () => second.resolve());
    expect(push).not.toHaveBeenCalled();
    expect(save).toHaveBeenNthCalledWith(3, 'a', 'FINAL');
    await act(async () => third.resolve());
    expect(push).toHaveBeenCalledWith('/dashboard');
  }
);

it.each(['cover-letter', 'outreach'])('orders %s generation after prior saves', async (tab) => {
  const first = deferred<void>();
  const generated = deferred<string>();
  const save = tab === 'cover-letter' ? updateCoverLetter : updateOutreachMessage;
  const generate = tab === 'cover-letter' ? generateCoverLetter : generateOutreachMessage;
  currentSearch = `id=a&tab=${tab}`;
  fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER', outreach_message: 'SERVER' }));
  save.mockReturnValueOnce(first.promise);
  generate.mockReturnValueOnce(generated.promise);
  const Builder = await importBuilder();
  render(<Builder />);
  fireEvent.change(await screen.findByDisplayValue('SERVER'), { target: { value: 'EDIT' } });
  await act(async () => screen.getByRole('button', { name: 'common.save' }).click());
  fireEvent.click(
    screen.getByRole('button', {
      name: tab === 'cover-letter' ? 'coverLetter.regenerate' : 'outreach.regenerate',
    })
  );
  await act(async () =>
    within(screen.getByRole('dialog'))
      .getByRole('button', {
        name: tab === 'cover-letter' ? 'coverLetter.regenerate' : 'outreach.regenerate',
      })
      .click()
  );
  expect(generate).not.toHaveBeenCalled();
  await act(async () => first.resolve());
  expect(generate).toHaveBeenCalledOnce();
  await act(async () => generated.resolve('GENERATED'));
  expect(screen.getByDisplayValue('GENERATED')).toBeInTheDocument();
  const unload = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(false);
});

describe.each(['cover-letter', 'outreach'] as const)('%s save queued during generation', (tab) => {
  it.each(['unchanged', 'edit-before-save', 'edit-after-save'] as const)(
    'keeps server and editor converged for %s content',
    async (editTiming) => {
      const generated = deferred<string>();
      const save = tab === 'cover-letter' ? updateCoverLetter : updateOutreachMessage;
      const generate = tab === 'cover-letter' ? generateCoverLetter : generateOutreachMessage;
      const regenerateLabel =
        tab === 'cover-letter' ? 'coverLetter.regenerate' : 'outreach.regenerate';
      let serverContent = 'SERVER';
      currentSearch = `id=a&tab=${tab}`;
      fetchResume.mockResolvedValue(
        response({ cover_letter: serverContent, outreach_message: serverContent })
      );
      generate.mockImplementationOnce(async () => {
        serverContent = await generated.promise;
        return serverContent;
      });
      save.mockImplementation(async (_id: string, content: string) => {
        serverContent = content;
      });
      const Builder = await importBuilder();
      render(<Builder />);
      const editor = await screen.findByDisplayValue('SERVER');
      fireEvent.click(screen.getByRole('button', { name: regenerateLabel }));
      await act(async () =>
        within(screen.getByRole('dialog')).getByRole('button', { name: regenerateLabel }).click()
      );
      expect(generate).toHaveBeenCalledWith('a', '');
      expect(editor).toBeEnabled();
      expect(screen.getByRole('button', { name: 'common.save' })).toBeEnabled();
      if (editTiming === 'edit-before-save') {
        fireEvent.change(editor, { target: { value: 'LATEST EDIT' } });
      }
      await act(async () => screen.getByRole('button', { name: 'common.save' }).click());
      expect(save).not.toHaveBeenCalled();
      if (editTiming === 'edit-after-save') {
        fireEvent.change(editor, { target: { value: 'LATEST EDIT' } });
      }
      await act(async () => generated.resolve('GENERATED'));

      const expected = editTiming === 'unchanged' ? 'GENERATED' : 'LATEST EDIT';
      expect(serverContent).toBe(expected);
      expect(screen.getByRole('textbox')).toHaveValue(expected);
      const unload = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(unload);
      expect(unload.defaultPrevented).toBe(false);
    }
  );
});

it('retains a matching restored attachment backup when replacement storage writes fail', async () => {
  localStorage.setItem(
    'resume_builder_attachment_draft:a',
    JSON.stringify({
      resumeId: 'a',
      updatedAt: Date.now(),
      coverLetter: 'RECOVERABLE',
      outreachMessage: '',
    })
  );
  fetchResume.mockResolvedValue(response({ cover_letter: 'SERVER' }));
  updateCoverLetter.mockRejectedValue(new Error('offline'));
  const Builder = await importBuilder();
  render(<Builder />);
  await screen.findByDisplayValue('SERVER');
  const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('quota');
  });
  try {
    fireEvent.click(screen.getByRole('button', { name: 'builder.draftRecovery.restoreDraft' }));
    await act(async () => screen.getByRole('button', { name: 'nav.backToDashboard' }).click());
    expect(screen.getByText('builder.leaveWithLocalDraft.description')).toBeInTheDocument();
    expect(screen.getByDisplayValue('RECOVERABLE')).toBeInTheDocument();
  } finally {
    storage.mockRestore();
  }
});

describe('standalone resume generation entry points', () => {
  it('keeps content tabs enabled without stored content and reaches outreach generation', async () => {
    // Standalone resume: no parent_id and none of the AI attachments stored.
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: 'Standalone resume',
    });
    currentSearch = 'id=a&tab=outreach';
    const Builder = await importBuilder();
    render(<Builder />);

    const coverTab = await screen.findByRole('button', {
      name: 'builder.previewTabs.coverLetter',
    });
    const outreachTab = screen.getByRole('button', {
      name: 'builder.previewTabs.outreach',
    });
    expect(coverTab).not.toBeDisabled();
    expect(outreachTab).not.toBeDisabled();
    // JD matching fundamentally needs a stored job, so it stays locked.
    expect(screen.getByRole('button', { name: 'builder.previewTabs.jdMatch' })).toBeDisabled();

    // The empty state collapses the two-column split into one full-width
    // generation card, so a single generate button exists.
    const prompts = await screen.findAllByRole('button', { name: 'generate-outreach' });
    expect(prompts).toHaveLength(1);
    await act(async () => prompts[0].click());

    await waitFor(() => expect(generateOutreachMessage).toHaveBeenCalledWith('a', ''));
  });

  it.each([
    ['cover-letter', 'generate-cover-letter', 'builder.leftPanel.coverLetterEditor'],
    ['outreach', 'generate-outreach', 'builder.leftPanel.outreachEditor'],
    ['interview-prep', 'generate-interview-prep', 'builder.leftPanel.interviewPrep'],
  ] as const)(
    'collapses the split into a single full-width %s generation card',
    async (tab, generateButton, leftPanelHeader) => {
      fetchResume.mockResolvedValue({
        processed_resume: RESUME,
        raw_resume: { processing_status: 'ready' },
        title: 'Standalone resume',
      });
      currentSearch = `id=a&tab=${tab}`;
      const Builder = await importBuilder();
      render(<Builder />);

      // Exactly one generation entry, centered in the full-width panel.
      const buttons = await screen.findAllByRole('button', { name: generateButton });
      expect(buttons).toHaveLength(1);
      // The two-column editor chrome is not rendered in the empty state.
      expect(screen.queryByText(leftPanelHeader)).not.toBeInTheDocument();
    }
  );

  it('shows generated interview prep as a single full-width read-only view', async () => {
    fetchResume.mockResolvedValue(response({ interview_prep: { role_fit_analysis: ['Ready'] } }));
    currentSearch = 'id=a&tab=interview-prep';
    const Builder = await importBuilder();
    render(<Builder />);

    await waitFor(() => {
      expect(screen.getAllByTestId('interview-prep')).toHaveLength(1);
    });
    expect(screen.getByTestId('interview-prep')).toHaveTextContent('present');
    expect(screen.queryByText('builder.leftPanel.interviewPrep')).not.toBeInTheDocument();
  });

  it('hides the ad-hoc JD input on tailored resumes', async () => {
    // The default fixture carries parent_id, so it is a tailored resume whose
    // stored job already drives generation.
    fetchResume.mockResolvedValue(response());
    currentSearch = 'id=a&tab=outreach';
    const Builder = await importBuilder();
    render(<Builder />);

    await screen.findAllByRole('button', { name: 'generate-outreach' });
    expect(screen.queryByLabelText('outreach-job-description')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'generate-outreach-with-jd' })
    ).not.toBeInTheDocument();
  });

  it.each([
    ['cover-letter', 'cover-letter', generateCoverLetter],
    ['outreach', 'outreach', generateOutreachMessage],
  ] as const)(
    'sends the pasted JD for role-targeted %s generation on a standalone resume',
    async (tab, promptType, generate) => {
      fetchResume.mockResolvedValue({
        processed_resume: RESUME,
        raw_resume: { processing_status: 'ready' },
        title: 'Standalone resume',
      });
      currentSearch = `id=a&tab=${tab}`;
      const Builder = await importBuilder();
      render(<Builder />);

      const textboxes = await screen.findAllByLabelText(`${promptType}-job-description`);
      fireEvent.change(textboxes[0], { target: { value: '  Need Kubernetes and FastAPI  ' } });
      const withJdButtons = await screen.findAllByRole('button', {
        name: `generate-${promptType}-with-jd`,
      });
      await act(async () => withJdButtons[0].click());

      await waitFor(() =>
        expect(generate).toHaveBeenCalledWith('a', 'Need Kubernetes and FastAPI')
      );
    }
  );

  it('passes an empty JD when standalone generation runs without a pasted JD', async () => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: 'Standalone resume',
    });
    currentSearch = 'id=a&tab=outreach';
    const Builder = await importBuilder();
    render(<Builder />);

    const prompts = await screen.findAllByRole('button', { name: 'generate-outreach' });
    await act(async () => prompts[0].click());

    await waitFor(() => expect(generateOutreachMessage).toHaveBeenCalledWith('a', ''));
    expect(fetchJobDescription).not.toHaveBeenCalled();
  });

  it('sends the pasted JD for role-targeted interview prep on a standalone resume', async () => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: 'Standalone resume',
    });
    currentSearch = 'id=a&tab=interview-prep';
    const Builder = await importBuilder();
    render(<Builder />);

    const textboxes = await screen.findAllByLabelText('interview-prep-job-description');
    fireEvent.change(textboxes[0], { target: { value: 'Need Kubernetes' } });
    const withJdButtons = await screen.findAllByRole('button', {
      name: 'generate-interview-prep-with-jd',
    });
    await act(async () => withJdButtons[0].click());

    await waitFor(() => expect(generateInterviewPrep).toHaveBeenCalledWith('a', 'Need Kubernetes'));
  });

  it('uses the JD edited in the regenerate dialog for standalone regeneration', async () => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: 'Standalone resume',
      cover_letter: 'EXISTING LETTER',
    });
    currentSearch = 'id=a&tab=cover-letter';
    const Builder = await importBuilder();
    render(<Builder />);
    await screen.findByDisplayValue('EXISTING LETTER');

    // With stored content the empty state is gone; the toolbar opens the dialog.
    fireEvent.click(screen.getByRole('button', { name: 'coverLetter.regenerate' }));
    const dialog = await screen.findByRole('dialog');
    const jdTextarea = within(dialog).getByLabelText('builder.generatePrompt.jobDescriptionLabel');
    fireEvent.change(jdTextarea, { target: { value: '  Need Kubernetes  ' } });
    await act(async () =>
      within(dialog).getByRole('button', { name: 'coverLetter.regenerate' }).click()
    );

    await waitFor(() => expect(generateCoverLetter).toHaveBeenCalledWith('a', 'Need Kubernetes'));
  });

  it('omits the JD textarea from the regenerate dialog on tailored resumes', async () => {
    fetchResume.mockResolvedValue(response({ cover_letter: 'EXISTING LETTER' }));
    currentSearch = 'id=a&tab=cover-letter';
    const Builder = await importBuilder();
    render(<Builder />);
    await screen.findByDisplayValue('EXISTING LETTER');

    fireEvent.click(screen.getByRole('button', { name: 'coverLetter.regenerate' }));
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).queryByLabelText('builder.generatePrompt.jobDescriptionLabel')
    ).not.toBeInTheDocument();
  });
});
