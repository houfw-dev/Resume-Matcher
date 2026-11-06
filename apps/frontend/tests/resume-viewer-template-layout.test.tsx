import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ResumeViewerPage from '@/app/(default)/resumes/[id]/page';
import { fetchResume, downloadResumePdf } from '@/lib/api/resume';
import { DEFAULT_TEMPLATE_SETTINGS, type TemplateSettings } from '@/lib/types/template-settings';
import { storeTemplateSettings } from '@/lib/utils/template-settings-storage';
import type { ResumeData } from '@/components/dashboard/resume-component';

const route = vi.hoisted(() => ({ resumeId: 'resume-xyz' }));
const push = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: route.resumeId }),
}));
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ decrementResumes: vi.fn(), setHasMasterResume: vi.fn() }),
}));
// A distinctive UI language proves screen render, PDF and diagnosis all share it.
vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'ja' }),
}));
vi.mock('@/components/enrichment/enrichment-modal', () => ({ EnrichmentModal: () => null }));

const resumePropsMock = vi.fn();
vi.mock('@/components/dashboard/resume-component', () => ({
  default: (props: unknown) => {
    resumePropsMock(props);
    return <div data-testid="viewer-resume" />;
  },
}));

const diagnosisModalPropsMock = vi.fn();
vi.mock('@/components/diagnosis/diagnosis-modal', () => ({
  DiagnosisModal: (props: unknown) => {
    diagnosisModalPropsMock(props);
    return <div data-testid="viewer-diagnosis-modal" />;
  },
}));

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
  return { ...actual, downloadBlobAsFile: vi.fn() };
});

const fetchResumeMock = vi.mocked(fetchResume);
const downloadPdfMock = vi.mocked(downloadResumePdf);

const parsed: ResumeData = {
  personalInfo: { name: '李勇', title: 'Java 工程师' },
} as unknown as ResumeData;

const customSettings: TemplateSettings = {
  ...DEFAULT_TEMPLATE_SETTINGS,
  template: 'vivid',
  pageSize: 'LETTER',
  compactMode: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  route.resumeId = 'resume-xyz';
  fetchResumeMock.mockResolvedValue({
    title: '李勇的简历',
    processed_resume: parsed,
    raw_resume: { processing_status: 'ready' },
  } as Awaited<ReturnType<typeof fetchResume>>);
  downloadPdfMock.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
});

describe('resume viewer follows the builder template settings', () => {
  it('renders <Resume> with the stored template, settings and the UI language', async () => {
    storeTemplateSettings(customSettings);
    render(<ResumeViewerPage />);

    await screen.findByTestId('viewer-resume');
    const props = resumePropsMock.mock.calls.at(-1)?.[0] as {
      resumeData: ResumeData;
      template: string;
      settings: TemplateSettings;
      locale: string;
    };
    expect(props.template).toBe('vivid');
    expect(props.settings).toEqual(customSettings);
    expect(props.settings.pageSize).toBe('LETTER');
    expect(props.settings.compactMode).toBe(true);
    expect(props.locale).toBe('ja');
    expect(props.resumeData).toBeTruthy();
  });

  it('downloads the PDF through the same settings and language', async () => {
    storeTemplateSettings(customSettings);
    render(<ResumeViewerPage />);

    const downloadButton = await screen.findByRole('button', {
      name: 'dashboard.downloadPdf',
    });
    await act(async () => {
      downloadButton.click();
    });

    await waitFor(() => expect(downloadPdfMock).toHaveBeenCalledTimes(1));
    expect(downloadPdfMock).toHaveBeenCalledWith('resume-xyz', customSettings, 'ja');
  });

  it('hands the display-state resume and intention title to the diagnosis modal', async () => {
    storeTemplateSettings(customSettings);
    render(<ResumeViewerPage />);

    await screen.findByTestId('viewer-diagnosis-modal');
    const modalProps = diagnosisModalPropsMock.mock.calls.at(-1)?.[0] as {
      resumeId: string;
      intentionTitle: string;
      resumeData: ResumeData;
    };
    expect(modalProps.resumeId).toBe('resume-xyz');
    expect(modalProps.intentionTitle).toBe('Java 工程师');
    // The modal measures exactly what the viewer shows (localized display state).
    expect(modalProps.resumeData).toBeTruthy();
    expect(modalProps.resumeData.personalInfo?.name).toBe('李勇');
  });

  it('falls back to default settings when nothing is stored', async () => {
    render(<ResumeViewerPage />);

    await screen.findByTestId('viewer-resume');
    const props = resumePropsMock.mock.calls.at(-1)?.[0] as {
      template: string;
      settings: TemplateSettings;
    };
    expect(props.template).toBe(DEFAULT_TEMPLATE_SETTINGS.template);
    expect(props.settings).toEqual(DEFAULT_TEMPLATE_SETTINGS);
  });
});
