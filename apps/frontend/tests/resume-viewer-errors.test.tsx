import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ResumeViewerPage from '@/app/(default)/resumes/[id]/page';
import {
  deleteResume,
  downloadResumeDocx,
  downloadResumePdf,
  fetchResume,
  renameResume,
  retryProcessing,
} from '@/lib/api/resume';
import { downloadBlobAsFile, openUrlInNewTab } from '@/lib/utils/download';

const route = vi.hoisted(() => ({ resumeId: 'resume-123' }));
const push = vi.fn();
const decrementResumes = vi.fn();
const setHasMasterResume = vi.fn();
const translate = (key: string) => key;

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: route.resumeId }),
}));
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: translate }) }));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ decrementResumes, setHasMasterResume }),
}));
vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en' }),
}));
vi.mock('@/components/enrichment/enrichment-modal', () => ({ EnrichmentModal: () => null }));
vi.mock('@/components/dashboard/resume-component', () => ({ default: () => null }));
vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  deleteResume: vi.fn(),
  retryProcessing: vi.fn(),
  renameResume: vi.fn(),
  downloadResumePdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => 'https://example.invalid/pdf'),
  downloadResumeDocx: vi.fn(),
  getResumeDocxUrl: vi.fn(() => 'https://example.invalid/docx'),
}));
vi.mock('@/lib/utils/download', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils/download')>();
  return {
    ...actual,
    downloadBlobAsFile: vi.fn(),
    openUrlInNewTab: vi.fn(() => false),
  };
});

const mockedFetch = vi.mocked(fetchResume);
const mockedDownload = vi.mocked(downloadResumePdf);
const mockedDownloadDocx = vi.mocked(downloadResumeDocx);
const mockedSaveBlob = vi.mocked(downloadBlobAsFile);
const mockedRename = vi.mocked(renameResume);
const mockedDelete = vi.mocked(deleteResume);

beforeEach(() => {
  vi.clearAllMocks();
  route.resumeId = 'resume-123';
  localStorage.clear();
  mockedFetch.mockResolvedValue({
    title: 'Original title',
    processed_resume: { personalInfo: { name: 'Ada' } },
    raw_resume: { processing_status: 'ready' },
  } as Awaited<ReturnType<typeof fetchResume>>);
});

describe('resume viewer operation errors', () => {
  it.each([
    new Error('HTTP 500 rendering failed'),
    new Error('Request timed out'),
    new TypeError('Failed to fetch'),
  ])('shows a retryable download error for %s', async (failure) => {
    mockedDownload.mockRejectedValue(failure);
    vi.mocked(openUrlInNewTab).mockReturnValue(false);
    render(<ResumeViewerPage />);

    const downloadButton = await screen.findByRole('button', {
      name: 'dashboard.downloadPdf',
    });
    await act(async () => downloadButton.click());

    expect(await screen.findByText('resumeViewer.downloadFailedTitle')).toBeInTheDocument();
    expect(
      screen.getByText(
        failure instanceof TypeError
          ? 'common.popupBlocked'
          : 'resumeViewer.errors.failedToDownload'
      )
    ).toBeInTheDocument();
    mockedDownload.mockResolvedValue(new Blob(['pdf']));
    await act(async () => screen.getByRole('button', { name: 'common.retry' }).click());
    expect(mockedDownload).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('common.success')).toBeInTheDocument();
    expect(screen.queryByText('resumeViewer.downloadFailedTitle')).not.toBeInTheDocument();
  });

  it('shows a retryable Word download error and retries the DOCX call', async () => {
    mockedDownloadDocx.mockRejectedValue(new Error('HTTP 500 build failed'));
    render(<ResumeViewerPage />);

    const wordButton = await screen.findByRole('button', {
      name: 'resumeViewer.downloadWord',
    });
    await act(async () => wordButton.click());

    expect(await screen.findByText('resumeViewer.downloadFailedTitle')).toBeInTheDocument();
    expect(screen.getByText('resumeViewer.errors.failedToDownload')).toBeInTheDocument();
    expect(mockedDownload).not.toHaveBeenCalled();
    mockedDownloadDocx.mockResolvedValue(new Blob(['docx']));
    await act(async () => screen.getByRole('button', { name: 'common.retry' }).click());
    expect(mockedDownloadDocx).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('common.success')).toBeInTheDocument();
  });

  it('falls back to opening the DOCX URL in a new tab on network failure', async () => {
    mockedDownloadDocx.mockRejectedValue(new TypeError('Failed to fetch'));
    vi.mocked(openUrlInNewTab).mockReturnValue(false);
    render(<ResumeViewerPage />);

    const wordButton = await screen.findByRole('button', {
      name: 'resumeViewer.downloadWord',
    });
    await act(async () => wordButton.click());

    expect(await screen.findByText('resumeViewer.downloadFailedTitle')).toBeInTheDocument();
    expect(screen.getByText('common.popupBlocked')).toBeInTheDocument();
    expect(mockedDownload).not.toHaveBeenCalled();
  });

  it('names PDF and Word downloads from name-age-workYears-education-intention', async () => {
    mockedFetch.mockResolvedValue({
      title: 'Original title',
      processed_resume: {
        personalInfo: {
          name: '王浩',
          age: '28岁',
          workYears: '5年',
          educationLevel: '硕士',
          title: 'Java开发工程师',
        },
      },
      raw_resume: { processing_status: 'ready' },
    } as Awaited<ReturnType<typeof fetchResume>>);
    mockedDownload.mockResolvedValue(new Blob(['pdf']));
    mockedDownloadDocx.mockResolvedValue(new Blob(['docx']));
    render(<ResumeViewerPage />);

    const pdfButton = await screen.findByRole('button', { name: 'dashboard.downloadPdf' });
    await act(async () => pdfButton.click());
    await waitFor(() => expect(mockedSaveBlob).toHaveBeenCalledTimes(1));
    expect(mockedSaveBlob).toHaveBeenCalledWith(
      expect.any(Blob),
      '王浩-28岁-5年-硕士-Java开发工程师.pdf'
    );

    await act(async () =>
      screen.getByRole('button', { name: 'resumeViewer.downloadWord' }).click()
    );
    await waitFor(() => expect(mockedSaveBlob).toHaveBeenCalledTimes(2));
    expect(mockedSaveBlob).toHaveBeenLastCalledWith(
      expect.any(Blob),
      '王浩-28岁-5年-硕士-Java开发工程师.docx'
    );
  });

  it('falls back to the latest education degree for the filename when 学历 is missing', async () => {
    mockedFetch.mockResolvedValue({
      title: 'Original title',
      processed_resume: {
        personalInfo: { name: '王浩', title: '后端开发' },
        education: [
          { id: 2, degree: '硕士' },
          { id: 1, degree: '本科' },
        ],
      },
      raw_resume: { processing_status: 'ready' },
    } as Awaited<ReturnType<typeof fetchResume>>);
    mockedDownload.mockResolvedValue(new Blob(['pdf']));
    render(<ResumeViewerPage />);

    const pdfButton = await screen.findByRole('button', { name: 'dashboard.downloadPdf' });
    await act(async () => pdfButton.click());
    await waitFor(() => expect(mockedSaveBlob).toHaveBeenCalledTimes(1));
    expect(mockedSaveBlob).toHaveBeenCalledWith(expect.any(Blob), '王浩-硕士-后端开发.pdf');
  });

  it('keeps the PDF button independent of an in-flight Word download', async () => {
    let settleWord!: (value: Blob) => void;
    mockedDownloadDocx.mockImplementationOnce(
      () =>
        new Promise<Blob>((resolve) => {
          settleWord = resolve;
        })
    );
    render(<ResumeViewerPage />);

    const wordButton = await screen.findByRole('button', {
      name: 'resumeViewer.downloadWord',
    });
    const pdfButton = screen.getByRole('button', { name: 'dashboard.downloadPdf' });
    expect(pdfButton).not.toBeDisabled();
    await act(async () => wordButton.click());
    expect(wordButton).toBeDisabled();
    expect(pdfButton).not.toBeDisabled();
    await act(async () => settleWord(new Blob(['docx'])));
    await waitFor(() => expect(wordButton).not.toBeDisabled());
  });

  it('retains the edited title and offers retry after rename failure', async () => {
    mockedRename.mockRejectedValueOnce(new Error('rename failed')).mockResolvedValue(undefined);
    render(<ResumeViewerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Original title' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Edited title' } });
    await act(async () => fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' }));

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(mockedRename).toHaveBeenCalledTimes(1);
    expect(screen.getByText('resumeViewer.renameFailedTitle')).toBeInTheDocument();
    await act(async () => screen.getByRole('button', { name: 'common.retry' }).click());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edited title' })).toBeVisible());
  });

  it('keeps the resume and retries deletion after failure', async () => {
    mockedDelete.mockRejectedValueOnce(new Error('delete failed')).mockResolvedValue(undefined);
    render(<ResumeViewerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'dashboard.deleteResume' }));
    const confirm = await screen.findByRole('button', {
      name: 'confirmations.deleteResumeConfirmLabel',
    });
    await act(async () => confirm.click());

    expect(screen.getByText('resumeViewer.deleteFailedTitle')).toBeInTheDocument();
    expect(decrementResumes).not.toHaveBeenCalled();
    await act(async () => screen.getByRole('button', { name: 'common.retry' }).click());
    expect(mockedDelete).toHaveBeenCalledTimes(2);
    expect(decrementResumes).toHaveBeenCalledTimes(1);
  });
});

it('shows deletion instead of a processing failure when retry returns 404', async () => {
  mockedFetch.mockResolvedValue({
    ...(await mockedFetch('resume-123')),
    processed_resume: null,
    raw_resume: {
      id: null,
      content: '',
      content_type: 'text/plain',
      created_at: '2026-01-01',
      processing_status: 'failed',
    },
  });
  vi.mocked(retryProcessing).mockRejectedValueOnce(
    new Error('Failed to retry processing (status 404)')
  );
  render(<ResumeViewerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'resumeViewer.retryProcessing' }));
  expect(await screen.findByText('common.resumeDeleted')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'resumeViewer.retryProcessing' })).toBeNull();
});

it('keeps the current resume visible when an old retry settles after identity changes', async () => {
  let settle!: (value: Awaited<ReturnType<typeof retryProcessing>>) => void;
  vi.mocked(retryProcessing).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        settle = resolve;
      })
  );
  mockedFetch.mockResolvedValueOnce({
    title: 'Failed A',
    processed_resume: null,
    raw_resume: { content: '', processing_status: 'failed' },
  } as Awaited<ReturnType<typeof fetchResume>>);
  const view = render(<ResumeViewerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'resumeViewer.retryProcessing' }));
  route.resumeId = 'resume-b';
  view.rerender(<ResumeViewerPage />);
  await screen.findByRole('button', { name: 'Original title' });
  await act(async () => settle({ resume_id: 'resume-123', processing_status: 'processing' }));
  expect(screen.getByRole('button', { name: 'Original title' })).toBeVisible();
  expect(screen.queryByText('resumeViewer.errors.stillProcessing')).not.toBeInTheDocument();
});

it('keeps the current resume title when an old rename settles after identity changes', async () => {
  let settle!: () => void;
  mockedRename.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        settle = resolve;
      })
  );
  const view = render(<ResumeViewerPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Original title' }));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Old A renamed' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  mockedFetch.mockResolvedValueOnce({
    title: 'New B title',
    processed_resume: { personalInfo: { name: 'B' } },
    raw_resume: { processing_status: 'ready' },
  } as Awaited<ReturnType<typeof fetchResume>>);
  route.resumeId = 'resume-b';
  view.rerender(<ResumeViewerPage />);
  await screen.findByRole('button', { name: 'New B title' });
  await act(async () => settle());
  expect(screen.getByRole('button', { name: 'New B title' })).toBeVisible();
  expect(mockedRename).toHaveBeenCalledWith('resume-123', 'Old A renamed');
});

it('keeps a replacement master cached when an old delete completes after unmount', async () => {
  let settle!: () => void;
  mockedDelete.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        settle = resolve;
      })
  );
  localStorage.setItem('master_resume_id', 'resume-123');
  const view = render(<ResumeViewerPage />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'confirmations.deleteMasterResumeTitle' })
  );
  fireEvent.click(
    await screen.findByRole('button', { name: 'confirmations.deleteResumeConfirmLabel' })
  );
  expect(mockedDelete).toHaveBeenCalledWith('resume-123');
  view.unmount();
  localStorage.setItem('master_resume_id', 'replacement-master');
  await act(async () => settle());
  expect(localStorage.getItem('master_resume_id')).toBe('replacement-master');
  expect(setHasMasterResume).not.toHaveBeenCalled();
  expect(decrementResumes).toHaveBeenCalledTimes(1);
  expect(push).not.toHaveBeenCalled();
});
