import type { Experience } from '@/components/dashboard/resume-component';

/**
 * Standalone org-unit line weak parsers file as a "plain" work description row
 * ("全球资金部" / "研发部" / "云计算集成部" / "Payments Department"). Tight
 * gate: short, no sentence punctuation, ends with a known organization suffix.
 * Mirrors the backend recognizer `_looks_like_department_line` in
 * apps/backend/app/services/parser.py so legacy stored resumes render the same
 * as freshly parsed ones.
 */
const DEPARTMENT_LINE_RE =
  /^\s*(?:[一-鿿][一-鿿A-Za-z0-9（）()·&/+\- ]{0,13}(?:事业部|事业群|部门|条线|分院|大区|办公室|中心|团队|小组|[部组室科处])|[A-Za-z0-9][A-Za-z0-9 &/+\-]{1,28}(?:Department|Dept\.?|Division|Team|Group))(?:[（(][^（）()]{1,12}[）)])?\s*$/;

const SENTENCE_PUNCT_RE = /[。．.，,；;：:！!？?、…]/;

export function looksLikeDepartmentLine(line: unknown): line is string {
  if (typeof line !== 'string') return false;
  const text = line.trim();
  if (text.length < 2) return false;
  if (SENTENCE_PUNCT_RE.test(text)) return false;
  return DEPARTMENT_LINE_RE.test(text);
}

export interface PromotedWorkEntry {
  /** Department to show in the header column — "" when the entry has none. */
  department: string;
  /** Description rows left after a promoted department line. */
  description: string[];
  descriptionStyles: Experience['descriptionStyles'];
}

/**
 * Resolve the department column for a work entry. Prefers the parsed
 * `department` field; when that is empty and the FIRST description row is a
 * standalone org-unit line styled "plain" (legacy data parsed before the
 * parser learned the field), promote it out of the description so the row
 * renders as 时间 | 公司 | 部门 | 岗位. Never mutates the entry.
 */
export function promoteWorkDepartment(exp: Experience): PromotedWorkEntry {
  const description = Array.isArray(exp.description) ? exp.description : [];
  const styles = exp.descriptionStyles ?? [];
  const explicit = exp.department?.trim() ?? '';
  if (explicit) {
    return {
      department: explicit,
      description,
      descriptionStyles: styles,
    };
  }
  if (styles[0] !== 'plain' || !looksLikeDepartmentLine(description[0])) {
    return { department: '', description, descriptionStyles: styles };
  }
  return {
    department: description[0].trim(),
    description: description.slice(1),
    descriptionStyles: styles.slice(1),
  };
}
