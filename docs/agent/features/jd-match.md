# JD Match Feature

> **Shows how well a tailored resume matches the original job description.**

## Overview

The Resume Builder includes a "JD Match" tab that shows how well a tailored resume matches the original job description.

## How It Works

1. User tailors a resume against a job description
2. Opens the tailored resume in the Builder
3. "JD MATCH" tab appears (only for tailored resumes)
4. Shows side-by-side comparison:
   - **Left panel**: Original job description (read-only)
   - **Right panel**: Resume with matching keywords highlighted in yellow

## Features

- **Keyword extraction**: Extracts significant keywords from JD (filters common stop words)
- **Case-insensitive matching**: Matches keywords regardless of case
- **Match statistics**: Shows total keywords, matches found, and match percentage
- **Color-coded percentage**: Green (≥50%), yellow (≥30%), red (<30%)
- **PDF export**: Download button on the JD Match tab renders the same stats and
  highlights through the server component `app/print/jd-match/[id]/page.tsx`
  (headless Chromium, selector `.jd-match-print`). Standalone resumes get 404 —
  without a stored job there is nothing to match.

## Key Files

| File | Purpose |
|------|---------|
| `apps/frontend/lib/utils/keyword-matcher.ts` | Keyword extraction and matching utilities (shared by tab and print page) |
| `apps/frontend/components/builder/jd-comparison-view.tsx` | Main split-view component |
| `apps/frontend/components/builder/jd-display.tsx` | Read-only JD display |
| `apps/frontend/components/builder/highlighted-resume-view.tsx` | Resume with keyword highlighting |
| `apps/frontend/app/print/jd-match/[id]/page.tsx` | Server-rendered print page for the PDF export |
| `apps/backend/app/routers/resumes.py` | `GET /{resume_id}/job-description` and `GET /{resume_id}/jd-match/pdf` endpoints |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /resumes/{resume_id}/job-description` | Fetch JD used to tailor a resume |
| `GET /resumes/{resume_id}/jd-match/pdf?pageSize=A4\|LETTER[&lang=]` | Export the comparison as PDF (tailored resumes only; 404 otherwise, 503 on render failure) |
