// Deterministic canonical casing for technical English terms.
//
// Same table, same regex boundaries, same field coverage as
// apps/backend/app/services/tech_terms.py: one case-insensitive pass fixes
// casing only ("java" -> "Java", "SPRING BOOT" -> "Spring Boot",
// "mysql集群" -> "MySQL集群"). It never adds/removes/translates anything;
// OCR/typo spelling correction stays the LLM's job. The term table itself is
// not hand-kept here — it is generated from rules/shared_terms.yaml into
// @/lib/generated/tech-terms.generated (drift gated by
// scripts/check_generated_rules.py); only the ES2017-specific matching logic
// lives in this file.
//
// Boundary semantics: a non-ASCII-alphanumeric boundary (or string start) on
// each side means adjacency to CJK, punctuation or whitespace matches
// ("Redis集群"), adjacency to another ASCII letter/digit does not ("Java"
// can't match inside "JavaScript", "Vue.js" can't match inside "Vue.jsx"),
// and longest terms win. The build targets ES2017, which has no lookbehind,
// so the leading boundary is consumed as a capture group and re-emitted by
// the replace callback — semantically identical to `(?<![A-Za-z0-9])`.
import type { ResumeData } from '@/components/dashboard/resume-component';
import { CANONICAL_TERMS } from '@/lib/generated/tech-terms.generated';

export { CANONICAL_TERMS };

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Longest-first so compounds win over their prefixes.
const SORTED_TERMS = [...new Set(CANONICAL_TERMS)].sort((a, b) => b.length - a.length);
// Group 1 is the leading boundary char (or empty at string start); the term
// itself is group 2. The boundary is consumed during matching but preserved in
// the replacement output.
const TERM_RE = new RegExp(
  `(^|[^A-Za-z0-9])(?:${SORTED_TERMS.map(escapeRegExp).join('|')})(?![A-Za-z0-9])`,
  'gi'
);
const CANONICAL_BY_LOWER = new Map<string, string>(
  SORTED_TERMS.map((term) => [term.toLowerCase(), term])
);

/** Replace every known term in one string with its canonical casing. */
export const canonicalizeTermsInText = (value: unknown): unknown => {
  if (typeof value !== 'string' || value.length === 0) {
    return value;
  }
  return value.replace(TERM_RE, (match, boundary: string) => {
    const term = match.slice(boundary.length);
    const canonical = CANONICAL_BY_LOWER.get(term.toLowerCase());
    return `${boundary}${canonical ?? term}`;
  });
};

const canonicalizeRows = (rows: unknown): unknown => {
  if (!Array.isArray(rows)) {
    return rows;
  }
  return rows.map((row) => canonicalizeTermsInText(row));
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Apply canonical term casing to a resume's content fields. Pure: the input
 * object is never mutated. Skips years, personalInfo, sectionMeta and URLs.
 */
export const canonicalizeTechTerms = (resume: ResumeData): ResumeData => {
  const data = resume as unknown as Record<string, unknown>;
  const result: Record<string, unknown> = { ...data };

  result.summary = canonicalizeTermsInText(data.summary);

  if (Array.isArray(data.workExperience)) {
    result.workExperience = data.workExperience.filter(isRecord).map((rawEntry) => {
      const entry: Record<string, unknown> = { ...rawEntry };
      for (const field of ['title', 'department'] as const) {
        entry[field] = canonicalizeTermsInText(entry[field]);
      }
      entry.description = canonicalizeRows(entry.description);
      return entry;
    });
  }

  if (Array.isArray(data.personalProjects)) {
    result.personalProjects = data.personalProjects.filter(isRecord).map((rawEntry) => {
      const entry: Record<string, unknown> = { ...rawEntry };
      for (const field of ['name', 'role'] as const) {
        entry[field] = canonicalizeTermsInText(entry[field]);
      }
      entry.description = canonicalizeRows(entry.description);
      return entry;
    });
  }

  if (isRecord(data.additional)) {
    const additional: Record<string, unknown> = { ...data.additional };
    for (const field of [
      'technicalSkills',
      'languages',
      'certificationsTraining',
      'awards',
    ] as const) {
      additional[field] = canonicalizeRows(additional[field]);
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
          ? rawSection.items.filter(isRecord).map((rawItem) => {
              const item: Record<string, unknown> = { ...rawItem };
              for (const field of ['title', 'subtitle'] as const) {
                item[field] = canonicalizeTermsInText(item[field]);
              }
              item.description = canonicalizeRows(item.description);
              return item;
            })
          : [];
        sections[key] = { ...rawSection, items };
      } else if (rawSection.sectionType === 'stringList') {
        sections[key] = {
          ...rawSection,
          strings: canonicalizeRows(rawSection.strings),
        };
      } else if (rawSection.sectionType === 'text' && typeof rawSection.text === 'string') {
        sections[key] = {
          ...rawSection,
          text: canonicalizeTermsInText(rawSection.text),
        };
      } else {
        sections[key] = rawSection;
      }
    }
    result.customSections = sections;
  }

  return result as unknown as ResumeData;
};
