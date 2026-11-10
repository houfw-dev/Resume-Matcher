# API Flow Maps

> Request/response flows for all Resume Matcher endpoints.

## Resume Upload

```
POST /api/v1/resumes/upload
├── Validate file (PDF/DOCX, ≤4MB)
├── parse_document() → Markdown
├── db.create_resume(status="processing")
├── parse_resume_to_json() → LLM
│   ├── Success: status="ready"
│   └── Failure: status="failed"
└── Return {resume_id}
```

## Resume Improvement

Any **master or standalone resume** (`parent_id` NULL, `processing_status =
"ready"`, with structured data) can be the tailoring source — not just the
single master. All three entry points (`POST /resumes/improve/preview`,
`/improve/confirm`, legacy `/improve`) run `_validate_tailor_source` first and
return **400** when the source is an already-tailored resume (no nested
grandchild chains), is still processing/failed, or has no processed data. The
refinement truth baseline is the selected source itself, so keyword injection
and master-alignment are grounded in the chosen resume rather than the global
master.

```
POST /api/v1/resumes/improve[/preview | /confirm]
├── Fetch resume + job from DB
├── _validate_tailor_source(resume) → 400 on tailored/non-ready/no-data source
├── extract_job_keywords() → LLM
├── improve_resume() / diff pipeline → LLM
├── refine_resume(master_resume = selected source's structured data)
├── [If enabled] generate_cover_letter() → LLM
├── [If enabled] generate_outreach_message() → LLM
├── [If enabled] generate_interview_prep() → LLM
├── db.create_resume(improved, parent_id = source resume id)
├── db.create_improvement(original_resume_id = source resume id)
└── Return {data, cover_letter, outreach_message, interview_prep}
```

The frontend picks the source on `/tailor` (`lib/utils/tailor-source.ts`):
eligible list = `parent_id` NULL + `ready`; selection priority is `?source=`
query param (set by the "tailor from this resume" button on the resume viewer)
→ the master → the cached localStorage master id → the first eligible resume;
with no eligible resume the page redirects to `/dashboard`.

## On-Demand AI Content (any resume)

The three on-demand generation endpoints share one job-context rule
(`_resolve_generation_job_context`): tailored resumes load their stored job via
the improvement record; standalone resumes generate from the resume alone with
an empty JD.

```
POST /api/v1/resumes/{id}/generate-interview-prep
├── Fetch resume (404 if missing); require processed_data (400 otherwise)
├── parent_id set?
│   ├── Yes → improvement record (400 if missing) → job (404 if missing) → its JD
│   └── No  → job_description = ""
├── _validate_ai_sources(resume, job)
├── JD blank?
│   ├── Yes → INTERVIEW_PREP_NO_JD_PROMPT (resume + 求职意向 only)
│   └── No  → INTERVIEW_PREP_PROMPT (truncated JD; custom prompts unsupported here)
├── generate_interview_prep() → LLM JSON
├── Validate InterviewPrepData
├── Save resumes.interview_prep as serialized JSON TEXT
└── Return {interview_prep, message}
```

`POST /resumes/{id}/generate-cover-letter` and
`POST /resumes/{id}/generate-outreach` follow the same resolution rule. The
cover-letter and outreach services branch on a blank JD
(`COVER_LETTER_NO_JD_PROMPT` / `OUTREACH_NO_JD_PROMPT`, built-in templates
only); on the JD-present path custom feature-prompt overrides remain supported.
Outreach's no-JD branch skips JD size validation entirely.

## Cover Letter Generation (explicit JD, any resume)

```
POST /api/v1/resumes/{id}/cover-letter/generate  body {"job_description": str}
├── Fetch resume (404 if missing); require processed_data (400 otherwise)
├── Validate source sizes (422 when JD exceeds 100,000 chars)
├── job_description blank?
│   ├── Yes → COVER_LETTER_NO_JD_PROMPT (resume-only, no custom-prompt override)
│   └── No  → COVER_LETTER_PROMPT (custom feature prompt override supported)
├── generate_cover_letter() → LLM plain text in the content language
├── Save resumes.cover_letter (reuses PATCH update and PDF export paths)
└── Return {content, message}
```

## Content PDF Exports (stored content, no LLM)

```
GET /api/v1/resumes/{id}/{cover-letter|interview-prep|jd-match}/pdf?pageSize=&lang=
├── Fetch resume (404 if missing)
├── Cover letter / interview prep: 404 when the stored content is empty
├── JD match: standalone resume → 404 (tailored resumes only);
│   tailored → re-resolve stored job (400 missing improvement / 404 missing job)
├── Build {frontend_base_url}/print/<kind>/{id}?pageSize=…[&lang=…]
├── render_resume_pdf(selector=".cover-letter-print" |
│                     ".interview-prep-print" | ".jd-match-print")
├── PDFRenderError → 503 (details logged)
└── application/pdf, attachment filename <kind>_{id}.pdf
```

The `/print/interview-prep/[id]` and `/print/jd-match/[id]` pages are server
components like the existing print routes (never `'use client'`, no `app/api`
routes): they fetch via `API_BASE` with `cache: 'no-store'`, localize through
`translate(locale, key)`, and the JD-match page reuses the pure
`keyword-matcher` utilities so its stats/highlights match the on-screen tab.

## PDF Generation

```
GET /api/v1/resumes/{id}/pdf
├── Fetch resume from DB
├── Build URL: {frontend}/print/resumes/{id}?{params}
├── Playwright render (wait for .resume-print)
└── Return PDF bytes
```

## Health Check

```
GET /api/v1/health
└── Return {status: "healthy"}        # pure liveness — does NOT call the LLM
```

## System Status

```
GET /api/v1/status                    # each check isolated → 200 (partial/degraded), never 500
├── try: get_llm_config()
│   ├── llm_configured = api_key set OR provider ∈ {ollama, openai_compatible}
│   └── check_llm_health() → llm_healthy   # failure here degrades only this field
├── try: db.get_stats()                     # failure → empty stats, still 200
└── Return {status, llm_configured, llm_healthy, has_master_resume, database_stats}
```

## Configuration Update

```
PUT /api/v1/config/llm-api-key
├── _load_config()
├── Merge new NON-SECRET values (provider/model/base/...)
├── (no longer persists any key — keys go through /config/api-keys)
├── _save_config()
└── Return masked config
```

## API Keys (per-provider, encrypted)

```
GET /api/v1/config/api-keys
└── Return {providers: [{provider, configured, masked_key}]}   # always masked

POST /api/v1/config/api-keys
├── For each provided provider key:
│   └── Fernet-encrypt → upsert into SQLite `api_keys` table   # other providers' keys untouched
└── Return {message, updated_providers}

DELETE /api/v1/config/api-keys/{provider}      # remove one provider's key
DELETE /api/v1/config/api-keys?confirm=...     # clear all keys
```

## Job Upload

```
POST /api/v1/jobs/upload
├── For each description:
│   └── db.create_job()
└── Return {job_id[]}
```

## Resume Operations

| Endpoint | Flow |
|----------|------|
| `GET /resumes?id=` | db.get_resume() |
| `GET /resumes/list` | db.list_resumes() |
| `PATCH /resumes/{id}` | db.update_resume() |
| `DELETE /resumes/{id}` | db.delete_resume() |

## Application Tracker

```
GET /api/v1/applications[?resume_id=<id>]
├── db.list_applications(resume_id=...)   # optional filter: resume_id OR master_resume_id match
└── Return {columns}        # grouped by the 7 status keys (all present):
                            #   saved/applied/no_response/response/interview/accepted/rejected

POST /api/v1/applications   # manual add from a pasted JD
├── db.create_job(jd)
├── [If company/role missing] extract_job_keywords() → LLM   # one best-effort call
├── db.create_application(status default "applied")          # dedupes on (job_id, resume_id)
└── Return Application

GET /api/v1/applications/{id}
├── db.get_application() + embed job_content + applied resume
└── Return {..., job_content, resume}    # resume: null if it was deleted
```

| Endpoint | Flow |
|----------|------|
| `PATCH /applications/{id}` | db.update_application() — status/position/notes/company/role/applied_at; server renumbers `position` |
| `PATCH /applications/bulk` | db.bulk_update_status() — move many cards to one column |
| `DELETE /applications/{id}` | db.delete_application() |
| `POST /applications/bulk-delete` | db.bulk_delete_applications() |

> **Auto-create:** `POST /resumes/improve/confirm` (and legacy `POST /resumes/improve`) create an `applied` card after persisting the tailored resume — best-effort (a tracker failure never breaks tailoring); company/role reuse the cached keyword extraction, so no extra LLM call.
