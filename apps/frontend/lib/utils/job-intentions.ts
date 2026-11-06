/**
 * Split a resume's 求职意向 (job intention) string into distinct target titles.
 *
 * Resumes sometimes list several directions in one field, e.g.
 * "Java 开发/大数据开发、后端架构". The diagnosis then needs the user to pick
 * one target title. Delimiters are separators only — conjunctions like 和/与
 * are intentionally NOT split ("研发与管理" is one compound title).
 */
const INTENTION_SPLIT_RE = /[/／、,，;；|｜]|\r?\n/;

export function splitJobIntentions(title: string | null | undefined): string[] {
  if (!title) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const part of title.split(INTENTION_SPLIT_RE)) {
    const trimmed = part.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    result.push(trimmed);
  }
  return result;
}
