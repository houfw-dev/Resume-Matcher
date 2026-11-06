// Presentation hygiene for resume content.
//
// KEEP IN SYNC with the normalize_text_hygiene block in
// apps/backend/app/services/parser.py (same regexes, same field coverage, same
// style semantics): trim rows, collapse whitespace runs, drop blank rows in
// lockstep with their styles, drop blank lines from text blocks, unify
// rendered string lists, and strip trailing sentence punctuation from LIST
// points only. Plain prose keeps its periods; punctuation is never added.
import type { ResumeData } from '@/components/dashboard/resume-component';

const VALID_DESCRIPTION_STYLES = new Set(['bullet', 'plain', 'label']);

// Terminal punctuation stripped from list points. Conservative: only the
// trailing run is removed.
const LIST_TRAILING_PUNCT_RE = /[。.；;！？!?]+[ 　\t]*$/;
// Runs of horizontal whitespace (tab, NBSP U+00A0, ideographic space U+3000)
// collapse to one ASCII space.
const WHITESPACE_RUN_RE = /[ \t 　]+/g;

export const cleanRow = (row: string): string => row.replace(WHITESPACE_RUN_RE, ' ').trim();

export const stripListEnding = (row: string): string =>
  row.replace(LIST_TRAILING_PUNCT_RE, '').trimEnd();

/**
 * Trim/drop description rows in lockstep with descriptionStyles. Blank rows
 * take their OWN style with them (a positional filter would shift every later
 * bullet/plain setting onto its neighbour). Bullet rows additionally lose
 * trailing sentence punctuation; plain and label rows are only trimmed.
 */
export const normalizeHygieneDescription = <
  T extends {
    description?: unknown;
    descriptionStyles?: unknown;
  },
>(
  item: T
): T => {
  if (typeof item !== 'object' || item === null || Array.isArray(item)) {
    return item;
  }
  const descriptions = Array.isArray(item.description) ? item.description : [];
  const styles = Array.isArray(item.descriptionStyles) ? item.descriptionStyles : undefined;
  const nextDescriptions: string[] = [];
  const nextStyles: unknown[] = [];

  descriptions.forEach((rawRow, index) => {
    if (typeof rawRow !== 'string') {
      return;
    }
    let row = cleanRow(rawRow);
    if (!row) {
      return;
    }
    let style =
      styles && index < styles.length && typeof styles[index] === 'string'
        ? (styles[index] as string)
        : 'bullet';
    if (!VALID_DESCRIPTION_STYLES.has(style)) {
      style = 'bullet';
    }
    if (style === 'bullet') {
      row = stripListEnding(row);
      if (!row) {
        return;
      }
    }
    nextDescriptions.push(row);
    if (styles) {
      nextStyles.push(style);
    }
  });

  return {
    ...item,
    description: nextDescriptions,
    ...(styles ? { descriptionStyles: nextStyles } : {}),
  };
};

/** Outer-trim a text block; trim every line and drop blank lines. */
export const cleanTextBlock = (
  value: unknown,
  { stripEndings }: { stripEndings: boolean }
): unknown => {
  if (typeof value !== 'string') {
    return value;
  }
  const lines: string[] = [];
  for (const rawLine of value.split(/\r\n|\r|\n/)) {
    let line = cleanRow(rawLine);
    if (!line) {
      continue;
    }
    if (stripEndings) {
      line = stripListEnding(line);
      if (!line) {
        continue;
      }
    }
    lines.push(line);
  }
  return lines.join('\n');
};

/** Trim rendered string-list entries, drop blanks, unify endings. */
export const cleanStringList = (values: unknown): unknown => {
  if (!Array.isArray(values)) {
    return values;
  }
  const cleaned: unknown[] = [];
  for (const value of values) {
    if (typeof value !== 'string') {
      cleaned.push(value);
      continue;
    }
    const row = stripListEnding(cleanRow(value));
    if (row) {
      cleaned.push(row);
    }
  }
  return cleaned;
};

const trimHeaderFields = <T extends object>(entry: T, fields: readonly string[]): T => {
  const record = entry as Record<string, unknown>;
  const next: Record<string, unknown> = {};
  for (const field of fields) {
    next[field] =
      typeof record[field] === 'string' ? (record[field] as string).trim() : record[field];
  }
  return { ...entry, ...next };
};

const PERSONAL_INFO_FIELDS = [
  'name',
  'title',
  'email',
  'phone',
  'location',
  'gender',
  'age',
  'workYears',
  'educationLevel',
  'website',
  'linkedin',
  'github',
] as const;

const WORK_FIELDS = ['title', 'company', 'department', 'location'] as const;
const PROJECT_FIELDS = ['name', 'role', 'scale', 'github', 'website'] as const;
const EDUCATION_FIELDS = ['institution', 'degree', 'description'] as const;
const ITEM_FIELDS = ['title', 'subtitle', 'location'] as const;

const DEDUPABLE_ADDITIONAL_FIELDS = [
  'technicalSkills',
  'languages',
  'certificationsTraining',
  'awards',
] as const;

// Mirrors _SELF_EVALUATION_KEYS in parser.py.
const SELF_EVALUATION_KEYS = new Set([
  'self_evaluation',
  'self_eval',
  'self_appraisal',
  'selfassessment',
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Deep presentation hygiene over a full resume. Pure: the input object is
 * never mutated (the builder keeps raw form state).
 */
export const normalizeTextHygiene = (resume: ResumeData): ResumeData => {
  const data = resume as unknown as Record<string, unknown>;
  const result: Record<string, unknown> = { ...data };

  result.summary = cleanTextBlock(data.summary, { stripEndings: true });

  if (isRecord(data.personalInfo)) {
    result.personalInfo = trimHeaderFields(data.personalInfo, PERSONAL_INFO_FIELDS);
  }

  if (Array.isArray(data.workExperience)) {
    result.workExperience = data.workExperience
      .filter(isRecord)
      .map((entry) => normalizeHygieneDescription(trimHeaderFields(entry, WORK_FIELDS)));
  }

  if (Array.isArray(data.education)) {
    result.education = data.education
      .filter(isRecord)
      .map((entry) => trimHeaderFields(entry, EDUCATION_FIELDS));
  }

  if (Array.isArray(data.personalProjects)) {
    result.personalProjects = data.personalProjects
      .filter(isRecord)
      .map((entry) => normalizeHygieneDescription(trimHeaderFields(entry, PROJECT_FIELDS)));
  }

  if (isRecord(data.additional)) {
    const additional: Record<string, unknown> = { ...data.additional };
    for (const field of DEDUPABLE_ADDITIONAL_FIELDS) {
      additional[field] = cleanStringList(additional[field]);
    }
    result.additional = additional;
  }

  if (isRecord(data.customSections)) {
    const sections: Record<string, unknown> = {};
    for (const [key, rawSection] of Object.entries(data.customSections)) {
      if (!isRecord(rawSection)) {
        sections[key] = rawSection;
        continue;
      }
      if (rawSection.sectionType === 'itemList') {
        const items = Array.isArray(rawSection.items)
          ? rawSection.items
              .filter(isRecord)
              .map((item) => normalizeHygieneDescription(trimHeaderFields(item, ITEM_FIELDS)))
          : [];
        sections[key] = {
          ...trimHeaderFields(rawSection, ['title']),
          items,
        };
      } else if (rawSection.sectionType === 'stringList') {
        sections[key] = {
          ...rawSection,
          strings: cleanStringList(rawSection.strings),
        };
      } else if (rawSection.sectionType === 'text') {
        sections[key] = {
          ...trimHeaderFields(rawSection, ['title']),
          text: cleanTextBlock(rawSection.text, {
            stripEndings: SELF_EVALUATION_KEYS.has(key),
          }),
        };
      } else {
        sections[key] = rawSection;
      }
    }
    result.customSections = sections;
  }

  return result as unknown as ResumeData;
};
