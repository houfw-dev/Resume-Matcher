/**
 * Display-side mirror of the backend Markdown-emphasis stripper
 * (apps/backend/app/services/parser.py: strip_markdown_emphasis*).
 *
 * LLM extraction occasionally leaks `**bold**` fragments into structured
 * fields — sometimes even split across fields (observed: educationLevel
 * "统招本科（**985&211)" followed by workYears " **5年…）**"). Resume
 * renderers never interpret Markdown, so every emphasis marker is removed
 * while its enclosed text is kept. Keep the regex behaviour in sync with the
 * Python copy; both are covered by their own deterministic tests.
 */

// No `s`/lookbehind flags (tsconfig targets ES2017): the negated character
// classes already span newlines, and the leading emphasis boundary is
// captured and restored instead of using a lookbehind.
const MD_BOLD_STAR_RE = /\*\*\s*([^*]+?)\s*\*\*/g;
const MD_BOLD_UNDER_RE = /__\s*([^_]+?)__/g;
// Single `*` / `_` only count as emphasis away from word characters, so
// "A*", "5*8" and "my_var" survive.
const MD_ITALIC_STAR_RE = /(^|[^\w*])\*([^*\s][^*]*?)\*(?![\w*])/g;
const MD_ITALIC_UNDER_RE = /(^|[^\w_])_([^_\s][^_]*?)_(?![\w_])/g;
const MD_CODE_RE = /`+([^`]+?)`+/g;
const MD_STRIKE_RE = /~~([^~]+?)~~/g;
// Orphan fragments (including the surviving half of a marker split across
// fields) are removed only after every paired marker is unwrapped.
const MD_ORPHAN_BOLD_RE = /\*\*|__/g;
const MD_ORPHAN_STRIKE_RE = /~~/g;

/**
 * Remove Markdown emphasis modifiers from one string, keeping the text.
 * Non-string input is returned unchanged.
 */
export function stripMarkdownEmphasis<T>(text: T): T;
export function stripMarkdownEmphasis(text: unknown): unknown;
export function stripMarkdownEmphasis(text: unknown): unknown {
  if (typeof text !== 'string') return text;
  let out = text;
  out = out.replace(MD_BOLD_STAR_RE, '$1');
  out = out.replace(MD_BOLD_UNDER_RE, '$1');
  out = out.replace(MD_ITALIC_STAR_RE, '$1$2');
  out = out.replace(MD_ITALIC_UNDER_RE, '$1$2');
  out = out.replace(MD_CODE_RE, '$1');
  out = out.replace(MD_STRIKE_RE, '$1');
  out = out.replace(MD_ORPHAN_BOLD_RE, '');
  out = out.replace(MD_ORPHAN_STRIKE_RE, '');
  return out;
}

/**
 * Rebuild a nested object/array with every string leaf emphasis-stripped.
 * Keys are never modified; non-string scalars pass through unchanged.
 */
export function stripMarkdownEmphasisDeep<T>(value: T): T;
export function stripMarkdownEmphasisDeep(value: unknown): unknown;
export function stripMarkdownEmphasisDeep(value: unknown): unknown {
  if (typeof value === 'string') {
    return stripMarkdownEmphasis(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => stripMarkdownEmphasisDeep(item));
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        stripMarkdownEmphasisDeep(item),
      ])
    );
  }
  return value;
}

/**
 * De-duplicate the rendered string-list fields of a ResumeData object.
 * Mirrors the backend parser's `dedupe_resume_lists`: once Markdown markers
 * are gone, entries that differed only by formatting collapse to the same
 * text (observed additional.languages ["英语四级", "英语四级**"] rendered
 * twice in the header fact grid). Comparison is whitespace-insensitive, the
 * first entry wins and empty strings are kept. Index-aligned arrays
 * (description / descriptionStyles) are intentionally not touched.
 */
const DEDUPABLE_FIELDS = [
  'technicalSkills',
  'certificationsTraining',
  'awards',
  'languages',
] as const;

function dedupeStringList(items: unknown[]): unknown[] {
  if (!items.every((item) => typeof item === 'string')) return items;
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = (item as string).trim();
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function dedupeResumeLists<T>(value: T): T;
export function dedupeResumeLists(value: unknown): unknown;
export function dedupeResumeLists(value: unknown): unknown {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return value;
  }
  const root = value as Record<string, unknown>;
  const additional = root.additional;
  if (additional !== null && typeof additional === 'object' && !Array.isArray(additional)) {
    const bucket = additional as Record<string, unknown>;
    for (const field of DEDUPABLE_FIELDS) {
      const items = bucket[field];
      if (Array.isArray(items)) bucket[field] = dedupeStringList(items);
    }
  }
  const customSections = root.customSections;
  if (
    customSections !== null &&
    typeof customSections === 'object' &&
    !Array.isArray(customSections)
  ) {
    for (const section of Object.values(customSections as Record<string, unknown>)) {
      if (section !== null && typeof section === 'object' && !Array.isArray(section)) {
        const strings = (section as Record<string, unknown>).strings;
        if (Array.isArray(strings)) {
          (section as Record<string, unknown>).strings = dedupeStringList(strings);
        }
      }
    }
  }
  return value;
}
