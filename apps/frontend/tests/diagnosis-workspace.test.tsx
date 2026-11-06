import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

const mockMeasureLayout = vi.fn();
vi.mock('@/lib/utils/measure-resume-layout', () => ({
  LayoutMeasurementError: class LayoutMeasurementError extends Error {},
  measureResumeLayout: (...args: unknown[]) => mockMeasureLayout(...args),
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
vi.mock('@/lib/api/diagnosis', () => ({
  diagnoseResume: vi.fn(),
  exportDiagnosisDocx: vi.fn(),
  fetchCompetencyModels: vi.fn(),
}));
vi.mock('@/lib/utils/download', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils/download')>();
  return {
    ...actual,
    downloadBlobAsFile: vi.fn(),
  };
});

const mockResumeProps = vi.fn();
vi.mock('@/components/dashboard/resume-component', () => ({
  default: (props: unknown) => {
    mockResumeProps(props);
    return <div data-testid="resume-structured" />;
  },
}));
vi.mock('@/components/diagnosis/diagnosis-report-view', () => ({
  DiagnosisReportView: ({ report }: { report: { counts: { effective: number } } }) => (
    <div data-testid="report-view">effective:{report.counts.effective}</div>
  ),
}));

import { DiagnosisWorkspace } from '@/components/diagnosis/diagnosis-workspace';
import { apiFetch } from '@/lib/api/client';
import { fetchResume, retryProcessing, deleteResume } from '@/lib/api/resume';
import {
  diagnoseResume,
  exportDiagnosisDocx,
  fetchCompetencyModels,
  type DiagnosisReport,
} from '@/lib/api/diagnosis';
import { downloadBlobAsFile } from '@/lib/utils/download';
import { LayoutMeasurementError } from '@/lib/utils/measure-resume-layout';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';
import type { RenderedLayout } from '@/lib/types/rendered-layout';

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

const reportA: DiagnosisReport = {
  resume_id: 'r-1',
  spec_version: '6',
  language: 'zh',
  target_title: TARGET_TITLE,
  competency_model: { key: 'java-p4', name: 'Java P4' },
  counts: { conform: 1, partial: 2, nonconform: 3, na: 0, effective: 6 },
  redline_passed: true,
  failed_redline_ids: [],
  dimensions: [],
  redlines: [],
  items: [
    {
      id: 1,
      dimension: 'base',
      dimension_name: '基础',
      sub_dimension: '',
      topic: 'contact',
      severity: 'normal',
      judgment_method: 'objective',
      rating: 'partial',
      evidence: 'e',
      suggestion: 's',
    },
  ],
  warnings: [],
};
const reportB: DiagnosisReport = {
  ...reportA,
  competency_model: { key: 'java-p4', name: 'Java P4' },
  counts: { conform: 4, partial: 4, nonconform: 1, na: 0, effective: 9 },
};

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

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
const downloadMock = vi.mocked(downloadBlobAsFile);

const onCloseMock = vi.fn<() => void>();
const onMutatedMock = vi.fn<() => void>();

const renderWorkspace = (strict = false) => {
  const tree = <DiagnosisWorkspace open onClose={onCloseMock} onResumeMutated={onMutatedMock} />;
  return render(strict ? <React.StrictMode>{tree}</React.StrictMode> : tree);
};

const uploadFromInput = (file: File = pdfFile()) => {
  const input = screen.getByTestId('diagnosis-upload-input') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
};

const waitForReport = async (effective = 6) => {
  const view = await screen.findByTestId('report-view');
  await waitFor(() => expect(view.textContent).toBe(`effective:${effective}`));
};

const confirmDelete = async () => {
  const title = screen.getByText('diagnosis.workspace.deleteConfirmTitle');
  const dialog = title.closest('[role="dialog"]') as HTMLElement;
  const confirmButton = within(dialog).getByRole('button', {
    name: 'diagnosis.workspace.deleteResume',
  });
  fireEvent.click(confirmButton);
  await screen.findByRole('button', { name: 'dashboard.uploadResume' });
};

const MIME_ACCEPT =
  'application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword';

const measuredLayout = {
  schema_version: 1,
  measured_at: '2026-10-24T00:00:00.000Z',
  template: 'swiss-single',
  page_size: 'A4',
  margins: { top: 10, bottom: 10, left: 10, right: 10 },
  content_width_px: 718,
  content_height_px: 1047,
  page_count: 2,
  total_height_px: 2000,
  two_column: false,
  header: { height_px: 100, cell_count: 1, rows: [{ cells: 1 }] },
  sections: [],
  points: [],
  page_mirror: [{ page: 1, text: '镜像' }],
  warnings: [],
} as unknown as RenderedLayout;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  apiFetchMock.mockResolvedValue(uploadResponse());
  fetchResumeMock.mockResolvedValue(readyRow());
  retryProcessingMock.mockResolvedValue({
    resume_id: 'r-1',
    processing_status: 'processing',
  });
  deleteResumeMock.mockResolvedValue(undefined);
  modelsMock.mockResolvedValue({ models: [], matched_key: 'java-p4' });
  diagnoseMock.mockResolvedValue(reportA);
  exportMock.mockResolvedValue(new Blob(['docx-bytes'], { type: 'application/octet-stream' }));
  mockResumeProps.mockClear();
  // jsdom cannot measure layout; default every flow to the text-estimate
  // fallback unless a test opts into a successful measurement.
  mockMeasureLayout.mockRejectedValue(
    new LayoutMeasurementError('resume rendered with zero height')
  );
  vi.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('DiagnosisWorkspace upload dropzone', () => {
  it('advertises the three accepted MIMEs and blocks a 5MB file locally', () => {
    renderWorkspace();
    const input = screen.getByTestId('diagnosis-upload-input') as HTMLInputElement;
    expect(input.getAttribute('accept')).toBe(MIME_ACCEPT);

    uploadFromInput(pdfFile('big.pdf', 5 * 1024 * 1024));

    expect(apiFetchMock).not.toHaveBeenCalled();
    // Still on the idle dropzone, with an inline validation error.
    expect(screen.getByRole('button', { name: 'dashboard.uploadResume' })).toBeInTheDocument();
    expect(screen.getByText(/exceeds the maximum size/)).toBeInTheDocument();
  });

  it('counts the upload in the status cache and records master state when is_master', async () => {
    apiFetchMock.mockResolvedValue(uploadResponse({ is_master: true }));
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    expect(mockStatus.incrementResumes).toHaveBeenCalledTimes(1);
    expect(mockStatus.setHasMasterResume).toHaveBeenCalledWith(true);
    expect(localStorage.getItem('master_resume_id')).toBe('r-1');
    expect(onMutatedMock).toHaveBeenCalledTimes(1);
  });
});

describe('DiagnosisWorkspace automatic diagnosis', () => {
  it('runs the base diagnosis exactly once with resolved title and model, then renders panes', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    expect(modelsMock).toHaveBeenCalledTimes(1);
    expect(modelsMock).toHaveBeenCalledWith(TARGET_TITLE);
    expect(diagnoseMock).toHaveBeenCalledTimes(1);
    expect(diagnoseMock).toHaveBeenCalledWith('r-1', {
      jobDescription: undefined,
      targetTitle: TARGET_TITLE,
      competencyModelKey: 'java-p4',
    });
    expect(screen.getByText('diagnosis.workspace.paneResume')).toBeInTheDocument();
    expect(screen.getByText('diagnosis.workspace.paneReport')).toBeInTheDocument();

    // Structured tab renders the shared <Resume> with localized heading props.
    const lastProps = mockResumeProps.mock.calls.at(-1)?.[0] as {
      resumeData: { personalInfo: { name: string } };
      sectionHeadings: { experience: string };
      fallbackLabels: { name: string };
    };
    expect(lastProps.resumeData.personalInfo.name).toBe('Jane Applicant');
    expect(lastProps.sectionHeadings.experience).toBe('resume.sections.experience');
    expect(lastProps.fallbackLabels.name).toBe('resume.defaults.name');
  });

  it('auto-runs once even under StrictMode double effects', async () => {
    renderWorkspace(true);
    uploadFromInput();
    await waitForReport();

    expect(diagnoseMock).toHaveBeenCalledTimes(1);
    expect(modelsMock).toHaveBeenCalledTimes(1);
  });

  it("defaults to the 'none' model when the catalog has no match", async () => {
    modelsMock.mockResolvedValue({ models: [], matched_key: null });
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    expect(diagnoseMock.mock.calls[0]?.[1]).toMatchObject({ competencyModelKey: 'none' });
  });

  it("falls back to 'none' when the catalog request fails", async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    modelsMock.mockRejectedValue(new Error('catalog down'));
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    expect(diagnoseMock.mock.calls[0]?.[1]).toMatchObject({ competencyModelKey: 'none' });
    consoleError.mockRestore();
  });

  it('surfaces parse failure with retry/delete/upload-again recovery', async () => {
    fetchResumeMock.mockResolvedValue(emptyReadyRow());
    renderWorkspace();
    uploadFromInput();

    await screen.findByText('diagnosis.workspace.parseFailed');
    expect(diagnoseMock).not.toHaveBeenCalled();

    // Retry processing → fresh successful poll → auto diagnosis runs.
    fetchResumeMock.mockResolvedValue(readyRow());
    fireEvent.click(screen.getByRole('button', { name: 'dashboard.retryProcessing' }));
    expect(retryProcessingMock).toHaveBeenCalledWith('r-1');
    await waitForReport();
    expect(diagnoseMock).toHaveBeenCalledTimes(1);
  });
});

describe('DiagnosisWorkspace layout measurement', () => {
  it('measures the localized display-state resume and ships the settings+layout pair', async () => {
    mockMeasureLayout.mockResolvedValue(measuredLayout);
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    expect(mockMeasureLayout).toHaveBeenCalledTimes(1);
    const measureArg = mockMeasureLayout.mock.calls[0]?.[0] as {
      resumeData: {
        personalInfo: { name: string };
        sectionMeta: unknown[];
      };
      settings: typeof DEFAULT_TEMPLATE_SETTINGS;
      headingProps: unknown;
      locale: string;
    };
    // Measurement runs on the SAME shape the comparison pane renders: the
    // raw parsed resume gains localized default sectionMeta before measuring.
    expect(measureArg.resumeData.personalInfo.name).toBe('Jane Applicant');
    expect(measureArg.resumeData.sectionMeta.length).toBeGreaterThan(0);
    expect(measureArg.settings).toEqual(DEFAULT_TEMPLATE_SETTINGS);
    expect(measureArg.locale).toBe('zh');

    expect(diagnoseMock).toHaveBeenCalledWith(
      'r-1',
      expect.objectContaining({
        templateSettings: DEFAULT_TEMPLATE_SETTINGS,
        renderedLayout: measuredLayout,
      })
    );
    expect(screen.queryByText('diagnosis.layoutSkipped')).not.toBeInTheDocument();

    // The structured pane renders <Resume> with the same settings and locale.
    const lastProps = mockResumeProps.mock.calls.at(-1)?.[0] as {
      template: string;
      settings: typeof DEFAULT_TEMPLATE_SETTINGS;
      locale: string;
    };
    expect(lastProps.template).toBe(DEFAULT_TEMPLATE_SETTINGS.template);
    expect(lastProps.settings).toEqual(DEFAULT_TEMPLATE_SETTINGS);
    expect(lastProps.locale).toBe('zh');
  });

  it('shows the measuring phase before the diagnosis phase', async () => {
    const measurement = deferred<RenderedLayout>();
    mockMeasureLayout.mockReturnValue(measurement.promise);
    renderWorkspace();
    uploadFromInput();

    expect(await screen.findByText('diagnosis.measuringLayout')).toBeInTheDocument();
    expect(diagnoseMock).not.toHaveBeenCalled();

    await act(async () => {
      measurement.resolve(measuredLayout);
    });
    await waitForReport();
    expect(diagnoseMock).toHaveBeenCalledTimes(1);
  });

  it('still diagnoses without layout fields and shows the neutral fallback note on failure', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    const options = diagnoseMock.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(options.templateSettings).toBeUndefined();
    expect(options.renderedLayout).toBeUndefined();
    expect(screen.getByText('diagnosis.layoutSkipped')).toBeInTheDocument();
  });

  it('re-measures on a JD re-run and keeps the fallback note if measurement keeps failing', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport(6);

    diagnoseMock.mockResolvedValueOnce(reportB);
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.jdToggle' }));
    fireEvent.change(screen.getByPlaceholderText('diagnosis.jobDescriptionPlaceholder'), {
      target: { value: 'Senior Java, JD body' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.jdRun' }));

    await waitFor(() => expect(screen.getByTestId('report-view').textContent).toBe('effective:9'));
    expect(mockMeasureLayout).toHaveBeenCalledTimes(2);
    const jdOptions = diagnoseMock.mock.calls[1]?.[1] as Record<string, unknown>;
    expect(jdOptions.renderedLayout).toBeUndefined();
  });
});

describe('DiagnosisWorkspace resume pane', () => {
  it('shows the parsed markdown in the Original tab', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.originalTab' }));
    const pre = await screen.findByText(/# Jane Applicant/);
    expect(pre.tagName).toBe('PRE');
    expect(pre.textContent).toContain('Markdown body');
    expect(screen.queryByTestId('resume-structured')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.structuredTab' }));
    expect(screen.getByTestId('resume-structured')).toBeInTheDocument();
  });
});

describe('DiagnosisWorkspace JD re-diagnosis', () => {
  it('reuses the resolved title/model, sends the JD and replaces the report', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport(6);

    // Base call consumed the default reportA; queue B for the JD re-run.
    diagnoseMock.mockResolvedValueOnce(reportB);
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.jdToggle' }));
    const textarea = screen.getByPlaceholderText('diagnosis.jobDescriptionPlaceholder');
    fireEvent.change(textarea, { target: { value: 'Senior Java backend, JD content' } });
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.jdRun' }));

    await waitFor(() => expect(screen.getByTestId('report-view').textContent).toBe('effective:9'));
    expect(diagnoseMock).toHaveBeenCalledTimes(2);
    expect(diagnoseMock.mock.calls[1]?.[1]).toEqual({
      jobDescription: 'Senior Java backend, JD content',
      targetTitle: TARGET_TITLE,
      competencyModelKey: 'java-p4',
    });
    // The catalog is only consulted by the automatic base run.
    expect(modelsMock).toHaveBeenCalledTimes(1);
    // JD box collapses after the run.
    expect(
      screen.queryByPlaceholderText('diagnosis.jobDescriptionPlaceholder')
    ).not.toBeInTheDocument();
  });

  it('keeps the previous report and shows an error when the JD re-run fails', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    diagnoseMock.mockResolvedValueOnce(reportA).mockRejectedValueOnce(new Error('llm down'));
    renderWorkspace();
    uploadFromInput();
    await waitForReport(6);

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.jdToggle' }));
    fireEvent.change(screen.getByPlaceholderText('diagnosis.jobDescriptionPlaceholder'), {
      target: { value: 'JD body' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.jdRun' }));

    expect(await screen.findByText('diagnosis.error')).toBeInTheDocument();
    expect(screen.getByTestId('report-view').textContent).toBe('effective:6');
    expect(diagnoseMock.mock.calls[1]?.[1]).toMatchObject({ jobDescription: 'JD body' });
    consoleError.mockRestore();
  });
});

describe('DiagnosisWorkspace Word export', () => {
  it('posts the on-screen report and downloads a date-stamped docx', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.downloadWord' }));
    await waitFor(() => expect(exportMock).toHaveBeenCalledTimes(1));
    expect(exportMock).toHaveBeenCalledWith('r-1', reportA);
    expect(downloadMock).toHaveBeenCalledTimes(1);
    const [, filename] = downloadMock.mock.calls[0] ?? [];
    // 简历诊断报告-姓名-时间 (mocked t() returns the raw key; name from parsed
    // resume personalInfo, stamp YYYYMMDD-HHmm local time).
    expect(filename).toMatch(/^diagnosis\.fileStem-Jane Applicant-\d{8}-\d{4}\.docx$/);
  });

  it('surfaces a download error and can retry', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    exportMock
      .mockRejectedValueOnce(new Error('export failed'))
      .mockResolvedValueOnce(new Blob(['docx-bytes'], { type: 'application/octet-stream' }));
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.downloadWord' }));
    await screen.findByText('diagnosis.downloadFailed');
    expect(downloadMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.downloadWord' }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledTimes(1));
    consoleError.mockRestore();
  });
});

describe('DiagnosisWorkspace delete and close', () => {
  it('plain close never deletes the resume', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onCloseMock).toHaveBeenCalledTimes(1);
    expect(deleteResumeMock).not.toHaveBeenCalled();
  });

  it('deletes a failed parse and returns to the dropzone', async () => {
    fetchResumeMock.mockResolvedValue(emptyReadyRow());
    renderWorkspace();
    uploadFromInput();
    await screen.findByText('diagnosis.workspace.parseFailed');

    const deleteButtons = screen.getAllByRole('button', {
      name: 'diagnosis.workspace.deleteResume',
    });
    // Header + parse-failure card.
    expect(deleteButtons).toHaveLength(2);
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    await confirmDelete();

    expect(deleteResumeMock).toHaveBeenCalledWith('r-1');
    expect(mockStatus.decrementResumes).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'dashboard.uploadResume' })).toBeInTheDocument();
  });

  it('clears master state and refreshes the list when the uploaded resume was master', async () => {
    apiFetchMock.mockResolvedValue(uploadResponse({ is_master: true }));
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.deleteResume' }));
    await confirmDelete();

    expect(deleteResumeMock).toHaveBeenCalledWith('r-1');
    expect(localStorage.getItem('master_resume_id')).toBeNull();
    expect(mockStatus.setHasMasterResume).toHaveBeenLastCalledWith(false);
    expect(mockStatus.decrementResumes).toHaveBeenCalledTimes(1);
    expect(onMutatedMock).toHaveBeenCalledTimes(2);
  });
});

describe('DiagnosisWorkspace pane controls', () => {
  it('moves the divider with arrow keys and collapses/restores panes', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    const separator = screen.getByRole('separator');
    expect(separator).toHaveAttribute('aria-valuenow', '45');
    fireEvent(separator, new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await waitFor(() => expect(separator).toHaveAttribute('aria-valuenow', '47'));
    expect((separator.parentElement as HTMLElement).style.gridTemplateColumns).toContain(
      'minmax(0,47fr)'
    );

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.hideLeft' }));
    await waitFor(() => expect(screen.queryByRole('separator')).not.toBeInTheDocument());
    const grid = screen.getByText('diagnosis.workspace.paneReport').closest('.grid') as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe('0px 0px minmax(0,1fr)');

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.showLeft' }));
    expect(await screen.findByRole('separator')).toHaveAttribute('aria-valuenow', '47');
  });

  it('disables hiding the last visible pane', async () => {
    renderWorkspace();
    uploadFromInput();
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.workspace.hideRight' }));
    expect(screen.getByRole('button', { name: 'diagnosis.workspace.hideLeft' })).toBeDisabled();
  });
});

describe('DiagnosisWorkspace close gating while busy', () => {
  it('cannot be closed while the diagnosis is running, then closes normally', async () => {
    const pending = deferred<DiagnosisReport>();
    diagnoseMock.mockReturnValue(pending.promise);
    renderWorkspace();
    uploadFromInput();

    await screen.findByText('diagnosis.workspace.diagnosing');
    expect(screen.queryByRole('button', { name: 'common.close' })).not.toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(overlay());
    expect(onCloseMock).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'diagnosis.workspace.deleteResume' })).toBeDisabled();

    await act(async () => {
      pending.resolve(reportA);
    });
    await waitForReport();

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onCloseMock).toHaveBeenCalledTimes(1);
  });

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
});
