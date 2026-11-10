/**
 * Canonical resume section ordering and section-title governance.
 *
 * The eight canonical blocks are, depending on the highest degree:
 *
 * formal (统招本科/统招硕士/博士):
 *   基础信息 → 教育背景 → 个人优势 → 专业技能 → 工作经历 → 项目经验
 *   → [其他自定义区块] → 培训与证书 → 荣誉奖项 → 自我评价
 * other (everything else, incl. 非统招本科/大专):
 *   基础信息 → 个人优势 → 专业技能 → 工作经历 → 项目经验
 *   → [其他自定义区块] → 培训与证书 → 荣誉奖项 → 教育背景 → 自我评价
 *
 * 培训与证书 / 荣誉奖项 are RENDER-ONLY slots: their data lives in the early
 * `additional` meta slot (additional.certificationsTraining / additional.awards)
 * but getRenderSections() projects them to the back of the resume. They are
 * never meta rows — not persisted, absent from the builder management list,
 * and invisible to the backend mirror / diagnosis checker.
 *
 * This module is pure (no React) and the META ordering is mirrored 1:1 by the
 * backend `app/services/section_order.py`; parity is enforced by tests on both
 * sides.
 */

import type { Education, ResumeData, SectionMeta } from '@/components/dashboard/resume-component';
import { DEFAULT_SECTION_META } from '@/lib/utils/section-helpers';

export type DegreeClass = 'formal' | 'other';

// ---------------------------------------------------------------------------
// Degree classification
// ---------------------------------------------------------------------------

/** Markers that identify a formal (full-time, unified-exam) degree. */
export const FORMAL_DEGREE_MARKERS = ['统招', '全日制'] as const;

/** Markers that identify a non-formal (continuing-education) degree. */
export const NON_FORMAL_DEGREE_MARKERS = [
  '自考',
  '成教',
  '函授',
  '网络教育',
  '网教',
  '电大',
  '开放大学',
  '开放教育',
  '业余',
  '专升本',
] as const;

// Ranked highest-first: 博士 must be checked before 硕士 because 博士研究生
// contains 研究生.
const DEGREE_LEVEL_PATTERNS: ReadonlyArray<readonly [number, RegExp]> = [
  [5, /博士/],
  [4, /硕士|研究生/],
  [3, /本科/],
  [2, /大专|专科|高职/],
  [1, /中专|中职|技校|高中/],
];

function degreeLevel(text: string): number {
  for (const [level, pattern] of DEGREE_LEVEL_PATTERNS) {
    if (pattern.test(text)) return level;
  }
  return 0;
}

function isFormalDegreeEntry(level: number, text: string): boolean {
  // Doctorates always take the education-second branch.
  if (level === 5) return true;
  if (level !== 3 && level !== 4) return false;
  const hasFormalMarker = FORMAL_DEGREE_MARKERS.some((marker) => text.includes(marker));
  if (!hasFormalMarker) return false;
  return !NON_FORMAL_DEGREE_MARKERS.some((marker) => text.includes(marker));
}

/**
 * Classify the resume's highest degree.
 *
 * The highest level across all education entries wins; among entries at that
 * level, a single formal one makes the resume formal. Anything that cannot be
 * recognised (missing education, malformed entries, 大专 or below) is
 * `other` — the education block then sits immediately before 自我评价.
 */
export function classifyHighestDegree(education?: readonly Education[] | null): DegreeClass {
  if (!Array.isArray(education)) return 'other';

  let maxLevel = 0;
  for (const entry of education) {
    if (!entry || typeof entry !== 'object') continue;
    const text = typeof entry.degree === 'string' ? entry.degree : '';
    maxLevel = Math.max(maxLevel, degreeLevel(text));
  }
  if (maxLevel === 0) return 'other';

  for (const entry of education) {
    if (!entry || typeof entry !== 'object') continue;
    const text = typeof entry.degree === 'string' ? entry.degree : '';
    if (degreeLevel(text) === maxLevel && isFormalDegreeEntry(maxLevel, text)) {
      return 'formal';
    }
  }
  return 'other';
}

// ---------------------------------------------------------------------------
// Canonical symbols and sequences
// ---------------------------------------------------------------------------

export const SELFEVAL_SYMBOL = '__selfeval__';
export const CUSTOM_CLUSTER_SYMBOL = '__custom__';

export const SELFEVAL_TITLE_TOKENS = [
  '自我评价',
  '自我评定',
  '个人评价',
  '自我介绍',
  '个人介绍',
  '个人简介',
  '个人简述',
  '个人总结',
] as const;

export const DEFAULT_SECTION_KEYS = [
  'personalInfo',
  'summary',
  'workExperience',
  'education',
  'personalProjects',
  'additional',
] as const;

export type DefaultSectionKey = (typeof DEFAULT_SECTION_KEYS)[number];

const DEFAULT_KEY_SET: ReadonlySet<string> = new Set(DEFAULT_SECTION_KEYS);

/** DOM id prefix for builder section anchors (the `?section=` deep-link target). */
export const SECTION_ANCHOR_PREFIX = 'builder-section-';

/** DOM id of a builder section's scroll anchor. */
export function sectionAnchorId(key: string): string {
  return `${SECTION_ANCHOR_PREFIX}${key}`;
}

/**
 * Validate a `?section=` search-param value against the six canonical meta
 * keys. Returns null for absent/unknown values so a stale link never focuses
 * a custom block or a render-only late module.
 */
export function parseSectionKeyParam(value: string | null): DefaultSectionKey | null {
  if (!value) return null;
  return DEFAULT_KEY_SET.has(value) ? (value as DefaultSectionKey) : null;
}

const CANONICAL_SEQUENCE_FORMAL: readonly string[] = [
  'personalInfo',
  'education',
  'summary',
  'additional',
  'workExperience',
  'personalProjects',
  CUSTOM_CLUSTER_SYMBOL,
  SELFEVAL_SYMBOL,
];

const CANONICAL_SEQUENCE_OTHER: readonly string[] = [
  'personalInfo',
  'summary',
  'additional',
  'workExperience',
  'personalProjects',
  CUSTOM_CLUSTER_SYMBOL,
  'education',
  SELFEVAL_SYMBOL,
];

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isMetaRecord(value: unknown): value is SectionMeta {
  return isObjectRecord(value) && typeof value.key === 'string';
}

/**
 * Resolve a meta row to a canonical slot symbol.
 *
 * Default keys win over title-token matching. Returns null for rows that
 * belong to the custom-section cluster.
 */
export function resolveSectionSymbol(meta: SectionMeta): string | null {
  if (DEFAULT_KEY_SET.has(meta.key)) return meta.key;
  const name = typeof meta.displayName === 'string' ? meta.displayName : '';
  if (SELFEVAL_TITLE_TOKENS.some((token) => name.includes(token))) {
    return SELFEVAL_SYMBOL;
  }
  return null;
}

/**
 * Place meta rows into the branch-specific canonical sequence.
 *
 * The first row wins each fixed slot; duplicate fixed-key rows and all
 * unrecognised custom rows keep their relative order inside the custom
 * cluster (between 项目经验 and the late education/自我评价 slots), so
 * 自我评价 always stays last.
 */
function placeSections(rows: readonly SectionMeta[], degreeClass: DegreeClass): SectionMeta[] {
  const sorted = [...rows].sort((a, b) => a.order - b.order);
  const fixedSlots = new Map<string, SectionMeta>();
  const customCluster: SectionMeta[] = [];
  let selfevalClaimed = false;

  for (const row of sorted) {
    if (DEFAULT_KEY_SET.has(row.key)) {
      if (!fixedSlots.has(row.key)) {
        fixedSlots.set(row.key, row);
      } else {
        customCluster.push(row);
      }
      continue;
    }
    const name = typeof row.displayName === 'string' ? row.displayName : '';
    if (!selfevalClaimed && SELFEVAL_TITLE_TOKENS.some((token) => name.includes(token))) {
      fixedSlots.set(SELFEVAL_SYMBOL, row);
      selfevalClaimed = true;
      continue;
    }
    customCluster.push(row);
  }

  const sequence = degreeClass === 'formal' ? CANONICAL_SEQUENCE_FORMAL : CANONICAL_SEQUENCE_OTHER;
  const ordered: SectionMeta[] = [];
  for (const symbol of sequence) {
    if (symbol === CUSTOM_CLUSTER_SYMBOL) {
      ordered.push(...customCluster);
    } else {
      const row = fixedSlots.get(symbol);
      if (row) ordered.push(row);
    }
  }
  return ordered;
}

/**
 * Return sections in the fixed canonical order for rendering.
 *
 * Hidden sections are excluded unless `includeHidden` is set (builder
 * management list). Falls back to DEFAULT_SECTION_META when the resume has
 * no stored meta, then re-sorts that fallback for the degree branch.
 */
export function getCanonicalSections(
  resumeData: ResumeData,
  options?: { includeHidden?: boolean }
): SectionMeta[] {
  const source =
    Array.isArray(resumeData.sectionMeta) && resumeData.sectionMeta.length
      ? resumeData.sectionMeta
      : DEFAULT_SECTION_META;
  // LLM safety net (mirrors the backend canonicalizer): a content-bearing
  // default block gets a meta row even when the model omitted it, so old
  // resumes self-heal at render time without re-parsing or re-saving.
  const rows = healMissingDefaultSections(source.filter(isMetaRecord), resumeData);
  const visible = options?.includeHidden ? rows : rows.filter((s) => s.isVisible);
  return placeSections(visible, classifyHighestDegree(resumeData.education));
}

// ---------------------------------------------------------------------------
// Render-only late modules (培训与证书 / 荣誉奖项)
// ---------------------------------------------------------------------------

/** React keys for the render-only late modules; they are NEVER meta ids. */
export const LATE_CERTIFICATIONS_KEY = '__late_certifications__';
export const LATE_AWARDS_KEY = '__late_awards__';

export type RenderSection =
  { kind: 'meta'; meta: SectionMeta } | { kind: 'certifications' } | { kind: 'awards' };

function hasRenderableStringEntries(value: unknown): boolean {
  return (
    Array.isArray(value) && value.some((item) => typeof item === 'string' && item.trim() !== '')
  );
}

/**
 * Canonical meta sequence plus render-only 培训与证书 / 荣誉奖项 markers.
 *
 * The two lists stay stored under the early `additional` slot but render at
 * the BACK of the resume as independent titled modules. Anchor order, first
 * hit:
 *   1. on the `other` degree branch, the late `education` row — placeSections
 *      structurally parks it after the custom cluster, so no projects-seen
 *      guard is needed;
 *   2. the self-evaluation row;
 *   3. document end.
 *
 * Hiding the `additional` meta row hides skills AND both late modules
 * (matching the two-column templates' isSectionVisible('additional') gate).
 */
export function getRenderSections(resumeData: ResumeData): RenderSection[] {
  const metas = getCanonicalSections(resumeData);
  const items: RenderSection[] = metas.map((meta) => ({ kind: 'meta', meta }));

  if (!metas.some((meta) => meta.key === 'additional')) {
    return items;
  }
  const additional = resumeData.additional;
  const hasCerts = hasRenderableStringEntries(additional?.certificationsTraining);
  const hasAwards = hasRenderableStringEntries(additional?.awards);
  if (!hasCerts && !hasAwards) {
    return items;
  }

  const markers: RenderSection[] = [];
  if (hasCerts) markers.push({ kind: 'certifications' });
  if (hasAwards) markers.push({ kind: 'awards' });

  const degreeClass = classifyHighestDegree(resumeData.education);
  let anchor = -1;
  if (degreeClass === 'other') {
    for (let i = 0; i < metas.length; i += 1) {
      if (metas[i].key === 'education') {
        anchor = i;
        break;
      }
    }
  }
  if (anchor === -1) {
    for (let i = 0; i < metas.length; i += 1) {
      if (resolveSectionSymbol(metas[i]) === SELFEVAL_SYMBOL) {
        anchor = i;
        break;
      }
    }
  }
  if (anchor === -1) anchor = items.length;
  items.splice(anchor, 0, ...markers);
  return items;
}

// ---------------------------------------------------------------------------
// Title governance
// ---------------------------------------------------------------------------

/** English canonical titles — the reset target for renamed default blocks. */
export const CANONICAL_DEFAULT_TITLES: Readonly<Record<DefaultSectionKey, string>> = Object.freeze({
  personalInfo: 'Personal Info',
  summary: 'Summary',
  workExperience: 'Experience',
  education: 'Education',
  personalProjects: 'Projects',
  additional: 'Skills & Awards',
});

/**
 * Titles that count as a NON-renamed default block: the English canonical
 * title, every shipped 7-locale title, and common zh aliases used by
 * uploaded resumes. Comparison is whitespace/case-folded.
 */
export const ACCEPTED_DEFAULT_TITLES: Readonly<Record<DefaultSectionKey, readonly string[]>> =
  Object.freeze({
    personalInfo: [
      'Personal Info',
      'Información Personal',
      '个人信息',
      '個人情報',
      '개인 정보',
      'Informações Pessoais',
      'Informations personnelles',
      '基础信息',
      '基本信息',
    ],
    summary: [
      'Summary',
      'Resumen',
      '概要',
      '요약',
      'Resumo',
      'Résumé',
      '个人优势',
      '核心优势',
      '竞争优势',
      '综合优势',
      '个人亮点',
    ],
    workExperience: [
      'Experience',
      'Experiencia',
      '工作经历',
      '職歴',
      '경력',
      'Experiência',
      'Expérience',
      '工作经验',
      '实习经历',
      '从业经历',
      '职业履历',
      '任职经历',
      '工作履历',
      '职场经历',
    ],
    education: [
      'Education',
      'Educación',
      '教育背景',
      '学歴',
      '학력',
      'Formação',
      'Formation',
      '教育经历',
      '学历信息',
      '求学履历',
    ],
    personalProjects: [
      'Projects',
      'Proyectos',
      '项目经历',
      'プロジェクト',
      '프로젝트',
      'Projetos',
      'Projets',
      '项目经验',
      '项目履历',
      '重点项目',
    ],
    additional: [
      'Skills & Awards',
      'Habilidades y Premios',
      '技能与荣誉',
      'スキル・受賞歴',
      '기술 및 수상 내역',
      'Habilidades e Prêmios',
      'Compétences et récompenses',
      '专业技能',
      '职业技能',
      '核心技能',
      '专业能力',
      '技能',
      '技能清单',
      '技术能力',
      '技术技能',
    ],
  });

/**
 * zh headings that identify a self-introduction custom block. Such blocks
 * render the canonical locale title `resume.sections.selfIntroduction`
 * (zh: 自我介绍) regardless of the stored heading.
 */
export const SELF_INTRODUCTION_TITLE_ALIASES: readonly string[] = Object.freeze([
  '自我介绍',
  '个人介绍',
  '个人简介',
  '个人简述',
  '个人评价',
]);

/** Whether a custom-section title is a zh alias for the self-introduction block. */
export function isSelfIntroductionAlias(name: string): boolean {
  const folded = collapseSectionTitle(name);
  return SELF_INTRODUCTION_TITLE_ALIASES.some((title) => collapseSectionTitle(title) === folded);
}

export function collapseSectionTitle(name: string): string {
  return name.trim().replace(/\s+/g, ' ').toLowerCase();
}

export function isAcceptedDefaultTitle(key: string, name: string): boolean {
  const accepted = ACCEPTED_DEFAULT_TITLES[key as DefaultSectionKey];
  if (!accepted) return false;
  const folded = collapseSectionTitle(name);
  return accepted.some((title) => collapseSectionTitle(title) === folded);
}

/**
 * Find a visible section whose title matches the candidate (trimmed,
 * whitespace-collapsed, case-insensitive). `excludeId` skips the row being
 * renamed.
 */
export function findDuplicateSectionTitle(
  visibleMeta: readonly SectionMeta[],
  candidate: string,
  excludeId?: string
): SectionMeta | undefined {
  const foldedCandidate = collapseSectionTitle(candidate);
  if (!foldedCandidate) return undefined;
  return visibleMeta.find(
    (section) =>
      section.id !== excludeId &&
      section.isVisible &&
      collapseSectionTitle(section.displayName ?? '') === foldedCandidate
  );
}

/**
 * Whether a name collides with a default-section title. The six English
 * canonical names are always reserved; pass the active locale's six
 * `resume.sections.*` titles to additionally reserve those.
 */
export function isReservedDefaultTitle(name: string, reservedNames?: readonly string[]): boolean {
  const folded = collapseSectionTitle(name);
  if (!folded) return false;
  const reserved = [...Object.values(CANONICAL_DEFAULT_TITLES), ...(reservedNames ?? [])];
  return reserved.some((title) => collapseSectionTitle(title) === folded);
}

export type SectionNameError = 'empty' | 'duplicate' | 'reserved';

/**
 * Validate a new/renamed custom-section name against visible sections.
 * Returns null when valid.
 */
export function validateSectionName(
  name: string,
  visibleMeta: readonly SectionMeta[],
  options?: { excludeId?: string; reservedNames?: readonly string[] }
): SectionNameError | null {
  const trimmed = name.trim();
  if (!trimmed) return 'empty';
  if (isReservedDefaultTitle(trimmed, options?.reservedNames)) return 'reserved';
  if (findDuplicateSectionTitle(visibleMeta, trimmed, options?.excludeId)) {
    return 'duplicate';
  }
  return null;
}

// ---------------------------------------------------------------------------
// Section content / emptiness
// ---------------------------------------------------------------------------

/** Required blocks stay visible even when empty (diagnosis item 3). */
export const REQUIRED_SECTION_KEYS: ReadonlySet<string> = new Set([
  'personalInfo',
  'education',
  'workExperience',
  'personalProjects',
  'additional',
]);

function isMeaningfulText(value: unknown): boolean {
  return typeof value === 'string' && value.trim().length > 0;
}

function describedEntryHasContent(entry: Record<string, unknown>): boolean {
  const scalarKeys = [
    'title',
    'name',
    'company',
    'department',
    'role',
    'subtitle',
    'location',
    'years',
    'institution',
    'degree',
    'github',
    'website',
  ];
  return (
    scalarKeys.some((key) => isMeaningfulText(entry[key])) ||
    (Array.isArray(entry.description) && entry.description.some((point) => isMeaningfulText(point)))
  );
}

function collectionHasContent(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.some((entry) => isObjectRecord(entry) && describedEntryHasContent(entry))
  );
}

/** Whether a titled section currently has any renderable content. */
export function hasSectionContent(meta: SectionMeta, resumeData: ResumeData): boolean {
  switch (meta.key) {
    case 'personalInfo': {
      const info = resumeData.personalInfo;
      return Boolean(info && Object.values(info).some((value) => isMeaningfulText(value)));
    }
    case 'summary':
      return isMeaningfulText(resumeData.summary);
    case 'workExperience':
      return collectionHasContent(resumeData.workExperience);
    case 'education':
      return collectionHasContent(resumeData.education);
    case 'personalProjects':
      return collectionHasContent(resumeData.personalProjects);
    case 'additional': {
      const additional = resumeData.additional;
      if (!additional) return false;
      return (
        (additional.technicalSkills?.some(isMeaningfulText) ||
          additional.languages?.some(isMeaningfulText) ||
          additional.certificationsTraining?.some(isMeaningfulText) ||
          additional.awards?.some(isMeaningfulText)) === true
      );
    }
    default: {
      const custom = resumeData.customSections?.[meta.key];
      if (!custom) return false;
      if (custom.sectionType === 'text') return isMeaningfulText(custom.text);
      if (custom.sectionType === 'itemList') {
        return (
          Array.isArray(custom.items) &&
          custom.items.some((item) => isObjectRecord(item) && describedEntryHasContent(item))
        );
      }
      if (custom.sectionType === 'stringList') {
        return Array.isArray(custom.strings) && custom.strings.some(isMeaningfulText);
      }
      return false;
    }
  }
}

/**
 * Reconcile meta rows with resume content.
 *
 * The LLM is instructed to emit one meta row per content-bearing section
 * but occasionally omits one (observed: education data present, no
 * education meta row), which made the section unrenderable in every
 * template. Every default block that currently holds renderable content
 * gets a canonical visible row appended; empty blocks are left untouched
 * and custom sections are never synthesised. `placeSections` afterwards
 * moves appended rows into their canonical slots.
 */
function healMissingDefaultSections(
  rows: readonly SectionMeta[],
  resumeData: ResumeData
): SectionMeta[] {
  const present = new Set(rows.map((row) => row.key));
  const healed = [...rows];
  for (const key of DEFAULT_SECTION_KEYS) {
    if (present.has(key)) continue;
    const template = DEFAULT_SECTION_META.find((row) => row.key === key);
    if (!template) continue;
    if (hasSectionContent(template, resumeData)) {
      healed.push({ ...template, isVisible: true });
    }
  }
  return healed;
}

// ---------------------------------------------------------------------------
// Save-time canonicalization
// ---------------------------------------------------------------------------

/**
 * Rebuild sectionMeta for persistence:
 * - falls back to the canonical default meta when missing/empty;
 * - heals content-bearing default blocks whose meta row the LLM omitted
 *   (appends a canonical visible row; empty blocks stay untouched);
 * - resets renamed DEFAULT blocks to the English canonical title (the
 *   localization layer renders the locale name); localised/alias titles stay;
 * - hides empty OPTIONAL blocks (summary + custom), never deleting data;
 * - rewrites `order` to dense ints of the degree-branch canonical sequence
 *   (hidden rows keep their slot so the builder list stays stable).
 *
 * Input rows and their objects are never mutated.
 */
export function canonicalizeSectionMeta(resumeData: ResumeData): SectionMeta[] {
  const source =
    Array.isArray(resumeData.sectionMeta) && resumeData.sectionMeta.length
      ? resumeData.sectionMeta
      : DEFAULT_SECTION_META;
  let rows: SectionMeta[] = source.filter(isMetaRecord).map((row) => ({ ...row }));

  // LLM safety net: heal content-bearing default blocks whose meta row the
  // model omitted (appended rows are fresh copies, never DEFAULT_SECTION_META).
  rows = healMissingDefaultSections(rows, resumeData);

  for (const row of rows) {
    if (DEFAULT_KEY_SET.has(row.key) && !isAcceptedDefaultTitle(row.key, row.displayName ?? '')) {
      row.displayName = CANONICAL_DEFAULT_TITLES[row.key as DefaultSectionKey];
    }
    if (
      row.isVisible &&
      !REQUIRED_SECTION_KEYS.has(row.key) &&
      !hasSectionContent(row, resumeData)
    ) {
      row.isVisible = false;
    }
  }

  const ordered = placeSections(rows, classifyHighestDegree(resumeData.education));
  ordered.forEach((row, index) => {
    row.order = index;
  });
  return ordered;
}
