import { describe, expect, it } from 'vitest';

import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';
import { normalizeResumeForRender, normalizeResumeForSave } from '@/lib/utils/resume-normalization';

const baseResume = {
  personalInfo: {
    name: 'Ada Lovelace',
    title: 'Software Engineer',
    email: 'ada@example.com',
  },
  summary: '',
  workExperience: [],
  education: [],
  personalProjects: [],
  additional: {},
} satisfies ResumeData;

describe('resume normalization', () => {
  it('drops empty description placeholders from the canonical save payload', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: 'Engineer',
          company: 'Analytical Engines Inc',
          years: '2024 - Present',
          description: ['', 'Built reliable systems', '   '],
        },
      ],
    };

    expect(normalizeResumeForSave(editorState).workExperience?.[0]).toMatchObject({
      description: ['Built reliable systems'],
    });
    expect(editorState.workExperience?.[0].description).toEqual([
      '',
      'Built reliable systems',
      '   ',
    ]);
  });

  it('persists work/education entries newest-first', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        { id: 1, company: 'Old', years: '2018.05 - 2020.11' },
        { id: 2, company: 'New', years: '2020.12 - 2026.04' },
      ],
      education: [
        { id: 1, institution: 'Bachelor', years: '2010.09 - 2014.06' },
        { id: 2, institution: 'Master', years: '2014.09 - 2017.06' },
      ],
    };

    const saved = normalizeResumeForSave(editorState);
    expect(saved.workExperience?.map((entry) => entry.company)).toEqual(['New', 'Old']);
    expect(saved.education?.map((entry) => entry.institution)).toEqual(['Master', 'Bachelor']);
  });

  it('drops entirely empty editor-only experience entries from the save payload', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: '',
          company: '',
          location: '',
          years: '',
          description: [''],
        },
      ],
    };

    expect(normalizeResumeForSave(editorState).workExperience).toEqual([]);
  });

  it('keeps an entry that only has a department and preserves the value', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: '',
          company: '',
          department: '平台研发部',
          location: '',
          years: '',
          description: [''],
        },
      ],
    };

    const saved = normalizeResumeForSave(editorState).workExperience;
    expect(saved).toHaveLength(1);
    expect(saved?.[0].department).toBe('平台研发部');
  });

  it('drops an entry whose only content is a whitespace-only department', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: '',
          company: '',
          department: '   ',
          location: '',
          years: '',
          description: [],
        },
      ],
    };

    expect(normalizeResumeForSave(editorState).workExperience).toEqual([]);
  });

  it('normalizes custom item-list sections for rendering and saving', () => {
    const editorState: ResumeData = {
      ...baseResume,
      customSections: {
        custom_1: {
          sectionType: 'itemList',
          items: [
            {
              id: 1,
              title: 'Publication',
              description: ['', 'Accepted at a systems workshop'],
            },
          ],
        },
      },
    };

    const normalized = normalizeResumeForRender(editorState);

    expect(normalized.customSections?.custom_1.items?.[0].description).toEqual([
      'Accepted at a systems workshop',
    ]);
  });

  it('ignores malformed persisted list and description values during normalization', () => {
    const malformedState = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: 'Engineer',
          company: 'Analytical Engines Inc',
          years: '2024 - Present',
          description: 'not-an-array',
        },
      ],
      additional: {
        technicalSkills: ['TypeScript', null, '  '],
        languages: 'not-an-array',
      },
    } as unknown as ResumeData;

    const normalized = normalizeResumeForSave(malformedState);

    expect(normalized.workExperience?.[0].description).toEqual([]);
    expect(normalized.additional?.technicalSkills).toEqual(['TypeScript']);
    expect(normalized.additional?.languages).toEqual([]);
  });

  it('keeps descriptionStyles aligned when blank description points are dropped', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: 'Engineer',
          company: 'Analytical Engines Inc',
          years: '2024 - Present',
          description: ['', 'Led the migration', 'Cut costs 40%'],
          descriptionStyles: ['bullet', 'plain', 'bullet'],
        },
      ],
    };

    const normalized = normalizeResumeForSave(editorState);
    const experience = normalized.workExperience?.[0];

    // The blank first point is dropped, so its style must be dropped with it —
    // otherwise 'Led the migration' inherits 'bullet' and 'Cut costs 40%'
    // inherits 'plain', silently flipping both.
    expect(experience?.description).toEqual(['Led the migration', 'Cut costs 40%']);
    expect(experience?.descriptionStyles).toEqual(['plain', 'bullet']);
  });

  it('leaves items without descriptionStyles untouched', () => {
    const editorState: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          title: 'Engineer',
          company: 'Analytical Engines Inc',
          years: '2024 - Present',
          description: ['', 'Shipped it'],
        },
      ],
    };

    const experience = normalizeResumeForSave(editorState).workExperience?.[0];

    expect(experience?.description).toEqual(['Shipped it']);
    expect(experience).not.toHaveProperty('descriptionStyles');
  });

  it('preserves the label style and project scale when normalizing', () => {
    const editorState: ResumeData = {
      ...baseResume,
      personalProjects: [
        {
          id: 1,
          name: '订单系统',
          scale: '10 人团队',
          description: ['负责内容', '主导交易链路重构'],
          descriptionStyles: ['label', 'bullet'],
        },
      ],
    };

    const project = normalizeResumeForSave(editorState).personalProjects?.[0];

    expect(project?.scale).toBe('10 人团队');
    expect(project?.descriptionStyles).toEqual(['label', 'bullet']);
  });
});

describe('normalization robustness against malformed persisted data', () => {
  // These inputs are not reachable from the editor, but they ARE reachable from
  // hand-edited localStorage or a legacy server row, and each one used to throw
  // or leak a bad value into the canonical PATCH payload.
  const malformed = (over: Record<string, unknown>): ResumeData =>
    ({ ...baseResume, ...over }) as unknown as ResumeData;

  it('coerces a null string list to [] instead of leaking null', () => {
    const out = normalizeResumeForSave(
      malformed({ additional: { technicalSkills: null, languages: undefined } })
    );

    expect(out.additional?.technicalSkills).toEqual([]);
    // `undefined` still means "absent" and is preserved.
    expect(out.additional?.languages).toBeUndefined();
  });

  it('does not throw on non-string scalar fields', () => {
    expect(() =>
      normalizeResumeForSave(
        malformed({ workExperience: [{ id: 1, title: 5, description: ['ok'] }] })
      )
    ).not.toThrow();
  });

  it('does not throw on a non-array description', () => {
    expect(() =>
      normalizeResumeForSave(
        malformed({ personalProjects: [{ id: 1, name: 'P', description: 'not-an-array' }] })
      )
    ).not.toThrow();
  });

  it('does not throw on a non-array custom itemList', () => {
    expect(() =>
      normalizeResumeForSave(
        malformed({
          customSections: { custom_1: { sectionType: 'itemList', items: { bogus: true } } },
        })
      )
    ).not.toThrow();
  });

  it('does not throw when top-level collections are not arrays', () => {
    expect(() =>
      normalizeResumeForSave(malformed({ workExperience: null, personalProjects: 'nope' }))
    ).not.toThrow();
  });
});

describe('normalization robustness — element level', () => {
  const malformed = (over: Record<string, unknown>): ResumeData =>
    ({ ...baseResume, ...over }) as unknown as ResumeData;

  it('drops null and primitive entries inside otherwise-valid arrays', () => {
    // Container guards were not enough: a null element throws on property
    // access inside normalizeDescriptionFields.
    const out = normalizeResumeForSave(
      malformed({
        workExperience: [null, { id: 1, title: 'Engineer' }, 'nope', undefined],
        personalProjects: [null, { id: 2, name: 'Proj' }],
      })
    );

    expect(out.workExperience).toHaveLength(1);
    expect(out.workExperience?.[0].title).toBe('Engineer');
    expect(out.personalProjects).toHaveLength(1);
  });

  it('drops null entries inside a custom itemList', () => {
    const out = normalizeResumeForSave(
      malformed({
        customSections: {
          custom_1: { sectionType: 'itemList', items: [null, { id: 1, title: 'C' }] },
        },
      })
    );

    expect(out.customSections?.custom_1.items).toHaveLength(1);
  });
});

describe('normalization robustness — sections and education', () => {
  const malformed = (over: Record<string, unknown>): ResumeData =>
    ({ ...baseResume, ...over }) as unknown as ResumeData;

  it('does not throw on a null customSections entry', () => {
    expect(() =>
      normalizeResumeForSave(malformed({ customSections: { broken: null, ok: undefined } }))
    ).not.toThrow();
  });

  it('drops null and primitive education entries', () => {
    const out = normalizeResumeForSave(
      malformed({ education: [null, { id: 1, institution: 'MIT' }, 'nope'] })
    );

    expect(out.education).toHaveLength(1);
    expect(out.education?.[0].institution).toBe('MIT');
  });

  it('does not throw when education is not an array', () => {
    expect(() => normalizeResumeForSave(malformed({ education: null }))).not.toThrow();
  });
});

describe('sectionMeta canonicalization on save', () => {
  const meta = (over: Partial<SectionMeta>) => ({
    id: 'x',
    key: 'x',
    displayName: 'X',
    sectionType: 'text' as const,
    isDefault: false,
    isVisible: true,
    order: 0,
    ...over,
  });

  it('rewrites scrambled meta to dense formal-branch order and resets renamed defaults', () => {
    const state: ResumeData = {
      ...baseResume,
      summary: '有内容的个人优势',
      education: [{ id: 1, degree: '统招本科' }],
      sectionMeta: [
        meta({
          id: 'workExperience',
          key: 'workExperience',
          displayName: 'Experience',
          sectionType: 'itemList',
          isDefault: true,
          order: 0,
        }),
        meta({
          id: 'personalInfo',
          key: 'personalInfo',
          displayName: 'Personal Info',
          sectionType: 'personalInfo',
          isDefault: true,
          order: 1,
        }),
        meta({
          id: 'education',
          key: 'education',
          displayName: 'Education',
          sectionType: 'itemList',
          isDefault: true,
          order: 2,
        }),
        meta({ id: 'summary', key: 'summary', displayName: '我的故事', isDefault: true, order: 3 }),
        meta({
          id: 'additional',
          key: 'additional',
          displayName: 'Skills & Awards',
          sectionType: 'stringList',
          isDefault: true,
          order: 4,
        }),
        meta({
          id: 'personalProjects',
          key: 'personalProjects',
          displayName: 'Projects',
          sectionType: 'itemList',
          isDefault: true,
          order: 5,
        }),
      ],
    };

    const saved = normalizeResumeForSave(state);
    expect(saved.sectionMeta?.map((m) => m.key)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]);
    expect(saved.sectionMeta?.map((m) => m.order)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(saved.sectionMeta?.find((m) => m.key === 'summary')?.displayName).toBe('Summary');
  });

  it('hides optional blocks whose content is pruned away, keeps required blocks visible', () => {
    const state: ResumeData = {
      ...baseResume,
      education: [{ id: 1, degree: '大专' }],
      customSections: {
        custom_empty: {
          sectionType: 'itemList',
          items: [{ id: 1, title: '   ', description: [''] }],
        },
        custom_filled: { sectionType: 'text', text: '证书内容' },
      },
      sectionMeta: [
        meta({
          id: 'personalInfo',
          key: 'personalInfo',
          displayName: 'Personal Info',
          sectionType: 'personalInfo',
          isDefault: true,
        }),
        meta({ id: 'summary', key: 'summary', displayName: 'Summary', isDefault: true }),
        meta({
          id: 'workExperience',
          key: 'workExperience',
          displayName: 'Experience',
          sectionType: 'itemList',
          isDefault: true,
        }),
        meta({
          id: 'education',
          key: 'education',
          displayName: 'Education',
          sectionType: 'itemList',
          isDefault: true,
        }),
        meta({
          id: 'personalProjects',
          key: 'personalProjects',
          displayName: 'Projects',
          sectionType: 'itemList',
          isDefault: true,
        }),
        meta({
          id: 'additional',
          key: 'additional',
          displayName: 'Skills & Awards',
          sectionType: 'stringList',
          isDefault: true,
        }),
        meta({ id: 'custom_empty', key: 'custom_empty', displayName: '荣誉证书' }),
        meta({ id: 'custom_filled', key: 'custom_filled', displayName: '资格证书' }),
      ],
    };

    const saved = normalizeResumeForSave(state);
    const byKey = Object.fromEntries((saved.sectionMeta ?? []).map((m) => [m.key, m]));
    // Optional + empty (summary, blank custom) hidden; filled custom stays.
    expect(byKey.summary.isVisible).toBe(false);
    expect(byKey.custom_empty.isVisible).toBe(false);
    expect(byKey.custom_filled.isVisible).toBe(true);
    // Required blocks stay visible even with no content, and keep dense slots.
    expect(byKey.education.isVisible).toBe(true);
    expect(byKey.workExperience.isVisible).toBe(true);
    // The blank custom's data row is still present (hidden, not deleted).
    expect(saved.customSections?.custom_empty).toBeDefined();
  });

  it('keeps accepted zh alias titles instead of resetting them', () => {
    const state: ResumeData = {
      ...baseResume,
      summary: '有内容',
      education: [{ id: 1, degree: '统招本科' }],
      sectionMeta: [
        meta({
          id: 'personalInfo',
          key: 'personalInfo',
          displayName: '个人信息',
          sectionType: 'personalInfo',
          isDefault: true,
        }),
        meta({
          id: 'education',
          key: 'education',
          displayName: '教育经历',
          sectionType: 'itemList',
          isDefault: true,
        }),
        meta({ id: 'summary', key: 'summary', displayName: '核心优势', isDefault: true }),
        meta({
          id: 'additional',
          key: 'additional',
          displayName: '技能与荣誉',
          sectionType: 'stringList',
          isDefault: true,
        }),
        meta({
          id: 'workExperience',
          key: 'workExperience',
          displayName: '工作经历',
          sectionType: 'itemList',
          isDefault: true,
        }),
        meta({
          id: 'personalProjects',
          key: 'personalProjects',
          displayName: '项目经历',
          sectionType: 'itemList',
          isDefault: true,
        }),
      ],
    };

    const saved = normalizeResumeForSave(state);
    const byKey = Object.fromEntries((saved.sectionMeta ?? []).map((m) => [m.key, m.displayName]));
    expect(byKey.education).toBe('教育经历');
    expect(byKey.summary).toBe('核心优势');
    expect(byKey.additional).toBe('技能与荣誉');
  });

  it('does not mutate the editor state while canonicalizing', () => {
    const state: ResumeData = {
      ...baseResume,
      sectionMeta: [
        meta({ id: 'summary', key: 'summary', displayName: 'My Story', isDefault: true, order: 4 }),
      ],
    };
    const snapshot = JSON.parse(JSON.stringify(state.sectionMeta));

    normalizeResumeForSave(state);
    expect(state.sectionMeta).toEqual(snapshot);
  });
});

describe('save normalizer runs the presentation-governance passes', () => {
  // Wiring locks: the date/term/hygiene modules have their own unit tests;
  // these fail if normalizeResumeForSave stops invoking them in chain order.
  it('canonicalizes date periods on every years field', () => {
    const state: ResumeData = {
      ...baseResume,
      workExperience: [{ id: 1, company: 'Acme', title: 'Engineer', years: 'Jan 2020 - Present' }],
    };

    expect(normalizeResumeForSave(state).workExperience?.[0].years).toBe('2020.01~至今');
  });

  it('canonicalizes tech-term casing before hygiene so list points unify', () => {
    const state: ResumeData = {
      ...baseResume,
      workExperience: [
        {
          id: 1,
          company: 'Acme',
          title: 'java 工程师',
          years: '2020.01~2023.01',
          description: ['熟悉 spring boot 与 mysql。', '散文式说明保持句号。'],
          descriptionStyles: ['bullet', 'plain'],
        },
      ],
      additional: { technicalSkills: ['java', 'mysql'] },
    };

    const saved = normalizeResumeForSave(state);
    expect(saved.workExperience?.[0].title).toBe('Java 工程师');
    expect(saved.workExperience?.[0].description).toEqual([
      '熟悉 Spring Boot 与 MySQL',
      '散文式说明保持句号。',
    ]);
    expect(saved.additional?.technicalSkills).toEqual(['Java', 'MySQL']);
  });

  it('renders through the same governance passes as save', () => {
    const state: ResumeData = {
      ...baseResume,
      summary: ' 五年 java 经验。\n\n',
    };

    expect(normalizeResumeForRender(state).summary).toBe('五年 Java 经验');
  });
});
