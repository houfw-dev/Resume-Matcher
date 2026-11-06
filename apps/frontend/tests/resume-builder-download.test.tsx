import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import type { ResumeData } from '@/components/dashboard/resume-component';

const fetchResume = vi.fn();
const updateResume = vi.fn();
const downloadResumePdf = vi.fn();
const downloadResumeDocx = vi.fn();

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('id=res-1'),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/api/resume', () => ({
  fetchResume: (...args: unknown[]) => fetchResume(...args),
  updateResume: (...args: unknown[]) => updateResume(...args),
  downloadResumePdf: (...args: unknown[]) => downloadResumePdf(...args),
  downloadResumeDocx: (...args: unknown[]) => downloadResumeDocx(...args),
  downloadCoverLetterPdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => ''),
  getResumeDocxUrl: vi.fn(() => ''),
  getCoverLetterPdfUrl: vi.fn(() => ''),
  updateCoverLetter: vi.fn(),
  updateOutreachMessage: vi.fn(),
  generateCoverLetter: vi.fn(),
  generateOutreachMessage: vi.fn(),
  generateInterviewPrep: vi.fn(),
  fetchJobDescription: vi.fn(() => Promise.resolve(null)),
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

const importBuilder = async () =>
  (await import('@/components/builder/resume-builder')).ResumeBuilder;

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
