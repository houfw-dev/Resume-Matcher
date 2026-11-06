/**
 * API client for job-less resume fine-tuning.
 *
 * Fine-tuning reorganizes the parsed resume using BOTH the structured data
 * and the original upload text as evidence, then previews the result before
 * the user chooses to overwrite the source or save it as a copy.
 */

import { apiPost } from './client';
import type { ResumeData } from '@/components/dashboard/resume-component';

export type FineTuneKind = 'all' | 'modules';
export type FineTuneMode = 'overwrite' | 'copy';

export interface FineTuneScope {
  kind: FineTuneKind;
  targets: string[];
}

export interface FineTunePreviewRequest {
  scope: FineTuneScope;
  instruction?: string;
  output_language?: string;
}

export type FineTuneFieldType =
  | 'skill'
  | 'description'
  | 'summary'
  | 'certification'
  | 'experience'
  | 'education'
  | 'project'
  | 'language'
  | 'award';

export type FineTuneChangeType = 'added' | 'removed' | 'modified';

export interface FineTuneFieldDiff {
  field_path: string;
  field_type: FineTuneFieldType;
  change_type: FineTuneChangeType;
  original_value: string | null;
  new_value: string | null;
  confidence: 'low' | 'medium' | 'high';
}

export interface FineTuneDiffSummary {
  total_changes: number;
  skills_added: number;
  skills_removed: number;
  descriptions_modified: number;
  certifications_added: number;
  high_risk_changes: number;
}

export interface FineTunePreviewResponse {
  preview_id: string;
  expires_at: string | null;
  scope: FineTuneScope;
  improved_data: ResumeData;
  diff_summary: FineTuneDiffSummary | null;
  detailed_changes: FineTuneFieldDiff[];
  warnings: string[];
}

export interface FineTuneConfirmRequest {
  preview_id: string;
  improved_data: ResumeData;
  mode: FineTuneMode;
  title?: string | null;
}

export interface FineTuneConfirmResponse {
  resume_id: string;
  mode: FineTuneMode;
  title: string | null;
}

async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  return data.detail || `${fallback} (status ${res.status}).`;
}

/** Generate a fine-tuned preview (preview row is registered server-side). */
export async function previewFineTune(
  resumeId: string,
  body: FineTunePreviewRequest
): Promise<FineTunePreviewResponse> {
  const res = await apiPost(`/resumes/${resumeId}/fine-tune/preview`, body);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to fine-tune resume'));
  }
  return res.json();
}

/** Confirm a previewed fine-tune, overwriting the source or saving a copy. */
export async function confirmFineTune(
  resumeId: string,
  body: FineTuneConfirmRequest
): Promise<FineTuneConfirmResponse> {
  const res = await apiPost(`/resumes/${resumeId}/fine-tune/confirm`, body);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to save fine-tuned resume'));
  }
  return res.json();
}
