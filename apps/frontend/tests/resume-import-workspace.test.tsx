import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockStatus = {
  incrementResumes: vi.fn(),
  decrementResumes: vi.fn(),
  setHasMasterResume: vi.fn(),
};

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'en' }),
}));
vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'zh', contentLanguage: 'zh' }),
}));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => mockStatus,
}));
vi.mock('@/lib/api/client', () => ({
  getUploadUrl: vi.fn(() => '/upload'),
  apiFetch: vi.fn(),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  retryProcessing: vi.fn(),
  deleteResume: vi.fn(),
}));
// Import-only guarantee: the dashboard workspace must never reach into the
// diagnosis APIs. The spies stay zero even though the module is mocked.
vi.mock('@/lib/api/diagnosis', () => ({
  diagnoseResume: vi.fn(),
  exportDiagnosisDocx: vi.fn(),
  fetchCompetencyModels: vi.fn(),
}));

const mockResumeProps = vi.fn();
vi.mock('@/components/dashboard/resume-component', () => ({
  default: (props: unknown) => {
    mockResumeProps(props);
    return <div data-testid="resume-structured" />;
  },
}));

import { ResumeImportWorkspace } from '@/components/dashboard/resume-import-workspace';
import { apiFetch } from '@/lib/api/client';
import { fetchResume, retryProcessing, deleteResume } from '@/lib/api/resume';
import { diagnoseResume, exportDiagnosisDocx, fetchCompetencyModels } from '@/lib/api/diagnosis';

const TARGET_TITLE = 'Java 高级工程师';
const RAW_MARKDOWN = '# Jane Applicant\n\n- Engineer at Acme\n\nMarkdown body';

const PROCESSED = {
  personalInfo: { name: 'Jane Applicant', title: TARGET_TITLE },
  workExperience: [{ company: 'Acme', role: 'Engineer', descriptions: ['shipped things'] }],
};

type FetchRow = Awaited<ReturnType<typeof fetchResume>>;
const readyRow = (processed: unknown = PROCESSED): FetchRow =>
  ({
    raw_resume: { processing_status: 'ready', content: RAW_MARKDOWN },
    processed_resume: processed,
  }) as FetchRow;
const emptyReadyRow = (): FetchRow =>
  ({
    raw_resume: { processing_status: 'ready', content: '' },
    processed_resume: {},
  }) as FetchRow;

const uploadResponse = (overrides: Record<string, unknown> = {}): Response =>
  new Response(
    JSON.stringify({
      resume_id: 'r-1',
      processing_status: 'processing',
      is_master: false,
      ...overrides,
    }),
    { status: 200, headers: { 'content-type': 'application/json' } }
  );

const pdfFile = (name = 'jane.pdf', size?: number): File =>
  new File([size ? new Uint8Array(size) : 'pdf-bytes'], name, {
    type: 'application/pdf',
  });

const overlay = (): Element => {
  const node = document.querySelector('.bg-black\\/50');
  if (!node) throw new Error('workspace overlay not found');
  return node;
};

const apiFetchMock = vi.mocked(apiFetch);
const fetchResumeMock = vi.mocked(fetchResume);
const retryProcessingMock = vi.mocked(retryProcessing);
const deleteResumeMock = vi.mocked(deleteResume);
const diagnoseMock = vi.mocked(diagnoseResume);
const exportMock = vi.mocked(exportDiagnosisDocx);
const modelsMock = vi.mocked(fetchCompetencyModels);

const onCloseMock = vi.fn<() => void>();
const onMutatedMock = vi.fn<() => void>();

const renderWorkspace = (strict = false) => {
  const tree = <ResumeImportWorkspace open onClose={onCloseMock} onResumeMutated={onMutatedMock} />;
  return render(strict ? <React.StrictMode>{tree}</React.StrictMode> : tree);
};

const uploadFromInput = (file: File = pdfFile()) => {
  const input = screen.getByTestId('resume-import-upload-input') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
};

const waitForImportedResume = async () => {
  await screen.findByText('importWorkspace.importSuccess');
  return screen.findByTestId('resume-structured');
};

const confirmDelete = async () => {
  const title = screen.getByText('importWorkspace.deleteConfirmTitle');
  const dialog = title.closest('[role="dialog"]') as HTMLElement;
  const confirmButton = within(dialog).getByRole('button', {
    name: 'importWorkspace.deleteResume',
  });
  fireEvent.click(confirmButton);
  await screen.findByRole('button', { name: 'dashboard.uploadResume' });
};

const MIME_ACCEPT =
  'application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword';

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  // A fresh Response per call: the upload hook consumes each body via
  // response.json(), so a shared instance breaks the second upload with
  // "Body has already been read".
  apiFetchMock.mockImplementation(() => Promise.resolve(uploadResponse()));
  fetchResumeMock.mockResolvedValue(readyRow());
  retryProcessingMock.mockResolvedValue({
    resume_id: 'r-1',
    processing_status: 'processing',
  });
  deleteResumeMock.mockResolvedValue(undefined);
  mockResumeProps.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResumeImportWorkspace upload dropzone', () => {
  it('advertises the three accepted MIMEs and blocks a 5MB file locally', () => {
    renderWorkspace();
    const input = screen.getByTestId('resume-import-upload-input') as HTMLInputElement;
    expect(input.getAttribute('accept')).toBe(MIME_ACCEPT);

    uploadFromInput(pdfFile('big.pdf', 5 * 1024 * 1024));

    expect(apiFetchMock).not.toHaveBeenCalled();
    // Still on the idle dropzone, with an inline validation error.
    expect(screen.getByRole('button', { name: 'dashboard.uploadResume' })).toBeInTheDocument();
    expect(screen.getByText(/exceeds the maximum size/)).toBeInTheDocument();
  });
});

describe('ResumeImportWorkspace upload error panel', () => {
  it('renders a rejected upload message exactly once although the hook stores it twice', async () => {
    apiFetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: 'Failed to parse document. Please upload a valid PDF, DOC, or DOCX file.',
        }),
        {
          status: 422,
          statusText: 'Unprocessable Content',
          headers: { 'content-type': 'application/json' },
        }
      )
    );
    renderWorkspace();
    uploadFromInput(pdfFile('legacy.doc'));

    // useFileUpload mirrors the same failure into its errors array AND echoes
    // it through onUploadError; the workspace panel must show it once, not twice.
    const messages = await screen.findAllByText(/Upload failed for legacy\.doc/);
    expect(messages).toHaveLength(1);
    expect(messages[0]?.textContent).toContain('Status: 422');
    expect(messages[0]?.textContent).toContain('Failed to parse document');

    // A rejected upload returns to the dropzone instead of entering processing.
    expect(screen.getByRole('button', { name: 'dashboard.uploadResume' })).toBeInTheDocument();
  });
});

describe('ResumeImportWorkspace import-only pipeline', () => {
  it('imports, parses and previews the resume without ever calling a diagnosis API', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForImportedResume();

    // The pipeline ends at import: no checklist, no competency catalog, no
    // report export — the dashboard entry is import-only by contract.
    expect(diagnoseMock).not.toHaveBeenCalled();
    expect(modelsMock).not.toHaveBeenCalled();
    expect(exportMock).not.toHaveBeenCalled();
    expect(screen.queryByText('diagnosis.workspace.paneReport')).not.toBeInTheDocument();

    // The structured preview renders the shared <Resume> with localized headings.
    const lastProps = mockResumeProps.mock.calls.at(-1)?.[0] as {
      resumeData: { personalInfo: { name: string } };
      sectionHeadings: { experience: string };
      fallbackLabels: { name: string };
    };
    expect(lastProps.resumeData.personalInfo.name).toBe('Jane Applicant');
    expect(lastProps.sectionHeadings.experience).toBe('resume.sections.experience');
    expect(lastProps.fallbackLabels.name).toBe('resume.defaults.name');
  });

  it('counts the upload in the status cache and records master state when is_master', async () => {
    apiFetchMock.mockResolvedValue(uploadResponse({ is_master: true }));
    renderWorkspace();
    uploadFromInput();
    await waitForImportedResume();

    expect(mockStatus.incrementResumes).toHaveBeenCalledTimes(1);
    expect(mockStatus.setHasMasterResume).toHaveBeenCalledWith(true);
    expect(localStorage.getItem('master_resume_id')).toBe('r-1');
    expect(onMutatedMock).toHaveBeenCalledTimes(1);
  });

  it('settles on a single success state under StrictMode double effects', async () => {
    renderWorkspace(true);
    uploadFromInput();
    await waitForImportedResume();

    expect(screen.getAllByText('importWorkspace.importSuccess')).toHaveLength(1);
    expect(screen.getByTestId('resume-structured')).toBeInTheDocument();
  });
});

describe('ResumeImportWorkspace parse failure recovery', () => {
  it('surfaces parse failure with retry/delete/upload-again recovery and no diagnosis', async () => {
    fetchResumeMock.mockResolvedValue(emptyReadyRow());
    renderWorkspace();
    uploadFromInput();

    await screen.findByText('importWorkspace.parseFailed');
    expect(diagnoseMock).not.toHaveBeenCalled();

    // Retry processing → fresh successful poll → the imported resume preview.
    fetchResumeMock.mockResolvedValue(readyRow());
    fireEvent.click(screen.getByRole('button', { name: 'dashboard.retryProcessing' }));
    expect(retryProcessingMock).toHaveBeenCalledWith('r-1');
    await waitForImportedResume();
    expect(diagnoseMock).not.toHaveBeenCalled();
  });

  it('deletes a failed parse and returns to the dropzone', async () => {
    fetchResumeMock.mockResolvedValue(emptyReadyRow());
    renderWorkspace();
    uploadFromInput();
    await screen.findByText('importWorkspace.parseFailed');

    const deleteButtons = screen.getAllByRole('button', {
      name: 'importWorkspace.deleteResume',
    });
    // Header + parse-failure card.
    expect(deleteButtons).toHaveLength(2);
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    await confirmDelete();

    expect(deleteResumeMock).toHaveBeenCalledWith('r-1');
    expect(mockStatus.decrementResumes).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'dashboard.uploadResume' })).toBeInTheDocument();
  });
});

describe('ResumeImportWorkspace delete and close', () => {
  it('plain close never deletes the resume', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForImportedResume();

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onCloseMock).toHaveBeenCalledTimes(1);
    expect(deleteResumeMock).not.toHaveBeenCalled();
  });

  it('the Done button closes the workspace', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForImportedResume();

    fireEvent.click(screen.getByRole('button', { name: 'importWorkspace.done' }));
    expect(onCloseMock).toHaveBeenCalledTimes(1);
  });

  it('clears master state and refreshes the list when the imported resume was master', async () => {
    apiFetchMock.mockResolvedValue(uploadResponse({ is_master: true }));
    renderWorkspace();
    uploadFromInput();
    await waitForImportedResume();

    fireEvent.click(screen.getByRole('button', { name: 'importWorkspace.deleteResume' }));
    await confirmDelete();

    expect(deleteResumeMock).toHaveBeenCalledWith('r-1');
    expect(localStorage.getItem('master_resume_id')).toBeNull();
    expect(mockStatus.setHasMasterResume).toHaveBeenLastCalledWith(false);
    expect(mockStatus.decrementResumes).toHaveBeenCalledTimes(1);
    expect(onMutatedMock).toHaveBeenCalledTimes(2);
  });

  it('returns to the dropzone and accepts a second import', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForImportedResume();

    fireEvent.click(screen.getByRole('button', { name: 'importWorkspace.backToUpload' }));
    expect(screen.getByRole('button', { name: 'dashboard.uploadResume' })).toBeInTheDocument();

    uploadFromInput(pdfFile('second.pdf'));
    await waitForImportedResume();
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('ResumeImportWorkspace close gating while busy', () => {
  it('cannot be closed while the file is uploading', async () => {
    apiFetchMock.mockReturnValue(new Promise<Response>(() => undefined));
    renderWorkspace();
    uploadFromInput();

    await screen.findByText('common.uploading');
    expect(screen.queryByRole('button', { name: 'common.close' })).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(overlay());
    expect(onCloseMock).not.toHaveBeenCalled();
  });

  it('cannot be closed while parsing is in flight', async () => {
    let resolvePoll!: (value: FetchRow) => void;
    fetchResumeMock.mockReturnValue(
      new Promise<FetchRow>((resolve) => {
        resolvePoll = resolve;
      })
    );
    renderWorkspace();
    uploadFromInput();

    await screen.findByText('importWorkspace.parsing');
    expect(screen.queryByRole('button', { name: 'common.close' })).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(overlay());
    expect(onCloseMock).not.toHaveBeenCalled();

    resolvePoll(readyRow());
    await waitForImportedResume();
    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onCloseMock).toHaveBeenCalledTimes(1);
  });
});
