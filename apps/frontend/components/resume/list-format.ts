// Leading numbering the source resume already carried ("1、", "1)", "①",
// "一、", bullet glyphs). Every resume list renders its OWN ordered numbers,
// so these prefixes are stripped on display/PDF to avoid double numbering
// ("1. 1、…"). Shared by DescriptionList (work/project/custom item points),
// PointTextList / OrderedStringList (summary, custom text, string lists) and
// the compact skill/award renderers.
// Glyph markers need no following whitespace ("•Java" is still a bullet);
// dash markers keep the whitespace requirement to protect minus signs and
// version ranges like "-30%" / "v1.0-2.0".
const POINT_MARKER_RE =
  /^\s*(?:\d{1,2}\s*[.、)）．:：]|[（(]\d{1,2}[)）]|[①②③④⑤⑥⑦⑧⑨⑩]|[•·・●▪▸▹◆■]|[\-—–]\s+|[一二三四五六七八九十]{1,3}\s*[、.．)）])\s*/;

export function stripPointMarker(point: string): string {
  return point.replace(POINT_MARKER_RE, '');
}

// Mirrors app/services/parser.py::_SUB_LABEL_CANDIDATES. Sub-module headings
// inside work/project descriptions (项目职责 / 技术栈 / …). Keep in sync with
// the backend tuple; the deterministic parser pass already emits the "label"
// style for these, and this set only bolds legacy rows still stored "plain".
const SUB_LABEL_CANDIDATES = new Set<string>([
  '技术难点及亮点',
  '技术难度及解决方案',
  '技术架构',
  '系统架构',
  '架构说明',
  '项目背景',
  '项目概述',
  '业务背景',
  '项目描述',
  '项目简介',
  '需求背景',
  '项目概况',
  '项目介绍',
  '工作职责',
  '工作内容',
  '项目职责',
  '个人职责',
  '项目责任',
  '核心职责与成果',
  '项目职责与成果',
  '项目职责和成果',
  '项目职责及成果',
  '工作职责与成果',
  '工作职责和成果',
  '工作职责及成果',
  '个人职责与成果',
  '职责与成果',
  '职责和成果',
  '职责及成果',
  '主要职责',
  '核心职责',
  '核心工作',
  '责任描述',
  '负责内容',
  '技术栈',
  '技术列表',
  '技术选型',
  '所用技术',
  '技术清单',
  '技术方案',
  '技术亮点',
  '技术难点',
  '难点及亮点',
  '难点与解决',
  '难点与方案',
  '解决方案',
  '项目亮点',
  '项目难点',
  '项目成果',
  '个人成果',
  '工作业绩',
  '项目业绩',
  '主要成果',
  '核心成果',
  // Outcome/effectiveness modules are peers of 项目亮点 (resumes often carry
  // both: highlight bullets then a 项目成效 prose block). Kept verbatim — not
  // in the canonical rename map — so they never nest under 项目亮点 as a
  // numbered sub-head. Mirror of parser.py / resume_docx.py candidate sets.
  '项目成效',
  '工作成效',
  '实施成效',
  '建设成效',
  '应用成效',
  '业务成效',
  '落地成效',
  '实际成效',
  '量化成效',
  '运营成效',
  '项目效果',
  '实施效果',
  '应用效果',
  '落地效果',
  '运行效果',
  '实际效果',
  '项目角色',
  '担任角色',
]);

// A label-only row ending in a colon: short CJK/latin heading, no sentence
// punctuation. Mirrors parser.py::_STANDALONE_SUB_LABEL_RE (colon form).
// A space/hyphen inside the run covers latin-prefixed heads such as
// "CPU 飙升问题：" rewritten by the model.
const STANDALONE_LABEL_RE =
  /^(?:[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,11}|[A-Za-z][A-Za-z /-]{0,20})\s*[：:]\s*$/;

// Sentence/line punctuation that proves a row is body text, not a heading.
// Mirrors _NESTED_GROUP_HEAD_PUNCT_RE in parser.py / resume_docx.py — keep
// the character class identical across all three sites.
const SENTENCE_PUNCTUATION_RE = /[，。；！？、,.!?;：:]/;

/**
 * Whether a stored "plain" description row is in fact a sub-module heading
 * (项目职责：/技术栈/负责内容…) that should render bold. Only applied to
 * legacy rows still stored as "plain" — rows parsed with the "label" style
 * are bold unconditionally.
 */
export function looksLikeSubLabel(point: string): boolean {
  const text = stripPointMarker(point).trim();
  if (!text) return false;
  const endsWithColon = /[：:]\s*$/.test(text);
  const core = text.replace(/[：:]\s*$/, '').trim();
  if (SUB_LABEL_CANDIDATES.has(core)) return true;
  if (!endsWithColon) return false;
  if (SENTENCE_PUNCTUATION_RE.test(core)) return false;
  return STANDALONE_LABEL_RE.test(text);
}

// Descriptive (non-duty) sub-labels: project intro/background and tech-stack
// enumerations. Such a label owns an UNNUMBERED body block — its content sits
// below the bold label aligned to the label's text edge, never taking a list
// number (it is context, not a duty/highlight point). Canonical targets
// 项目背景/技术栈 plus the labels that keep their verbatim name but share the
// descriptive layout （项目描述/系统架构/架构说明). Mirrors the parser-side
// split that forces the content to "plain" on fresh uploads.
const PROJECT_INLINE_PLAIN_LABELS = new Set<string>([
  '项目简介',
  '项目描述',
  '项目概况',
  '项目背景',
  '项目概述',
  '业务背景',
  '需求背景',
  '项目介绍',
  '技术架构',
  '系统架构',
  '架构说明',
  '技术栈',
  '技术列表',
  '技术选型',
  '所用技术',
  '技术清单',
]);

// Canonical descriptive label cores: bold head whose following rows form an
// unnumbered body block. Looked up AFTER canonical renaming, so aliases are
// covered; 项目描述/系统架构/架构说明 stay verbatim but get the same layout.
const PROJECT_DESCRIPTIVE_LABELS = new Set<string>([
  '项目背景',
  '技术栈',
  '项目描述',
  '系统架构',
  '架构说明',
]);

/**
 * Whether a (already canonicalized) sub-label core is a descriptive head
 * （项目背景 / 技术栈 / …) whose content renders as an unnumbered body block.
 */
export function isProjectDescriptiveLabel(labelDesc: string): boolean {
  const core = stripPointMarker(labelDesc)
    .trim()
    .replace(/[：:]\s*$/, '')
    .trim();
  return PROJECT_DESCRIPTIVE_LABELS.has(core);
}

/**
 * Whether a (canonicalized) descriptive label is the tech-stack enumeration:
 * its rows merge into one inline-wrapped line, unlike prose bodies
 * （项目背景/项目描述/系统架构/架构说明） which keep one paragraph per row.
 */
export function isProjectTechStackLabel(labelDesc: string): boolean {
  const core = stripPointMarker(labelDesc)
    .trim()
    .replace(/[：:]\s*$/, '')
    .trim();
  return core === '技术栈';
}

// Canonical bullet-region module cores (mirror parser._PROJECT_REGION_BULLET_CORES
// and resume_docx._PROJECT_BULLET_LABELS): the only labels whose numbered lists
// keep the number gutter. Every OTHER peer module (项目成效/项目治理/难点/方案/…)
// renders flush with the label edge — its unnumbered rows carry no empty gutter.
const CANONICAL_NUMBERED_MODULE_CORES = new Set(['项目职责', '项目亮点']);

/**
 * Whether a (canonicalized) sub-label core is one of the two numbered duty/
 * highlight modules. Peer modules outside the big four
 * （项目背景/技术栈/项目职责/项目亮点） return false and render flush.
 */
export function isCanonicalNumberedModule(labelDesc: string): boolean {
  const core = stripPointMarker(labelDesc)
    .trim()
    .replace(/[：:]\s*$/, '')
    .trim();
  return CANONICAL_NUMBERED_MODULE_CORES.has(core);
}

/**
 * Whether a heading row is a RECOGNIZED sub-module name （项目职责 / 技术栈 /
 * 负责内容 / …). A short colon heading that is NOT recognized is a nested
 * point head inside a duty/highlight module (e.g. "重大生产环境问题解决："
 * under 项目亮点）, not a module separator.
 */
export function isKnownSubLabel(point: string): boolean {
  const core = stripPointMarker(point)
    .trim()
    .replace(/[：:]\s*$/, '')
    .trim();
  return SUB_LABEL_CANDIDATES.has(core);
}

// Bare (colon-less) bold sub-headings that GROUP the points below them, e.g.
// "架构演进与技术债务治理" on its own row followed by duty bullets. The source
// prints them without a number or colon; weak models store them as short
// rows (plain, label OR bullet) among the points. The renderer numbers such a
// head as a level-1 point and its details as 1.1/1.2 sub-points. Mirrors
// parser.py::_is_nested_head_shaped / _plan_nested_group_heads and the
// resume_docx.py helpers — keep the three in sync.
const NESTED_GROUP_HEAD_MAX_LEN = 16;
// A real grouping structure holds at least this many head groups per module;
// an isolated short row amid normal points is a peer point, never a head.
const NESTED_GROUP_MIN_HEADS = 2;

/**
 * Shape-only test for a bare bold group heading (no successor check). True
 * for short (≤16 chars), unnumbered, colon-less rows without
 * sentence/enumeration punctuation, whether the weak model stored them as
 * plain, label or bullet. The structural decision lives in
 * planNestedGroupHeads(). Source-numbered enumerations ("2）机审"), colon
 * headings and prose sentences fail.
 */
export function looksLikeNestedGroupHead(
  point: string,
  style: DescriptionRowStyle | null | undefined
): boolean {
  if (style !== 'plain' && style !== 'label' && style !== 'bullet') return false;
  const text = point.trim();
  if (!text || /[：:]\s*$/.test(text)) return false;
  // A source-numbered enumeration ("2）机审") is a detail row, not a head.
  if (stripPointMarker(text) !== text) return false;
  if (text.length > NESTED_GROUP_HEAD_MAX_LEN) return false;
  return !SENTENCE_PUNCTUATION_RE.test(text);
}

/**
 * Plan which bare rows are nested group heads for one project entry.
 * Render-site mirror of parser.py::_plan_nested_group_heads: label rows
 * delimit module spans (duty/highlight open a list span, background/tech a
 * body span). Inside a list span, a head-shaped row qualifies only with a
 * detail-shaped successor, a non-head-shaped predecessor, and at least
 * NESTED_GROUP_MIN_HEADS qualified heads in the same span — so flat peer
 * lists and isolated short points keep their ordinary rendering.
 */
export function planNestedGroupHeads(
  items: string[],
  styles?: Array<DescriptionRowStyle | null | undefined>,
  options?: { canonicalizeLabels?: boolean }
): Set<number> {
  if (!options?.canonicalizeLabels) return new Set();
  const styleAt = (index: number): DescriptionRowStyle => styles?.[index] ?? 'bullet';
  const isLabelRow = (index: number): boolean => {
    const style = styleAt(index);
    return (style === 'label' || style === 'plain') && looksLikeSubLabel(items[index]);
  };

  const spans: Array<Set<number>> = [];
  let current = new Set<number>();
  let inListSpan = false;
  const closeSpan = (): void => {
    if (current.size) {
      spans.push(current);
      current = new Set();
    }
  };

  items.forEach((desc, index) => {
    if (isLabelRow(index)) {
      closeSpan();
      const labelDesc = canonicalizeProjectSubLabel(desc);
      inListSpan = !isProjectDescriptiveLabel(labelDesc);
      return;
    }
    if (!inListSpan || !looksLikeNestedGroupHead(desc, styleAt(index))) return;
    const nextIndex = index + 1;
    if (nextIndex >= items.length) return;
    // A module label next means no detail row follows.
    if (isLabelRow(nextIndex)) return;
    if (looksLikeNestedGroupHead(items[nextIndex], styleAt(nextIndex))) return;
    const prevIndex = index - 1;
    if (prevIndex >= 0 && !isLabelRow(prevIndex)) {
      if (looksLikeNestedGroupHead(items[prevIndex], styleAt(prevIndex))) return;
    }
    current.add(index);
  });
  closeSpan();

  const qualified = new Set<number>();
  for (const heads of spans) {
    if (heads.size >= NESTED_GROUP_MIN_HEADS) {
      heads.forEach((i) => qualified.add(i));
    }
  }
  return qualified;
}

const CJK_CHAR_RE = /[一-鿿]/;
// A body row carrying sentence punctuation, or a label prefix glued to prose
// ("项目亮点：实时时延<50ms"), is not a stack entry; such a body stays stacked
// instead of joining with a separator.
const INLINE_DISQUALIFY_RE = /[。；！？!?;]|^[一-鿿A-Za-z][一-鿿A-Za-z0-9/]{0,9}[：:]/;

// A structured tech-stack category row ("后端：Java 8、Spring Boot",
// "数据库：MySQL、Redis", "监控： Prometheus"): a short category prefix, a
// colon and non-empty content. Mirrors TECH_STACK_CATEGORY_RE in
// app/services/resume_docx.py — keep in sync. Such a block renders as an
// ordered list (one number per category row); pure-name stacks stay inline.
export const TECH_STACK_CATEGORY_RE = /^[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,10}[：:]\s*\S/;

// Sentence punctuation distinguishes a real category row ("后端：Java、Go")
// from a glued achievement/background sentence ("项目亮点：时延降到 600ms。").
const CATEGORY_SENTENCE_RE = /[。；！？!?;]/;

export function isTechStackCategoryRow(row: string): boolean {
  // A standalone "http(s)://…" URL matches the short-colon shape by accident
  // (prefix "https" + colon); a link is never a 分类：… row. Mirrors the URL
  // guards in parser._is_tech_stack_category_row / resume_docx — keep in sync.
  if (/^(?:https?:\/\/|www\.)/i.test(row.trim())) return false;
  if (!TECH_STACK_CATEGORY_RE.test(row) || CATEGORY_SENTENCE_RE.test(row)) return false;
  // A glued known sub-module ("技术难点及亮点：实时时延<50ms", no period) stays
  // prose even though it has the same short-colon shape as a category row.
  const core = row.replace(/[：:].*$/, '').trim();
  return (
    !SUB_LABEL_CANDIDATES.has(core) && !SUB_LABEL_CANDIDATES.has(canonicalProjectLabelCore(core))
  );
}

/**
 * Join a tech-stack body into one display string: CJK content uses the
 * enumeration comma （、）, all-ASCII stacks (Spring Boot, Nacos, …) use ", ".
 */
export function joinInlineBodyRows(rows: string[]): string {
  const separator = rows.some((row) => CJK_CHAR_RE.test(row)) ? '、' : ', ';
  return rows.join(separator);
}

// Longest-first glued descriptive prefix, e.g. "项目简介：面向…" /
// "技术列表：SpringAI、…". Mirrors parser.py::_INLINE_SUB_LABEL_RE restricted
// to the descriptive label set.
const PROJECT_GLUED_LABEL_RE = new RegExp(
  `^(${[...PROJECT_INLINE_PLAIN_LABELS]
    .sort((a, b) => b.length - a.length)
    .join('|')})(\\s*[：:])\\s*`
);

export interface ProjectGluedRow {
  /** Canonicalized bold label INCLUDING its colon ("项目背景："). */
  label: string;
  /** Content text after the colon, marker stripped. */
  content: string;
}

/**
 * Split a legacy project row whose descriptive label is glued to its content
 * ("项目简介：面向…" → { label: "项目背景：", content: "面向…" }). Returns null
 * for heading-only rows (those are sub-labels), non-descriptive labels and
 * ordinary bullets. Display-only — stored strings are never mutated.
 */
export function splitProjectPlainPrefix(point: string): ProjectGluedRow | null {
  const text = stripPointMarker(point).trim();
  const match = PROJECT_GLUED_LABEL_RE.exec(text);
  if (!match) return null;
  const [, labelCore, colonRaw] = match;
  const content = text.slice(match[0].length).trim();
  if (!content) return null;
  const colon = /[：:]/.exec(colonRaw)?.[0] ?? '：';
  const canonicalCore = PROJECT_SUB_LABEL_ALIASES[labelCore] ?? labelCore;
  return { label: canonicalCore + colon, content };
}

/**
 * Whether a project row is a descriptive/background/tech line whose label is
 * glued to its content ("项目简介：…", "技术列表：…") and therefore renders as
 * unnumbered body text. Requires non-empty content after the colon — a
 * heading-only row is a sub-label, not this case.
 */
export function isProjectPlainPrefixRow(point: string): boolean {
  return splitProjectPlainPrefix(point) !== null;
}

// PROJECT sub-module headings are unified to four canonical names: duty
// groups → 项目职责， highlight/result/difficulty groups → 项目亮点，
// intro/background groups → 项目背景， tech-stack groups → 技术栈.
// Display-only mirror of parser.py::PROJECT_SUB_LABEL_CANONICAL so
// already-stored resumes show canonical names without re-parsing; the backend
// persists the rename on fresh uploads. Applied at project render sites only
// — a work entry's 工作职责 stays verbatim.
const PROJECT_SUB_LABEL_ALIASES: Record<string, string> = {
  项目成果: '项目亮点',
  个人成果: '项目亮点',
  技术亮点: '项目亮点',
  技术难点: '项目亮点',
  难点与解决: '项目亮点',
  技术难点及亮点: '项目亮点',
  工作职责: '项目职责',
  主要职责: '项目职责',
  负责内容: '项目职责',
  核心工作: '项目职责',
  工作内容: '项目职责',
  // Personal-duty phrasings ("个人职责：" / "项目责任：") are the same duty
  // module under a different heading.
  个人职责: '项目职责',
  项目责任: '项目职责',
  // Combined duty + result heading ("核心职责与成果：") opens a duty region.
  核心职责与成果: '项目职责',
  // Combined duty + result headings ("项目职责与成果：") open a duty region;
  // they are unified to the canonical 项目职责 name for projects.
  项目职责与成果: '项目职责',
  项目职责和成果: '项目职责',
  项目职责及成果: '项目职责',
  工作职责与成果: '项目职责',
  工作职责和成果: '项目职责',
  工作职责及成果: '项目职责',
  个人职责与成果: '项目职责',
  职责与成果: '项目职责',
  职责和成果: '项目职责',
  职责及成果: '项目职责',
  项目概述: '项目背景',
  业务背景: '项目背景',
  项目简介: '项目背景',
  需求背景: '项目背景',
  项目概况: '项目背景',
  项目介绍: '项目背景',
  技术选型: '技术栈',
  技术架构: '技术栈',
  所用技术: '技术栈',
  技术清单: '技术栈',
  技术列表: '技术栈',
};

/**
 * Map a bare PROJECT sub-label core to its canonical name
 * ("项目成果" → "项目亮点"); unmapped cores come back unchanged. Mirrors
 * parser.py::PROJECT_SUB_LABEL_CANONICAL and backs label-region extraction
 * (lib/utils/description-regions.ts).
 */
export function canonicalProjectLabelCore(core: string): string {
  return PROJECT_SUB_LABEL_ALIASES[core] ?? core;
}

/**
 * Rename a PROJECT sub-label to its canonical name, preserving any trailing
 * colon ("项目成果：" → "项目亮点："). Rows that are not mapped aliases are
 * returned unchanged.
 */
export function canonicalizeProjectSubLabel(desc: string): string {
  const text = stripPointMarker(desc).trim();
  const match = text.match(/^(.*?)([：:])?\s*$/);
  const core = match?.[1].trim() ?? text;
  const suffix = match?.[2] ?? '';
  const canonical = PROJECT_SUB_LABEL_ALIASES[core];
  return canonical === undefined ? desc : canonical + suffix;
}

// Longest first so 技术难点及亮点 wins over 技术难点. Mirrors the backend
// inline-label split, which already turns these rows into label + content on
// fresh parses; this only rewrites the visible prefix of already-stored rows.
const PROJECT_INLINE_LABEL_RE = new RegExp(
  `^(${Object.keys(PROJECT_SUB_LABEL_ALIASES)
    .sort((a, b) => b.length - a.length)
    .join('|')})(\\s*[：:])`
);

/**
 * Rename a leading label prefix glued to body text
 * ("技术难点及亮点：实时时延…" → "项目亮点：实时时延…"). Only a curated alias
 * immediately followed by a colon matches; ordinary duty bullets are returned
 * untouched. The row is not split — legacy layout is preserved.
 */
export function canonicalizeProjectSubLabelPrefix(desc: string): string {
  const text = stripPointMarker(desc);
  const match = text.match(PROJECT_INLINE_LABEL_RE);
  if (!match) return desc;
  const [, alias, colon] = match;
  return text.replace(PROJECT_INLINE_LABEL_RE, PROJECT_SUB_LABEL_ALIASES[alias] + colon);
}

// Mirrors the backend DescriptionStyle literal (app/schemas/models.py).
export type DescriptionRowStyle = 'bullet' | 'plain' | 'label';

export interface DescriptionListRow {
  desc: string;
  /** false for "plain" body rows sharing the list but carrying no number. */
  numbered: boolean;
  /**
   * Nested point head inside a duty/highlight module: a bold row
   * ("重大生产环境问题解决：" under 项目亮点） owning the detail rows until the
   * next head. The head itself is always the level-1 numbered point
   * (1. 2. 3. …); every detail below it is level 2 and renders as a
   * hierarchical sub-point (1.1, 1.2, …), regardless of the stored style —
   * layered content under a sub-module is always an ordered list. The module
   * label itself is NOT a list row.
   */
  bold?: boolean;
  /**
   * 1 (default): module-level point. 2: detail under a nested bold head —
   * indented one extra gutter, composite numbering.
   */
  level?: 1 | 2;
}

export interface DescriptionLabelBlock {
  kind: 'label';
  desc: string;
  /**
   * Descriptive head (项目背景/技术栈/…): the following rows form an
   * unnumbered BODY block aligned to the label text, not a numbered list.
   * Always false outside project render sites.
   */
  descriptive: boolean;
}

export interface DescriptionListBlock {
  kind: 'list';
  /**
   * Lists owned by a sub-label are indented one number gutter so their
   * numbering starts at the label's text edge; loose lists (bullets with no
   * sub-label above them) keep the outer alignment.
   */
  indented: boolean;
  /**
   * Peer-module flush (project sites only): the block is owned by a label
   * OUTSIDE the big four （项目背景/技术栈/项目职责/项目亮点）, e.g. 项目成效.
   * Numbered rows keep their markers at the label edge, while unnumbered
   * (plain) rows drop the empty 3ch marker gutter and align exactly with the
   * label text instead of indenting under it.
   */
  flush: boolean;
  rows: DescriptionListRow[];
}

export interface DescriptionBodyBlock {
  kind: 'body';
  /** Unnumbered descriptive content (项目背景/技术栈), one entry per row. */
  rows: string[];
  /**
   * Tech-stack enumeration: rows render as ONE inline-wrapped line
   * ("Spring Boot、Nacos、Kafka") instead of one row per line. Prose bodies
   * (项目背景/系统架构/…) stay stacked.
   */
  inline: boolean;
}

export type DescriptionBlock = DescriptionLabelBlock | DescriptionListBlock | DescriptionBodyBlock;

/**
 * Partition an entry's description rows into sub-modules. A "label" row (or a
 * legacy "plain" row that is really a heading) becomes a bold block head; the
 * following bullet/plain rows form ONE independent list whose numbering
 * restarts at 1. Bullet/plain runs not preceded by a label form a single
 * loose list. Each label starts a new list block, so consecutive sub-modules
 * render as 负责内容 1..n / 难点与解决 1..m instead of one continuous list.
 *
 * At project render sites, descriptive labels （项目背景/技术栈/…) instead own
 * a "body" block — unnumbered rows aligned to the label's text edge — and
 * legacy rows that glue such a label to its text ("项目简介：面向…") are split
 * into a bold label plus a body row.
 */
export function buildDescriptionBlocks(
  items: string[],
  styles?: Array<DescriptionRowStyle | null | undefined>,
  options?: { canonicalizeLabels?: boolean }
): DescriptionBlock[] {
  // Structural head plan (project render sites only): head-shaped bullets
  // inside duty/highlight modules become bold level-1 numbered heads.
  const nestedHeadIndices = planNestedGroupHeads(items, styles, options);
  const blocks: DescriptionBlock[] = [];
  // Kind of block the next content row joins: duty labels open numbered
  // lists, descriptive labels （项目背景/技术栈) open unnumbered body blocks.
  let nextBlockKind: 'list' | 'body' = 'list';
  // True while the most recent heading was a label, i.e. the next opened list
  // belongs to a sub-label and must be indented.
  let nextListIndented = false;
  // True when the next opened list belongs to a peer module outside the big
  // four （项目成效/…): its unnumbered rows align flush with the label edge.
  let nextListFlush = false;
  // Whether the next opened body block is a tech-stack enumeration (rows
  // merged into one inline-wrapped line) rather than stacked prose rows.
  let nextBodyInline = false;
  // A recognized sub-module label （项目职责/项目亮点/…) has been seen: only
  // afterwards can unknown colon headings be nested numbered point heads.
  let moduleSeen = false;
  // Rows after a nested bold head belong to that head until the next head.
  let nestedHeadOpen = false;

  const openBlock = (): DescriptionListBlock | DescriptionBodyBlock => {
    const last = blocks[blocks.length - 1];
    if (last && (last.kind === 'list' || last.kind === 'body') && last.kind === nextBlockKind) {
      return last;
    }
    if (nextBlockKind === 'body') {
      const block: DescriptionBodyBlock = { kind: 'body', rows: [], inline: nextBodyInline };
      blocks.push(block);
      return block;
    }
    const block: DescriptionListBlock = {
      kind: 'list',
      indented: nextListIndented,
      flush: nextListFlush,
      rows: [],
    };
    blocks.push(block);
    return block;
  };

  items.forEach((desc, index) => {
    const style = styles?.[index] ?? 'bullet';
    // A stored "label" style is only a heading when the row itself is
    // heading-shaped (sub-label name or short colon-terminated title); a
    // label-styled content paragraph ("负责整体架构：……。") is demoted to
    // content, mirroring repair_project_label_regions() on the backend.
    const isLabel = (style === 'label' || style === 'plain') && looksLikeSubLabel(desc);
    if (isLabel) {
      const labelDesc = options?.canonicalizeLabels ? canonicalizeProjectSubLabel(desc) : desc;
      const descriptive = Boolean(
        options?.canonicalizeLabels && isProjectDescriptiveLabel(labelDesc)
      );
      // At project render sites, an UNKNOWN bold colon heading inside an
      // already-open duty/highlight module is not a module separator: it is
      // the level-1 numbered point head ("1. 重大生产环境问题解决：" under
      // 项目亮点）; every detail below it becomes a level-2 sub-point
      // (1.1, 1.2 …), including rows stored "plain" — layered content under a
      // sub-module is always an ordered list. Consecutive heads share the
      // module's list so the head numbers continue 1..n.
      const nestedNumberedHead =
        Boolean(options?.canonicalizeLabels) &&
        moduleSeen &&
        nextBlockKind === 'list' &&
        !isKnownSubLabel(desc);
      if (nestedNumberedHead) {
        const block = openBlock();
        nestedHeadOpen = true;
        if (block.kind === 'list') {
          block.rows.push({ desc: labelDesc, numbered: true, bold: true });
        }
        return;
      }
      blocks.push({ kind: 'label', desc: labelDesc, descriptive });
      moduleSeen = true;
      nestedHeadOpen = false;
      nextBlockKind = descriptive ? 'body' : 'list';
      nextBodyInline = descriptive && isProjectTechStackLabel(labelDesc);
      nextListIndented = true;
      // Peer modules outside the big four （项目成效/项目治理/…) keep their
      // content flush with the label edge instead of reserving a number gutter.
      nextListFlush =
        Boolean(options?.canonicalizeLabels) &&
        !descriptive &&
        !isCanonicalNumberedModule(labelDesc);
      return;
    }
    // Legacy glued descriptive row ("项目简介：面向…" / "技术列表：SpringAI…"):
    // split into a bold canonical label plus its body content. The label
    // owns subsequent rows until the next label, mirroring fresh parses.
    if (options?.canonicalizeLabels) {
      const glued = splitProjectPlainPrefix(desc);
      if (glued) {
        blocks.push({ kind: 'label', desc: glued.label, descriptive: true });
        moduleSeen = true;
        nestedHeadOpen = false;
        nextBlockKind = 'body';
        nextBodyInline = isProjectTechStackLabel(glued.label);
        nextListIndented = true;
        nextListFlush = false;
        const body = openBlock();
        if (body.kind === 'body') body.rows.push(glued.content);
        return;
      }
    }
    // A bare bold sub-heading inside a duty/highlight module (short,
    // unnumbered row without a colon, followed by detail points — even when
    // stored as a bullet) is a nested level-1 numbered head; its following
    // points become 1.1/1.2.
    if (
      options?.canonicalizeLabels &&
      moduleSeen &&
      nextBlockKind === 'list' &&
      !isKnownSubLabel(desc) &&
      nestedHeadIndices.has(index)
    ) {
      const block = openBlock();
      nestedHeadOpen = true;
      if (block.kind === 'list') {
        block.rows.push({ desc, numbered: true, bold: true });
      }
      return;
    }
    // Open the block BEFORE clearing the indent flag so the first row after a
    // label joins the label's indented list; later rows reuse that block.
    const block = openBlock();
    nextListIndented = false;
    nextListFlush = false;
    if (block.kind === 'body') {
      // Content under 项目背景/技术栈 is always unnumbered, regardless of the
      // stored style. A glued legacy alias glued mid-body ("技术难点及亮点：…")
      // still gets its prefix unified (→ 项目亮点：), layout unchanged.
      block.rows.push(options?.canonicalizeLabels ? canonicalizeProjectSubLabelPrefix(desc) : desc);
      return;
    }
    // Plain rows after a label stay in the label's (indented) list; plain
    // rows elsewhere continue the loose list, whose numbering merely skips
    // them, matching the historical legacy render. Legacy rows that glue a
    // renamed duty/highlight label to their text keep their layout but show
    // the canonical prefix. Every detail row under a nested bold head is a
    // numbered level-2 sub-point (1.1/1.2 …), even when stored "plain".
    const rowDesc = options?.canonicalizeLabels ? canonicalizeProjectSubLabelPrefix(desc) : desc;
    block.rows.push({
      desc: rowDesc,
      numbered: nestedHeadOpen ? true : style !== 'plain',
      ...(nestedHeadOpen ? { level: 2 as const } : null),
    });
  });

  // Tech-stack region post-processing:
  // - A structured region with category rows ("后端：…", "数据库：…") renders
  //   as an ordered list with one number per category row (rule: structured
  //   tech stacks are presented as an ordered list); bare-name rows inside a
  //   mixed region are numbered too.
  // - Otherwise a region containing a prose sentence (legacy glued achievement
  //   row) renders stacked instead of inline — separators between full
  //   sentences read as a typo.
  for (let i = 0; i < blocks.length; i += 1) {
    const block = blocks[i];
    if (block.kind !== 'body' || !block.inline) continue;
    if (block.rows.some((row) => isTechStackCategoryRow(row))) {
      blocks[i] = {
        kind: 'list',
        indented: true,
        flush: false,
        rows: block.rows.map((row) => ({ desc: row, numbered: true })),
      };
    } else if (block.rows.some((row) => INLINE_DISQUALIFY_RE.test(row))) {
      block.inline = false;
    }
  }

  return blocks;
}
