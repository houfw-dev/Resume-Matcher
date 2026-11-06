import { describe, expect, it } from 'vitest';
import type { Education, ResumeData, SectionMeta } from '@/components/dashboard/resume-component';
import {
  ACCEPTED_DEFAULT_TITLES,
  canonicalizeSectionMeta,
  classifyHighestDegree,
  findDuplicateSectionTitle,
  getCanonicalSections,
  hasSectionContent,
  isAcceptedDefaultTitle,
  isReservedDefaultTitle,
  isSelfIntroductionAlias,
  SELFEVAL_SYMBOL,
  resolveSectionSymbol,
  validateSectionName,
} from '@/lib/utils/section-order';
import zh from '@/messages/zh.json';

/** Canonical section ordering, degree-branch classification and title governance. */

function edu(degree: string): Education {
  return { id: 0, degree };
}

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
  };
}

const defaultMeta = (): SectionMeta[] => [
  meta({
    id: 'personalInfo',
    key: 'personalInfo',
    displayName: 'Personal Info',
    sectionType: 'personalInfo',
    isDefault: true,
    order: 0,
  }),
  meta({ id: 'summary', key: 'summary', displayName: 'Summary', isDefault: true, order: 1 }),
  meta({
    id: 'workExperience',
    key: 'workExperience',
    displayName: 'Experience',
    sectionType: 'itemList',
    isDefault: true,
    order: 2,
  }),
  meta({
    id: 'education',
    key: 'education',
    displayName: 'Education',
    sectionType: 'itemList',
    isDefault: true,
    order: 3,
  }),
  meta({
    id: 'personalProjects',
    key: 'personalProjects',
    displayName: 'Projects',
    sectionType: 'itemList',
    isDefault: true,
    order: 4,
  }),
  meta({
    id: 'additional',
    key: 'additional',
    displayName: 'Skills & Awards',
    sectionType: 'stringList',
    isDefault: true,
    order: 5,
  }),
];

describe('classifyHighestDegree', () => {
  it('always treats doctorates as formal, even without 统招 marker', () => {
    expect(classifyHighestDegree([edu('博士')])).toBe('formal');
    expect(classifyHighestDegree([edu('在职博士')])).toBe('formal');
    expect(classifyHighestDegree([edu('博士研究生')])).toBe('formal');
  });

  it('treats 统招/全日制 本科/硕士 as formal', () => {
    expect(classifyHighestDegree([edu('统招硕士')])).toBe('formal');
    expect(classifyHighestDegree([edu('全日制硕士研究生')])).toBe('formal');
    expect(classifyHighestDegree([edu('统招本科')])).toBe('formal');
    expect(classifyHighestDegree([edu('全日制本科')])).toBe('formal');
  });

  it('treats marker-less masters as other', () => {
    expect(classifyHighestDegree([edu('硕士')])).toBe('other');
    expect(classifyHighestDegree([edu('在职研究生')])).toBe('other');
    expect(classifyHighestDegree([edu('MBA 硕士')])).toBe('other');
  });

  it('treats every non-formal marker as other, including with formal markers', () => {
    for (const marker of [
      '自考',
      '成教',
      '函授',
      '网络教育',
      '网教',
      '电大',
      '开放大学',
      '开放教育',
      '业余',
    ]) {
      expect(classifyHighestDegree([edu(`${marker}本科`)])).toBe('other');
    }
    expect(classifyHighestDegree([edu('全日制自考本科')])).toBe('other');
    expect(classifyHighestDegree([edu('全日制专升本')])).toBe('other');
  });

  it('treats 大专 and below as other even when full-time', () => {
    expect(classifyHighestDegree([edu('全日制大专')])).toBe('other');
    expect(classifyHighestDegree([edu('统招大专')])).toBe('other');
    expect(classifyHighestDegree([edu('大专')])).toBe('other');
    expect(classifyHighestDegree([edu('中专')])).toBe('other');
    expect(classifyHighestDegree([edu('高中')])).toBe('other');
  });

  it('uses the highest level across multiple entries', () => {
    expect(classifyHighestDegree([edu('大专'), edu('统招本科')])).toBe('formal');
    expect(classifyHighestDegree([edu('自考本科'), edu('大专')])).toBe('other');
    // Formal lower degree does not upgrade a non-formal highest degree.
    expect(classifyHighestDegree([edu('全日制本科'), edu('在职硕士')])).toBe('other');
  });

  it('falls back to other for missing or malformed data', () => {
    expect(classifyHighestDegree(undefined)).toBe('other');
    expect(classifyHighestDegree([])).toBe('other');
    expect(classifyHighestDegree([{} as Education])).toBe('other');
    expect(classifyHighestDegree([{ id: 1 } as Education])).toBe('other');
    expect(classifyHighestDegree([edu('')])).toBe('other');
  });
});

describe('resolveSectionSymbol', () => {
  it('maps default keys to themselves', () => {
    expect(resolveSectionSymbol(meta({ key: 'additional', displayName: '技能与荣誉' }))).toBe(
      'additional'
    );
    expect(resolveSectionSymbol(meta({ key: 'education' }))).toBe('education');
  });

  it('recognises selfeval by title tokens', () => {
    expect(resolveSectionSymbol(meta({ displayName: '自我评价' }))).toBe('__selfeval__');
    expect(resolveSectionSymbol(meta({ displayName: '个人总结' }))).toBe('__selfeval__');
  });

  it('treats legacy honors headings as ordinary custom sections', () => {
    // The legacy 荣誉证书 slot was removed; such headings no longer claim a
    // fixed position and ride the custom cluster under their stored title.
    for (const title of ['荣誉证书', '资格证书', '奖项经历', '获奖情况', '奖状']) {
      expect(resolveSectionSymbol(meta({ displayName: title }))).toBeNull();
    }
  });

  it('returns null for ordinary custom sections', () => {
    expect(resolveSectionSymbol(meta({ displayName: '兴趣爱好' }))).toBeNull();
  });
});

describe('getCanonicalSections', () => {
  const fullMeta = (): SectionMeta[] => {
    const rows = defaultMeta();
    rows.push(
      meta({ id: 'custom_hobby', key: 'custom_hobby', displayName: '兴趣爱好', order: 6 }),
      meta({ id: 'custom_honors', key: 'custom_honors', displayName: '荣誉证书', order: 7 }),
      meta({ id: 'custom_eval', key: 'custom_eval', displayName: '自我评价', order: 8 })
    );
    return rows;
  };

  it('places education second for formal degrees with all blocks present', () => {
    const data = { sectionMeta: fullMeta(), education: [edu('统招本科')] } as ResumeData;
    expect(getCanonicalSections(data).map((s) => s.key)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'custom_hobby',
      'custom_honors',
      'custom_eval',
    ]);
  });

  it('moves education before selfeval for non-formal degrees, keeping the custom cluster', () => {
    const data = { sectionMeta: fullMeta(), education: [edu('大专')] } as ResumeData;
    expect(getCanonicalSections(data).map((s) => s.key)).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'custom_hobby',
      'custom_honors',
      'education',
      'custom_eval',
    ]);
  });

  it('places education directly before selfeval when no other custom block follows', () => {
    const rows = defaultMeta();
    rows.push(meta({ id: 'custom_eval', key: 'custom_eval', displayName: '自我评价', order: 6 }));
    const data = { sectionMeta: rows, education: [edu('自考本科')] } as ResumeData;
    expect(getCanonicalSections(data).map((s) => s.key)).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'education',
      'custom_eval',
    ]);
  });

  it('keeps unknown custom sections in their stored relative order', () => {
    const rows = defaultMeta();
    rows.push(
      meta({ id: 'custom_b', key: 'custom_b', displayName: '出版物', order: 7 }),
      meta({ id: 'custom_a', key: 'custom_a', displayName: '志愿者', order: 6 })
    );
    const data = { sectionMeta: rows, education: [edu('统招本科')] } as ResumeData;
    expect(getCanonicalSections(data).map((s) => s.key)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'custom_a',
      'custom_b',
    ]);
  });

  it('excludes hidden sections unless includeHidden is set', () => {
    const rows = defaultMeta();
    rows[1] = { ...rows[1], isVisible: false };
    const data = { sectionMeta: rows, education: [edu('统招本科')] } as ResumeData;
    const visible = getCanonicalSections(data).map((s) => s.key);
    expect(visible).not.toContain('summary');
    const all = getCanonicalSections(data, { includeHidden: true }).map((s) => s.key);
    expect(all).toContain('summary');
  });

  it('sorts the default-missing fallback by degree branch', () => {
    const formal = { education: [edu('统招硕士')] } as ResumeData;
    expect(getCanonicalSections(formal).map((s) => s.key)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]);
    const other = { education: [edu('大专')] } as ResumeData;
    expect(getCanonicalSections(other).map((s) => s.key)).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'education',
    ]);
  });

  it('heals an education row the LLM omitted while education data exists (1905c3db)', () => {
    const rows = [
      meta({
        id: 'personalInfo',
        key: 'personalInfo',
        displayName: 'Personal Info',
        sectionType: 'personalInfo',
        isDefault: true,
        order: 0,
      }),
      meta({ id: 'summary', key: 'summary', displayName: 'Summary', isDefault: true, order: 1 }),
      meta({
        id: 'additional',
        key: 'additional',
        displayName: 'Skills & Awards',
        sectionType: 'stringList',
        isDefault: true,
        order: 2,
      }),
      meta({
        id: 'workExperience',
        key: 'workExperience',
        displayName: 'Experience',
        sectionType: 'itemList',
        isDefault: true,
        order: 3,
      }),
      meta({
        id: 'personalProjects',
        key: 'personalProjects',
        displayName: 'Projects',
        sectionType: 'itemList',
        isDefault: true,
        order: 4,
      }),
      meta({ id: 'self_evaluation', key: 'self_evaluation', displayName: '自我评价', order: 5 }),
    ];
    const data = {
      sectionMeta: rows,
      education: [
        { id: 1, institution: '湖北理工学院', degree: '本科', description: ['专业: 计算机科学'] },
      ],
    } as unknown as ResumeData;
    const out = getCanonicalSections(data);
    const education = out.find((s) => s.key === 'education');
    expect(education).toBeDefined();
    expect(education?.isVisible).toBe(true);
    expect(education?.isDefault).toBe(true);
    expect(education?.displayName).toBe('Education');
    // Non-formal 本科 → other branch: education slots in directly before
    // self-evaluation.
    expect(out.map((s) => s.key)).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'education',
      'self_evaluation',
    ]);
    // Healing is render-time: the stored meta array is not mutated.
    expect(rows.map((s) => s.key)).not.toContain('education');
    // includeHidden (builder management list) shows the healed row too.
    expect(getCanonicalSections(data, { includeHidden: true }).map((s) => s.key)).toContain(
      'education'
    );
  });

  it('heals every content-bearing omitted default but never empty ones', () => {
    const rows = [
      meta({
        id: 'personalInfo',
        key: 'personalInfo',
        sectionType: 'personalInfo',
        isDefault: true,
      }),
    ];
    const filled = {
      sectionMeta: rows,
      summary: '个人优势',
      workExperience: [{ company: 'A 公司' }],
      education: [{ institution: '某大学', degree: '统招本科' }],
      personalProjects: [{ name: '项目甲' }],
      additional: { technicalSkills: ['Python'] },
    } as unknown as ResumeData;
    const keys = getCanonicalSections(filled).map((s) => s.key);
    expect(keys).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]);

    const empty = {
      sectionMeta: rows,
      summary: '',
      workExperience: [],
      education: [],
      personalProjects: [],
      additional: { technicalSkills: [] },
    } as unknown as ResumeData;
    expect(getCanonicalSections(empty).map((s) => s.key)).toEqual(['personalInfo']);
  });
});

describe('title validators', () => {
  const rows = (): SectionMeta[] => [
    meta({ id: 'custom_1', displayName: 'Volunteering', isVisible: true }),
    meta({ id: 'custom_2', displayName: 'Hobbies', isVisible: true }),
    meta({ id: 'custom_hidden', displayName: 'Secret', isVisible: false }),
  ];

  it('finds duplicates case/whitespace-insensitive, ignoring hidden rows', () => {
    expect(findDuplicateSectionTitle(rows(), '  volunteering ')?.id).toBe('custom_1');
    expect(findDuplicateSectionTitle(rows(), 'HOBBIES')?.id).toBe('custom_2');
    expect(findDuplicateSectionTitle(rows(), 'Secret')).toBeUndefined();
    expect(findDuplicateSectionTitle(rows(), 'Volunteering', 'custom_1')).toBeUndefined();
  });

  it('reserves English canonical and extra locale default names', () => {
    expect(isReservedDefaultTitle('Education')).toBe(true);
    expect(isReservedDefaultTitle('  education ')).toBe(true);
    expect(isReservedDefaultTitle('Volunteering')).toBe(false);
    expect(isReservedDefaultTitle('教育背景', ['教育背景'])).toBe(true);
    expect(isReservedDefaultTitle('教育背景')).toBe(false);
  });

  it('validateSectionName reports empty / reserved / duplicate / null', () => {
    expect(validateSectionName('  ', rows())).toBe('empty');
    expect(validateSectionName('Summary', rows())).toBe('reserved');
    expect(validateSectionName('教育背景', rows(), { reservedNames: ['教育背景'] })).toBe(
      'reserved'
    );
    expect(validateSectionName('hobbies', rows())).toBe('duplicate');
    expect(validateSectionName('Publications', rows())).toBeNull();
  });

  it('accepts every shipped locale title for its default key', () => {
    for (const [key, titles] of Object.entries(ACCEPTED_DEFAULT_TITLES)) {
      for (const title of titles) {
        expect(isAcceptedDefaultTitle(key, title)).toBe(true);
      }
    }
    expect(isAcceptedDefaultTitle('summary', 'My Story')).toBe(false);
  });

  it('accepts the zh headings imported resumes actually use', () => {
    for (const title of ['个人优势', '核心优势', '竞争优势', '综合优势', '个人亮点']) {
      expect(isAcceptedDefaultTitle('summary', title)).toBe(true);
    }
    // 个人简介 belongs to the self-introduction group, never the summary block.
    expect(isAcceptedDefaultTitle('summary', '个人简介')).toBe(false);
    // 个人评价 is a self-introduction alias, never the summary block.
    expect(isAcceptedDefaultTitle('summary', '个人评价')).toBe(false);
    // 个人总结 now parses into the self_evaluation custom block, never summary.
    expect(isAcceptedDefaultTitle('summary', '个人总结')).toBe(false);
    for (const title of [
      '专业技能',
      '职业技能',
      '核心技能',
      '专业能力',
      '技能',
      '技能清单',
      '技术能力',
      '技术技能',
      '技能与荣誉',
    ]) {
      expect(isAcceptedDefaultTitle('additional', title)).toBe(true);
    }
    for (const title of ['实习经历', '从业经历', '职业履历', '任职经历', '工作履历', '职场经历']) {
      expect(isAcceptedDefaultTitle('workExperience', title)).toBe(true);
    }
    for (const title of ['项目经历', '项目经验', '项目履历', '重点项目']) {
      expect(isAcceptedDefaultTitle('personalProjects', title)).toBe(true);
    }
    for (const title of ['教育经历', '教育背景', '学历信息', '求学履历']) {
      expect(isAcceptedDefaultTitle('education', title)).toBe(true);
    }
  });

  it('recognises self-introduction alias headings', () => {
    for (const title of ['自我介绍', '个人介绍', '个人简介', '个人简述', '个人评价']) {
      expect(isSelfIntroductionAlias(title)).toBe(true);
      expect(resolveSectionSymbol(meta({ displayName: title }))).toBe(SELFEVAL_SYMBOL);
    }
    // Honors aliases lost their canonical slot: they are plain custom titles.
    for (const title of ['荣誉证书', '荣誉/证书', '获奖情况', '资质荣誉', '资格证书']) {
      expect(isSelfIntroductionAlias(title)).toBe(false);
      expect(resolveSectionSymbol(meta({ displayName: title }))).toBeNull();
    }
    expect(isSelfIntroductionAlias('自我评价')).toBe(false);
    // 个人总结 owns the terminal self-evaluation slot like 自我评价, but its
    // stored title is rendered verbatim (it is not an 自我介绍 alias).
    expect(resolveSectionSymbol(meta({ displayName: '个人总结' }))).toBe(SELFEVAL_SYMBOL);
    expect(isSelfIntroductionAlias('个人总结')).toBe(false);
  });

  it('canonical zh headings for every block', () => {
    // zh.json is the shipped canonical source; imported aliases render under it.
    expect(zh.resume.sections.education).toBe('教育背景');
    expect(zh.resume.sections.skillsOnly).toBe('专业技能');
    expect(zh.resume.sections.projects).toBe('项目经验');
    expect(zh.resume.sections.experience).toBe('工作经历');
    expect(zh.resume.sections.summary).toBe('个人优势');
    expect(zh.resume.sections.selfIntroduction).toBe('自我介绍');
  });
});

describe('hasSectionContent', () => {
  it('detects empty and filled sections', () => {
    const empty = {
      summary: '',
      education: [{}],
      workExperience: [],
      personalProjects: [{ id: 1 }],
      additional: { technicalSkills: ['  '] },
      customSections: { custom_1: { sectionType: 'text', text: '   ' } },
    } as unknown as ResumeData;
    expect(hasSectionContent(meta({ key: 'summary' }), empty)).toBe(false);
    expect(hasSectionContent(meta({ key: 'education' }), empty)).toBe(false);
    expect(hasSectionContent(meta({ key: 'workExperience' }), empty)).toBe(false);
    expect(hasSectionContent(meta({ key: 'personalProjects' }), empty)).toBe(false);
    expect(hasSectionContent(meta({ key: 'additional' }), empty)).toBe(false);
    expect(hasSectionContent(meta({ key: 'custom_1' }), empty)).toBe(false);

    const filled = {
      summary: 'hello',
      education: [{ id: 1, degree: 'BSc' }],
      workExperience: [{ id: 1, title: 'Dev' }],
      personalProjects: [{ id: 1, name: 'X' }],
      additional: { languages: ['EN'] },
      customSections: { custom_1: { sectionType: 'stringList', strings: ['a'] } },
    } as unknown as ResumeData;
    expect(hasSectionContent(meta({ key: 'summary' }), filled)).toBe(true);
    expect(hasSectionContent(meta({ key: 'education' }), filled)).toBe(true);
    expect(hasSectionContent(meta({ key: 'workExperience' }), filled)).toBe(true);
    expect(hasSectionContent(meta({ key: 'personalProjects' }), filled)).toBe(true);
    expect(hasSectionContent(meta({ key: 'additional' }), filled)).toBe(true);
    expect(hasSectionContent(meta({ key: 'custom_1' }), filled)).toBe(true);
  });
});

describe('canonicalizeSectionMeta', () => {
  it('rewrites scrambled legacy order to dense canonical order', () => {
    const rows = defaultMeta();
    rows.forEach((r, i) => {
      r.order = 10 - i;
    });
    const data = {
      sectionMeta: rows,
      education: [edu('统招本科')],
      summary: 'x',
    } as ResumeData;
    const out = canonicalizeSectionMeta(data);
    expect(out.map((s) => s.key)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]);
    expect(out.map((s) => s.order)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it('resets renamed default titles to English canonical but keeps accepted aliases', () => {
    const rows = [
      meta({ id: 'summary', key: 'summary', displayName: 'My Story', isDefault: true }),
      meta({ id: 'education', key: 'education', displayName: '教育经历', isDefault: true }),
    ];
    const out = canonicalizeSectionMeta({ sectionMeta: rows, summary: 'x' } as ResumeData);
    expect(out.find((s) => s.key === 'summary')?.displayName).toBe('Summary');
    expect(out.find((s) => s.key === 'education')?.displayName).toBe('教育经历');
  });

  it('hides empty optional sections but never required ones, preserving data', () => {
    const rows = defaultMeta();
    rows.push(
      meta({ id: 'custom_empty', key: 'custom_empty', displayName: '荣誉证书' }),
      meta({ id: 'custom_filled', key: 'custom_filled', displayName: '自我评价' })
    );
    const data = {
      sectionMeta: rows,
      customSections: {
        custom_empty: { sectionType: 'text', text: '' },
        custom_filled: { sectionType: 'text', text: '本人评价……' },
      },
    } as unknown as ResumeData;
    const out = canonicalizeSectionMeta(data);
    expect(out.find((s) => s.key === 'summary')?.isVisible).toBe(false);
    expect(out.find((s) => s.key === 'custom_empty')?.isVisible).toBe(false);
    expect(out.find((s) => s.key === 'custom_filled')?.isVisible).toBe(true);
    // Required blocks stay visible even when empty.
    expect(out.find((s) => s.key === 'education')?.isVisible).toBe(true);
    expect(out.find((s) => s.key === 'workExperience')?.isVisible).toBe(true);
    // Data is preserved, not deleted.
    expect(data.customSections?.custom_empty.text).toBe('');
  });

  it('keeps hidden rows in their canonical slot with dense order', () => {
    const rows = defaultMeta();
    rows[3] = { ...rows[3], isVisible: false }; // education hidden
    const data = { sectionMeta: rows, education: [edu('统招本科')] } as ResumeData;
    const out = canonicalizeSectionMeta(data);
    expect(out.map((s) => s.key)).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]);
    expect(out.map((s) => s.order)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it('does not mutate the input rows', () => {
    const rows = defaultMeta();
    const snapshot = rows.map((r) => ({ ...r }));
    canonicalizeSectionMeta({ sectionMeta: rows } as ResumeData);
    expect(rows).toEqual(snapshot);
  });

  it('heals content-bearing default rows the LLM omitted at save time', () => {
    const rows = [
      meta({
        id: 'personalInfo',
        key: 'personalInfo',
        displayName: 'Personal Info',
        sectionType: 'personalInfo',
        isDefault: true,
        order: 0,
      }),
      meta({
        id: 'workExperience',
        key: 'workExperience',
        displayName: 'Experience',
        sectionType: 'itemList',
        isDefault: true,
        order: 1,
      }),
    ];
    const data = {
      sectionMeta: rows,
      education: [{ id: 1, institution: '湖北理工学院', degree: '本科' }],
      summary: '个人优势',
      additional: { technicalSkills: ['Java'] },
      workExperience: [{ company: '某公司' }],
    } as unknown as ResumeData;
    const out = canonicalizeSectionMeta(data);
    const education = out.find((s) => s.key === 'education');
    expect(education).toBeDefined();
    expect(education?.isVisible).toBe(true);
    expect(education?.displayName).toBe('Education');
    // other branch (marker-less 本科): education lands right before the end…
    expect(out.map((s) => s.key)).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'education',
    ]);
    // the stored input meta is untouched
    expect(rows.map((s) => s.key)).toEqual(['personalInfo', 'workExperience']);
  });
});
