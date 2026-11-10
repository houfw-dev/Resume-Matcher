export function downloadBlobAsFile(blob: Blob, filename: string): void {
  if (typeof document === 'undefined') return;
  if (!document.body) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    link.remove();
  }, 1000);
}

export function openUrlInNewTab(url: string): boolean {
  if (typeof window === 'undefined') return false;
  const newWindow = window.open(url, '_blank', 'noopener,noreferrer');
  if (newWindow) {
    newWindow.opener = null;
    return true;
  }
  return false;
}

/**
 * Sanitize a resume title for use as a filename
 * - Removes/replaces invalid filename characters
 * - Truncates to reasonable length
 * - Provides fallback if title is empty
 */
export type DownloadKind = 'resume' | 'cover-letter' | 'outreach' | 'interview-prep' | 'jd-match';

const FALLBACK_PREFIXES: Record<DownloadKind, string> = {
  resume: 'resume',
  'cover-letter': 'cover_letter',
  outreach: 'outreach',
  'interview-prep': 'interview_prep',
  'jd-match': 'jd_match',
};

export function sanitizeFilename(
  title: string | null | undefined,
  fallbackId: string,
  type: DownloadKind = 'resume',
  ext: 'pdf' | 'docx' = 'pdf'
): string {
  // Use fallback if no title
  if (!title?.trim()) {
    return `${FALLBACK_PREFIXES[type]}_${fallbackId}.${ext}`;
  }

  // Normalize Unicode to NFC form to ensure consistent representation
  // This ensures "Currículum" (NFD: i + combining accent) and "Currículum" (NFC: í as single char) produce the same filename
  let sanitized = title.normalize('NFC').trim();

  // Remove or replace invalid characters: / \ : * ? " < > |
  sanitized = sanitized
    .replace(/[/\\:*?"<>|]/g, '-') // Replace invalid chars with dash
    .replace(/\s+/g, ' ') // Normalize whitespace
    .trim();

  // Truncate to 100 characters using Array.from() to handle multi-byte characters correctly
  // This prevents splitting multi-byte UTF-8 characters (Chinese, Japanese, emoji) mid-sequence
  const chars = Array.from(sanitized); // Handles grapheme clusters properly
  if (chars.length > 100) {
    sanitized = chars.slice(0, 100).join('').trim();
  }

  // Add the requested extension
  return `${sanitized}.${ext}`;
}

/** Header facts used for resume download filenames (all optional). */
export interface ResumeFilenameFacts {
  /** 姓名 */
  name?: string | null;
  /** 年龄 */
  age?: string | null;
  /** 工作年限 */
  workYears?: string | null;
  /** 学历 (callers may fall back to the latest education degree) */
  educationLevel?: string | null;
  /** 求职意向 */
  title?: string | null;
}

/**
 * Build the resume PDF/DOCX download filename from header facts.
 * Format: 姓名-年龄-工作年限-学历-求职意向 (e.g. "王浩-28岁-5年-硕士-Java开发工程师.pdf").
 * Empty facts are skipped (no dangling dashes); falls back to resume_<id>.<ext>
 * when none exist. Mirrors the backend ``_resume_download_stem`` helper.
 */
export function buildResumeFactFilename(
  facts: ResumeFilenameFacts,
  fallbackId: string,
  ext: 'pdf' | 'docx' = 'pdf'
): string {
  const orderedFacts = [facts.name, facts.age, facts.workYears, facts.educationLevel, facts.title];
  const parts = orderedFacts
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  if (parts.length === 0) return `resume_${fallbackId}.${ext}`;
  return sanitizeFilename(parts.join('-'), fallbackId, 'resume', ext);
}

/**
 * Build the diagnosis Word report filename.
 * Format: <报告名>-<姓名>-<YYYYMMDD-HHmm>.docx
 * (e.g. "简历诊断报告-王浩-20261030-2156.docx"); a blank name is skipped.
 * The stamp uses local time and contains no filename-illegal characters.
 * Mirrors the backend ``diagnosis_docx_stem`` helper.
 */
export function buildDiagnosisReportFilename(
  fileStem: string,
  candidateName?: string | null,
  now: Date = new Date()
): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
  const stem = fileStem.trim();
  const name = candidateName?.trim();
  const raw = name ? `${stem}-${name}-${stamp}` : `${stem}-${stamp}`;
  return sanitizeFilename(raw, 'diagnosis', 'resume', 'docx');
}

const KIND_LABELS: Record<DownloadKind, string> = {
  resume: 'Resume',
  'cover-letter': 'Cover Letter',
  outreach: 'Outreach Message',
  'interview-prep': 'Interview Prep',
  'jd-match': 'JD Match',
};

/**
 * Build a personalized download filename for resume/attachment PDFs.
 * Format: "{Name} - {Type} - {Company}.pdf" (falls back gracefully when data is missing)
 */
export function buildResumeFilename(
  name: string | null | undefined,
  company: string | null | undefined,
  fallbackId: string,
  type: DownloadKind = 'resume'
): string {
  const typeLabel = KIND_LABELS[type];
  const cleanName = name?.trim() || null;
  const cleanCompany = company?.trim() || null;

  let raw: string;
  if (cleanName && cleanCompany) {
    raw = `${cleanName} - ${typeLabel} - ${cleanCompany}`;
  } else if (cleanName) {
    raw = `${cleanName} - ${typeLabel}`;
  } else {
    return sanitizeFilename(
      cleanCompany ? `${typeLabel} - ${cleanCompany}` : null,
      fallbackId,
      type
    );
  }

  return sanitizeFilename(raw, fallbackId, type);
}
