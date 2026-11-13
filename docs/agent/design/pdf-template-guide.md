# PDF Template Guide

> PDF rendering and template editing for resumes and cover letters.

## Rendering Flow

```
Backend: GET /resumes/{id}/pdf
├── Build URL: {frontend}/print/resumes/{id}?params
├── Playwright opens headless Chrome
├── Waits for .resume-print selector
├── Waits for document.fonts.ready
├── Generates PDF (zero margins, print_background=true)
└── Returns PDF bytes
```

## Print Routes

| Route | Selector | Output |
|-------|----------|--------|
| `/print/resumes/[id]` | `.resume-print` | Resume PDF |
| `/print/cover-letter/[id]` | `.cover-letter-print` | Cover letter PDF |

## Renderer Limits

| Environment variable | Default | Supported range | Purpose |
|----------------------|---------|-----------------|---------|
| `PDF_MAX_CONCURRENCY` | 4 | 1-16 | Maximum active exports; excess requests fail immediately instead of queueing |
| `PDF_RENDER_TIMEOUT_SECONDS` | 75 | 1-600 | Total export lifetime, including browser/page creation and cleanup |
| `PDF_CLEANUP_RESERVE_SECONDS` | 5 | 0.1-30 | Portion of the total lifetime reserved for resource cleanup |

The renderer replaces a disconnected cached browser automatically. On Windows
event loops that require the thread fallback, a cancelled or timed-out request
continues to occupy its concurrency slot until its bounded worker exits.
If page cleanup exceeds its reserve, the shared browser is retired and its
teardown retains a slot; saturated follow-up requests receive the same immediate
busy outcome until cleanup finishes, after which a healthy browser is created.
Cancellation during page cleanup also retires the browser and propagates the
cancellation; capacity remains owned until browser and Playwright teardown finish.
An ordinary Playwright error while closing the page is logged and retires the
browser, but does not discard an already-generated PDF or replace an earlier
render failure. Exceeding the cleanup deadline still makes an otherwise successful
export time out.

Retirement immediately removes that browser from the cache, so new exports cannot
join it. Existing exports keep using their own pages until their render and page
cleanup scopes finish; only then does the retirement owner close the shared
browser. Concurrent cleanup failures therefore retire that generation only once
without aborting or replaying healthy exports. The retirement reservation owns
unclosed resources independently of the existing exports' request slots; it is
kept while those exports use their existing deadlines to finish.

A successful stop of the owned Playwright driver is a teardown acknowledgement,
even if its Browser object retains a stale `is_connected()` flag. If driver
shutdown fails, cleanup quarantines its browser/driver objects and admission slot
until application restart. Playwright's stop method is one-shot, so retrying a
failed stop can return without doing any cleanup; such a return is not accepted
as proof of teardown. Quarantine logs the failure and completes the cleanup task
instead of leaving an unsignalled waiter. Application shutdown reports any
quarantined generations and waits for still-active cleanup owners within the
cleanup reserve; it does not cancel them or release their capacity prematurely.
If an external shutdown cancels retirement before teardown is acknowledged,
including before the cleanup task first runs, its browser/driver and reservation
move into the same terminal quarantine. Cancellation still propagates. This
retains explicit ownership; it does not claim the browser was physically stopped.

## Query Parameters

| Param | Default | Range |
|-------|---------|-------|
| template | swiss-single | swiss-single, swiss-two-column |
| pageSize | A4 | A4, LETTER |
| marginTop/Bottom/Left/Right | 10 | 5-25mm |
| sectionSpacing | 3 | 1-5 |
| itemSpacing | 2 | 1-5 |
| lineHeight | 3 | 1-5 |
| fontSize | 3 | 1-5 |
| headerScale | 3 | 1-5 |

## Critical CSS Rule

In `globals.css`, whitelist print classes or PDFs will be blank:

```css
@media print {
  body * { visibility: hidden !important; }
  
  .resume-print,
  .resume-print * { visibility: visible !important; }
  
  .cover-letter-print,
  .cover-letter-print * { visibility: visible !important; }
}
```

## Page Breaks / Fragmentation

PDFs are natural-flow Chromium pagination of the print route (no JS
pagination), so break rules live entirely in CSS. The intended granularity:

- **The resume root (`.resume-body`) is fragmentable** — `break-inside: auto`
  in print. A previous `break-inside: avoid-page !important` on the root made
  the whole resume monolithic; Chromium then pushed entire sections to the
  next page and left most of the previous page blank (large inter-page gaps).
  Never reintroduce an avoid rule on `.resume-body` or any ancestor that can
  exceed one page.
- **Sections (`.resume-section`) may span pages**; section titles use
  `break-after: avoid` so a title is never orphaned, and the title is kept
  with its first item via `break-before: avoid`.
- **Individual entries (`.resume-item`) stay atomic** (`break-inside: avoid`);
  an entry taller than a page is still split as a last resort.
- **Print forces `.resume-items` to block flow** (`display: block !important`
  in `_base.module.css @media print`). Column-flex stacks fragment
  conservatively in Chromium (atomic flex items get pushed early and reopen
  the same whitespace gap); block flow fills pages densely. Entries already
  carry their inter-item margin. **Grid-section exception:** the work/
  education section elements also carry `entryGridSection`
  (modern/latex/clean) or `entrySectionWork`/`entrySectionEdu`
  (swiss-single) and OWN the column tracks their subgrid rows inherit. As a
  plain block the parent stops being a grid, `grid-template-columns: subgrid`
  computes to one implicit column and every cell stacks vertically — so each
  template module re-asserts `display: grid !important` inside its own
  `@media print` via the higher-specificity `:global(.resume-print) …`
  selector (0,2,0 over the base 0,1,0). Do not remove that rule.
- The on-screen `PaginatedPreview` mirrors the same policy in JS
  (`use-pagination.ts`: item + title bounds, never whole sections).

## Template Structure

```
components/resume/
├── index.ts                    # Template exports
├── resume-single-column.tsx    # Full-width vertical
└── resume-two-column.tsx       # 65% main + 35% sidebar
```

## Adding New Templates

1. Create `components/resume/resume-{name}.tsx`
2. Export from `components/resume/index.ts`
3. Add to template selector in `formatting-controls.tsx`
4. Add thumbnail preview

## Template Props

```typescript
interface TemplateProps {
  resumeData: ResumeData;
  settings: TemplateSettings;
}
```

## CSS Classes

```css
.resume-section        /* Section container */
.resume-section-title  /* Section heading */
.resume-items          /* Items container */
.resume-item           /* Individual entry (won't split across pages) */
```

## Error Handling

If Playwright can't connect to frontend, returns HTTP 503 with:
```
Cannot connect to frontend for PDF generation.
Please ensure: 1) Frontend is running
              2) FRONTEND_BASE_URL matches your frontend URL
```

## DOCX (Word) Export

Alongside PDF, the resume viewer offers `GET /api/v1/resumes/{id}/docx`
(`lib/api/resume.ts::downloadResumeDocx`). Word does not render CSS, so DOCX
is a **single canonical editable layout** built directly from structured
`processed_data` with python-docx — it deliberately does **not** follow the
seven visual resume templates, and there are no template/query settings.
Generation is pure CPU: no LLM call, no Chromium, no concurrency slots.

Semantics mirror the on-screen swiss-single template so screen, PDF and
Word never disagree:

- Section order / default-title governance / omitted-row healing come from
  `canonicalize_section_meta`; the legacy department repair
  (`promote_work_departments`) runs on a private deepcopy.
- Header fact grid: 性别 / 年龄 / 学历 / 工作年限 / 求职意向 / 期望城市 / 电话 /
  邮箱 / 外语水平; languages appear only here, never in 专业技能.
- Four-column borderless entry tables: work 时间｜公司｜部门｜岗位 (job title
  regular weight), education with school bold, projects with name/role bold.
- Description blocks: `label` is a bold standalone row and resets the bullet
  counter; `bullet` rows render as a hanging `1. 2. …` sequence per label;
  `plain` rows are unnumbered body text.
- Skills are an ordered list (a single entry is a plain paragraph) at the
  early `additional` slot; **培训与证书 and 荣誉奖项 are independent titled
  sections projected to the BACK of the resume** — after the custom-section
  cluster, anchored (first hit) before the legacy honors row, before the
  late education row on the other-degree branch, before 自我评价, or at
  document end. They are render-only slots (data stays under `additional`;
  never meta rows), mirroring the frontend `getRenderSections` projection
  via `_late_modules_anchor`; hiding the additional meta row hides all
  three modules.
- Leaked Markdown emphasis markers are stripped and rendered string lists
  de-duplicated on the copy (e.g. `英语四级` / `英语四级**` collapse to one
  外语水平 fact); source-carried list numbering is removed.
- Static chrome is bilingual (`zh`/`en`). `?lang=` overrides; when omitted
  the chrome follows the **content language** (Han-character detection), so
  the viewer page calls the endpoint without `lang`.
- Filename uses an ASCII fallback plus RFC 5987 `filename*=UTF-8''…`.
  Both DOCX and PDF name the file `姓名-年龄-工作年限-学历-求职意向`
  (e.g. `王浩-28岁-5年-硕士-Java开发工程师.docx`); facts come from
  `personalInfo` (学历 falls back to the first `education[].degree`),
  empty facts are skipped, illegal filename characters are replaced, and
  when no fact exists the ASCII fallback `resume-<id8>.<ext>` is used
  (DOCX additionally falls back to `简历-<id8>` for the UTF-8 stem).

Builder: `app/services/resume_docx.py::build_resume_docx`; endpoint contract
in [front-end-apis.md](../apis/front-end-apis.md). PDF layout behavior is
unchanged; its download filename follows the same five-fact rule.
