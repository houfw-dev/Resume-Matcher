# Resume Template Settings

> **Template types and extensive formatting controls.**

## Template Types

| Template | Description |
|----------|-------------|
| `swiss-single` | Traditional single-column layout with maximum content density |
| `swiss-two-column` | 65%/35% split with experience in main column, skills in sidebar |
| `modern` | Single-column with colorful accent headers and customizable theme colors |
| `modern-two-column` | Two-column layout combining modern accents with space-efficient design |
| `latex` | Classic serif single-column with Title-Case ruled headers and company-first entries (LaTeX-style). Single-typeface — driven by the Header Font control |
| `clean` | Minimal sans single-column with large understated gray UPPERCASE headers and single-line entries. Single-typeface — driven by the Body Font control |
| `vivid` | Colorful two-column (Awesome-CV lineage): two-tone accent name, monospace contact with circular icons, accent small-caps headers, accent arrow bullets. Supports the Accent Color control |

## Formatting Controls

| Control | Range | Default | Effect |
|---------|-------|---------|--------|
| Margins | 5-25mm | 8mm | Page margins |
| Section Spacing | 1-5 | 3 | Gap between major sections |
| Item Spacing | 1-5 | 2 | Gap between items within sections |
| Line Height | 1-5 | 3 | Text line height |
| Base Font Size | 1-5 | 3 | Overall text scale (11-16px) |
| Header Scale | 1-5 | 3 | Name/section header size multiplier |
| Header Font | serif/sans-serif/mono | serif | Font family for headers |
| Body Font | serif/sans-serif/mono | sans-serif | Font family for body text |
| Compact Mode | boolean | false | Apply 0.6x spacing multiplier (spacing only; margins unchanged) |
| Contact Icons | boolean | false | Show icons next to contact info |
| Accent Color | blue/green/orange/red | blue | Accent color for color templates (modern, modern-two-column, vivid) |

## Key Files

| File | Purpose |
|------|---------|
| `apps/frontend/lib/types/template-settings.ts` | Type definitions, defaults, CSS variable mapping |
| `apps/frontend/components/resume/styles/_tokens.css` | Global design tokens (colors) |
| `apps/frontend/components/resume/styles/_base.module.css` | Shared typography and layout styles |
| `apps/frontend/components/builder/formatting-controls.tsx` | UI controls for template settings |
| `apps/frontend/components/resume/resume-single-column.tsx` | Single column template |
| `apps/frontend/components/resume/resume-two-column.tsx` | Two column template |
| `apps/frontend/components/resume/resume-modern.tsx` | Modern single column template |
| `apps/frontend/components/resume/resume-modern-two-column.tsx` | Modern two column template |
| `apps/backend/app/routers/resumes.py` | PDF generation endpoint with accentColor support |

## CSS Variables

Templates use CSS custom properties for styling:

- `--section-gap`, `--item-gap`, `--line-height` - Spacing
- `--font-size-base`, `--header-scale`, `--section-header-scale` - Typography
- `--header-font` - Header font family
- `--body-font` - Body text font family
- `--margin-top/bottom/left/right` - Page margins
- `--accent-primary`, `--accent-light` - Accent colors for Modern templates

> **Note**: Templates should use the styles exported from `apps/frontend/components/resume/styles/_base.module.css` (e.g., `baseStyles['resume-section']`, `baseStyles['resume-item-subtitle']`) to ensure all spacing and typography respond to template settings.

### Typography Classes

The base stylesheet includes specialized classes for improved subtitle visibility:

| Class | Font Size | Weight | Usage |
|-------|-----------|--------|-------|
| `resume-item-subtitle` | 0.95× base | 600 | Company names, education degrees, project roles |
| `resume-item-subtitle-sm` | 0.88× base | 600 | Same fields in compact two-column layouts |

These classes provide **better visibility** than the generic `resume-meta` class (0.82× base, weight 400), making subtitles 13-16% larger and semi-bold.

Formatting controls include an "Effective Output" summary that reflects compact-mode adjustments for spacing/line-height.

---

## Description Styles (`descriptionStyles`)

Each description row renders in one of three styles: **numbered** bullet,
**plain** unnumbered paragraph (continuation prose), or **label** — a bold
sub-module heading (项目职责 / 项目亮点 / 负责内容 / 技术栈 …) that owns the
following bullet group.

### Shape

`descriptionStyles` is a positional array parallel to `description`:

```jsonc
{
  "description":       ["Led the platform migration", "Rebuilt the ingest tier"],
  "descriptionStyles": ["plain",                      "bullet"]
}
```

`descriptionStyles[i]` describes `description[i]`. Values: `"bullet"` | `"plain"`
| `"label"`.

### Label groups

`list-format.ts::buildDescriptionBlocks()` partitions the rows into alternating
label/list blocks. Each `"label"` row:

- renders **bold** (`resume-sub-label`, `data-sub-label`) and consumes no
  number;
- starts a **new `<ol>` whose numbering restarts at 1** — each sub-module
  numbers 1..N independently instead of one continuous list;
- indents its list by one number gutter (`resume-list-indented`, 3.5ch) so the
  markers align with the label's text edge. **Project sites are the
  exception** (`DescriptionList flushLabels`, set next to
  `canonicalizeLabels` at all seven templates): 项目背景/技术栈/项目职责/
  项目亮点 reserve no 3ch label gutter and align with the PROJECT NAME edge,
  their duty lists skip the indent (numbers start at the same edge), and
  descriptive bodies are padding-left 0. Work-experience and custom-item
  labels keep the gutter.

`"plain"` rows following a label stay unnumbered but remain inside that
indented list (e.g. 难点与解决 的补充说明行). Legacy data stored before the
`"label"` style existed is upgraded at render time: heading-only `"plain"`
rows matching `looksLikeSubLabel()` (curated Chinese/English sub-module names,
or a short heading ending in `：`/`:`) become labels, while prose containing an
inline colon stays plain. In the builder, the marker toggle cycles
bullet → plain → label.

**Project-only canonical naming.** At project render sites `DescriptionList`
takes `canonicalizeLabels`, which unifies sub-module names for display
(`canonicalizeProjectSubLabel`, mirrored at parse time by
`parser.PROJECT_SUB_LABEL_CANONICAL` so fresh uploads persist the rename) into
four canonical names:
项目成果 / 技术亮点 / 技术难点 / 难点与解决 / 技术难点及亮点 → **项目亮点**;
工作职责 / 主要职责 / 负责内容 / 核心工作 / 工作内容 → **项目职责**;
项目概述 / 业务背景 / 项目简介 / 需求背景 / 项目概况 / 项目介绍 → **项目背景**;
技术选型 / 技术架构 / 所用技术 / 技术清单 / 技术列表 → **技术栈**.
项目描述 / 系统架构 / 架构说明 are deliberately **not** aliases — their names
stay verbatim. Work-experience or custom-item labels are never renamed.
Legacy duty/highlight rows where the label is glued to body text keep their
layout; only the visible prefix is rewritten
(`canonicalizeProjectSubLabelPrefix`).

**Descriptive project labels own an unnumbered body block.** A descriptive
label (the canonical 项目背景 / 技术栈 plus the verbatim 项目描述 / 系统架构 /
架构说明 — `isProjectDescriptiveLabel`) renders bold and all of its content
renders on following lines in a dedicated `data-sub-body` block: rows are
`[data-body-row]` divs and carry no number. At project sites the block is
flush (`resume-sub-body-flush`, padding-left 0), so body text, the bold label
and the project name share one left edge; the duty lists under 项目职责/
项目亮点 start at that edge too (`flushLabels`).
The body continues until the next sub-label, regardless of each stored
row's `bullet`/`plain` style — intro/background prose and tech-stack
enumerations are context, not duty points; only 项目职责/项目亮点 points take
numbers. A legacy row whose label is glued to its content (`项目简介：面向…` /
`技术列表：SpringAI…`) splits display-only into a bold canonical label plus a
body row (`splitProjectPlainPrefix`, no stored-data mutation); a glued
duty/highlight alias that appears inside a body keeps its layout and only its
prefix is rewritten. The parser mirrors the layout on fresh uploads
(`PROJECT_INLINE_PLAIN_LABELS`): the split content row is forced to `"plain"`
in projects; a heading-only label row still becomes a bold label as usual.

### The alignment invariant

**The two arrays must stay index-aligned.** Anything that adds, removes, filters
or reorders `description` rows must apply the identical operation to
`descriptionStyles`. A desync is silent — it does not error, it just moves every
later row's marker onto its neighbour.

Enforced in three places:

| Layer | File | Behaviour |
|---|---|---|
| Editor | `apps/frontend/components/builder/forms/{experience,projects,generic-item}-form.tsx` | `alignDescriptionStyles()` before every splice |
| Client normalize | `apps/frontend/lib/utils/resume-normalization.ts` | filters both arrays in lockstep |
| Server | `apps/backend/app/schemas/models.py` `_align_description_styles` | truncates/pads by index, defaults to `"bullet"` |

The server aligns **by index**, so it cannot detect a desync — it can only
guarantee length. Correctness has to be preserved upstream.

### Models that carry it

`Experience`, `Project`, `CustomSectionItem` (`apps/backend/app/schemas/models.py`). Rides
inside the existing `processed_data` JSON column — **no migration needed**.

`Education.description` is a scalar `str | None`, so it has no styles array.

### Prompts that must preserve it

Four prompts instruct the model to keep the arrays aligned:

- `apps/backend/app/prompts/templates.py` — the three improve variants
- `apps/backend/app/prompts/refinement.py` — `KEYWORD_INJECTION_PROMPT`

A prompt is **not** a guarantee for positional metadata. `inject_keywords` is
the last writer on the improve path, so `apps/backend/app/services/refiner.py::_preserve_description_styles()`
restores the field locally after it — matching the defence-in-depth pattern
already used for dates, skills, `personalInfo` and custom sections.

### Rendering

All seven templates render rows through
`apps/frontend/components/resume/description-list.tsx`, which partitions rows with
`buildDescriptionBlocks()` into three block kinds: label blocks render as bold
`data-sub-label` divs (with a `data-descriptive` marker on 项目背景/技术栈-type
heads); duty list blocks are their own `<ol>` restarting at 1 (indented when
label-owned); descriptive blocks render as unnumbered `data-sub-body` /
`[data-body-row]` divs. At project sites (`flushLabels`) all three kinds are
flush with the project-name left edge — labels carry no 3ch gutter, owned
lists skip the indent, bodies use `resume-sub-body-flush`.
The marker is `aria-hidden="true"`; `"plain"` list rows omit the marker and
consume no number. The JD-match preview
(`apps/frontend/components/builder/highlighted-resume-view.tsx`) applies the same
bold/numbering/body rules (including the glued-row display split) so the builder
does not contradict the PDF.

Print and screen pagination bind a label to the first row of its list or body
(CSS `break-after: avoid` on
`.resume-item > [data-sub-label]:has(+ :is(ul, ol, [data-sub-body]))`, body-row
`break-inside: avoid`, and the mirrored bound extension in `use-pagination.ts`
which follows `ul, ol, [data-sub-body]` siblings), so sub-module headings never
orphan at a page bottom.

Coverage: `apps/frontend/tests/template-description-styles.test.tsx` asserts marker presence
per template; `apps/frontend/tests/description-list.test.tsx` and
`apps/frontend/tests/list-format.test.ts` pin bold labels, restart numbering
and indentation; `apps/frontend/tests/resume-normalization.test.ts` pins the lockstep filter.

### Project header row (`Project.scale`)

`Project` carries a `scale` field (项目规模 / 团队规模) the parser promotes from
inline `项目规模：…` / `团队规模：…` rows (`parser.extract_project_header_fields`,
non-overwriting). In swiss-single each project renders one justified four-column
row — **name | time | scale | role** (`entryColumnsProject`); empty tracks still
reserve their columns so values line up across projects, and when time, scale
and role are all empty the name falls back to a full-width row.

### Work header row (`Experience.department`)

In swiss-single each work entry renders one justified four-column row
(`entryColumnsWork`) — **time | company | department | role** — with the date
flush left and the role flush right (两端对齐). The department track always
renders (empty string reserves space, so roles line up across entries), the
role is deliberately **not bold** (`entryRole`, regular weight), and an
optional `location` stays appended to the company cell.

The section wrapper (`entrySectionWork`), not the individual rows, owns the
column tracks (`minmax(0, 10.5rem) minmax(0, 1.35fr) minmax(0, 1fr) auto`);
each entry item and its header row nest as `grid-template-columns: subgrid`
spanning `1 / -1`. Independent per-row grids used to size the `auto` role
track separately, so a long title squeezed the `fr` tracks on that row and
shifted its department cell left (the 部门不对齐 regression). Subgrid makes
the role track as wide as the section-widest title exactly once, so every
row's department/role edges coincide. modern/latex/clean mirror the same
contract with `entryGridSection` / `entryGridItem` / `entryGrid` /
`entryGridThree`; rows without a department keep three cells and span the
role across the department+role tracks (`grid-column: 3 / -1`). The
name-first project grid (`entryColumnsProject`) is intentionally left
independent. In print, the base `.resume-items` block-flow override would
collapse these grids to one stacked column, so each module re-asserts
`display: grid !important` in its `@media print` block — see the PDF guide's
"Print forces `.resume-items` to block flow" entry; do not remove it.

The org unit on its own source line (`武汉软通动力 / 全球资金部`, also
研发部 / 云计算集成部 / 保险事业群 / 平台研发中心 / "Payments Team") must
land in `Experience.department`, not in the description. Two layers guarantee
it: the parse prompt documents the field (both JSON schema examples carry
`department`) and `parser.promote_work_departments` deterministically lifts a
leading `"plain"` description row that looks like a standalone org unit into an
empty `department` field at parse time; the renderer mirrors the same
recognizer in `components/resume/work-department.ts` (`promoteWorkDepartment`)
so already-stored resumes render correctly without a re-parse. A promoted line
is removed from the description lists; bullet-styled or sentence-like rows are
never promoted. The full upload→JSON rule set (extraction, field mapping, all
seven post-LLM passes) is documented in
[resume-parsing-rules.md](resume-parsing-rules.md).
