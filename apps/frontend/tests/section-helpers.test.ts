import { describe, expect, it } from 'vitest';
import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';
import {
  DEFAULT_SECTION_META,
  createCustomSection,
  ensureDefaultSectionMeta,
  generateCustomSectionId,
  getAllSections,
  getSectionMeta,
  getSortedSections,
  localizeDefaultSectionMeta,
  migrateTextSectionToSummary,
  withLocalizedDefaultSections,
} from '@/lib/utils/section-helpers';

/** Pure resume-section metadata logic (ordering, custom IDs, localization). */

function meta(overrides: Partial<SectionMeta>): SectionMeta {
  return {
    id: 'x',
    key: 'x',
    displayName: 'X',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 0,
    ...overrides,
  } as SectionMeta;
}

function resume(sectionMeta?: SectionMeta[]): ResumeData {
  return { sectionMeta } as unknown as ResumeData;
}

describe('DEFAULT_SECTION_META', () => {
  it('follows the formal-degree canonical order (education second)', () => {
    expect(DEFAULT_SECTION_META.map((s) => s.id)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]);
    expect(DEFAULT_SECTION_META.map((s) => s.order)).toEqual([0, 1, 2, 3, 4, 5]);
  });
});

describe('getSectionMeta', () => {
  it('returns the resume sectionMeta when present', () => {
    const sm = [meta({ id: 'a' })];
    expect(getSectionMeta(resume(sm))).toBe(sm);
  });

  it('falls back to DEFAULT_SECTION_META when missing or empty', () => {
    expect(getSectionMeta(resume(undefined))).toBe(DEFAULT_SECTION_META);
    expect(getSectionMeta(resume([]))).toBe(DEFAULT_SECTION_META);
  });
});

describe('getSortedSections', () => {
  it('keeps only visible sections, sorted by order', () => {
    const sm = [
      meta({ id: 'c', order: 2, isVisible: true }),
      meta({ id: 'a', order: 0, isVisible: true }),
      meta({ id: 'hidden', order: 1, isVisible: false }),
    ];
    expect(getSortedSections(resume(sm)).map((s) => s.id)).toEqual(['a', 'c']);
  });
});

describe('getAllSections', () => {
  it('includes hidden sections, sorted by order', () => {
    const sm = [
      meta({ id: 'b', order: 1, isVisible: false }),
      meta({ id: 'a', order: 0, isVisible: true }),
    ];
    expect(getAllSections(resume(sm)).map((s) => s.id)).toEqual(['a', 'b']);
  });
});

describe('generateCustomSectionId', () => {
  it('starts at custom_1 when none exist', () => {
    expect(generateCustomSectionId([])).toBe('custom_1');
    expect(generateCustomSectionId([meta({ id: 'summary' })])).toBe('custom_1');
  });

  it('increments past the highest existing custom id', () => {
    const sections = [meta({ id: 'custom_1' }), meta({ id: 'custom_3' })];
    expect(generateCustomSectionId(sections)).toBe('custom_4');
  });
});

describe('createCustomSection', () => {
  it('creates a non-default visible section after the last order', () => {
    const existing = [meta({ id: 'summary', order: 5 })];
    const created = createCustomSection(existing, 'Volunteering', 'itemList');
    expect(created.id).toBe('custom_1');
    expect(created.displayName).toBe('Volunteering');
    expect(created.sectionType).toBe('itemList');
    expect(created.isDefault).toBe(false);
    expect(created.isVisible).toBe(true);
    expect(created.order).toBe(6); // maxOrder + 1
  });
});

describe('localizeDefaultSectionMeta', () => {
  const t = (key: string) => `t:${key}`;

  it('localizes a default section whose name is still the English default', () => {
    const out = localizeDefaultSectionMeta(
      [meta({ id: 'summary', displayName: 'Summary', isDefault: true })],
      t
    );
    expect(out[0].displayName).toBe('t:resume.sections.summary');
  });

  it('overwrites a renamed default section title (titles are locked)', () => {
    const out = localizeDefaultSectionMeta(
      [meta({ id: 'summary', displayName: 'My Story', isDefault: true })],
      t
    );
    expect(out[0].displayName).toBe('t:resume.sections.summary');
  });

  it('leaves non-default (custom) sections untouched', () => {
    const out = localizeDefaultSectionMeta(
      [meta({ id: 'custom_1', displayName: 'Summary', isDefault: false })],
      t
    );
    expect(out[0].displayName).toBe('Summary');
  });

  it('canonicalizes zh alias headings for 自我介绍 custom blocks only', () => {
    const out = localizeDefaultSectionMeta(
      [
        meta({ id: 'custom_eval', key: 'custom_eval', displayName: '个人简介', isDefault: false }),
        meta({
          id: 'custom_intro',
          key: 'custom_intro',
          displayName: '个人简述',
          isDefault: false,
        }),
        meta({
          id: 'custom_eval2',
          key: 'custom_eval2',
          displayName: '个人评价',
          isDefault: false,
        }),
        // Legacy honors headings lost their canonical slot: they render verbatim.
        meta({
          id: 'custom_honors',
          key: 'custom_honors',
          displayName: '获奖情况',
          isDefault: false,
        }),
        meta({ id: 'custom_cert', key: 'custom_cert', displayName: '资格证书', isDefault: false }),
        meta({
          id: 'custom_hobby',
          key: 'custom_hobby',
          displayName: '兴趣爱好',
          isDefault: false,
        }),
      ],
      t
    );
    expect(out.map((s) => s.displayName)).toEqual([
      't:resume.sections.selfIntroduction',
      't:resume.sections.selfIntroduction',
      't:resume.sections.selfIntroduction',
      '获奖情况',
      '资格证书',
      '兴趣爱好',
    ]);
  });
});

describe('withLocalizedDefaultSections', () => {
  const t = (key: string) => `t:${key}`;

  it('generates localized defaults when the resume has no sectionMeta', () => {
    const out = withLocalizedDefaultSections(resume(undefined), t);
    expect(out.sectionMeta).toHaveLength(DEFAULT_SECTION_META.length);
    const summary = out.sectionMeta!.find((s) => s.id === 'summary');
    expect(summary!.displayName).toBe('t:resume.sections.summary');
  });

  it('renders work/education entries newest-first', () => {
    const data = {
      ...resume(undefined),
      workExperience: [
        { company: 'Old', years: '2018.05 - 2020.11' },
        { company: 'New', years: '2020.12 - 2026.04' },
      ],
      education: [
        { institution: 'Bachelor', years: '2010.09 - 2014.06' },
        { institution: 'Master', years: '2014.09 - 2017.06' },
      ],
    } as ResumeData;
    const out = withLocalizedDefaultSections(data, t);
    expect(out.workExperience!.map((entry) => entry.company)).toEqual(['New', 'Old']);
    expect(out.education!.map((entry) => entry.institution)).toEqual(['Master', 'Bachelor']);
  });
});

describe('ensureDefaultSectionMeta', () => {
  const baseMeta: SectionMeta[] = DEFAULT_SECTION_META.map((section) => ({ ...section }));

  it('returns the stored rows untouched when every default block exists', () => {
    const data = { ...resume(baseMeta), summary: '已有优势' } as ResumeData;
    const out = ensureDefaultSectionMeta(data);
    expect(out).toHaveLength(DEFAULT_SECTION_META.length);
    expect(out.map((s) => s.key)).toEqual(DEFAULT_SECTION_META.map((s) => s.key));
  });

  it('inserts a missing empty optional block (个人优势) as visible — built-ins are always listed', () => {
    // Mirrors an uploaded resume whose sectionMeta omits summary entirely.
    // The editor always lists built-in blocks; an empty optional block is
    // hidden from the resume/PDF downstream, not in the builder.
    const stored = baseMeta.filter((section) => section.key !== 'summary');
    const data = { ...resume(stored), summary: '' } as ResumeData;
    const out = ensureDefaultSectionMeta(data);
    const summary = out.find((s) => s.key === 'summary');
    expect(summary).toBeDefined();
    expect(summary!.isVisible).toBe(true);
  });

  it('inserts a missing content-bearing summary block as visible', () => {
    const stored = baseMeta.filter((section) => section.key !== 'summary');
    const data = { ...resume(stored), summary: '主导多个 0 到 1 项目' } as ResumeData;
    const out = ensureDefaultSectionMeta(data);
    expect(out.find((s) => s.key === 'summary')!.isVisible).toBe(true);
  });

  it('never mutates the stored rows or the DEFAULT_SECTION_META constant', () => {
    const stored = baseMeta.filter((section) => section.key !== 'summary');
    const frozen = JSON.stringify(stored);
    const defaultSnapshot = JSON.stringify(DEFAULT_SECTION_META);
    ensureDefaultSectionMeta({ ...resume(stored) });
    expect(JSON.stringify(stored)).toBe(frozen);
    expect(JSON.stringify(DEFAULT_SECTION_META)).toBe(defaultSnapshot);
  });
});

describe('migrateTextSectionToSummary', () => {
  const selfEvalMeta: SectionMeta = meta({
    id: 'self_evaluation',
    key: 'self_evaluation',
    displayName: '自我评价',
    sectionType: 'text',
    isDefault: false,
    order: 6,
  });

  it('moves a 自我评价 text block into 个人优势 and deletes the custom block', () => {
    const data = {
      summary: '',
      sectionMeta: [
        ...DEFAULT_SECTION_META.filter((s) => s.key !== 'summary').map((s) => ({ ...s })),
        selfEvalMeta,
      ],
      customSections: {
        self_evaluation: { sectionType: 'text', text: '学习能力强，乐于分享。' },
      },
    } as ResumeData;

    const out = migrateTextSectionToSummary(data, 'self_evaluation');
    expect(out).not.toBeNull();
    expect(out!.summary).toBe('学习能力强，乐于分享。');
    expect(out!.customSections!.self_evaluation).toBeUndefined();
    const keys = out!.sectionMeta!.map((s) => s.key);
    expect(keys).toContain('summary');
    expect(keys).not.toContain('self_evaluation');
    expect(out!.sectionMeta!.find((s) => s.key === 'summary')!.isVisible).toBe(true);
    // Input is never mutated.
    expect(data.summary).toBe('');
    expect(data.customSections!.self_evaluation.text).toBe('学习能力强，乐于分享。');
  });

  it('appends to an existing 个人优势 without duplicating contained text', () => {
    const data = {
      summary: '具备架构设计经验。',
      sectionMeta: [...DEFAULT_SECTION_META.map((s) => ({ ...s })), selfEvalMeta],
      customSections: {
        self_evaluation: { sectionType: 'text', text: '学习能力强，乐于分享。' },
      },
    } as ResumeData;

    const out = migrateTextSectionToSummary(data, 'self_evaluation')!;
    expect(out.summary).toBe('具备架构设计经验。\n学习能力强，乐于分享。');

    // Running it conceptually twice with text already contained adds nothing.
    const again = migrateTextSectionToSummary(
      {
        ...out,
        customSections: { dup: { sectionType: 'text', text: '具备架构设计经验。' } },
        sectionMeta: [...out.sectionMeta!, meta({ id: 'dup', key: 'dup', displayName: '重复块' })],
      },
      'dup'
    )!;
    expect(again.summary).toBe('具备架构设计经验。\n学习能力强，乐于分享。');
  });

  it('refuses to migrate a non-text (list) custom section', () => {
    const data = {
      summary: '',
      sectionMeta: [meta({ id: 'custom_1', key: 'custom_1', sectionType: 'itemList' })],
      customSections: { custom_1: { sectionType: 'itemList', items: [] } },
    } as ResumeData;
    expect(migrateTextSectionToSummary(data, 'custom_1')).toBeNull();
    expect(migrateTextSectionToSummary(data, 'missing')).toBeNull();
  });
});
