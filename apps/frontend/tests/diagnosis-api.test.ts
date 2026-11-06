import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { diagnoseResume, fetchCompetencyModels } from '@/lib/api/diagnosis';
import type { DiagnosisReport } from '@/lib/api/diagnosis';

const report: DiagnosisReport = {
  resume_id: 'r1',
  spec_version: 'V4',
  language: 'zh',
  target_title: 'Java 开发工程师',
  competency_model: null,
  counts: { conform: 12, partial: 2, nonconform: 1, na: 7, effective: 15 },
  redline_passed: false,
  failed_redline_ids: [16],
  dimensions: [],
  redlines: [],
  items: [],
  warnings: [],
};

describe('diagnoseResume', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts to the diagnosis route with null JD, target and model when omitted', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(report), { status: 200 }));

    await expect(diagnoseResume('r1')).resolves.toEqual(report);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/r1/diagnose');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      job_description: null,
      target_title: null,
      competency_model_key: null,
    });
  });

  it('sends trimmed JD, target title and model key, and maps error detail into a throw', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    await diagnoseResume('r1', {
      jobDescription: '  Java architect  ',
      targetTitle: '  大数据开发工程师 ',
      competencyModelKey: 'java-p7',
    });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      job_description: 'Java architect',
      target_title: '大数据开发工程师',
      competency_model_key: 'java-p7',
    });

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Resume has no processed data.' }), { status: 400 })
    );
    await expect(diagnoseResume('r1')).rejects.toThrow('Resume has no processed data.');
  });

  it('sends the explicit no-model sentinel when the user opts out', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(report), { status: 200 }));
    await diagnoseResume('r1', { competencyModelKey: 'none' });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).competency_model_key).toBe('none');
  });

  it('ships template settings and measured layout only as a pair', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(report), { status: 200 }));
    const templateSettings = {
      template: 'vivid',
      pageSize: 'LETTER',
      margins: { top: 8, bottom: 8, left: 8, right: 8 },
      spacing: { section: 2, item: 1, lineHeight: 2 },
      fontSize: { base: 2, headerScale: 3, headerFont: 'serif', bodyFont: 'sans-serif' },
      compactMode: true,
      showContactIcons: false,
      accentColor: 'green',
    };
    const renderedLayout = {
      schema_version: 1,
      measured_at: '2026-10-24T10:00:00.000Z',
      template: 'vivid',
      page_size: 'LETTER',
      margins: { top: 8, bottom: 8, left: 8, right: 8 },
      content_width_px: 742,
      content_height_px: 986,
      page_count: 2,
      total_height_px: 1900,
      two_column: true,
      header: { height_px: 100, cell_count: 3, rows: [{ cells: 3 }] },
      sections: [],
      points: [],
      page_mirror: [{ page: 1, text: '镜像' }],
      warnings: [],
    };
    await diagnoseResume('r1', {
      templateSettings: templateSettings as never,
      renderedLayout: renderedLayout as never,
    });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.template_settings).toEqual(templateSettings);
    expect(body.rendered_layout).toEqual(renderedLayout);
  });

  it('omits both layout fields when only one side is available', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(report), { status: 200 }));
    await diagnoseResume('r1', {
      renderedLayout: { page_count: 1 } as never,
    });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).not.toHaveProperty('template_settings');
    expect(body).not.toHaveProperty('rendered_layout');
  });
});

describe('fetchCompetencyModels', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const catalog = {
    models: [
      { key: 'java-p3', name: 'P3 初级Java开发工程师能力模型', family: 'Java', level: 'P3' },
      { key: 'java-p4', name: 'P4 Java开发工程师能力模型', family: 'Java', level: 'P4' },
    ],
    matched_key: null,
  };

  it('fetches the catalog without a query when no title is given', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(catalog), { status: 200 }));

    await expect(fetchCompetencyModels()).resolves.toEqual(catalog);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/diagnosis/competency-models');
  });

  it('encodes the trimmed target title as a query parameter', async () => {
    const matched = { ...catalog, matched_key: 'java-p4' };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(matched), { status: 200 }));

    const result = await fetchCompetencyModels('  Java 开发工程师 ');
    expect(result.matched_key).toBe('java-p4');
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/diagnosis/competency-models?title=Java%20%E5%BC%80%E5%8F%91%E5%B7%A5%E7%A8%8B%E5%B8%88'
    );
  });

  it('throws on a non-OK catalog response', async () => {
    fetchMock.mockResolvedValue(new Response('nope', { status: 500 }));
    await expect(fetchCompetencyModels('Java')).rejects.toThrow(/competency models/);
  });
});
