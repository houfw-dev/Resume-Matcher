import type {
  CustomSection,
  CustomSectionItem,
  Experience,
  Project,
  ResumeData,
} from '@/components/dashboard/resume-component';
import { canonicalizeDatePeriod } from '@/lib/utils/date-period';
import { canonicalizeSectionMeta } from '@/lib/utils/section-order';
import { sortTimelineNewestFirst } from '@/lib/utils/timeline-sort';
import { canonicalizeTechTerms } from '@/lib/utils/tech-terms';
import { normalizeTextHygiene } from '@/lib/utils/text-hygiene';

type DescribedItem = {
  description?: unknown;
  descriptionStyles?: unknown;
};

const isMeaningfulText = (value: unknown): value is string => {
  return typeof value === 'string' && value.trim().length > 0;
};

// Param is `unknown`, not `string[] | undefined`: this runs against persisted
// data that TypeScript never validated, and the narrow type hid that.
const normalizeStringList = (items?: unknown): string[] | undefined => {
  // Only `undefined` means "field absent" — preserve it so the key stays out
  // of the payload. Every other non-array (notably `null` from malformed
  // persisted data) is coerced to []; the old `if (!items) return items`
  // returned null unchanged, leaking it into a value typed `string[] |
  // undefined` and crashing callers that assume an array.
  if (items === undefined) return undefined;
  if (!Array.isArray(items)) return [];
  return items.filter(isMeaningfulText).map((item) => item.trim());
};

const isObjectRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

// Canonical "yyyy.MM~yyyy.MM" / "yyyy.MM~至今" presentation on every years
// field; mirrors normalize_date_periods() in the backend parser, which also
// runs in the read-time self-heal chain. Colloquial values pass through.
const withCanonicalYears = <T>(item: T): T => {
  if (isObjectRecord(item) && typeof item.years === 'string') {
    return { ...item, years: canonicalizeDatePeriod(item.years) } as T;
  }
  return item;
};

const normalizeDescriptionFields = <T extends DescribedItem>(item: T): T => {
  // A null element inside an otherwise-valid array throws on property access.
  // Guarding the container was not enough — persisted arrays can hold nulls.
  if (!isObjectRecord(item)) {
    return item;
  }
  const descriptions = Array.isArray(item.description) ? item.description : [];
  // descriptionStyles is positional — styles[i] belongs to description[i]. It
  // must be filtered in lockstep, or dropping a blank description silently
  // shifts every later point's bullet/plain setting onto its neighbour.
  const styles = Array.isArray(item.descriptionStyles) ? item.descriptionStyles : undefined;
  const nextDescriptions: string[] = [];
  const nextStyles: unknown[] = [];

  descriptions.forEach((description, index) => {
    if (!isMeaningfulText(description)) {
      return;
    }

    nextDescriptions.push(description.trim());
    if (styles) {
      // "label" (bold sub-module heading) must survive save; anything unknown
      // falls back to "bullet".
      const style = styles[index];
      nextStyles.push(style === 'plain' || style === 'label' ? style : 'bullet');
    }
  });

  return {
    ...item,
    description: nextDescriptions,
    ...(styles ? { descriptionStyles: nextStyles } : {}),
  };
};

// Optional chaining guards null/undefined but NOT a non-string: a numeric
// `title` from malformed persisted data makes `.trim` undefined and throws
// "item.title?.trim is not a function". isMeaningfulText type-checks first.
const hasExperienceContent = (item: Experience): boolean => {
  return Boolean(
    isMeaningfulText(item.title) ||
    isMeaningfulText(item.company) ||
    isMeaningfulText(item.department) ||
    isMeaningfulText(item.location) ||
    isMeaningfulText(item.years) ||
    (Array.isArray(item.description) && item.description.length)
  );
};

const hasProjectContent = (item: Project): boolean => {
  return Boolean(
    isMeaningfulText(item.name) ||
    isMeaningfulText(item.role) ||
    isMeaningfulText(item.years) ||
    isMeaningfulText(item.scale) ||
    isMeaningfulText(item.github) ||
    isMeaningfulText(item.website) ||
    (Array.isArray(item.description) && item.description.length)
  );
};

const hasCustomItemContent = (item: CustomSectionItem): boolean => {
  return Boolean(
    isMeaningfulText(item.title) ||
    isMeaningfulText(item.subtitle) ||
    isMeaningfulText(item.location) ||
    isMeaningfulText(item.years) ||
    (Array.isArray(item.description) && item.description.length)
  );
};

const normalizeCustomSection = (section: CustomSection): CustomSection => {
  // A persisted customSections entry can be null or a primitive; reading
  // .sectionType off it throws. Guard the section value, not only its items.
  if (!isObjectRecord(section)) {
    return section;
  }

  if (section.sectionType === 'itemList') {
    return {
      ...section,
      // Array.isArray, not `|| []` — a malformed truthy non-array (an object
      // from hand-edited storage) reaches .map and throws.
      items: (Array.isArray(section.items) ? section.items : [])
        .filter(isObjectRecord)
        .map((item) => withCanonicalYears(normalizeDescriptionFields(item)))
        .filter(hasCustomItemContent),
    };
  }

  if (section.sectionType === 'stringList') {
    return {
      ...section,
      strings: normalizeStringList(section.strings),
    };
  }

  return section;
};

export const normalizeResumeForSave = (resumeInput: ResumeData): ResumeData => {
  // Mirrors the backend parse/heal chain order: canonical tech-term casing
  // first, THEN presentation hygiene (trim, whitespace collapse, lockstep
  // blank-row drops, unified list-point endings, summary/custom-text blank-
  // line removal) so casing-only duplicates collapse in later steps.
  const resume = normalizeTextHygiene(canonicalizeTechTerms(resumeInput));

  const customSections = resume.customSections
    ? Object.fromEntries(
        Object.entries(resume.customSections).map(([key, section]) => [
          key,
          normalizeCustomSection(section),
        ])
      )
    : resume.customSections;

  const normalized: ResumeData = {
    ...resume,
    // Entries persist newest-first, mirroring the render-time order.
    workExperience:
      sortTimelineNewestFirst(
        (Array.isArray(resume.workExperience) ? resume.workExperience : [])
          .filter(isObjectRecord)
          .map((item) => withCanonicalYears(normalizeDescriptionFields(item)))
          .filter(hasExperienceContent)
      ) ?? [],
    personalProjects: (Array.isArray(resume.personalProjects) ? resume.personalProjects : [])
      .filter(isObjectRecord)
      .map((item) => withCanonicalYears(normalizeDescriptionFields(item)))
      .filter(hasProjectContent),
    // education was the one top-level collection left unguarded, so a null or
    // primitive entry survived normalization and reached the render path.
    // Education.description is a scalar, so there are no styles to align here.
    education:
      sortTimelineNewestFirst(
        (Array.isArray(resume.education) ? resume.education : [])
          .filter(isObjectRecord)
          .map(withCanonicalYears)
      ) ?? [],
    additional: resume.additional
      ? {
          ...resume.additional,
          technicalSkills: normalizeStringList(resume.additional.technicalSkills),
          languages: normalizeStringList(resume.additional.languages),
          certificationsTraining: normalizeStringList(resume.additional.certificationsTraining),
          awards: normalizeStringList(resume.additional.awards),
        }
      : resume.additional,
    customSections,
  };

  // Fixed canonical section order + title governance: rewrite meta order for
  // the degree branch, reset renamed default titles, and hide empty optional
  // blocks. Runs against the NORMALIZED content so emptiness sees the same
  // pruned data the resume renders.
  return { ...normalized, sectionMeta: canonicalizeSectionMeta(normalized) };
};

export const normalizeResumeForRender = (resume: ResumeData): ResumeData => {
  return normalizeResumeForSave(resume);
};
