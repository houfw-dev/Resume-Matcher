/**
 * V4 diagnosis rubric → builder deep-link mapping.
 *
 * The diagnosis report offers a "fix in builder" CTA only for rubric items
 * whose remedy lives in ONE canonical builder section. Holistic items
 * (appearance, timeline consistency, growth narrative, compliance, JD fit,
 * competency judgments) have no single owning section, so they return null
 * and render no CTA rather than dumping the user on an arbitrary block.
 *
 * Pure module (no React) — unit-tested directly in
 * tests/diagnosis-fix-link.test.ts.
 */

import type { DefaultSectionKey } from '@/lib/utils/section-order';

export type FocusSectionKey = DefaultSectionKey;

/**
 * Rubric item id (see backend app/services/diagnosis_rules.json) → the meta
 * key of the builder section that owns the fix.
 *
 *  4 基本信息        → personalInfo
 *  5 教育经历        → education
 *  6 个人优势        → summary
 *  7 专业技能        → additional (technicalSkills lives under additional)
 *  8 工作经历        → workExperience
 *  9 项目经验        → personalProjects
 * 10 自我评价        → summary (self-evaluation merges into the summary block)
 * 11 培训与证书      → additional (certificationsTraining lives under additional)
 * 12 荣誉奖项        → additional (awards lives under additional)
 * 14 任职连续性      → workExperience (employment gaps are edited in work entries)
 */
const ITEM_FIX_SECTION: Readonly<Record<number, FocusSectionKey>> = Object.freeze({
  4: 'personalInfo',
  5: 'education',
  6: 'summary',
  7: 'additional',
  8: 'workExperience',
  9: 'personalProjects',
  10: 'summary',
  11: 'additional',
  12: 'additional',
  14: 'workExperience',
});

/** The builder section that owns a rubric item's fix, or null when unmappable. */
export function getDiagnosisFixSection(itemId: number): FocusSectionKey | null {
  return ITEM_FIX_SECTION[itemId] ?? null;
}

/**
 * Builder deep link for fixing one rubric item, or null when the item has no
 * single owning section. The builder's `?section=` param is consumed by
 * ResumeForm to scroll to and briefly highlight the target block.
 */
export function buildDiagnosisFixHref(resumeId: string, itemId: number): string | null {
  const section = getDiagnosisFixSection(itemId);
  if (!section) return null;
  return `/builder?id=${encodeURIComponent(resumeId)}&tab=resume&section=${section}`;
}
