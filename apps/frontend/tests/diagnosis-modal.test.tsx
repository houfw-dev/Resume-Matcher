import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DiagnosisModal } from '@/components/diagnosis/diagnosis-modal';
import type { CompetencyCatalog, DiagnosisReport } from '@/lib/api/diagnosis';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { LayoutMeasurementError } from '@/lib/utils/measure-resume-layout';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';
import type { RenderedLayout } from '@/lib/types/rendered-layout';

const diagnoseResumeMock = vi.fn();
const exportDiagnosisDocxMock = vi.fn();
const downloadBlobAsFileMock = vi.fn();
const fetchCompetencyModelsMock = vi.fn();
const mockRouterPush = vi.fn();

vi.mock('@/lib/api/diagnosis', () => ({
  diagnoseResume: (...args: unknown[]) => diagnoseResumeMock(...args),
  exportDiagnosisDocx: (...args: unknown[]) => exportDiagnosisDocxMock(...args),
  fetchCompetencyModels: (...args: unknown[]) => fetchCompetencyModelsMock(...args),
}));

vi.mock('@/lib/utils/download', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/utils/download')>();
  return {
    ...actual,
    downloadBlobAsFile: (...args: unknown[]) => downloadBlobAsFileMock(...args),
  };
});

vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'zh' }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: (...args: unknown[]) => mockRouterPush(...args) }),
}));

const measureResumeLayoutMock = vi.fn();
vi.mock('@/lib/utils/measure-resume-layout', () => ({
  LayoutMeasurementError: class LayoutMeasurementError extends Error {},
  measureResumeLayout: (...args: unknown[]) => measureResumeLayoutMock(...args),
}));

// t() returns the key itself with {placeholder} substitution so assertions can
// target stable keys; backend-provided strings (topics, evidence) stay real.
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string, params?: Record<string, string | number>) =>
      key.replace(/\{(\w+)\}/g, (_m, name) => String(params?.[name] ?? '')),
  }),
}));

const MODELS = [
  { key: 'java-p3', name: 'P3 初级Java开发工程师能力模型', family: 'Java', level: 'P3' },
  { key: 'java-p4', name: 'P4 Java开发工程师能力模型', family: 'Java', level: 'P4' },
  { key: 'java-p5', name: 'P5 高级Java开发工程师能力模型', family: 'Java', level: 'P5' },
];

/** Catalog factory: only the Java engineering title auto-matches P4. */
function catalogFor(title?: string): CompetencyCatalog {
  return {
    models: MODELS,
    matched_key: title === 'Java 开发工程师' ? 'java-p4' : null,
  };
}

function makeReport(): DiagnosisReport {
  return {
    resume_id: 'r1',
    spec_version: 'V4',
    language: 'zh',
    target_title: '大数据开发',
    competency_model: null,
    counts: { conform: 1, partial: 0, nonconform: 1, na: 1, effective: 2 },
    redline_passed: false,
    // V4 keeps exactly one red line: item 16 (风险与合规).
    failed_redline_ids: [16],
    dimensions: [
      {
        key: 'appearance',
        name: '简历外观',
        counts: { conform: 1, partial: 0, nonconform: 0, na: 0, effective: 1 },
      },
      {
        key: 'compliance',
        name: '风险与合规',
        counts: { conform: 0, partial: 0, nonconform: 1, na: 0, effective: 1 },
      },
      {
        // All items N/A (JD-gated fit item without a JD): zero applicable.
        key: 'fit',
        name: '目标岗位匹配度',
        counts: { conform: 0, partial: 0, nonconform: 0, na: 1, effective: 0 },
      },
    ],
    redlines: [
      {
        id: 16,
        topic: '风险与合规',
        passed: false,
        rating: 'nonconform',
        evidence: '简历正文出现疑似身份证号 110101…34',
        suggestion: '删除身份证号等敏感信息，改用必要的联系方式',
      },
    ],
    items: [
      {
        id: 1,
        dimension: 'appearance',
        dimension_name: '简历外观',
        sub_dimension: '格式规范',
        topic: '格式规范',
        severity: 'normal',
        judgment_method: 'objective',
        rating: 'conform',
        evidence: '顺序正确',
        suggestion: '',
      },
      {
        id: 16,
        dimension: 'compliance',
        dimension_name: '风险与合规',
        sub_dimension: '风险与合规',
        topic: '风险与合规',
        severity: 'redline',
        judgment_method: 'objective',
        rating: 'nonconform',
        evidence: '简历正文出现疑似身份证号 110101…34',
        suggestion: '删除身份证号等敏感信息，改用必要的联系方式',
      },
      {
        id: 17,
        dimension: 'fit',
        dimension_name: '目标岗位匹配度',
        sub_dimension: '目标岗位匹配度',
        topic: '目标岗位匹配度',
        severity: 'normal',
        judgment_method: 'subjective',
        rating: 'na',
        evidence: '未提供目标岗位 JD，岗位匹配与职级能力相关检查项不适用。',
        suggestion: '',
      },
    ],
    warnings: ['检查项 11 未获得 AI 评级，默认部分符合，请人工复核'],
  } satisfies DiagnosisReport;
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchCompetencyModelsMock.mockImplementation(async (title?: string) => catalogFor(title));
});

describe('DiagnosisModal — request form and target title', () => {
  it('with no intention listed, shows the hint and sends no target with model none', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);

    expect(screen.getByText('diagnosis.targetEmptyHint')).toBeInTheDocument();
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() => expect(diagnoseResumeMock).toHaveBeenCalledTimes(1));
    expect(diagnoseResumeMock).toHaveBeenCalledWith(
      'r1',
      {
        jobDescription: undefined,
        targetTitle: undefined,
        competencyModelKey: 'none',
      },
      expect.any(AbortSignal)
    );
  });

  it('shows a single intention read-only and uses it as the target', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(
      <DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} intentionTitle="大数据开发工程师" />
    );

    // Single intention is bold text, not a target radio; models load below.
    expect(document.querySelector('input[name="diagnosis-target-title"]')).toBeNull();
    expect(screen.getByText('大数据开发工程师')).toBeInTheDocument();
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: undefined,
          targetTitle: '大数据开发工程师',
          competencyModelKey: 'none',
        },
        expect.any(AbortSignal)
      )
    );
  });

  it('offers a radio per intention, defaults to the first, and reports the pick', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(
      <DiagnosisModal
        resumeId="r1"
        open
        onOpenChange={vi.fn()}
        intentionTitle="Java 开发/大数据开发、前端"
      />
    );

    await screen.findByText('diagnosis.modeBasicTitle');
    // The dialog renders through a portal, so query document, not container.
    const targetRadios = document.querySelectorAll('input[name="diagnosis-target-title"]');
    expect(targetRadios).toHaveLength(3);
    expect(screen.getByRole('radio', { name: 'Java 开发' })).toBeChecked();

    fireEvent.click(screen.getByRole('radio', { name: '大数据开发' }));
    expect(screen.getByRole('radio', { name: '大数据开发' })).toBeChecked();
    // Catalog is re-queried for the newly selected title.
    await waitFor(() => expect(fetchCompetencyModelsMock).toHaveBeenCalledWith('大数据开发'));
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: undefined,
          targetTitle: '大数据开发',
          competencyModelKey: 'none',
        },
        expect.any(AbortSignal)
      )
    );
  });

  it('passes a typed job description through to the API', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);

    await screen.findByText('diagnosis.modeBasicTitle');
    // The JD textarea only mounts in JD mode.
    fireEvent.click(screen.getByRole('radio', { name: /modeJdTitle/ }));
    const jdBox = screen.getByLabelText('diagnosis.jobDescriptionLabel');
    // Empty JD mode blocks the run and shows the required hint.
    expect(screen.getByText('diagnosis.jdRequiredHint')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'diagnosis.run' })).toBeDisabled();
    // Model radios never mount in JD mode — the triple overlap is impossible.
    expect(document.querySelector('input[name="diagnosis-competency-model"]')).toBeNull();

    fireEvent.change(jdBox, {
      target: { value: '  Java 架构师岗位  ' },
    });
    expect(screen.getByRole('button', { name: 'diagnosis.run' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: 'Java 架构师岗位',
          targetTitle: undefined,
          competencyModelKey: 'none',
        },
        expect.any(AbortSignal)
      )
    );
  });
});

describe('DiagnosisModal — cancellation', () => {
  it('aborts a running diagnosis from the Cancel button and stays on the form', async () => {
    // The pending call only settles when its AbortSignal fires.
    diagnoseResumeMock.mockImplementation(
      (_resumeId: string, _options: unknown, signal?: AbortSignal) =>
        new Promise<never>((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        })
    );

    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    const cancelButton = await screen.findByRole('button', { name: 'common.cancel' });
    const signal = diagnoseResumeMock.mock.calls[0][2] as AbortSignal;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(false);

    await act(async () => cancelButton.click());

    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole('button', { name: 'common.cancel' })).toBeNull();
    expect(screen.getByRole('button', { name: 'diagnosis.run' })).toBeEnabled();
    // Flush the aborted continuation: the AbortError must not become an error panel.
    await act(async () => {});
    expect(screen.queryByText('diagnosis.error')).toBeNull();

    // The retired run cannot clobber a successor: rerun resolves and renders the report.
    diagnoseResumeMock.mockImplementationOnce(() => Promise.resolve(makeReport()));
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    await waitFor(() => expect(diagnoseResumeMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('diagnosis.countsLabel')).toBeInTheDocument();
  });

  it('aborts the in-flight run when the dialog is closed', async () => {
    diagnoseResumeMock.mockImplementation(
      (_resumeId: string, _options: unknown, signal?: AbortSignal) =>
        new Promise<never>((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        })
    );

    const onOpenChange = vi.fn();
    const { rerender } = render(<DiagnosisModal resumeId="r1" open onOpenChange={onOpenChange} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    const signal = diagnoseResumeMock.mock.calls[0][2] as AbortSignal;

    rerender(<DiagnosisModal resumeId="r1" open={false} onOpenChange={onOpenChange} />);
    expect(signal.aborted).toBe(true);
  });
});

describe('DiagnosisModal — competency model picker', () => {
  it('fetches the catalog for the target title and upgrades into model mode on auto-match', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(
      <DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} intentionTitle="Java 开发工程师" />
    );

    await waitFor(() => expect(fetchCompetencyModelsMock).toHaveBeenCalledWith('Java 开发工程师'));
    await screen.findByText('diagnosis.modelMatchedHint');
    const p4 = screen.getByRole('radio', { name: /P4 Java开发工程师能力模型/ });
    expect(p4).toBeChecked();
    // A confident match switches the modal into model mode; there is no
    // "none" radio anymore — opting out means returning to the basic card.
    expect(screen.getByRole('radio', { name: /modeModelTitle/ })).toBeChecked();
    expect(screen.queryByRole('radio', { name: 'diagnosis.modelNone' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: undefined,
          targetTitle: 'Java 开发工程师',
          competencyModelKey: 'java-p4',
        },
        expect.any(AbortSignal)
      )
    );
  });

  it('stays on basic mode when nothing matches and lets the user pick a level manually', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(
      <DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} intentionTitle="大数据开发工程师" />
    );

    await screen.findByText('diagnosis.modeBasicTitle');
    // No confident match: the modal must not bounce the user into model mode.
    expect(screen.getByRole('radio', { name: /modeBasicTitle/ })).toBeChecked();

    fireEvent.click(screen.getByRole('radio', { name: /modeModelTitle/ }));
    await screen.findByText('diagnosis.modelNoMatchHint');
    fireEvent.click(screen.getByRole('radio', { name: /高级Java开发工程师能力模型/ }));
    expect(screen.getByRole('radio', { name: /高级Java开发工程师能力模型/ })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: undefined,
          targetTitle: '大数据开发工程师',
          competencyModelKey: 'java-p5',
        },
        expect.any(AbortSignal)
      )
    );
  });

  it('lets the user opt out of a title auto-match by returning to the basic card', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(
      <DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} intentionTitle="Java 开发工程师" />
    );

    await screen.findByText('diagnosis.modelMatchedHint');
    expect(screen.getByRole('radio', { name: /P4 Java开发工程师能力模型/ })).toBeChecked();

    // Back to basic: the run carries the explicit 'none' opt-out.
    fireEvent.click(screen.getByRole('radio', { name: /modeBasicTitle/ }));
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: undefined,
          targetTitle: 'Java 开发工程师',
          competencyModelKey: 'none',
        },
        expect.any(AbortSignal)
      )
    );
  });

  it('surfaces a catalog failure only inside model mode and keeps the basic run working', async () => {
    fetchCompetencyModelsMock.mockRejectedValueOnce(new Error('500'));
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);

    await screen.findByText('diagnosis.modeBasicTitle');
    // Basic mode never blocks on the catalog; the error is revealed only when
    // the user explicitly enters model mode.
    expect(screen.queryByText('diagnosis.modelLoadError')).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: /modeModelTitle/ }));
    expect(await screen.findByText('diagnosis.modelLoadError')).toBeInTheDocument();

    // Retry restores the catalog (the default mock serves the next call).
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.modelRetry' }));
    await waitFor(() => expect(fetchCompetencyModelsMock).toHaveBeenCalledTimes(2));

    // A basic run still sends the explicit none opt-out.
    fireEvent.click(screen.getByRole('radio', { name: /modeBasicTitle/ }));
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() =>
      expect(diagnoseResumeMock).toHaveBeenCalledWith(
        'r1',
        {
          jobDescription: undefined,
          targetTitle: undefined,
          competencyModelKey: 'none',
        },
        expect.any(AbortSignal)
      )
    );
  });
});

describe('DiagnosisModal — template layout measurement', () => {
  const measuredResume = {
    personalInfo: { name: '王浩', title: 'Java 开发工程师' },
    workExperience: [
      {
        company: '甲公司',
        title: '工程师',
        years: '2023.01 至今',
        description: ['负责核心系统开发'],
      },
    ],
  } as unknown as ResumeData;

  const fakeLayout: RenderedLayout = {
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
  };

  beforeEach(() => {
    measureResumeLayoutMock.mockReset();
    localStorage.clear();
  });

  const renderModal = () =>
    render(
      <DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} resumeData={measuredResume} />
    );

  it('measures the render with the stored builder settings and ships both fields', async () => {
    measureResumeLayoutMock.mockResolvedValue(fakeLayout);
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    renderModal();

    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() => expect(diagnoseResumeMock).toHaveBeenCalledTimes(1));
    expect(measureResumeLayoutMock).toHaveBeenCalledWith({
      resumeData: measuredResume,
      settings: DEFAULT_TEMPLATE_SETTINGS,
      headingProps: expect.anything(),
      locale: 'zh',
    });
    expect(diagnoseResumeMock).toHaveBeenCalledWith(
      'r1',
      expect.objectContaining({
        templateSettings: DEFAULT_TEMPLATE_SETTINGS,
        renderedLayout: fakeLayout,
      }),
      expect.any(AbortSignal)
    );
    expect(screen.queryByText('diagnosis.layoutSkipped')).not.toBeInTheDocument();
  });

  it('shows the measuring label while the offscreen render is in flight', async () => {
    let resolveLayout!: (layout: RenderedLayout) => void;
    const pending = new Promise<RenderedLayout>((resolve) => {
      resolveLayout = resolve;
    });
    measureResumeLayoutMock.mockReturnValue(pending);
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    renderModal();

    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    expect(await screen.findByText('diagnosis.measuringLayout')).toBeInTheDocument();
    expect(diagnoseResumeMock).not.toHaveBeenCalled();

    await act(async () => {
      resolveLayout(fakeLayout);
    });
    await screen.findByText('diagnosis.countsLabel');
    expect(diagnoseResumeMock).toHaveBeenCalledTimes(1);
  });

  it('still diagnoses without layout fields and shows the neutral fallback note on failure', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    measureResumeLayoutMock.mockRejectedValue(
      new LayoutMeasurementError('resume rendered with zero height')
    );
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    renderModal();

    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() => expect(diagnoseResumeMock).toHaveBeenCalledTimes(1));
    const options = diagnoseResumeMock.mock.calls[0]?.[1] as Record<string, unknown>;
    expect(options.templateSettings).toBeUndefined();
    expect(options.renderedLayout).toBeUndefined();
    expect(await screen.findByText('diagnosis.layoutSkipped')).toBeInTheDocument();
    warnSpy.mockRestore();
  });

  it('never measures when no resume data is supplied', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);

    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    await waitFor(() => expect(diagnoseResumeMock).toHaveBeenCalledTimes(1));
    expect(measureResumeLayoutMock).not.toHaveBeenCalled();
    expect(screen.queryByText('diagnosis.layoutSkipped')).not.toBeInTheDocument();
  });
});

describe('DiagnosisModal — checklist report', () => {
  it('renders counts (no score), failed red line, warnings and grouped items', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);

    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    expect(await screen.findByText('diagnosis.countsLabel')).toBeInTheDocument();
    // Overall counts line plus one per dimension (3 dimensions).
    expect(screen.getAllByText('diagnosis.countsSummary')).toHaveLength(4);
    // Score-era UI is gone.
    expect(screen.queryByText('/100')).not.toBeInTheDocument();
    expect(screen.queryByText('良')).not.toBeInTheDocument();
    // V4 has exactly one red line (item 16): the banner lists it by its
    // public topic, and the same finding renders in the compliance item row.
    expect(screen.getByText('diagnosis.redlineFailed')).toBeInTheDocument();
    expect(screen.getAllByText('风险与合规').length).toBeGreaterThanOrEqual(2);
    // Confidential rule wording (一票否决 / the internal standard) is never
    // sent to the client — the row carries only a localized severity key.
    expect(screen.queryByText('一票否决')).not.toBeInTheDocument();
    expect(screen.getByText(/检查项 11/)).toBeInTheDocument();
    // Conforming item visible under its dimension heading: the sub-dimension
    // label and the topic both show the same text.
    expect(screen.getAllByText('格式规范')).toHaveLength(2);
    // Evidence and suggestion rendered
    expect(screen.getByText('简历正文出现疑似身份证号 110101…34')).toBeInTheDocument();
    expect(screen.getByText('删除身份证号等敏感信息，改用必要的联系方式')).toBeInTheDocument();
  });

  it('shows the pass banner and no failure list when the sole red line passes', async () => {
    const passed: DiagnosisReport = {
      ...makeReport(),
      counts: { conform: 2, partial: 0, nonconform: 0, na: 1, effective: 2 },
      redline_passed: true,
      failed_redline_ids: [],
      redlines: [
        {
          id: 16,
          topic: '风险与合规',
          passed: true,
          rating: 'conform',
          evidence: '未发现身份证号、银行卡号等敏感信息',
          suggestion: '',
        },
      ],
      items: makeReport().items.map((item) =>
        item.id === 16
          ? {
              ...item,
              rating: 'conform' as const,
              evidence: '未发现身份证号、银行卡号等敏感信息',
              suggestion: '',
            }
          : item
      ),
    };
    diagnoseResumeMock.mockResolvedValueOnce(passed);
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    expect(await screen.findByText('diagnosis.redlinePassed')).toBeInTheDocument();
    expect(screen.queryByText('diagnosis.redlineFailed')).not.toBeInTheDocument();
  });

  it('problems filter hides conforming and N/A items', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    await screen.findByText('diagnosis.countsLabel');

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.filterProblems' }));

    await waitFor(() => expect(screen.queryByText('格式规范')).not.toBeInTheDocument());
    // The failed #16 red-line finding stays (banner + problem item row).
    expect(screen.getByText('简历正文出现疑似身份证号 110101…34')).toBeInTheDocument();
    // The N/A JD-gated item's evidence is hidden under the problems filter
    // (the dimension name still shows in the counts summary).
    expect(screen.queryByText(/未提供目标岗位 JD/)).not.toBeInTheDocument();
  });

  it('downloads the Word report, posting the on-screen report back to the API', async () => {
    const report = makeReport();
    diagnoseResumeMock.mockResolvedValueOnce(report);
    const blob = new Blob(['PKdocx'], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    exportDiagnosisDocxMock.mockResolvedValueOnce(blob);
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    await screen.findByText('diagnosis.countsLabel');

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.downloadWord' }));

    await waitFor(() => expect(exportDiagnosisDocxMock).toHaveBeenCalledTimes(1));
    // The whole rendered report is posted back so the backend makes no second
    // LLM call; the same resume id scopes the candidate-name lookup.
    expect(exportDiagnosisDocxMock).toHaveBeenCalledWith('r1', report);
    await waitFor(() => expect(downloadBlobAsFileMock).toHaveBeenCalledTimes(1));
    const [savedBlob, filename] = downloadBlobAsFileMock.mock.calls[0];
    expect(savedBlob).toBe(blob);
    // Mocked t() returns the raw key; without a candidate name the browser
    // saves e.g. diagnosis.fileStem-20261030-2156.docx (real locale renders
    // 简历诊断报告-20261030-2156.docx).
    expect(filename).toMatch(/^diagnosis\.fileStem-\d{8}-\d{4}\.docx$/);
  });

  it('shows a download error and allows retrying the download', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    exportDiagnosisDocxMock.mockRejectedValueOnce(new Error('500'));
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    await screen.findByText('diagnosis.countsLabel');

    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.downloadWord' }));

    expect(await screen.findByText('diagnosis.downloadFailed')).toBeInTheDocument();

    const blob = new Blob(['PKdocx']);
    exportDiagnosisDocxMock.mockResolvedValueOnce(blob);
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.downloadWord' }));
    await waitFor(() => expect(downloadBlobAsFileMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('diagnosis.downloadFailed')).not.toBeInTheDocument();
  });

  it('shows a generic error with retry when the API fails', async () => {
    diagnoseResumeMock.mockRejectedValueOnce(new Error('network'));
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    expect(await screen.findByText('diagnosis.error')).toBeInTheDocument();

    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(await screen.findByText('diagnosis.countsLabel')).toBeInTheDocument();
    expect(diagnoseResumeMock).toHaveBeenCalledTimes(2);
  });

  /** Report whose only problem is item 9 (项目经验 → personalProjects). */
  function makeFixableReport(): DiagnosisReport {
    return {
      ...makeReport(),
      redline_passed: true,
      failed_redline_ids: [],
      redlines: [],
      dimensions: [
        {
          key: 'content',
          name: '撰写规范',
          counts: { conform: 0, partial: 0, nonconform: 1, na: 0, effective: 1 },
        },
      ],
      items: [
        {
          id: 9,
          dimension: 'content',
          dimension_name: '撰写规范',
          sub_dimension: '项目经验',
          topic: '项目经验',
          severity: 'normal',
          judgment_method: 'objective',
          rating: 'nonconform',
          evidence: '项目缺少技术栈字段。',
          suggestion: '为每个项目补一行技术栈。',
        },
      ],
    };
  }

  it('deep-links from the fix CTA to the owning builder section and closes the modal', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeFixableReport());
    const onOpenChange = vi.fn();
    render(<DiagnosisModal resumeId="r1" open onOpenChange={onOpenChange} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));

    const fixButton = await screen.findByRole('button', {
      name: 'diagnosis.fixInBuilder',
    });
    fireEvent.click(fixButton);

    expect(mockRouterPush).toHaveBeenCalledWith(
      '/builder?id=r1&tab=resume&section=personalProjects'
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('renders no fix CTA for problem items without a single owning section (e.g. red line #16)', async () => {
    diagnoseResumeMock.mockResolvedValueOnce(makeReport());
    render(<DiagnosisModal resumeId="r1" open onOpenChange={vi.fn()} />);
    await screen.findByText('diagnosis.modeBasicTitle');
    fireEvent.click(screen.getByRole('button', { name: 'diagnosis.run' }));
    await screen.findByText('diagnosis.countsLabel');

    expect(screen.queryByRole('button', { name: 'diagnosis.fixInBuilder' })).toBeNull();
  });
});
