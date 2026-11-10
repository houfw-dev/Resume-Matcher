/**
 * Pure scope-token semantics for fine-tuning.
 *
 * The token grammar mirrors the backend (app/schemas/fine_tune.py):
 * - "all" tunes every replaceable section;
 * - section tokens select whole modules;
 * - `work_N` / `project_N` select one canonical (0-based) entry;
 * - `work_N:<region>` / `project_N:<region>` select one label sub-module
 *   inside one entry (e.g. project_2:highlights = only the rows under the
 *   项目亮点 label); the label row itself and all other rows stay frozen;
 * - `custom_<key>` selects one custom section (builder keys are themselves
 *   custom_N, so their token carries a double prefix: custom_custom_1).
 *
 * The legacy whole-section token `customSections` stays supported for old
 * previews/replays, but the dialog no longer produces it.
 *
 * personalInfo and sectionMeta have no tokens: they are always frozen.
 */

import type { FineTuneScope } from '@/lib/api/fine-tune';
import { REGION_IDS, type RegionId } from '@/lib/utils/description-regions';

export const FINE_TUNE_SECTION_TOKENS = [
  'summary',
  'workExperience',
  'education',
  'personalProjects',
  'additional',
  'customSections',
] as const;

export type FineTuneSectionToken = (typeof FINE_TUNE_SECTION_TOKENS)[number];

const SECTION_TOKEN_SET: ReadonlySet<string> = new Set(FINE_TUNE_SECTION_TOKENS);
// The build targets ES2017, where unicode property escapes (\p{L}/\p{N}) are
// not downleveled by TypeScript and throw at runtime. Enumerate the scripts
// used by the seven supported locales (Latin/CJK/kana/Hangul plus Greek and
// Cyrillic) instead. This stays permissive of non-ASCII keys from
// non-compliant parsers; the shape check passing still does not mean the key
// exists on the resume (that is an ignored out-of-range target at runtime,
// mirroring work_N semantics and the backend's custom_[\w.-]+ gate).
const CUSTOM_KEY_CHARS =
  'A-Za-z0-9_.\\-' + // ASCII word chars plus dot/dash
  'À-ɏ' + // Latin-1 + Latin Extended (es/fr/pt accents)
  'Α-Ͽ' + // Greek
  'Ѐ-ӿ' + // Cyrillic
  '㐀-䶿' + // CJK Ext A
  '一-鿿' + // CJK Unified Ideographs
  '぀-ゟ' + // Hiragana
  '゠-ヿ' + // Katakana
  'ᄀ-ᇿ㄰-㆏가-힣'; // Hangul jamo, compat jamo, syllables
const REGION_ALTERNATION = REGION_IDS.join('|');
const TOKEN_PATTERN = new RegExp(
  `^(?:summary|education|additional|customSections|workExperience|personalProjects|work_\\d+|project_\\d+|(?:work|project)_\\d+:(?:${REGION_ALTERNATION})|custom_[${CUSTOM_KEY_CHARS}]+)$`
);
const ITEM_TOKEN_PATTERN = /^(work|project)_(\d+)$/;
const REGION_TOKEN_PATTERN = new RegExp(`^(work|project)_(\\d+):(${REGION_ALTERNATION})$`);
const CUSTOM_TOKEN_PATTERN = new RegExp(`^custom_([${CUSTOM_KEY_CHARS}]+)$`);

export const MAX_FINE_TUNE_TARGETS = 30;

/** Rendered-preview heading groups that can receive the blue scope outline. */
export type FineTuneHeadingKey =
  'summary' | 'experience' | 'education' | 'projects' | 'additional' | 'custom';

export function isSectionToken(token: string): token is FineTuneSectionToken {
  return SECTION_TOKEN_SET.has(token);
}

export function isValidTargetToken(token: string): boolean {
  return TOKEN_PATTERN.test(token);
}

export function itemToken(kind: 'work' | 'project', index: number): string {
  return `${kind}_${index}`;
}

export function parseItemToken(token: string): { kind: 'work' | 'project'; index: number } | null {
  const match = ITEM_TOKEN_PATTERN.exec(token);
  if (!match) return null;
  return { kind: match[1] as 'work' | 'project', index: Number(match[2]) };
}

/** Token for one label sub-module inside one entry: project_2:highlights. */
export function regionToken(kind: 'work' | 'project', index: number, regionId: RegionId): string {
  return `${kind}_${index}:${regionId}`;
}

/** Decode a region token ("project_2:highlights"); item/section tokens give null. */
export function parseRegionToken(
  token: string
): { kind: 'work' | 'project'; index: number; regionId: RegionId } | null {
  const match = REGION_TOKEN_PATTERN.exec(token);
  if (!match) return null;
  return {
    kind: match[1] as 'work' | 'project',
    index: Number(match[2]),
    regionId: match[3] as RegionId,
  };
}

/** All region tokens belonging to one entry ("project_2:techStack", …). */
export function regionTokensForItem(kind: 'work' | 'project', index: number): string[] {
  return REGION_IDS.map((regionId) => regionToken(kind, index, regionId));
}

/** Whether a token selects a single custom section (custom_<key>). */
export function isCustomSectionToken(token: string): boolean {
  // The legacy whole-section token "customSections" has no underscore.
  return CUSTOM_TOKEN_PATTERN.test(token);
}

/** Token for one custom section: custom_<key>. */
export function customSectionToken(key: string): string {
  return `custom_${key}`;
}

/** Decode a custom_<key> token once, so custom_custom_1 resolves to custom_1. */
export function customKeyFromToken(token: string): string | null {
  const match = CUSTOM_TOKEN_PATTERN.exec(token);
  return match ? match[1] : null;
}

/** Custom-section keys selected by per-block tokens, in first-seen order. */
export function customSectionKeysFromTargets(targets: readonly string[]): string[] {
  const keys: string[] = [];
  for (const token of targets) {
    const key = customKeyFromToken(token);
    if (key !== null && !keys.includes(key)) keys.push(key);
  }
  return keys;
}

/** Whether the legacy aggregated token (every custom block) is selected. */
export function targetsWholeCustomSections(targets: readonly string[]): boolean {
  return targets.includes('customSections');
}

/** Custom blocks (key + real heading) the blue outline should frame. */
export function customHeadingLabels(
  targets: readonly string[],
  blocks: ReadonlyArray<{ key: string; displayName: string }>
): string[] {
  if (targetsWholeCustomSections(targets)) {
    return blocks.map((block) => block.displayName);
  }
  const labels: string[] = [];
  for (const key of customSectionKeysFromTargets(targets)) {
    const block = blocks.find((candidate) => candidate.key === key);
    const label = block?.displayName ?? key;
    if (!labels.includes(label)) labels.push(label);
  }
  return labels;
}

/** Keep only known tokens, preserve first-seen order, cap at the backend limit. */
export function normalizeTargets(tokens: readonly string[]): string[] {
  return Array.from(new Set(tokens.filter(isValidTargetToken))).slice(0, MAX_FINE_TUNE_TARGETS);
}

/** True when a whole section is selected (item tokens under it are redundant). */
export function isWholeSectionSelected(
  targets: readonly string[],
  section: 'workExperience' | 'personalProjects'
): boolean {
  return targets.includes(section);
}

/**
 * Toggle a module-row token: a whole section drops its per-item tokens, and
 * the legacy `customSections` row is mutually exclusive with per-block
 * `custom_<key>` tokens.
 */
export function toggleSectionToken(targets: readonly string[], token: string): string[] {
  if (isCustomSectionToken(token)) {
    if (targets.includes(token)) {
      return normalizeTargets(targets.filter((t) => t !== token));
    }
    return normalizeTargets([...targets.filter((t) => t !== 'customSections'), token]);
  }
  if (!isSectionToken(token)) return normalizeTargets(targets);
  if (targets.includes(token)) {
    if (token === 'workExperience' || token === 'personalProjects') {
      const prefix = token === 'workExperience' ? 'work_' : 'project_';
      return targets.filter((t) => t !== token && !t.startsWith(prefix));
    }
    if (token === 'customSections') {
      return targets.filter((t) => t !== token && !isCustomSectionToken(t));
    }
    return targets.filter((t) => t !== token);
  }
  if (token === 'workExperience' || token === 'personalProjects') {
    const prefix = token === 'workExperience' ? 'work_' : 'project_';
    return normalizeTargets([...targets.filter((t) => !t.startsWith(prefix)), token]);
  }
  if (token === 'customSections') {
    return normalizeTargets([...targets.filter((t) => !isCustomSectionToken(t)), token]);
  }
  return normalizeTargets([...targets, token]);
}

/** Toggle one entry token unless its whole section is already selected. */
export function toggleItemToken(
  targets: readonly string[],
  section: 'workExperience' | 'personalProjects',
  index: number
): string[] {
  if (targets.includes(section)) return [...targets];
  const kind = section === 'workExperience' ? 'work' : 'project';
  const token = itemToken(kind, index);
  if (targets.includes(token)) return targets.filter((t) => t !== token);
  // Selecting the whole entry supersedes its sub-module selections: sweep them.
  const prefix = `${token}:`;
  return normalizeTargets([...targets.filter((t) => t !== token && !t.startsWith(prefix)), token]);
}

/**
 * Toggle one label sub-module token. No-op when its whole section or whole
 * entry is already selected (those supersede region tokens, mirroring the
 * backend scope gate).
 */
export function toggleRegionToken(
  targets: readonly string[],
  kind: 'work' | 'project',
  index: number,
  regionId: RegionId
): string[] {
  const section = kind === 'work' ? 'workExperience' : 'personalProjects';
  if (targets.includes(section) || targets.includes(itemToken(kind, index))) {
    return [...targets];
  }
  const token = regionToken(kind, index, regionId);
  if (targets.includes(token)) return targets.filter((t) => t !== token);
  return normalizeTargets([...targets, token]);
}

/** Which rendered heading groups are affected by a module-level selection. */
export function targetsToHeadingKeys(targets: readonly string[]): FineTuneHeadingKey[] {
  const keys = new Set<FineTuneHeadingKey>();
  for (const token of targets) {
    if (token === 'summary') keys.add('summary');
    else if (token === 'education') keys.add('education');
    else if (token === 'additional') keys.add('additional');
    else if (token === 'customSections' || isCustomSectionToken(token)) keys.add('custom');
    else if (token === 'workExperience' || token.startsWith('work_')) keys.add('experience');
    else if (token === 'personalProjects' || token.startsWith('project_')) keys.add('projects');
  }
  return Array.from(keys);
}

/** Normalize a rendered heading for comparison (case/colon/space-insensitive). */
export function normalizeHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/[:：]\s*$/u, '')
    .trim();
}

/** Match a rendered section heading against any of the expected labels. */
export function headingMatches(headingText: string, labels: readonly string[]): boolean {
  const normalized = normalizeHeading(headingText);
  if (!normalized) return false;
  return labels.some((label) => normalizeHeading(label) === normalized);
}

/** Build the request scope for a wizard selection. */
export function buildScope(kind: 'all' | 'modules', targets: readonly string[]): FineTuneScope {
  return kind === 'all'
    ? { kind: 'all', targets: [] }
    : { kind: 'modules', targets: normalizeTargets(targets) };
}
