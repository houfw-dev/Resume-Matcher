import { describe, expect, it } from 'vitest';
import type {
  Education,
  ResumeData,
  SectionMeta,
  SectionType,
} from '@/components/dashboard/resume-component';
import {
  getCanonicalSections,
  getRenderSections,
  LATE_AWARDS_KEY,
  LATE_CERTIFICATIONS_KEY,
  resolveSectionSymbol,
  SELFEVAL_SYMBOL,
  type RenderSection,
} from '@/lib/utils/section-order';

/**
 * getRenderSections: the canonical meta sequence plus two render-only markers
 * (培训与证书 / 荣誉奖项) projected to the back of the resume. The markers are
 * never meta rows — invisible to the builder list, persistence, diagnosis and
 * the backend mirror.
 */

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

const defaultRow = (
  id: string,
  displayName: string,
  order: number,
  sectionType: SectionType = 'itemList'
): SectionMeta => meta({ id, key: id, displayName, sectionType, isDefault: true, order });

/** Two custom cluster rows (one legacy honors-titled) and a selfeval row. */
const fullMeta = (): SectionMeta[] => [
  defaultRow('personalInfo', '基本信息', 0, 'personalInfo'),
  defaultRow('education', '教育背景', 1),
  defaultRow('summary', '个人优势', 2, 'text'),
  defaultRow('additional', '专业技能', 3, 'stringList'),
  defaultRow('workExperience', '工作经历', 4),
  defaultRow('personalProjects', '项目经验', 5),
  meta({ id: 'custom_hobby', key: 'custom_hobby', displayName: '兴趣爱好', order: 6 }),
  meta({
    id: 'custom_honors',
    key: 'custom_honors',
    displayName: '荣誉证书',
    sectionType: 'stringList',
    order: 7,
  }),
  meta({ id: 'custom_eval', key: 'custom_eval', displayName: '自我评价', order: 8 }),
];

const fullData = (degree: string): ResumeData =>
  ({
    education: [edu(degree)],
    additional: {
      technicalSkills: ['Java'],
      certificationsTraining: ['PMP 证书'],
      awards: ['国家奖学金'],
    },
    customSections: {
      custom_hobby: { sectionType: 'text', text: '阅读' },
      custom_honors: { sectionType: 'stringList', strings: ['科技进步奖'] },
      custom_eval: { sectionType: 'text', text: '踏实肯干' },
    },
    sectionMeta: fullMeta(),
  }) as ResumeData;

/** Markers as stable tokens; meta rows resolved through the real symbol rule. */
function signature(items: RenderSection[]): string[] {
  return items.map((item) =>
    item.kind === 'meta' ? (resolveSectionSymbol(item.meta) ?? item.meta.key) : item.kind
  );
}

describe('getRenderSections', () => {
  it('formal: legacy honors-titled custom row rides the cluster; markers anchor before selfeval', () => {
    expect(signature(getRenderSections(fullData('统招本科')))).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'custom_hobby',
      'custom_honors',
      'certifications',
      'awards',
      SELFEVAL_SYMBOL,
    ]);
  });

  it('other branch without the extra custom row: markers anchor before the late education row', () => {
    const data = fullData('本科');
    data.sectionMeta = fullMeta().filter((row) => row.key !== 'custom_honors');
    expect(signature(getRenderSections(data))).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'custom_hobby',
      'certifications',
      'awards',
      'education',
      SELFEVAL_SYMBOL,
    ]);
  });

  it('other branch with a legacy honors-titled custom row: markers still anchor before education', () => {
    expect(signature(getRenderSections(fullData('本科')))).toEqual([
      'personalInfo',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'custom_hobby',
      'custom_honors',
      'certifications',
      'awards',
      'education',
      SELFEVAL_SYMBOL,
    ]);
  });

  it('formal with no selfeval/custom rows: markers land at document end', () => {
    const data: ResumeData = {
      education: [edu('统招本科')],
      workExperience: [{ id: 1 }],
      personalProjects: [{ id: 1 }],
      additional: {
        technicalSkills: ['Java'],
        certificationsTraining: ['PMP 证书'],
        awards: ['国家奖学金'],
      },
      sectionMeta: [
        defaultRow('personalInfo', '基本信息', 0, 'personalInfo'),
        defaultRow('education', '教育背景', 1),
        defaultRow('summary', '个人优势', 2, 'text'),
        defaultRow('additional', '专业技能', 3, 'stringList'),
        defaultRow('workExperience', '工作经历', 4),
        defaultRow('personalProjects', '项目经验', 5),
      ],
    } as ResumeData;
    // The explicit empty summary meta stays in the projection (renderers hide
    // empty blocks themselves); markers still anchor after projects.
    expect(signature(getRenderSections(data))).toEqual([
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
      'certifications',
      'awards',
    ]);
  });

  it('emits only the marker whose list has entries', () => {
    const certsOnly = fullData('统招本科');
    certsOnly.additional = { technicalSkills: ['Java'], certificationsTraining: ['PMP 证书'] };
    expect(signature(getRenderSections(certsOnly))).toContain('certifications');
    expect(signature(getRenderSections(certsOnly))).not.toContain('awards');

    const awardsOnly = fullData('统招本科');
    awardsOnly.additional = { technicalSkills: ['Java'], awards: ['国家奖学金'] };
    expect(signature(getRenderSections(awardsOnly))).toContain('awards');
    expect(signature(getRenderSections(awardsOnly))).not.toContain('certifications');
  });

  it('with neither list populated the projection is exactly the meta mapping', () => {
    const data = fullData('统招本科');
    data.additional = { technicalSkills: ['Java'] };
    const projected = getRenderSections(data);
    const expected: RenderSection[] = getCanonicalSections(data).map((row) => ({
      kind: 'meta',
      meta: row,
    }));
    expect(projected).toEqual(expected);
  });

  it('hidden additional meta row suppresses both markers even with cert/award data', () => {
    const data = fullData('统招本科');
    data.sectionMeta = fullMeta().map((row) =>
      row.key === 'additional' ? { ...row, isVisible: false } : row
    );
    const projected = getRenderSections(data);
    expect(projected.every((item) => item.kind === 'meta')).toBe(true);
    expect(projected.some((item) => item.kind === 'meta' && item.meta.key === 'additional')).toBe(
      false
    );
  });

  it('blank or non-string entries never produce a marker', () => {
    const data = fullData('统招本科');
    data.additional = {
      technicalSkills: ['Java'],
      certificationsTraining: ['', '   '],
      awards: [123, null, '  '] as unknown as string[],
    };
    expect(getRenderSections(data).every((item) => item.kind === 'meta')).toBe(true);
  });

  it('heals a missing additional meta row when cert data exists, then projects markers', () => {
    const data = fullData('统招本科');
    data.sectionMeta = fullMeta().filter((row) => row.key !== 'additional');
    const projected = signature(getRenderSections(data));
    expect(projected).toContain('additional');
    expect(projected).toContain('certifications');
    expect(projected).toContain('awards');
    // Healed additional keeps its early canonical slot, before work.
    expect(projected.indexOf('additional')).toBeLessThan(projected.indexOf('workExperience'));
  });

  it('never leaks the markers into getCanonicalSections (persistence/builder view)', () => {
    const data = fullData('统招本科');
    const metas = getCanonicalSections(data);
    expect(metas.every((row) => row.id !== LATE_CERTIFICATIONS_KEY)).toBe(true);
    expect(metas.every((row) => row.id !== LATE_AWARDS_KEY)).toBe(true);
    expect(metas.every((row) => row.key !== LATE_CERTIFICATIONS_KEY)).toBe(true);
    const projected = getRenderSections(data);
    expect(projected.filter((item) => item.kind !== 'meta')).toHaveLength(2);
    expect(metas).toHaveLength(projected.length - 2);
  });
});
