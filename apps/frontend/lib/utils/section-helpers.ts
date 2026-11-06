/**
 * Section helpers for dynamic resume section management.
 *
 * These utilities handle section metadata operations including
 * getting default sections, sorting, and managing custom sections.
 */

import type { ResumeData, SectionMeta, SectionType } from '@/components/dashboard/resume-component';
import { DEFAULT_SECTION_KEYS, isSelfIntroductionAlias } from '@/lib/utils/section-order';
import { orderTimelineSectionsNewestFirst } from '@/lib/utils/timeline-sort';

export type TranslationFunction = (key: string, params?: Record<string, string | number>) => string;

/**
 * Default section metadata.
 * Used when a resume doesn't have sectionMeta defined.
 *
 * Order follows the formal-degree canonical sequence (education second):
 * 基础信息 → 教育背景 → 个人优势 → 专业技能 → 工作经历 → 项目经验.
 * The non-formal-degree branch is applied at render time by
 * `getCanonicalSections` in lib/utils/section-order.ts.
 */
export const DEFAULT_SECTION_META: SectionMeta[] = [
  {
    id: 'personalInfo',
    key: 'personalInfo',
    displayName: 'Personal Info',
    sectionType: 'personalInfo',
    isDefault: true,
    isVisible: true,
    order: 0,
  },
  {
    id: 'education',
    key: 'education',
    displayName: 'Education',
    sectionType: 'itemList',
    isDefault: true,
    isVisible: true,
    order: 1,
  },
  {
    id: 'summary',
    key: 'summary',
    displayName: 'Summary',
    sectionType: 'text',
    isDefault: true,
    isVisible: true,
    order: 2,
  },
  {
    id: 'additional',
    key: 'additional',
    displayName: 'Skills & Awards',
    sectionType: 'stringList',
    isDefault: true,
    isVisible: true,
    order: 3,
  },
  {
    id: 'workExperience',
    key: 'workExperience',
    displayName: 'Experience',
    sectionType: 'itemList',
    isDefault: true,
    isVisible: true,
    order: 4,
  },
  {
    id: 'personalProjects',
    key: 'personalProjects',
    displayName: 'Projects',
    sectionType: 'itemList',
    isDefault: true,
    isVisible: true,
    order: 5,
  },
];

const DEFAULT_SECTION_I18N_KEY_BY_ID: Readonly<Record<string, string>> = Object.freeze({
  personalInfo: 'resume.sections.personalInfo',
  summary: 'resume.sections.summary',
  workExperience: 'resume.sections.experience',
  education: 'resume.sections.education',
  personalProjects: 'resume.sections.projects',
  additional: 'resume.sections.skills',
});

/**
 * Localize default section display names.
 *
 * Default block titles are locked (section-title governance): every built-in
 * row renders the locale title keyed by its id, so a renamed default title
 * (e.g. a legacy custom displayName) is corrected at render without a data
 * migration. Custom sections keep their stored displayName, EXCEPT zh alias
 * headings for the canonical 自我介绍 block
 * (自我介绍/个人介绍/个人简介/个人简述/个人评价), which always renders the
 * locale canonical title.
 */
export function localizeDefaultSectionMeta(
  sections: SectionMeta[],
  t: TranslationFunction
): SectionMeta[] {
  return sections.map((section) => {
    if (!section.isDefault) {
      const name = section.displayName ?? '';
      if (isSelfIntroductionAlias(name)) {
        return { ...section, displayName: t('resume.sections.selfIntroduction') };
      }
      return section;
    }

    const i18nKey = DEFAULT_SECTION_I18N_KEY_BY_ID[section.id];
    if (!i18nKey) return section;

    return { ...section, displayName: t(i18nKey) };
  });
}

/**
 * Return a ResumeData object with localized default sectionMeta.
 *
 * - If resumeData.sectionMeta is missing, it generates it from DEFAULT_SECTION_META.
 * - Default section titles always render from the locale (title lock).
 * - Work/education entries always render newest-first (mirrors the backend
 *   parser ordering), so viewer, PDF and builder preview agree regardless of
 *   the stored order; the same order is persisted on the next builder save.
 */
export function withLocalizedDefaultSections(
  resumeData: ResumeData,
  t: TranslationFunction
): ResumeData {
  const baseMeta = resumeData.sectionMeta?.length ? resumeData.sectionMeta : DEFAULT_SECTION_META;
  const localizedMeta = localizeDefaultSectionMeta(baseMeta, t);
  return orderTimelineSectionsNewestFirst({
    ...resumeData,
    sectionMeta: localizedMeta,
  });
}

/**
 * Get section metadata from resume data, falling back to defaults.
 */
export function getSectionMeta(resumeData: ResumeData): SectionMeta[] {
  return resumeData.sectionMeta?.length ? resumeData.sectionMeta : DEFAULT_SECTION_META;
}

/**
 * Ensure every default block has a meta row, inserting canonical rows the
 * parser omitted for an empty optional block (observed: resumes with no
 * 个人优势 row at all, so the builder offered no form for it).
 *
 * Builder contract: built-in blocks are always listed regardless of content,
 * so inserted rows always start visible (an empty 个人优势 is hidden from
 * the resume/PDF downstream by save-time canonicalization, never in the
 * editor). Input rows are never mutated.
 */
export function ensureDefaultSectionMeta(resumeData: ResumeData): SectionMeta[] {
  const stored =
    Array.isArray(resumeData.sectionMeta) && resumeData.sectionMeta.length
      ? resumeData.sectionMeta
      : DEFAULT_SECTION_META;
  const present = new Set(stored.map((section) => section.key));
  const additions: SectionMeta[] = [];
  for (const key of DEFAULT_SECTION_KEYS) {
    if (present.has(key)) continue;
    const template = DEFAULT_SECTION_META.find((section) => section.key === key);
    if (template) additions.push({ ...template, isVisible: true });
  }
  return additions.length ? [...stored, ...additions] : stored;
}

/**
 * Merge two text blocks for the 自我评价 → 个人优势 migration.
 *
 * Empty sides are ignored; a block already contained in the other is not
 * duplicated. Returns the joined text (no trimming when nothing is added).
 */
function mergeTextBlocks(existing: string, incoming: string): string {
  const base = existing.trim();
  const extra = incoming.trim();
  if (!extra) return existing;
  if (!base) return incoming.trim();
  if (base === extra || base.includes(extra)) return existing.trimEnd();
  if (extra.includes(base)) return incoming.trim();
  return `${existing.trimEnd()}\n${incoming.trim()}`;
}

/**
 * Migrate a custom TEXT block (e.g. the parser-emitted 自我评价 block) into
 * the built-in 个人优势 (summary) block: its text is merged into `summary`,
 * the custom block is deleted, and a visible summary meta row is guaranteed.
 *
 * This is the data action behind renaming such a block to 个人优势 — the
 * name itself is reserved for the default block, so renaming cannot keep it
 * custom. Returns null when the section is missing or not a text block.
 * Never mutates the input.
 */
export function migrateTextSectionToSummary(
  resumeData: ResumeData,
  sectionKey: string
): ResumeData | null {
  const custom = resumeData.customSections?.[sectionKey];
  if (!custom || custom.sectionType !== 'text') return null;

  const mergedSummary = mergeTextBlocks(resumeData.summary ?? '', custom.text ?? '');
  const sectionMeta = ensureDefaultSectionMeta(resumeData)
    .filter((section) => section.key !== sectionKey)
    .map((section) =>
      section.key === 'summary'
        ? { ...section, isVisible: mergedSummary.trim().length > 0 }
        : section
    );
  const customSections = { ...(resumeData.customSections ?? {}) };
  delete customSections[sectionKey];
  return { ...resumeData, summary: mergedSummary, sectionMeta, customSections };
}

/**
 * Get sorted sections (visible only) for rendering.
 */
export function getSortedSections(resumeData: ResumeData): SectionMeta[] {
  return [...getSectionMeta(resumeData)]
    .filter((s) => s.isVisible)
    .sort((a, b) => a.order - b.order);
}

/**
 * Get all sections (including hidden) for management UI.
 */
export function getAllSections(resumeData: ResumeData): SectionMeta[] {
  return [...getSectionMeta(resumeData)].sort((a, b) => a.order - b.order);
}

/**
 * Generate a unique ID for a new custom section.
 */
export function generateCustomSectionId(existingSections: SectionMeta[]): string {
  const customSections = existingSections.filter((s) => s.id.startsWith('custom_'));
  const maxId = customSections.reduce((max, s) => {
    const num = parseInt(s.id.replace('custom_', ''), 10);
    return isNaN(num) ? max : Math.max(max, num);
  }, 0);
  return `custom_${maxId + 1}`;
}

/**
 * Create a new custom section with metadata.
 */
export function createCustomSection(
  existingSections: SectionMeta[],
  displayName: string,
  sectionType: SectionType
): SectionMeta {
  const id = generateCustomSectionId(existingSections);
  const maxOrder = Math.max(...existingSections.map((s) => s.order), 0);

  return {
    id,
    key: id,
    displayName,
    sectionType,
    isDefault: false,
    isVisible: true,
    order: maxOrder + 1,
  };
}
