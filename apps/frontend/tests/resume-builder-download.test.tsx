import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import type { ResumeData } from '@/components/dashboard/resume-component';

const fetchResume = vi.fn();
const updateResume = vi.fn();
const downloadResumePdf = vi.fn();
const downloadResumeDocx = vi.fn();
const downloadInterviewPrepPdf = vi.fn();
const downloadJdMatchPdf = vi.fn();
const downloadOutreachPdf = vi.fn();
const fetchJobDescription = vi.fn<(resumeId: string) => Promise<{ content: string } | null>>(() =>
  Promise.resolve(null)
);

// Stable instance: the builder re-syncs its active tab from searchParams on
// every reference change, so a fresh URLSearchParams per render would undo
// tab switches driven inside the test.
const SEARCH_PARAMS = new URLSearchParams('id=res-1');

vi.mock('next/navigation', () => ({
  useSearchParams: () => SEARCH_PARAMS,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/api/resume', () => ({
  fetchResume: (...args: unknown[]) => fetchResume(...args),
  updateResume: (...args: unknown[]) => updateResume(...args),
  downloadResumePdf: (...args: unknown[]) => downloadResumePdf(...args),
  downloadResumeDocx: (...args: unknown[]) => downloadResumeDocx(...args),
  downloadInterviewPrepPdf: (...args: unknown[]) => downloadInterviewPrepPdf(...args),
  downloadJdMatchPdf: (...args: unknown[]) => downloadJdMatchPdf(...args),
  downloadOutreachPdf: (...args: unknown[]) => downloadOutreachPdf(...args),
  downloadCoverLetterPdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => ''),
  getResumeDocxUrl: vi.fn(() => ''),
  getCoverLetterPdfUrl: vi.fn(() => ''),
  getOutreachPdfUrl: vi.fn(() => ''),
  getInterviewPrepPdfUrl: vi.fn(() => ''),
  getJdMatchPdfUrl: vi.fn(() => ''),
  updateCoverLetter: vi.fn(),
  updateOutreachMessage: vi.fn(),
  generateCoverLetter: vi.fn(),
  generateOutreachMessage: vi.fn(),
  generateInterviewPrep: vi.fn(),
  fetchJobDescription: (resumeId: string) => fetchJobDescription(resumeId),
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
vi.mock('@/components/builder/cover-letter-editor', () => ({ CoverLetterEditor: () => null }));
vi.mock('@/components/builder/outreach-editor', () => ({ OutreachEditor: () => null }));
vi.mock('@/components/builder/cover-letter-preview', () => ({ CoverLetterPreview: () => null }));
vi.mock('@/components/builder/outreach-preview', () => ({ OutreachPreview: () => null }));
vi.mock('@/components/builder/generate-prompt', () => ({ GeneratePrompt: () => null }));
vi.mock('@/components/builder/interview-prep-view', () => ({ InterviewPrepView: () => null }));
vi.mock('@/components/builder/jd-comparison-view', () => ({ JDComparisonView: () => null }));
vi.mock('@/components/builder/regenerate-wizard', () => ({ RegenerateWizard: () => null }));
vi.mock('@/hooks/use-regenerate-wizard', () => ({
  useRegenerateWizard: () => ({ step: 'idle', reset: vi.fn() }),
}));

vi.mock('@/lib/utils/download', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils/download')>();
  return {
    ...actual,
    downloadBlobAsFile: vi.fn(),
    openUrlInNewTab: vi.fn(() => false),
  };
});

import { downloadBlobAsFile } from '@/lib/utils/download';

const saveBlobMock = vi.mocked(downloadBlobAsFile);

const RESUME: ResumeData = {
  personalInfo: {
    name: '王浩',
    age: '28岁',
    workYears: '5年',
    educationLevel: '硕士',
    title: 'Java开发工程师',
  },
  summary: '',
  workExperience: [],
  education: [],
  personalProjects: [],
  additional: {},
} as ResumeData;

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
  localStorage.clear();
  vi.clearAllMocks();
  fetchResume.mockResolvedValue({
    processed_resume: RESUME,
    raw_resume: { processing_status: 'ready' },
    title: '王浩的简历',
  });
  updateResume.mockResolvedValue({ processed_resume: RESUME });
  downloadResumePdf.mockResolvedValue(new Blob(['pdf']));
  downloadResumeDocx.mockResolvedValue(new Blob(['docx']));
  downloadInterviewPrepPdf.mockResolvedValue(new Blob(['interview-pdf']));
  downloadJdMatchPdf.mockResolvedValue(new Blob(['jd-pdf']));
  downloadOutreachPdf.mockResolvedValue(new Blob(['outreach-pdf']));
});

afterEach(() => {
  cleanup();
  vi.resetModules();
});

describe('builder resume download naming', () => {
  it('names the Word download 姓名-年龄-工作年限-学历-求职意向.docx', async () => {
    const Builder = await importBuilder();
    render(<Builder />);
    const wordButton = await screen.findByRole('button', {
      name: 'resumeViewer.downloadWord',
    });

    await act(async () => wordButton.click());

    await waitFor(() => expect(saveBlobMock).toHaveBeenCalledTimes(1));
    expect(downloadResumeDocx).toHaveBeenCalledWith('res-1');
    expect(downloadResumePdf).not.toHaveBeenCalled();
    expect(saveBlobMock).toHaveBeenCalledWith(
      expect.any(Blob),
      '王浩-28岁-5年-硕士-Java开发工程师.docx'
    );
  });

  it('names the PDF download with the same five facts', async () => {
    const Builder = await importBuilder();
    render(<Builder />);
    const pdfButton = await screen.findByRole('button', { name: 'dashboard.downloadPdf' });

    await act(async () => pdfButton.click());

    await waitFor(() => expect(saveBlobMock).toHaveBeenCalledTimes(1));
    expect(downloadResumePdf).toHaveBeenCalledOnce();
    expect(saveBlobMock).toHaveBeenCalledWith(
      expect.any(Blob),
      '王浩-28岁-5年-硕士-Java开发工程师.pdf'
    );
  });

  it('falls back to the latest education degree for the Word filename', async () => {
    const resumeWithDegree: ResumeData = {
      ...RESUME,
      personalInfo: { name: '王浩', title: '后端开发' },
      education: [
        { id: 2, degree: '硕士' },
        { id: 1, degree: '本科' },
      ],
    } as ResumeData;
    fetchResume.mockResolvedValue({
      processed_resume: resumeWithDegree,
      raw_resume: { processing_status: 'ready' },
    });
    const Builder = await importBuilder();
    render(<Builder />);
    const wordButton = await screen.findByRole('button', {
      name: 'resumeViewer.downloadWord',
    });

    await act(async () => wordButton.click());

    await waitFor(() => expect(saveBlobMock).toHaveBeenCalledTimes(1));
    expect(saveBlobMock).toHaveBeenCalledWith(expect.any(Blob), '王浩-硕士-后端开发.docx');
  });
});

describe('builder downloads while the resume is not ready', () => {
  // A processing/failed record used to render enabled download buttons: the
  // print route then timed out on a hidden element (blank PDF) or Chromium
  // burned the full 60s render timeout. The builder must keep both export
  // controls disabled until the record has loaded successfully.
  it.each([
    ['processing', 'processing'],
    ['failed', 'failed'],
  ])('disables PDF and Word downloads for a %s record', async (_label, status) => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: status },
      title: '王浩的简历',
    });
    const Builder = await importBuilder();
    render(<Builder />);

    expect(await screen.findByRole('alert')).toHaveTextContent('builder.alerts.loadFailed');

    const pdfButton = screen.getByRole('button', { name: 'dashboard.downloadPdf' });
    const wordButton = screen.getByRole('button', { name: 'resumeViewer.downloadWord' });
    expect(pdfButton).toBeDisabled();
    expect(wordButton).toBeDisabled();

    await act(async () => pdfButton.click());
    await act(async () => wordButton.click());
    expect(downloadResumePdf).not.toHaveBeenCalled();
    expect(downloadResumeDocx).not.toHaveBeenCalled();
    expect(saveBlobMock).not.toHaveBeenCalled();
  });
});

describe('builder interview prep / JD match PDF downloads', () => {
  const INTERVIEW_PREP = {
    role_fit_analysis: ['Strong backend background'],
    resume_questions: [],
    project_follow_ups: [],
    skill_gaps: [],
    talking_points: [],
  };

  it('downloads the stored interview preparation as a named PDF', async () => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: '王浩的简历',
      interview_prep: INTERVIEW_PREP,
    });
    const Builder = await importBuilder();
    render(<Builder />);

    const prepTab = await screen.findByRole('button', {
      name: 'builder.previewTabs.interviewPrep',
    });
    await act(async () => prepTab.click());

    const downloadButton = await screen.findByRole('button', { name: 'common.download' });
    await act(async () => downloadButton.click());

    await waitFor(() => expect(downloadInterviewPrepPdf).toHaveBeenCalledTimes(1));
    expect(downloadInterviewPrepPdf).toHaveBeenCalledWith('res-1', 'A4', 'en');
    expect(saveBlobMock).toHaveBeenCalledWith(expect.any(Blob), '王浩 - Interview Prep.pdf');
  });

  it('downloads the JD match report as a named PDF for a tailored resume', async () => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: '王浩的简历',
      parent_id: 'master-resume',
    });
    fetchJobDescription.mockResolvedValue({ content: 'Java Spring Boot Kubernetes' });
    const Builder = await importBuilder();
    render(<Builder />);

    const jdTab = await screen.findByRole('button', { name: 'builder.previewTabs.jdMatch' });
    await waitFor(() => expect(jdTab).not.toBeDisabled());
    await act(async () => jdTab.click());

    const downloadButton = await screen.findByRole('button', { name: 'common.download' });
    await act(async () => downloadButton.click());

    await waitFor(() => expect(downloadJdMatchPdf).toHaveBeenCalledTimes(1));
    expect(downloadJdMatchPdf).toHaveBeenCalledWith('res-1', 'A4', 'en');
    expect(saveBlobMock).toHaveBeenCalledWith(expect.any(Blob), '王浩 - JD Match.pdf');
  });

  it('downloads the stored outreach message as a named PDF', async () => {
    fetchResume.mockResolvedValue({
      processed_resume: RESUME,
      raw_resume: { processing_status: 'ready' },
      title: '王浩的简历',
      outreach_message: 'Hello recruiter, ...',
    });
    const Builder = await importBuilder();
    render(<Builder />);

    const outreachTab = await screen.findByRole('button', {
      name: 'builder.previewTabs.outreach',
    });
    await act(async () => outreachTab.click());

    const downloadButton = await screen.findByRole('button', { name: 'common.download' });
    await act(async () => downloadButton.click());

    await waitFor(() => expect(downloadOutreachPdf).toHaveBeenCalledTimes(1));
    expect(downloadOutreachPdf).toHaveBeenCalledWith('res-1', 'A4', 'en');
    expect(saveBlobMock).toHaveBeenCalledWith(expect.any(Blob), '王浩 - Outreach Message.pdf');
  });
});
