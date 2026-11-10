import { describe, expect, it } from 'vitest';
import { buildDiagnosisFixHref, getDiagnosisFixSection } from '@/lib/utils/diagnosis-fix-link';
import {
  parseSectionKeyParam,
  sectionAnchorId,
  SECTION_ANCHOR_PREFIX,
} from '@/lib/utils/section-order';

/**
 * The rubric item → builder-section contract. Every mapped item must point at
 * the single canonical block that owns its fix; every other rubric item
 * (appearance, timeline, growth, compliance, fit, competence) must return
 * null so the report renders no misleading CTA.
 */
describe('diagnosis → builder fix-link mapping', () => {
  it('maps each section-owned rubric item to its canonical builder block', () => {
    const expected: ReadonlyArray<[number, string]> = [
      [4, 'personalInfo'],
      [5, 'education'],
      [6, 'summary'],
      [7, 'additional'],
      [8, 'workExperience'],
      [9, 'personalProjects'],
      [10, 'summary'],
      [11, 'additional'],
      [12, 'additional'],
      [14, 'workExperience'],
    ];
    for (const [itemId, section] of expected) {
      expect(getDiagnosisFixSection(itemId)).toBe(section);
    }
  });

  it('returns null for holistic items without a single owning section', () => {
    const unmapped = [1, 2, 3, 13, 15, 16, 17, 18, 19, 20, 21, 22];
    for (const itemId of unmapped) {
      expect(getDiagnosisFixSection(itemId)).toBeNull();
    }
  });

  it('returns null for unknown / out-of-range item ids', () => {
    expect(getDiagnosisFixSection(0)).toBeNull();
    expect(getDiagnosisFixSection(99)).toBeNull();
    expect(getDiagnosisFixSection(-8)).toBeNull();
  });

  it('builds a tab+section deep link for a mapped item', () => {
    expect(buildDiagnosisFixHref('r1', 9)).toBe(
      '/builder?id=r1&tab=resume&section=personalProjects'
    );
  });

  it('encodes the resume id in the deep link', () => {
    expect(buildDiagnosisFixHref('a b/1', 4)).toBe(
      '/builder?id=a%20b%2F1&tab=resume&section=personalInfo'
    );
  });

  it('returns null href for unmappable items', () => {
    expect(buildDiagnosisFixHref('r1', 16)).toBeNull();
    expect(buildDiagnosisFixHref('r1', 1)).toBeNull();
  });
});

describe('parseSectionKeyParam — builder ?section= validation', () => {
  it('passes through the six canonical meta keys', () => {
    for (const key of [
      'personalInfo',
      'summary',
      'workExperience',
      'education',
      'personalProjects',
      'additional',
    ]) {
      expect(parseSectionKeyParam(key)).toBe(key);
    }
  });

  it('rejects absent, unknown and render-only values', () => {
    expect(parseSectionKeyParam(null)).toBeNull();
    expect(parseSectionKeyParam('')).toBeNull();
    expect(parseSectionKeyParam('__late_certifications__')).toBeNull();
    expect(parseSectionKeyParam('custom_hobby')).toBeNull();
    expect(parseSectionKeyParam('https://evil.example/path')).toBeNull();
  });

  it('derives stable DOM anchor ids for section focus', () => {
    expect(sectionAnchorId('education')).toBe(`${SECTION_ANCHOR_PREFIX}education`);
  });
});
