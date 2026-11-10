# Frontend API Client

> API client layer for Resume Matcher frontend.

## Base Client (`lib/api/client.ts`)

```typescript
export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
export const API_BASE = `${API_URL}/api/v1`;

export async function apiFetch(endpoint: string, options?: RequestInit);
export async function apiPost<T>(endpoint: string, body: T);
export async function apiPatch<T>(endpoint: string, body: T);
export async function apiPut<T>(endpoint: string, body: T);
export async function apiDelete(endpoint: string);
export function getUploadUrl(): string;
```

## Resume Operations (`lib/api/resume.ts`)

```typescript
// Job descriptions
uploadJobDescriptions(descriptions: string[], resumeId: string) → job_id

// Resume improvement
improveResume(resumeId: string, jobId: string) → ImprovedResult

// CRUD
fetchResume(resumeId: string) → ResumeResponse['data']
fetchResumeList(includeMaster?: boolean) → ResumeListItem[]
updateResume(resumeId: string, data: ResumeData) → ResumeResponse['data']
deleteResume(resumeId: string) → void

// PDF
downloadResumePdf(resumeId: string, settings?: TemplateSettings) → Blob
downloadCoverLetterPdf(resumeId: string, pageSize?: PageSize, locale?: Locale) → Blob
downloadInterviewPrepPdf(resumeId: string, pageSize?: PageSize, locale?: Locale) → Blob
downloadJdMatchPdf(resumeId: string, pageSize?: PageSize, locale?: Locale) → Blob
// get*PdfUrl companions build the same URLs for the popup-blocked new-tab fallback

// Word (canonical editable layout; viewer page only)
getResumeDocxUrl(resumeId: string, locale?: Locale) → string
downloadResumeDocx(resumeId: string, locale?: Locale) → Blob

// Content updates
updateCoverLetter(resumeId: string, content: string) → void
updateOutreachMessage(resumeId: string, content: string) → void

// On-demand generated content (any resume with processed data)
generateCoverLetter(resumeId: string, jobDescription?: string) → string
generateOutreachMessage(resumeId: string, jobDescription?: string) → string
generateInterviewPrep(resumeId: string, jobDescription?: string) → InterviewPrepData
generateCoverLetterFromResume(resumeId: string, jobDescription?: string) → string
```

**On-demand generation works for every resume, not just tailored ones.** The three
endpoints `POST /resumes/{id}/generate-cover-letter`, `POST /resumes/{id}/generate-outreach`
and `POST /resumes/{id}/generate-interview-prep` accept an optional JSON body
`{"job_description": string}` (default `""`, max 100,000 chars — oversized returns 422
before the handler runs; a missing/empty body stays backwards compatible). Resolution
follows `_resolve_requested_job_context`: a non-empty `job_description` pasted in the
request (the standalone-resume "target this job" option) **takes precedence** and is
size-checked directly with no job-record lookup; otherwise the endpoints fall back to
`_resolve_generation_job_context` — a tailored resume (`parent_id` set) loads its stored
job through the improvement record, 400 when the improvement is missing and 404 when the
job is missing, while a standalone resume proceeds with an **empty job description**.
The services branch on the empty/whitespace JD and use the built-in no-JD templates
`COVER_LETTER_NO_JD_PROMPT`, `OUTREACH_NO_JD_PROMPT` and `INTERVIEW_PREP_NO_JD_PROMPT`
(these take only `{resume_data}` + `{output_language}`, so custom feature-prompt
overrides — which require `{job_description}` — apply solely on the JD-present path).
Generated content is persisted on the resume (`cover_letter` / `outreach_message` /
`interview_prep`), so the PATCH updates and PDF exports work immediately. All three
return 404 when the resume is missing, 400 when it has no processed data, and 500
(generic message, details logged) on generation failure.

`generateCoverLetterFromResume` posts to `POST /api/v1/resumes/{resume_id}/cover-letter/generate`
with body `{"job_description": string}` (default `""`, max 100,000 chars — oversized
returns 422). It also works for **any** resume with processed data and needs no stored
job context: an empty/whitespace `job_description` produces a resume-only cover letter
via the `COVER_LETTER_NO_JD_PROMPT` template, while a provided JD tailors the letter to
the role. Returns `GenerateContentResponse { content, message }`.

**Content PDF exports** reuse the stored content (no extra LLM call) and render the
provider-free server components under `/print/*` via headless Chromium:

- `GET /api/v1/resumes/{id}/cover-letter/pdf` — 404 when no cover letter is stored;
  print selector `.cover-letter-print`; filename `cover_letter_{id}.pdf`.
- `GET /api/v1/resumes/{id}/outreach/pdf` — 404 when no outreach message is stored;
  renders the `/print/outreach/[id]` server component; selector `.outreach-print`;
  filename `outreach_{id}.pdf`.
- `GET /api/v1/resumes/{id}/interview-prep/pdf` — 404 when no interview prep is stored;
  print selector `.interview-prep-print`; filename `interview_prep_{id}.pdf`.
- `GET /api/v1/resumes/{id}/jd-match/pdf` — **tailored-only**: a standalone resume gets
  404 ("JD matching is only available for tailored resumes"); a tailored resume
  re-resolves its stored job (400/404 propagation as above). The print page recomputes
  keyword stats with the same pure `keyword-matcher` utilities as the on-screen
  comparison, so PDF and tab show identical percentages and highlights; selector
  `.jd-match-print`; filename `jd_match_{id}.pdf`.

All four accept `pageSize` (`A4`|`LETTER`, default `A4`) and optional `lang`
(`^[a-z]{2}(-[A-Z]{2})?$`) for the print-page chrome, return `application/pdf`, and
surface Chromium failures as **503** (`PDFRenderError`, details logged). The frontend
saves blobs through `buildResumeFilename(name, company, id, kind)` with kinds
`cover-letter` / `outreach` / `interview-prep` / `jd-match`, and falls back to opening
the `get*PdfUrl` URL in a new tab when the blob fetch hits a network `TypeError`.

> **Print-CSS contract.** The global `@media print` block hides `body *` and reveals
> only an allow-list of print roots (`.resume-print`, `.cover-letter-print`,
> `.outreach-print`, `.interview-prep-print`, `.jd-match-print`). A new `/print/*`
> route whose root class is missing from that allow-list renders a valid but
> **completely blank PDF** — add the class (and its `*` descendants) to both the
> visibility and layout rules in `app/(default)/css/globals.css`, and pass the same
> selector as `render_resume_pdf(..., selector=...)`.

**Resume PDF / DOCX readiness gates.** `GET /api/v1/resumes/{id}/pdf` (renders the
`/print/resumes/[id]` server component via Chromium) and `GET /api/v1/resumes/{id}/docx`
fail fast before any render/build work when the record cannot produce a document:

- **409** when `processing_status` is not `ready` (`pending` / `processing` / `failed`).
  Previously the PDF endpoint launched Chromium anyway: the print route errors on
  markdown-only records or renders a hidden zero-size `.resume-print` shell, so the
  caller burned the full 60s render timeout (503) or received a blank-page PDF. The
  detail is an actionable "still being processed … download again" message.
- **422** (PDF) / **400** (DOCX) when the record is `ready` but holds no renderable
  structured `ResumeData` — neither `processed_data` nor JSON-parseable `content`
  (e.g. markdown-only content). The detail directs the user to retry parsing or open
  the resume in the builder.
- 404 still takes precedence for an unknown id; renderer/build failures remain
  503 (PDF) / 500 (DOCX), details logged server-side.

The print page itself (`app/print/resumes/[id]/page.tsx`) throws instead of returning
an empty `ResumeData` shell, and the builder keeps its PDF/Word buttons disabled until
the record reaches its loaded state, so the gates are defended at every layer.

## Resume Diagnosis (`lib/api/diagnosis.ts`)

```typescript
diagnoseResume(resumeId: string, options?: { jobDescription?: string; targetTitle?: string; competencyModelKey?: string | null; templateSettings?: TemplateSettings; renderedLayout?: RenderedLayout }) → DiagnosisReport
fetchCompetencyModels(title?: string) → CompetencyCatalog  // { models: {key, name, family, level}[], matched_key: string | null }
exportDiagnosisDocx(resumeId: string, report: DiagnosisReport) → Blob  // .docx
```

Backend endpoints:

- `GET /api/v1/diagnosis/competency-models?title=…` — lists the shipped per-role competency models and the model auto-matched for `title` (omit `title` for `matched_key: null`). Title→level matching is server-side regex data in the rules artifact; the picker calls this on modal open and whenever the selected target title changes. Today the catalog is the **Java engineering level matrix**: keys `java-p3`…`java-p8` (family `Java`, levels P3–P8), five capability elements per level (系统架构 / 业务架构 / 开发技能 / 应用技能 / 项目管理) keyed to base items 18–22 via `item_id`.
- `POST /api/v1/resumes/{resume_id}/diagnose` — body `{"job_description": string | null, "target_title": string | null, "competency_model_key": string | null, "template_settings"?: TemplateSettingsIn, "rendered_layout"?: RenderedLayoutIn}` (the last two are optional, shipped **only as a pair** after the browser offscreen-measures the resume with the builder's chosen template). Runs the V4-optimized checklist rubric (**7 dimensions / 22 contiguous items / 1 red line — no scoring**: verdicts only, no total/band/weights). Dimension layout: 简历外观 appearance 1–2, 撰写规范 content 3–13 (11 = 培训与证书, 12 = 荣誉奖项, 13 = 时间线自洽), 工作稳定性 stability 14 (risk marker, never a veto), 职业成长性 growth 15, 风险与合规 compliance 16, 目标岗位匹配度 fit 17, 专业能力 competence 18–22. Each non-competence item also carries a per-failure **质检违规等级建议** (`qc`: 🔴 严重 / 🟡 一般 / 🟢 轻微 / 💡 提示) used only as the LLM's internal rating guide (the five competence pointer rows ship with an empty `qc`). Items carry a server-side prerequisite (`""` / `"jd"` / `"intention"`) driving **two independent gates**: without a JD only **17** is `na`; without a resolved level model (no clear 求职意向, no title match and no explicit pick, or `"none"`) **18–22** are `na` — so a no-JD run whose target title auto-matches a model still judges 18–22, and a JD run with no intention still gets 18–22 `na`. `target_title` drives model auto-matching; when omitted/null the backend defaults to the resume's `personalInfo.title`. Item **15** is objectively `na` below 5 effective dev years (internships/non-dev time excluded), otherwise LLM-judged. Items **11/12** are objectively `na` when the optional module renders no entries (`additional.certificationsTraining` / `.awards` empty, or the additional meta hidden — module existence is never an LLM question); with entries present they are LLM-judged for relevance / count / format / ordering, and the authoritative certification / award / language entry lists ride the facts packet. 13 item ids always have deterministic Python checkers (`1–10, 13, 14, 16`; #1 merges order + title-governance + oversized-paragraph checks, with #1/#2 preferring the measured render snapshot over the text-length estimates when one is shipped, #3 requires all five core modules unconditionally, #7 merges the 8–15 skill count with mainstream-stack coverage, #9 uses a six-field proxy, requires 2–4 projects unconditionally and treats 项目时间 as conditionally optional, #13 merges date format/validity, unnoted work-work and education-education overlaps (兼职/外包 and 双学位/联合培养/在职 notes exempt), project-inside-work-tenure containment (【个人业余项目】 exempts), first-full-time-job-vs-highest-degree-enrollment order (6-month tolerance; in-service degrees and internships exempt) and stated-years with a ±0.5-year tolerance, #14 emits non-veto risk evidence and #16 runs the privacy scan over both the structured data and the verbatim original upload); the fact basis is two-layered: the resume's stored original markdown — the upload-time parser/OCR transcription (legacy md `content` fallback), sent to the LLM verbatim, bounded at 20,000 chars with an explicit truncation notice — grounds content-level facts (what happened / exact wording / numbers), while module organization (which module an entry belongs to, whether an optional module exists or is empty, entry counts/ordering, duplication in the finished resume) is authoritative in the structured data plus the objective facts packet, because the raw upload often groups certs/awards/languages under catch-all headings such as 「其他」 that parsing has since regrouped into `additional.certificationsTraining` / `.awards` / `.languages`; the remaining supported semantic items are judged by one structured LLM call against the confidential criteria/QC text (the V4 workbook has no global-rules sheet — same-fact-judged-once attribution is folded directly into the prompt). `competency_model_key`: a real catalog key fills the five competence base items **18–22 in place** with that level's behavioral standards (the checklist always stays at 22 items / 7 dimensions — there are no synthetic item ids); `"none"` explicitly opts out even when the title auto-matches; `null`/blank uses the title auto-match (P3 初级 → P4 generic `Java 开发工程师` → P5 高级 → P6 资深 → P7 架构师 → P8 技术专家, first match wins). Returns a **flat** payload (no `data` envelope):
  - `counts` and per-dimension `counts`: `{conform, partial, nonconform, na, effective}` — `na` items are excluded from `effective` (`effective + na === 22`).
  - `redline_passed` + `failed_redline_ids` (the single red-line id is **16** 风险与合规 — privacy leak / fraud / confidentiality veto; only an explicit `nonconform` fails it), plus a `redlines` list with each red line's `{id, topic, passed, rating, evidence, suggestion}`. Stability item 14's 🔴-level findings are *not* vetoes.
  - `target_title` (the title actually used) and `competency_model` (`{key, name}` or `null`).
  - `dimensions` follow spec order and always end with `{key: "competence", name: "专业能力", counts}` (its five rows are `na` without a resolved intention/model, regardless of the JD).
  - `items`: flat list of `{id, dimension, dimension_name, sub_dimension, topic, severity ("redline" | "normal"), judgment_method ("objective" | "subjective"), rating ("conform" | "partial" | "nonconform" | "na"), evidence, suggestion}`. `topic` is a short **public problem-location label** — the 二级维度 verbatim (e.g. `时间线自洽`, `任职连续性`, `风险与合规`). The full rubric `criterion` and the `qc` 质检违规等级建议 text stay server-side (sent to the LLM only) and are never serialized; the model is explicitly forbidden from quoting thresholds or rule codes. For `partial`/`nonconform` rows `evidence` says where/what is wrong in this resume (module/field + concrete facts) and `suggestion` gives the matching fix (and nothing unrelated). **`conform` rows always serialize both fields as empty strings** — no positive description, no praise, no optional tips (enforced server-side for LLM and deterministic verdicts alike); `na` rows carry only the applicability reason in `evidence` and an empty `suggestion`.
  - `warnings` for items the LLM omitted (defaulted to `partial`, empty suggestion).
  404 when the resume is missing, 400 when it has no processed data or `competency_model_key` is neither a catalog key nor `"none"` (generic message: model unavailable, choose another), **413** when the request body exceeds **128 KiB** (`Content-Length` guard; generic message, details logged — also caps an over-long JD), **422** when an optional layout field violates its bounds. The call is long (LLM) and uses the 240s default client timeout.
- **Rendered-layout snapshot (optional)** — `template_settings` mirrors the builder's `TemplateSettings` (`template` one of the seven template ids, `pageSize` `A4`|`LETTER`, four 5–25 mm integer margins, 1–5 spacing/font levels, booleans, enum-validated font/accent; all fields optional) and `rendered_layout` is a client-produced, browser-measured snapshot of that template's real offscreen render: `{schema_version, measured_at, template, page_size, margins, content_width_px, content_height_px, page_count (1–12), total_height_px, two_column, header{height_px, cell_count, rows[]}, sections[≤40]{key,title,visible,index,height_px,pages[]}, points[≤300]{locator, location, text(≤120), chars, visual_lines, height_px, page}, page_mirror[≤12]{page, text(≤6000)}, warnings[≤20]}` with a total JSON payload cap of **48 KB**; `locator` is one of `{kind:"summary", point_index}` / `{kind:"entry", section:"workExperience"|"personalProjects", entry_index, point_index}` / `{kind:"custom_text", key, point_index}` / `{kind:"custom_item", key, entry_index, point_index}` (point enumeration mirrors the backend traversal exactly; `stringList` custom sections are excluded from points). Both schemas use `extra="ignore"`. The backend accepts the snapshot only when its `template` **and** `page_size` match `template_settings` (a mismatch logs and is discarded wholesale — #1/#2 then fall back to the 46-chars-per-line / 950-chars-per-page text estimates, exactly as legacy clients behave; an empty body `{}` remains valid). When accepted, deterministic items **#1** (per-point measured visual lines, >6 fails; unmatched points still fall back to the char estimate) and **#2** (measured `page_count`, >3 fails) judge the real render — evidence says “按所选模板…实际渲染”, never “估算” — and the LLM prompt gains a “所选模板的实际渲染结果” block (facts JSON + per-page text mirror, ≤12,000 chars) with a hard rule: items 1/2 are already decided, so the LLM must not re-assert paragraph/page-length problems anywhere or infer appearance from character counts; text facts remain grounded solely in the original resume and structured JSON. Snapshots are never persisted. Full rationale: [docs/agent/features/resume-diagnosis.md](../features/resume-diagnosis.md) §“所选模板的实际渲染结果（前端测量快照）”.
- `GET /api/v1/resumes/{resume_id}/docx?lang=zh-CN` — builds a **single canonical editable Word file** from structured `processed_data` (JSON `content` fallback when `processed_data` is missing; no LLM, no Chromium, pure CPU). DOCX deliberately does **not** follow the seven visual templates: one normative layout mirroring the on-screen swiss-single semantics — canonical section order/title healing via `canonicalize_section_meta`, header fact grid (a borderless three-column Word table: 性别/年龄/学历/工作年限/求职意向/期望城市/电话/邮箱/外语水平， one `label：value` pair per cell so a label can never split from its value across wrapped lines; 语言只进事实网格) followed by a labeled personal-link row (个人网站/领英/GitHub， protocol-stripped, muted gray), four-column entry headers (work 时间｜公司｜部门｜岗位 with the job title **not** bold; education with school bold; projects with name/role bold), `label` bold standalone rows that restart bullet numbering, `plain` unnumbered body, ordered skills at the early `additional` slot, and **independent 培训与证书 / 荣誉奖项 sections projected to the back of the resume** (after the custom-section cluster; anchor: legacy honors row → other-branch education → self-evaluation → document end; render-only slots, data stays under `additional`). Markdown emphasis stripping and rendered-list de-duplication (e.g. a doubled 英语四级 fact) are replayed on a private deepcopy. The optional `lang` (`^[a-z]{2}(-[A-Z]{2})?$`) selects only the static chrome; when omitted the chrome follows the **content language** (Han-character detection). Returns the docx media type with an ASCII fallback + RFC 5987 `filename*=UTF-8''…` header; the download is named `姓名-年龄-工作年限-学历-求职意向` (e.g. `王浩-28岁-5年-硕士-Java开发工程师.docx`) — facts from `personalInfo` (学历 falls back to the first `education[].degree`), empty facts skipped, illegal filename characters replaced; with no facts at all the UTF-8 stem falls back to `简历-<id8>` and the ASCII filename is always `resume-<id8>.docx`. The `GET …/pdf` endpoint uses the same five-fact naming (helper `_resume_download_stem` / `_resume_download_headers`), and the frontend blob saves mirror it via `buildResumeFactFilename` (viewer PDF + Word, builder PDF). 404 when the resume is missing, **409 when it is not yet `ready`** (see the readiness-gates paragraph above), 400 when a `ready` record has no structured data available, 500 generic (details logged server-side) on build failure.
- `POST /api/v1/resumes/{resume_id}/diagnose/document` — body is the **`DiagnosisReport` already shown on screen** (re-posted by the client; no second LLM call). Renders it with python-docx into a bilingual Word report (CJK fonts: 黑体 headings / 宋体 body) and returns `application/vnd.openxmlformats-officedocument.wordprocessingml.document` with `Content-Disposition: attachment` (ASCII fallback + RFC 5987 `filename*=UTF-8''…`, stem `简历诊断报告-<姓名>-<YYYYMMDD-HHMM>` local time — e.g. `简历诊断报告-王浩-20261030-2156.docx`; name resolved from `processed_data.personalInfo.name`, illegal filename characters replaced; a missing name falls back to `resume-<id8>` — frontend blob saves mirror it via `buildDiagnosisReportFilename`). Document sections: ① overall counts (`适用 N 项 —— 符合/部分符合/不符合；不适用 M 项`), target title, a `能力模型匹配：<model>：…` line driven by the competence dimension counts when a model was used, red-line verdict, ② failed red lines with topic + `检查位置` + problem + fix (omitted entirely when the red line passes), ③ per-dimension counts table with 6 columns (`维度 / 适用 / 符合 / 部分符合 / 不符合 / 不适用`, one row per report dimension), ④ 问题描述与优化方案 for every partial/nonconform item (sorted red-line first, grouped by dimension; each heading shows `#id` + public topic and label-value rows 检查位置 / 问题描述 / 优化方案 grounded in the posted report), ⑤ appendix table of all 22 checks with columns `序号 / 维度 / 检查位置 / 评级` — the confidential standards (criteria, QC guidance, level standards) are never rendered. Subtitle counts are dynamic (`N 维度 / M 检查项 / K 红线`). 404 when the resume is missing, 500 (generic message, details logged server-side) on render failure.

Resume upload accepts matching PDF, DOC or DOCX filename/MIME pairs. The backend
returns 400 for unsupported or mismatched types, 413 for raw/expanded/extracted
size limits, and 422 for malformed documents or textless PDFs that OCR could
not recover (when the optional `ocr` extra is installed — `uv sync --extra
ocr`, offline PP-OCR via pypdfium2 + rapidocr-onnxruntime, no external
service — scanned and glyph-as-outline PDFs are rasterised and recognised
automatically instead of being rejected; only genuinely unrecognisable files
still 422). Upload and
retry processing return 409 when a newer processing attempt supersedes the
request, or 404 when the resume is deleted while processing.

## Preview and confirmation

Preview returns `data.preview_id` and `data.preview_expires_at`; confirmation forwards `preview_id` with the unchanged proposed resume. Successful retries return the same stored response without creating another resume. An active confirmation returns 409 with `Retry-After: 1`; stale or expired input snapshots require a new preview. See [the complete contract and transaction lifecycle](../features/preview-confirmation.md).

**Tailoring source eligibility.** Tailoring is no longer master-only: any master or standalone resume (`parent_id` NULL) that is `processing_status = "ready"` and has structured data can be the source. Already-tailored resumes are rejected on all three entry points (`/improve/preview`, `/improve/confirm`, legacy `/improve`) with **400** — `"Tailored resumes cannot be used as a tailoring source; choose the master or a standalone resume."` — so the lineage never nests grandchildren; a non-ready source returns 400 `"The selected resume is not ready for tailoring yet."` and a source without processed data returns 400 `"The selected resume has no processed data to tailor."`. The new child keeps `parent_id`/`improvement.original_resume_id` pointing at the selected source, and the refinement truth baseline (keyword-injection and alignment checks) is grounded in that source rather than the global master. The frontend selects sources via `lib/utils/tailor-source.ts` (`isEligibleTailorSource` / `selectTailorSource`): the `/tailor` page dropdown lists only eligible resumes, the resume-viewer "tailor from this resume" button deep-links with `?source=<id>`, an ineligible `?source=` falls back to the master, and a list with no eligible resume redirects to `/dashboard`. The tracker column `applications.master_resume_id` is reused unchanged as the source-resume id (no migration).

**Deterministic tailored-resume title.** The tailored resume's `title` (shown in the viewer and reused as the tracker card role) is built without an LLM call as `姓名-岗位名称`: `personalInfo.name` plus the role cached in the job's keyword extraction (`job_keywords.role`), falling back to the first slash-separated segment of `personalInfo.title` 求职意向, then a localized generic title ("定制简历" / "Tailored Resume" / …). One line, 80-character cap. This replaced the LLM-generated title after models were observed echoing prompt rules into the stored title; manual renaming via `PATCH /resumes/{id}/title` is unchanged.

## Resume Fine-Tune (`lib/api/fine-tune.ts`)

```typescript
previewFineTune(resumeId, { scope: { kind: "all" | "modules", targets: string[] }, instruction?, output_language? }) → FineTunePreviewResponse
confirmFineTune(resumeId, { preview_id, improved_data, mode: "overwrite" | "copy", title? }) → FineTuneConfirmResponse
```

Job-less self-improvement: the LLM reorganizes/polishes content grounded in BOTH the structured data and the original upload text (`extra_evidence`); facts present in neither source are stripped or kept only as `GROUNDING_REVIEW` warnings. Scope tokens: `all` (empty targets) or 1–30 deduplicated tokens from `summary|education|additional|customSections|workExperience|personalProjects|work_N|project_N|(work|project)_N:<region>|custom_<key>` (N is the 0-based stored/canonical sequence, same convention as enrichment `exp_N`; `custom_<key>` selects one custom section by its `customSections` dictionary key — builder keys are themselves `custom_N`, giving the double-prefixed `custom_custom_1`; `customSections` is the legacy whole-section token kept for backward compatibility). The third scope level is a label sub-module region inside one entry: `(work|project)_N:<region>` with `<region>` one of `techStack|background|duties|highlights|achievements|role` (projects carry techStack/background/duties/highlights; work entries carry techStack/duties/achievements/role — curated label cores, never renamed). Region scope rewrites ONLY the content rows under that label, in place, keeping the original row count; the label row itself, its style and every other row are byte-frozen, and styles are always taken from source rows. A whole-section or whole-entry token supersedes (`work_N` sweeps its regions). A syntactically valid `custom_<key>`/`work_N`/region token whose index, key or region the resume does not contain is **not** a 422: it is accepted and reported in `warnings` as an ignored out-of-range target; per-key custom overlay only replaces keys present on both source and candidate, and `customSections` supersedes any per-block tokens. When the model returns more (or merged/split) rows than the region owns, the extras are dropped and `warnings` carries a `REGION_APPEND_DROPPED: …` entry (matched by prefix for localization). `personalInfo` and `sectionMeta` are always frozen. The response includes the full `improved_data`, `diff_summary`, `detailed_changes`, and `warnings` (which also lists ignored out-of-range targets). Full product/contract notes: [fine-tune.md](../features/fine-tune.md).

Backend endpoints:

- `POST /api/v1/resumes/{resume_id}/fine-tune/preview` — runs the LLM (240s budget), grounding and scope restriction, then registers a `fine_tune_previews` row. Repeating the same source+payload returns the same `preview_id` (idempotent). `400` when the resume has no structured data, `404` when missing, `422` on bad scope tokens / kind-targets combination / over-long instruction, `504` on operation timeout, `500` generic (details logged).
- `POST /api/v1/resumes/{resume_id}/fine-tune/confirm` — claims the preview and persists. **`overwrite`** updates `content`/`processed_data`/`content_type`/`processing_status` only — `original_markdown` and `is_master` are untouched; **`copy`** creates a non-master child (`parent_id`, inherited `original_markdown`, filename `finetuned_…`, default title suffix ` (fine-tuned)`), with no Improvement/tracker side effects. `400` for unknown/expired `preview_id`, echoed payload whose hash differs, or a registered preview that no longer satisfies grounding/scope on replay; **`409` has two meanings** — resume changed after preview (`source_hash` mismatch; generate a new preview) and another confirmation in progress (`Retry-After: 1`). Re-confirming a completed preview replays the same `resume_id` (no second copy). Deleting the source removes its preview rows; reset-database clears the table.

## Resume Wizard (`lib/api/resume-wizard.ts`)

```typescript
postResumeWizardTurn(payload: ResumeWizardTurnRequest) → ResumeWizardTurnResponse
finalizeResumeWizard(state: ResumeWizardState) → ResumeWizardFinalizeResponse
createInitialResumeWizardState() → ResumeWizardState
```

Backend endpoints:

- `POST /api/v1/resume-wizard/turn` — one adaptive turn. `action` is `start | answer | skip | back | review`. `answer`/`skip` run one AI call that updates `resume_data`, returns the next `current_question`, `inferred_skills`, and a strict boolean `is_complete` flag; `back`/`review`/`start` are deterministic (no LLM). The service validates the complete model envelope before advancing history or progress. Invalid envelopes return a recoverable `422` and leave the client state unchanged. Work, education, and project entries carry stable positive IDs: a correction retains the current entry ID, while an addition uses ID `0` and receives the next available ID. Partial model echoes preserve entries they omit. Deterministic fallback questions and review copy use the configured content language. The full `ResumeWizardState` round-trips in the request and response.
- `POST /api/v1/resume-wizard/finalize` — creates the single master resume from the draft (`processing_status: "ready"`), or `409` if a master already exists.

The wizard is an AI-led, one-question-at-a-time flow that builds a general master resume; it does not require a job description and does not replace the upload parser. Question and content text are produced in the configured **content language**; static UI chrome uses the `resumeWizard.*` i18n keys.

## Application Tracker (`lib/api/tracker.ts`)

Tracker patches distinguish omission from explicit null: omitted `status` keeps the current column, while `status: null` returns 422. Nullable text/date fields remain clearable. Each move from `saved` to a non-saved column stamps `applied_at` if it has no date; explicit dates (including an explicitly cleared date in the same patch) are preserved. Bulk moves use the same rule. Moving back to `saved` retains any existing date; applying again fills a missing date. Moves between non-saved columns leave cleared dates empty.

Create, move, and delete operations reserve the SQLite writer before allocating or renumbering column positions. This keeps positions contiguous across concurrent single/bulk operations and separate database connections; the resume/job pair uniqueness constraint remains independent.

```typescript
// Kanban board (7 status columns: saved | applied | no_response |
// response | interview | accepted | rejected)
listApplications() → ApplicationListResponse        // { columns: Record<status, Application[]> }
createApplication(payload: ManualApplicationCreate) → Application   // manual add from a pasted JD
getApplicationDetail(id: string) → ApplicationDetail               // embedded JD + applied resume (resume null if deleted)
updateApplication(id: string, payload: ApplicationUpdate) → Application   // status/position/notes/company/role/applied_at

// Bulk
bulkUpdateStatus(applicationIds: string[], status: ApplicationStatus) → ApplicationActionResponse
deleteApplication(id: string) → void
bulkDeleteApplications(applicationIds: string[]) → ApplicationActionResponse
```

## Config Operations (`lib/api/config.ts`)

```typescript
fetchLlmConfig() → LLMConfig
updateLlmConfig(config: LLMConfigUpdate) → LLMConfig
testLlmConnection() → LLMHealthCheck
fetchSystemStatus() → SystemStatus

// Per-provider API keys (encrypted server-side; switching the active
// provider no longer wipes another provider's key — responses always masked)
fetchApiKeyStatus() → ApiKeyStatusResponse           // { providers: [{ provider, configured, masked_key }] }
updateApiKeys(keys: ApiKeysUpdateRequest) → ApiKeysUpdateResponse
deleteApiKey(provider: ApiKeyProvider) → void
clearAllApiKeys() → void

// Feature flags
fetchFeatureConfig() → FeatureConfig
updateFeatureConfig(config: FeatureConfigUpdate) → FeatureConfig

// Language
fetchLanguageConfig() → LanguageConfig
updateLanguageConfig(language: string) → LanguageConfig
```

> `updateLlmApiKey` (`PUT /config/llm-api-key`) no longer persists a key — keys are managed per-provider via the encrypted `/config/api-keys` endpoints above.

## Provider Info

```typescript
export const PROVIDER_INFO = {
  openai: {
    name: 'OpenAI',
    defaultModel: 'gpt-5-nano-2025-08-07',
    requiresKey: true,
  },
  anthropic: {
    name: 'Anthropic',
    defaultModel: 'claude-haiku-4-5-20251001',
    requiresKey: true,
  },
  openrouter: {
    name: 'OpenRouter',
    defaultModel: 'deepseek/deepseek-chat',
    requiresKey: true,
  },
  gemini: {
    name: 'Google Gemini',
    defaultModel: 'gemini-3-flash-preview',
    requiresKey: true,
  },
  deepseek: {
    name: 'DeepSeek',
    defaultModel: 'deepseek-chat',
    requiresKey: true,
  },
  ollama: {
    name: 'Ollama (Local)',
    defaultModel: 'gemma3:4b',
    requiresKey: false,
  },
};
```

## Usage

```typescript
import { fetchResume, API_BASE, PROVIDER_INFO } from '@/lib/api';
```

Legacy `.doc` (OLE2 binary Word) files pass compound-file header validation. MarkItDown has no OLE2 Word converter, so the parser then falls back to a **local conversion tool**: headless LibreOffice (`soffice`/`libreoffice` on `PATH`, or `/Applications/LibreOffice.app/.../soffice` on macOS), then the macOS built-in `textutil`. Conversion is bounded (60s, worker thread, no shell). When no converter backend is installed (e.g. Linux without LibreOffice) or conversion fails/times out, the endpoint returns a specific actionable **422** telling the user to re-save the file as PDF or DOCX; structurally invalid containers still return the generic parse 422. The Docker image does not bundle LibreOffice, so server deployments should expect the re-save 422 for legacy `.doc`.

## Refinement and monitoring statistics

`refinement_stats.passes_attempted` counts attempted refinement stages. `passes_completed` counts stages that changed content; a failed or unchanged keyword injection no longer counts as completed. `keywords_eligible` counts missing source-supported candidates before injection, while `keywords_injected` counts those actually present in the final result. `alignment_violations_fixed` counts critical violations resolved by the local correction pass. Preview and legacy improve responses share the same statistics model and conversion.

Preview error logs identify the stage actually running, including cancellation and timeout. Client messages keep the existing generic error boundary. The opt-in monitor records monotonic elapsed milliseconds and explicit skipped/error/cancelled outcomes; see its [run and isolation contract](../../../apps/backend/e2e_monitor/README.md). These counters and heuristic scores do not claim commercial ATS accuracy.
