import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CoverLetterStudio } from '@/components/cover-letter/cover-letter-studio';
import {
  downloadCoverLetterPdf,
  fetchResume,
  generateCoverLetterFromResume,
  updateCoverLetter,
} from '@/lib/api/resume';

const push = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'en' }),
}));
vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en' }),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  generateCoverLetterFromResume: vi.fn(),
  updateCoverLetter: vi.fn(),
  downloadCoverLetterPdf: vi.fn(),
  getCoverLetterPdfUrl: vi.fn(() => '/cover-letter.pdf'),
}));
vi.mock('@/lib/utils/download', () => ({
  buildResumeFilename: () => 'cover-letter.pdf',
  downloadBlobAsFile: vi.fn(),
  openUrlInNewTab: vi.fn(() => true),
}));

const mockedFetchResume = vi.mocked(fetchResume);
const mockedGenerate = vi.mocked(generateCoverLetterFromResume);
const mockedUpdate = vi.mocked(updateCoverLetter);
const mockedDownloadPdf = vi.mocked(downloadCoverLetterPdf);

function readyResume(overrides: Record<string, unknown> = {}) {
  return {
    resume_id: 'res-123',
    title: 'Jane resume',
    cover_letter: '',
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
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedFetchResume.mockResolvedValue(readyResume());
});

describe('CoverLetterStudio', () => {
  it('generates a resume-only letter when the JD textarea is empty', async () => {
    mockedGenerate.mockResolvedValue('Dear team, ...');
    render(<CoverLetterStudio resumeId="res-123" />);

    const generateButton = await screen.findByRole('button', {
      name: 'coverLetter.generate',
    });
    fireEvent.click(generateButton);

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalledTimes(1));
    expect(mockedGenerate).toHaveBeenCalledWith('res-123', '');
    expect(await screen.findByDisplayValue('Dear team, ...')).toBeInTheDocument();
    // After generation the button offers regeneration.
    expect(screen.getByRole('button', { name: 'coverLetter.regenerate' })).toBeInTheDocument();
    // Backend persistence makes the generated letter the save baseline.
    expect(screen.getByRole('button', { name: 'common.save' })).toBeDisabled();
  });

  it('passes the trimmed job description to the generation endpoint', async () => {
    mockedGenerate.mockResolvedValue('Tailored letter');
    render(<CoverLetterStudio resumeId="res-123" />);

    await screen.findByRole('button', { name: 'coverLetter.generate' });
    const jdBox = screen.getByLabelText('coverLetter.studio.jobDescriptionLabel');
    fireEvent.change(jdBox, { target: { value: '  Need FastAPI and ETL  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'coverLetter.generate' }));

    await waitFor(() =>
      expect(mockedGenerate).toHaveBeenCalledWith('res-123', 'Need FastAPI and ETL')
    );
  });

  it('prefills an existing cover letter and saves edits', async () => {
    mockedFetchResume.mockResolvedValue(readyResume({ cover_letter: 'Previously saved letter' }));
    mockedUpdate.mockResolvedValue(undefined);
    render(<CoverLetterStudio resumeId="res-123" />);

    const resultBox = await screen.findByDisplayValue('Previously saved letter');
    const saveButton = screen.getByRole('button', { name: 'common.save' });
    expect(saveButton).toBeDisabled();

    fireEvent.change(resultBox, {
      target: { value: 'Previously saved letter, edited' },
    });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(mockedUpdate).toHaveBeenCalledWith('res-123', 'Previously saved letter, edited')
    );
    expect(await screen.findByText('coverLetter.studio.saved')).toBeInTheDocument();
  });

  it('downloads the PDF using the existing cover letter endpoint', async () => {
    mockedFetchResume.mockResolvedValue(readyResume({ cover_letter: 'A letter' }));
    mockedDownloadPdf.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
    render(<CoverLetterStudio resumeId="res-123" />);

    const downloadButton = await screen.findByRole('button', {
      name: 'dashboard.downloadPdf',
    });
    fireEvent.click(downloadButton);

    await waitFor(() => expect(mockedDownloadPdf).toHaveBeenCalledWith('res-123', 'A4', 'en'));
  });

  it('disables PDF download until a letter exists', async () => {
    render(<CoverLetterStudio resumeId="res-123" />);
    const downloadButton = await screen.findByRole('button', {
      name: 'dashboard.downloadPdf',
    });
    expect(downloadButton).toBeDisabled();
  });

  it('navigates back to the resume viewer', async () => {
    render(<CoverLetterStudio resumeId="res-123" />);
    fireEvent.click(await screen.findByRole('button', { name: 'coverLetter.studio.backToResume' }));
    expect(push).toHaveBeenCalledWith('/resumes/res-123');
  });
});
