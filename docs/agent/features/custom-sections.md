# Custom Sections System

> **Dynamic resume sections with full customization.**

## Section Types

| Type           | Description                                             | Example Uses                       |
| -------------- | ------------------------------------------------------- | ---------------------------------- |
| `personalInfo` | Special type for header (always first)                  | Name, contact details              |
| `text`         | Single text block                                       | Summary, objective, statement      |
| `itemList`     | Array of items with title, subtitle, years, description | Experience, projects, publications |
| `stringList`   | Simple array of strings                                 | Skills, languages, hobbies         |

## Section Features

- **Fixed order**: Section order is canonical and locked — there are no
  drag handles or up/down controls (see [Fixed section order](#fixed-section-order)).
- **Rename custom sections**: Only custom sections can be renamed. The six
  default block titles are locked (a lock icon is shown instead of the
  pencil).
- **Hide sections**: Toggle visibility (hidden sections still editable, just not in PDF)
- **Delete sections**: Remove custom sections entirely; deleting a default section hides it
- **Add custom sections**: Create new sections with a name that is non-blank,
  not a duplicate of a visible section, and not a reserved default title

## Section Controls (UI)

Each section (except Personal Info) has these controls in the header:

| Control       | Icon                                    | Function                                             |
| ------------- | --------------------------------------- | ---------------------------------------------------- |
| Visibility    | 👁 Eye / EyeOff                          | Toggle show/hide in PDF preview                      |
| Lock / Rename | 🔒 Lock (defaults) / ✏️ Pencil (custom) | Default titles are locked; customs are editable      |
| Delete        | 🗑 Trash                                 | Hide (default) or delete after confirmation (custom) |

There is deliberately **no reorder control**: order is derived from the
canonical rule on every render and save.

## Fixed section order

The single-column templates (swiss-single/default, modern, latex, clean)
enforce one fixed sequence with a degree-based exception for the education
block:

- **Formal branch** (doctorate, or 统招/全日制 本科/硕士 without non-formal
  markers such as 自考/成教/函授/网络教育/电大/开放大学/业余/专升本):
  personalInfo → **education** → summary → additional(skills only) →
  workExperience → personalProjects → _custom cluster_ →
  培训与证书 → 荣誉奖项 → self-evaluation
- **Other branch** (non-formal bachelor/master, 大专 even if full-time,
  中专/高中, or education missing): personalInfo → summary →
  additional(skills only) → workExperience → personalProjects →
  _custom cluster_ → 培训与证书 → 荣誉奖项 → **education** →
  self-evaluation

The 培训与证书 / 荣誉奖项 positions are **render-only projections**, not meta
rows: both lists stay stored in the early `additional` slot
(`additional.certificationsTraining` / `additional.awards`, edited in the
skills-section form) and are projected to the back at render time by
`getRenderSections()`. They are invisible to the builder section list,
persistence, the backend mirror and diagnosis #1, and disappear together
with the skills block when the additional meta row is hidden. The projection
anchors, first hit: the late `education` row on the other degree branch,
then the self-evaluation row, then document end. With no self-evaluation row
the modules land at document end.

Rules:

- The **custom cluster** holds every section not on the fixed list
  (unknown customs, including a duplicate-key row and any legacy
  荣誉证书-titled block), preserving their relative order, and sits between
  personalProjects and the late modules / education.
- **Self-introduction** = a title containing 自我评价 / 自我评定
  / 个人评价 / 自我介绍 / 个人介绍 / 个人简介 / 个人简述 / 个人总结, always
  rendered last.
  Legacy/custom sections titled 荣誉证书 / 获奖情况 / … no longer own a fixed
  slot (the honors slot was removed — a DB scan found zero stored honors
  blocks): they ride the custom cluster under their stored title, while
  fresh uploads map certificates/awards into `additional` (see below).
  Education sits directly before self-evaluation in the other branch.
- Hidden sections keep dense-order slots; missing sections are skipped.
- The **three two-column templates are exempt** from the fixed meta
  sequence (their main/sidebar split is hardcoded layout): they keep using
  raw `sectionMeta.order` via `getSortedSections` and never reorder. The
  exemption does not change the late cert/award projection, which is
  hardcoded the same way in JSX: 培训与证书 / 荣誉奖项 both render in the
  **main column after every custom section** (certificates first, awards
  directly after); the sidebar keeps education/skills/languages/links but no
  longer shows awards.

### Title governance

- Default block titles are **locked**; a renamed default title is reset to
  the canonical English name on save and re-localized on render. Shipped
  locale titles and accepted zh aliases are recognized as "not renamed"; the
  alias table is shared by the diagnosis checker and covered by tests on both
  sides. The canonical zh headings and their accepted aliases are:

  | Canonical (zh)                        | Accepted aliases (upload headings)                                                                     |
  | ------------------------------------- | ------------------------------------------------------------------------------------------------------ |
  | 个人优势 (summary)                    | 核心优势、竞争优势、综合优势、个人亮点                                                                 |
  | 自我介绍 (custom self-intro block)    | 个人介绍、个人简介、个人简述、个人评价（标题为「自我评价/自我评定/个人总结」的版块占用同一末位槽，但保留原标题） |
  | 工作经历                              | 工作经验、实习经历、从业经历、职业履历、任职经历、工作履历、职场经历                                   |
  | 项目经验                              | 项目经历、项目履历、重点项目                                                                           |
  | 教育背景                              | 教育经历、学历信息、求学履历                                                                           |
  | 专业技能                              | 职业技能、核心技能、专业能力、技能、技能清单、技术能力、技术技能、技能与荣誉                           |

  The six default blocks render their canonical title from the locale
  (`resume.sections.*`); the one canonical **custom** block (自我介绍,
  including 个人介绍/个人简介/个人简述/个人评价 headings) is rewritten at
  render by `localizeDefaultSectionMeta` (`section-helpers.ts`) via
  `isSelfIntroductionAlias`; stored data is never mutated. Other custom
  titles — including legacy 荣誉证书 headings — render verbatim. Frontend
  tables: `lib/utils/section-order.ts`; backend mirror:
  `app/services/section_order.py`.

- New/renamed custom sections may not duplicate a **visible** section title
  (whitespace-folded, case-insensitive) and may not reserve a default title.
  Reusing a hidden section's name is allowed.
- An **optional** block (summary and every custom section) with a title but
  no content is auto-hidden on save (`isVisible = false`); its data is
  preserved, and typing into it in the builder reveals it again in the same
  update. **Required** blocks (personalInfo, education, workExperience,
  personalProjects, additional) stay visible even when empty — that condition
  is owned by diagnosis item 3 instead.

### Where the rule runs

- Frontend pure logic: `apps/frontend/lib/utils/section-order.ts`
  (`getCanonicalSections`, `canonicalizeSectionMeta`, `classifyHighestDegree`,
  `validateSectionName`); save normalization calls it from
  `lib/utils/resume-normalization.ts`, the four single-column templates call
  `getCanonicalSections`, and the builder renders via the same resolver.
- Backend mirror: `apps/backend/app/services/section_order.py`. PATCH
  canonicalizes before storage; GET canonicalizes the **response only**
  (legacy scrambled storage is rendered correctly without being rewritten by
  a read). The wizard finalize path stores canonical meta directly.
- The diagnosis checker (item 1) is the backstop for data that never passed
  through either normalization path — see
  [resume-diagnosis.md](resume-diagnosis.md).

### Upload parser section mapping

The upload parse prompt (`app/prompts/templates.py::PARSE_RESUME_PROMPT`,
schema example `RESUME_SCHEMA_EXAMPLE`) enforces the same identity rules at
extraction time, so imported Chinese headings never merge:

- 个人优势 / 核心优势 / 竞争优势 / 综合优势 / 个人亮点 (and
  Summary/Profile/Objective) → top-level `summary` only, never duplicated
  into customSections.
- 自我介绍 / 个人介绍 / 个人简介 / 个人简述 / 个人评价 / 自我评价 / 自我评定 /
  个人总结 → a **separate** customSections text block, key `self_evaluation`,
  displayName copied verbatim (a 个人总结 heading stays 个人总结) — never folded
  into summary; it claims the same terminal self-evaluation slot. The render
  layer canonicalizes 自我介绍-family titles (including 个人评价 → 自我介绍),
  while 自我评价/自我评定/个人总结 stay
  verbatim.
- 工作经历 / 工作经验 / 实习经历 / 从业经历 / 职业履历 / 任职经历 / 工作履历 /
  职场经历 → `workExperience`; 项目经验 / 项目经历 / 项目履历 / 重点项目 →
  `personalProjects`; 教育背景 / 教育经历 / 学历信息 / 求学履历 → `education`.
- 专业技能 / 职业技能 / 核心技能 / 专业能力 / 技术能力 / 技术技能 / 技能 /
  技能清单 → `additional.technicalSkills`, one array element per source line
  (group labels such as 后端框架：… preserved).
- 荣誉证书 / 荣誉/证书 / 荣誉 / 证书 / 获奖情况 / 资质荣誉 / 资格证书 / 奖项 /
  资质认证, whether or not they have their **own heading**, NEVER create a
  custom section on fresh uploads: certificate/qualification items go to
  `additional.certificationsTraining`, award/prize items go to
  `additional.awards` (one string per source line, date/issuer kept inline;
  a mixed 荣誉证书 heading is split between the two arrays by entry type).
  Legacy/custom honors-titled sections already stored no longer have a
  dedicated slot (removed): they render as ordinary custom sections inside
  the custom cluster under their stored title, and the parser never emits
  new ones.
- 语言能力 → `additional.languages`; 求职意向/期望职位 → `personalInfo.title`;
  期望城市 → `personalInfo.location`.
- 头部人口统计信息（性别/年龄/工作年限/学历）按原文**逐字**抽取，括号标注
  必须保留 —— 如 `统招本科(211)` 不得截成 `本科`（(211)/(985)/双一流/统招/
  全日制 等限定词同理）。LLM 抽取之后还有一道**确定性回填**
  (`parser.backfill_personal_info_from_markdown`)：在原文头部区域（首个
  「标签：值」到下一节标题之间）按标签正则补全被 LLM 留空的姓名/性别/年龄/
  工作年限/学历/求职意向/意向城市/电话/邮箱，并把语言能力并入
  `additional.languages`；四个 demographic 字段以原文为准（会纠正被截断的
  LLM 值），联系方式仅在为空时回填，语言列表去重合并。标签词出现在正文
  （如求职意向「电话销售」）或节标题之后都不会误判。
- **容器错装修复**（`parser.reconcile_custom_section_shapes`，解析链第 13 道，
  读时自愈链与 DOCX 构建器镜像）：弱模型可能声明了 `sectionType` 却把内容写进
  另一个容器——`stringList` 的条目落在 `items`（`strings=null`，所有模板只按
  `strings` 渲染，表现为只有标题的空版块），或反向的 `itemList` 条目落在
  `strings`。修复把条目确定性迁移到与声明类型匹配的容器（item 标题→字符串；
  字符串→`{id, title}` 条目），声明容器本身已有内容时不动，幂等。

#### Builder: 自我评价 → 个人优势 migration

The builder (`components/builder/resume-form.tsx`, helpers in
`lib/utils/section-helpers.ts`) supports two related reconciliations:

- **Renaming a custom TEXT block to a summary title** (个人优势 / 核心优势 /
  Summary / Resumen / …, matched by `isAcceptedDefaultTitle('summary', …)`)
  does NOT keep a custom block with a reserved name. `migrateTextSectionToSummary`
  merges the block's text into the top-level `summary` string (existing content
  is preserved, appended on a new line; text already contained is not
  duplicated), deletes the custom block and its meta row, and guarantees a
  visible `summary` meta row. Non-text (list) custom blocks keep the
  reserved-name rejection — only text blocks can migrate.
- **Built-in blocks are always listed in the builder, visibility locked.**
  Uploaded resumes sometimes omit the optional summary row entirely, which
  previously meant the builder offered no 个人优势 form at all.
  `ensureDefaultSectionMeta` inserts every missing default row for the editor,
  and `ResumeForm` forces all six built-in rows visible regardless of stored
  content (`SectionHeader` renders with `visibilityLocked`, no eye toggle and
  no delete — built-ins can be neither hidden nor removed in the editor).
  The first text typed into a previously hidden/missing 个人优势 persists the
  visibility flip in the same update. Viewer/PDF paths are unchanged:
  save-time `canonicalizeSectionMeta` keeps hiding empty optional blocks from
  the resume render, so an empty 个人优势 never produces an empty heading or
  triggers diagnosis item #1. Only **custom** blocks keep their hide/delete
  controls.

Format fidelity: each source bullet/line becomes its own array element
(skills, descriptions, string lists); text blocks keep one point per line
joined by `\n`; lines are never joined into one big paragraph with commas or
connectors. customSections formatting is preserved end to end: the parse
prompt requires text blocks to be one `\n`-joined string (never an array or
space join), and the `CustomSection.text` schema validator
(`_coerce_multiline_text`) joins a model-returned line array with `\n`
instead of the prose-field space joiner, so the original line structure
survives even with weak models.

In-item sub-modules (project/work descriptions) get the same treatment via two
deterministic post-LLM passes (`parser.extract_project_header_fields` then
`parser.normalize_item_sub_labels`):

- a row that is **only** a sub-label (`技术架构：` / `工作职责：` /
  `负责内容` / `项目亮点：` / any unplanned label the prompt never enumerated)
  is forced to `descriptionStyles: "label"` so it renders as a **bold** label
  line without a number, even when the model numbered it;
- PROJECT sub-label names are unified to four canonical names
  (`parser.PROJECT_SUB_LABEL_CANONICAL`, **projects only** — work entries and
  custom itemLists keep source labels verbatim):
  项目亮点 group ← 项目成果/技术亮点/技术难点/难点与解决/技术难点及亮点；
  项目职责 group ← 工作职责/主要职责/负责内容/核心工作/工作内容；
  项目背景 group ← 项目概述/业务背景/项目简介/需求背景/项目概况/项目介绍；
  技术栈 group ← 技术选型/技术架构/所用技术/技术清单/技术列表.
  (项目描述/系统架构/架构说明 are deliberately **not** aliases — their names
  stay verbatim, but they share the descriptive layout below.) The parse
  prompt asks the LLM to emit the canonical name; the deterministic pass
  renames weak-model output (standalone label, split-inline label, and
  colon-less `"label"` rows). The frontend mirrors the map display-only
  (`list-format.ts::canonicalizeProjectSubLabel`, enabled via
  `<DescriptionList canonicalizeLabels />` at the seven project render sites)
  so already-stored resumes show canonical names without re-parsing. Legacy
  duty/highlight rows that glue the label to body text keep their layout and
  only their visible prefix is rewritten
  (`canonicalizeProjectSubLabelPrefix`); legacy glued background/tech rows are
  instead display-split into a bold canonical label plus its content
  (`splitProjectPlainPrefix`) — stored strings are never mutated;
- a curated sub-label glued to its first content line
  (`负责内容：Spring AI …`) is split into a `label` row plus the unchanged
  content row (which keeps its original `plain`/`bullet` style). Normal duty
  bullets with mid-sentence colons are never split;
- inline `项目规模：…` / `团队规模：…` and `项目角色：…` / `担任角色：…`
  rows are promoted into `Project.scale` / `Project.role` (only when that
  field is empty — never overwriting — and the row is removed together with
  its positional style);
- **descriptive project rows are never numbered**: background/intro and
  tech-stack labels （项目背景/项目概述/业务背景/项目简介/需求背景/项目概况/
  项目介绍/项目描述/技术栈/技术选型/技术架构/所用技术/技术清单/技术列表/
  系统架构/架构说明） render **bold**, and ALL of their content renders on
  following lines in an unnumbered body block (`data-sub-body` /
  `[data-body-row]`) until the next sub-label. At project render sites the
  bold label, its body rows and the numbers of its duty lists all share the
  PROJECT NAME left edge (`flushLabels` on `DescriptionList`: labels reserve
  no number gutter, body is `resume-sub-body-flush` padding-left 0, label-owned
  lists skip the 3.5ch indent; work-experience labels keep the 3ch gutter).
  On fresh uploads the parser enforces the body layout by splitting a glued
  row into a `label` row plus a **`plain`** content row
  (`PROJECT_INLINE_PLAIN_LABELS`, project-scoped; work entries keep the model
  style). The frontend mirrors it display-only for already-stored resumes:
  heading-only labels are promoted (`looksLikeSubLabel`, then canonicalized),
  and glued rows (`项目简介：面向…` / `技术列表：SpringAI…`) split into a bold
  canonical label plus a body row (`splitProjectPlainPrefix` /
  `isProjectDescriptiveLabel`, only when `canonicalizeLabels` is on), so
  项目简介/技术列表 show as bold 项目背景/技术栈 with aligned unnumbered body
  text while only 项目职责/项目亮点 points take numbers. Print CSS and
  `use-pagination.ts` bind the bold label to its body block so it never
  orphans at a page break;
- structures with no schema field (tables such as 难点/方案/效果 grids,
  free-form blocks) stay verbatim inside the description rows — the parse
  prompt requires one `plain` row per source line/cell and forbids joining
  cells with `-` or renumbering. Locks: `tests/unit/test_parser.py`
  (`TestNormalizeItemSubLabels`, `TestExtractProjectHeaderFields`) and
  `tests/unit/test_parse_prompt.py`. Every emitted content section gets a
  `sectionMeta` row whose `displayName` is the source heading copied verbatim;
  projects are extracted one entry each and aligned to the diagnosis item 9
  six-field proxy (name, role, period `""` when absent — never invented,
  background/scenario, ≥2 explicit technologies when listed, duty verbs,
  quantified results verbatim). Content locks for these rules live in
  `tests/unit/test_parse_prompt.py` and
  `tests/unit/test_custom_section_schema.py`.

Source-carried list markers (`1、`/`1.`/`1)`/`(1)`/`①`/`一、`/`•`/`- ` …)
are stripped at two layers so the renderer's own numbering never doubles up:

- deterministic post-LLM pass `parser.strip_source_point_numbering` cleans
  every stored array element (work/project descriptions, technicalSkills,
  languages, certificationsTraining, awards, custom `strings[]` and
  `items[].description[]`); prose fields are left untouched;
- the shared frontend stripper `stripPointMarker`
  (`components/resume/list-format.ts`) is applied by every template and the
  builder JD-highlight view, so legacy data parsed before the pass is cleaned
  at render too.
  Locks: `tests/unit/test_parser.py::TestStripSourcePointNumbering`,
  `tests/unit/test_parse_prompt.py::test_source_list_numbering_must_not_be_copied`,
  `tests/description-list.test.tsx`.

Legacy meta-less parses (snake_case custom keys, no `sectionMeta`) remain
diagnosable: items 3/6/10 fall back to key-token matching
(`personal_advantages`, `self_evaluation`, …) and read points from `text`,
`strings[]`, or `items[].title/subtitle/description[]`.

### Rendering conventions

Point text and entry headers follow fixed rendering rules across the resume
templates (components under `apps/frontend/components/resume/`):

- **所有列表统一渲染为有序编号列表**（查看页、PDF 导出、编辑器预览共用同一
  组件，格式天然一致）：
  - 工作经历 / 项目经历 / 自定义 itemList 的要点：`DescriptionList`
    （`description-list.tsx`，分组逻辑在 `list-format.ts::buildDescriptionBlocks`）
    渲染为有序列表，每个**子模块各自一个 `<ol>`、编号从 1 重新计数**（负责内容
    1..n / 难点与解决 1..m，不再连续编号）；
    `descriptionStyles: "label"` 的子模块标题行（如「项目职责：」「技术亮点：」
    「负责内容」）**加粗**、保留 3ch 编号栏但不占号；**项目经验**的标题在渲染时
    统一改名（仅显示层，工作经历/自定义板块不动），共四个规范名：项目成果/
    技术亮点/技术难点/难点与解决/技术难点及亮点 →「项目亮点」，工作职责/主要职责/
    负责内容/核心工作/工作内容 →「项目职责」，项目概述/业务背景/项目简介/需求背景/
    项目概况/项目介绍 →「项目背景」，技术选型/技术架构/所用技术/技术清单/技术列表
    →「技术栈」（「项目描述/系统架构/架构说明」**不改名**，原样保留但同样走描述性
    排版）。**项目经验**的四个规范名标题（项目背景/技术栈/项目职责/项目亮点）一律与
    **项目名称左缘对齐**（`DescriptionList flushLabels`：标题不保留 3ch 编号栏，
    职责/亮点名下列表数字也从该左缘起排、不再缩进，描述性正文块 `padding-left: 0`）；
    工作经历/自定义板块维持原排版——标题保留 3ch 编号栏，名下列表整体缩进一个编号栏宽
    （`resume-list-indented`，3.5ch），列表数字与标题文字左缘对齐。旧数据中
    以 `"plain"` 存储的独立小标题由 `looksLikeSubLabel()` 在渲染时按同样规则升级。
    **项目背景/技术栈等描述性子模块**（`isProjectDescriptiveLabel`）：标题**加粗**，
    其全部正文换行渲染在标题下方的无编号正文块中（`data-sub-body` /
    `[data-body-row]`，项目站点与标题/项目名称同左缘），
    直到遇到下一个子模块标题；旧数据中标签与正文粘合的行（`项目简介：…`、
    `技术列表：…` 等）在显示时拆分为加粗规范名标题 + 对齐正文
    （`splitProjectPlainPrefix`，不改存储数据）；只有职责/亮点类要点占号。正文块中
    若混入粘合的职责/亮点别名行（`技术难点及亮点：…`），仍就地替换前缀
    （`canonicalizeProjectSubLabelPrefix`），排版不变。打印 CSS 与
    `use-pagination.ts` 会把加粗标题与其正文块绑定，分页时标题不会孤行。
    vivid 模板原有的 `➜` 箭头标记已移除。
  - swiss-single（默认及 PDF 模板）的项目头部为**一行四栏**
    `项目名称 | 项目时间 | 项目规模 | 项目角色`（`entryColumnsProject`，左对齐、
    空栏仍占轨道以跨条目对齐；时间/规模/角色全空时项目名单独占一行）；
    `scale`（项目规模/团队规模）由解析管线从行内 `项目规模：…` 提升为独立字段。
  - 个人优势 (summary) 与**所有**自定义 text 板块（含自我评价、志愿经历等）：
    共享 `PointTextList`；原文按换行拆分（解析时每行一个要点），单行渲染为
    左对齐 `<p>`，多行渲染为悬挂式 `1.`/`2.` 编号 `<ol>`。导入解析时若自我
    评价类板块是一整段 `；`/`。` 文本，后处理 `split_blob_text_sections` 会
    按子句拆成多行（仅此一族板块；详见 resume-parsing-rules.md 第 9 道工序），
    从而直接以有序列表呈现。
  - 自定义 stringList 板块（荣誉证书等）：`OrderedStringList`
    （`point-text-list.tsx`）渲染为编号列表，单条时为段落；不再以逗号/`•`
    拼成一行。
  - 专业技能在 swiss-single（默认及 PDF 模板）中本就为编号列表
    （`skillOrderedList`）；其余模板保留各自的紧凑技能排版（标签/行内排列）。
  - 原文自带的编号（`1、`、`1)`、`①`、`一、`、项目符号）逐点剥除，避免双重
    编号。所有列表 **left-aligned, never justified**（模板中不使用
    `text-justify`）。
- **PDF/打印页一律密排，页与页之间不留结构性空白**（swiss-single，默认及 PDF
  模板）：`@media print` 中 swiss-single 的条目允许跨页，但断点只落在**要点
  行之间**——条目头部与首个要点保持同页、单行要点不被切开；纯头条目（无要点的
  工作/教育行）彼此不绑定，任何一行都能填满上一页底部。注意 break-after 绑定
  只能加在「后面确实跟着 `<ul>/<ol>`」的头部元素上（`:has(+ :is(ul, ol))`），
  否则纯头条目会被串成一整块推到下一页，造成大片留白。子模块标题行同理：
  `.resume-item > [data-sub-label]:has(+ :is(ul, ol))` 与其名下首个要点同页。自定义 text/stringList
  与技能列表（`.resume-section > ol`）同样「列表可跨页、单行不切」。屏幕分页预览
  的 JS 边界算法（`use-pagination.ts::collectUnbreakableBounds`）与这些规则一一
  对应（`<ol>` 与 `<ul>` 同等处理），保证预览与导出一致。
- **The four full-width templates (swiss-single, modern, latex, clean) lay
  work/education entry headers out as justified CSS grids whose SECTION owns
  the column tracks and whose rows nest as subgrids** (`WorkEntryRow` /
  `EducationEntryRow`; swiss-single classes `entrySectionWork` /
  `entrySectionEdu` + `entrySubgridItem` / `entryColumnsWork` /
  `entryColumnsWorkThree` / `entryColumns4` in `swiss-single.module.css`;
  the other three modules use `entryGridSection` / `entryGridItem` /
  `entryGrid` / `entryGridThree`):
  - Work without department = **time | company | role** (the role spans the
    department+role tracks with `grid-column: 3 / -1`, class
    `entryColumnsWorkThree` / `entryGridThree`); with a department it is four
    tracks, **time | company | department | role**. Location stays appended
    to the company cell with `·`.
  - Education = **time | university | major | degree**; major is
    `education.description`.
  - The section grid defines the tracks once — work
    `minmax(0, 10.5rem) minmax(0, 1.35fr) minmax(0, 1fr) auto`, swiss-single
    education the same first three tracks plus a fixed `minmax(0, 7rem)`
    degree track — and every entry/item row is
    `grid-template-columns: subgrid` spanning `1 / -1`, so all rows share
    identical column edges. Previously each row was an independent grid: a
    long job title grew that row's `auto` role track, squeezed the `fr`
    tracks and pushed the department column left (visible 不对齐). Subgrid
    sizes the role track to the section-widest title once, aligning every
    department/role edge with zero extra wrapping.
  - Project = **name | time | scale | role** (`ProjectEntryRow`, class
    `entryColumnsProject`: `2fr | 9.5rem | 0.9fr | 1.1fr`); this name-first
    grid deliberately stays independent of the time-first section grids;
    when all three metadata tracks are empty the name renders full-width on
    its own row.
  - The 10.5rem date track is deliberately wider than the date glyphs, so the
    company/school column starts a little right of them (DOCX mirrors it with
    a 3.3cm first track).
  - Date/company/department cells are left-aligned; the role is flush right
    (`justify-self: end` / `text-align: right`) so the row is 两端对齐. Long
    values wrap inside their own column (`minmax(0, …)`,
    `overflow-wrap: anywhere`) instead of pushing the date around.
    Description bullets render below, left-aligned.
  - `vivid` and the two-column templates (`resume-two-column`,
    `resume-modern-two-column`) keep their own entry layouts — the
    section/subgrid rule is specific to the four full-width ATS layouts.
  - **Print caveat (PDF regression, 2026-11):** `_base.module.css` forces
    `.resume-items` to `display: block !important` inside `@media print`,
    and these section elements carry `resume-items` too. A block parent makes
    the rows' `subgrid` compute to a single implicit column, so every cell
    stacks vertically in the PDF while the on-screen preview stays correct.
    Each of the four modules therefore re-asserts
    `:global(.resume-print) .entryGridSection { display: grid !important }`
    (or `.entrySectionWork, .entrySectionEdu` for swiss-single) inside its
    own `@media print` block; the 0,2,0 selector wins over the base 0,1,0
    rule. Keep that rule when touching these grids.
- **swiss-single header facts.** Below the left-aligned name, the header
  renders a labeled, left-aligned fact grid (`infoGrid` / `infoCell`) in
  the Chinese-resume order: **性别 / 年龄 / 学历 / 工作年限 / 求职意向 /
  意向城市 / 电话 / 邮箱 / 外语水平**. Only present facts render; empty
  fields are omitted. `求职意向` maps to `personalInfo.title`,
  `意向城市` to `personalInfo.location`, `学历` falls back to the first
  education entry's `degree` when `personalInfo.educationLevel` is empty,
  and `外语水平` joins `additional.languages` with `、`. Labels come from
  `PersonalInfoLabels` (`lib/utils/resume-headings.ts`, i18n keyed under
  `resume.personalInfo.*`) and are plumbed through the viewer page, print
  page, and `PaginatedPreview`. Website / LinkedIn / GitHub stay on their
  own links row (or the contact row / sidebar in other templates), each
  prefixed with its localized label (个人网站 / 领英 / GitHub) and rendered
  as a clickable anchor even when the stored value is an absolute
  `https://…` URL; the anchor text strips the protocol / `www.` prefix.
  The DOCX export mirrors the same contract in one borderless
  three-column header grid: facts occupy one labeled `label：value` cell
  each (so Word can never split a label from its value across lines), and
  the personal links occupy their own labeled, muted-gray row.
- **Language proficiency never renders under 专业技能 (swiss-single).**
  `additional.languages` (英语 CET-6 / 日语 N1 / 雅思…) feeds only the
  header fact grid as 外语水平; the early `additional` slot (heading
  专业技能) renders `technicalSkills` only — certifications/awards are
  projected to independent late modules at the back of the resume (see
  above) — and hides itself when skills are absent. The parse prompt
  likewise forbids placing language proficiency or language certificates
  in `technicalSkills`, even when the source nests them inside a combined
  skills block. modern/latex/clean still render a bold-label languages line
  inside the early skills block, and the two-column templates keep a
  languages block in the sidebar; none of them render languages in the late
  cert/award modules.
- **工作经历 / 教育经历一律按开始时间倒序（最新在前）。** 三层保证一致：
  解析后处理 `parser.sort_timeline_sections_newest_first`（新上传/重新解析/
  定制结果均排序）、前端渲染统一入口 `withLocalizedDefaultSections`
  （查看页、PDF 打印页、编辑器预览，存量数据无需迁移即按倒序显示）、
  保存归一化 `normalizeResumeForSave`（下次在编辑器保存时落库为倒序）。
  排序键取 `years` 字符串的**首个**日期，支持 `2018.05`、`2010.09-2014.06`、
  `Jun 2020`、`2020年5月`、纯年份；无日期的条目保持原相对顺序并沉到该节
  末尾。项目经历与自定义区块不参与排序。
- **Header demographics are first-class `personalInfo` fields**:
  `gender`, `age`, `workYears`, `educationLevel` (all strings, default
  `""`). The parse prompt extracts them verbatim from the source header
  (性别 / 年龄 / 工作年限 / 最高学历), never inferring them from the name
  or dates; the builder's personal-info form edits all four. They round
  -trip through `ResumeData` validation, PATCH saves, improve/confirm
  preservation, and the wizard-draft normalizer. Diagnosis item 4 treats
  `gender` as a V4-required field (missing 性别 is nonconform); age /
  work years / education level are recommended-only and never fail.

## Hidden Section Behavior

- Hidden sections appear in the form with:
  - Dashed border and 60% opacity
  - "Hidden from PDF" badge (amber)
- Hidden sections are still editable
- Only PDF/preview hides them (single-column templates filter by visibility
  after canonical ordering; two-column templates keep using
  `getSortedSections`)
- The builder shows all sections (including hidden) in canonical order via
  `getCanonicalSections(data, { includeHidden: true })`

## Key Files

| File                                                         | Purpose                                                                            |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `apps/backend/app/schemas/models.py`                         | `SectionType`, `SectionMeta`, `CustomSection` models, default meta injection       |
| `apps/backend/app/services/section_order.py`                 | Backend mirror of the ordering/classification/canonicalization logic               |
| `apps/frontend/lib/utils/section-order.ts`                   | Canonical order, degree classifier, title validation, emptiness, canonicalization  |
| `apps/frontend/lib/utils/section-helpers.ts`                 | Default meta, localization, legacy `getSortedSections` (two-column templates only) |
| `apps/frontend/lib/utils/resume-normalization.ts`            | Runs `canonicalizeSectionMeta` on the save payload                                 |
| `apps/frontend/components/builder/section-header.tsx`        | Section controls UI (lock, rename-customs, hide, delete)                           |
| `apps/frontend/components/builder/add-section-dialog.tsx`    | Add custom section dialog with name validation                                     |
| `apps/frontend/components/builder/resume-form.tsx`           | Dynamic form rendering in canonical order                                          |
| `apps/frontend/components/resume/dynamic-resume-section.tsx` | Renders custom sections in templates                                               |

## Data Structure

```typescript
interface ResumeData {
  // ... existing fields (personalInfo, summary, etc.)
  sectionMeta?: SectionMeta[]; // Section order, names, visibility
  customSections?: Record<string, CustomSection>; // Custom section data
}
```

## Migration

Existing resumes need no migration script. Lazy normalization adds default
section metadata when a resume is fetched with `sectionMeta` missing, and both
view/print rendering and save/PATCH flows derive canonical order on the fly
(see [Where the rule runs](#where-the-rule-runs)). Legacy scrambled storage is
therefore displayed correctly immediately; the first builder save persists
the canonical meta. Until then, diagnosis item 1 flags the stored violation.

> **Important**: The `normalize_resume_data()` function uses `copy.deepcopy(DEFAULT_SECTION_META)` to avoid shared mutable reference bugs. Always use deep copies when assigning default mutable values.
