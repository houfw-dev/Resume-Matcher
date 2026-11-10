/**
 * Canonical date-period formatting.
 *
 * KEEP IN SYNC with the backend mirror
 * `apps/backend/app/services/parser.py::canonicalize_date_period`
 * (regexes, month table, present markers and skip chars must agree).
 *
 * Output forms:
 * - "2020.06~2023.09"  (range, tilde connector, no spaces)
 * - "2021.05~至今"     (open-ended range; every marker language collapses to 至今)
 * - "2020~2021"        (year-only precision is preserved — never invent months)
 * - "2020.06"          (single point)
 *
 * Values carrying non-date prose (colloquial durations like "三年经验",
 * stray words, multiple present markers) come back byte-identical, apart
 * from one optional trailing parenthesized note such as "（实习）".
 */

const EN_MONTH_BY_NAME: Readonly<Record<string, number>> = Object.freeze({
  jan: 1,
  january: 1,
  feb: 2,
  february: 2,
  mar: 3,
  march: 3,
  apr: 4,
  april: 4,
  may: 5,
  jun: 6,
  june: 6,
  jul: 7,
  july: 7,
  aug: 8,
  august: 8,
  sep: 9,
  sept: 9,
  september: 9,
  oct: 10,
  october: 10,
  nov: 11,
  november: 11,
  dec: 12,
  december: 12,
});

const MONTH_ALTERNATION = Object.keys(EN_MONTH_BY_NAME)
  .sort((a, b) => b.length - a.length)
  .join('|');

// "2020.06" / "2020/6" / "2020-06" / "2020年6月" (no day part).
const NUMERIC_POINT_RE = /(\d{4})\s*[年./-]\s*(0?[1-9]|1[0-2])(?!\d|[./-]\d)(?:\s*月)?/g;
// "Jan 2020" / "January 2020" (optional trailing dot).
const EN_POINT_RE = new RegExp(`\\b(${MONTH_ALTERNATION})\\.?\\s+(\\d{4})`, 'gi');
// Bare four-digit year, never adjacent to another date component. ES2017 has
// no lookbehind, so the leading non-digit/non-dot boundary is captured as
// group 1 (empty at string start) and the token offset is compensated below.
const BARE_YEAR_RE = /(^|[^\d.])(\d{4})(?!\d|[./-]\d)/g;
const PRESENT_RE = /至今|现在|目前|Present|Current|Now|Ongoing/gi;
const CONNECTOR_WORD_RE = /\bto\b/gi;
const TRAILING_NOTE_RE = /^[（(][^（）()]*[)）]\s*$/;
// Characters allowed between date points: whitespace, dash family, tildes, 至.
const SKIP_CHARS = new Set([' ', '\t', '\r', '\n', ' ', '-', '–', '—', '―', '~', '～', '至']);

interface SpanToken {
  start: number;
  end: number;
  text: string;
}

interface MatchSpan {
  index: number;
  0: string;
  groups: string[];
}

const collect = (value: string, re: RegExp): MatchSpan[] => {
  re.lastIndex = 0;
  const spans: MatchSpan[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(value)) !== null) {
    spans.push({ index: m.index, 0: m[0], groups: m.slice(1) });
    if (m[0] === '') re.lastIndex += 1;
  }
  return spans;
};

const overlaps = (start: number, end: number, tokens: SpanToken[]): boolean =>
  tokens.some((token) => start < token.end && token.start < end);

export function canonicalizeDatePeriod(value: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    return value;
  }

  // Specific (month-precise) tokens first; bare years fill only unclaimed
  // spans so "2020.06" never yields both a numeric and a year token.
  const tokens: SpanToken[] = [];

  for (const match of collect(value, NUMERIC_POINT_RE)) {
    tokens.push({
      start: match.index,
      end: match.index + match[0].length,
      text: `${Number(match.groups[0]).toString().padStart(4, '0')}.${Number(match.groups[1])
        .toString()
        .padStart(2, '0')}`,
    });
  }

  for (const match of collect(value, EN_POINT_RE)) {
    const month = EN_MONTH_BY_NAME[match.groups[0].toLowerCase()];
    if (!overlaps(match.index, match.index + match[0].length, tokens)) {
      tokens.push({
        start: match.index,
        end: match.index + match[0].length,
        text: `${Number(match.groups[1]).toString().padStart(4, '0')}.${month
          .toString()
          .padStart(2, '0')}`,
      });
    }
  }

  for (const match of collect(value, BARE_YEAR_RE)) {
    // Group 1 is the consumed boundary char; the year itself starts after it.
    const start = match.index + match.groups[0].length;
    const end = start + match.groups[1].length;
    if (!overlaps(start, end, tokens)) {
      tokens.push({
        start,
        end,
        text: Number(match.groups[1]).toString().padStart(4, '0'),
      });
    }
  }

  tokens.sort((a, b) => a.start - b.start);

  const presentMatches = collect(value, PRESENT_RE).filter(
    (match) => !overlaps(match.index, match.index + match[0].length, tokens)
  );

  const points = tokens.map((token) => token.text);
  const hasPresent = presentMatches.length > 0;
  const ordered: SpanToken[] = hasPresent
    ? [
        ...tokens,
        ...presentMatches.map((match) => ({
          start: match.index,
          end: match.index + match[0].length,
          text: '至今',
        })),
      ].sort((a, b) => a.start - b.start)
    : tokens;

  if (
    presentMatches.length > 1 ||
    points.length < 1 ||
    points.length > 2 ||
    (hasPresent && points.length !== 1)
  ) {
    return value;
  }

  // Everything outside date/marker tokens must be connectors/whitespace;
  // one trailing parenthesized note is allowed after the final token.
  let note = '';
  let cursor = 0;
  for (const token of ordered) {
    const gap = value.slice(cursor, token.start).replace(CONNECTOR_WORD_RE, '');
    if (Array.from(gap).some((char) => !SKIP_CHARS.has(char))) {
      return value;
    }
    cursor = token.end;
  }
  const tail = value.slice(cursor).trim();
  if (tail) {
    if (!TRAILING_NOTE_RE.test(tail)) {
      return value;
    }
    note = tail;
  }

  if (hasPresent) {
    return `${points[0]}~至今${note}`;
  }
  if (points.length === 2) {
    return `${points[0]}~${points[1]}${note}`;
  }
  return `${points[0]}${note}`;
}
