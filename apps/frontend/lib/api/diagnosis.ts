/**
 * Resume diagnosis API client (rubric V4, checklist edition:
 * 22 items / 7 dimensions / 1 red line, no score; per-role competency models
 * such as the Java P3–P8 level matrix fill the 专业能力 items 18–22 with
 * role-specific standards when matched or picked). Item 17 requires a target
 * JD; items 18–22 independently require a resolved level model (clear target
 * intention) but no JD. Payloads expose only the public `topic` label per
 * item — criteria and QC guidance stay server-side.
 */
import { apiFetch, apiPost } from './client';
import type { TemplateSettings } from '@/lib/types/template-settings';
import type { RenderedLayout } from '@/lib/types/rendered-layout';

export type DiagnosisRating = 'conform' | 'partial' | 'nonconform' | 'na';
export type DiagnosisSeverity = 'redline' | 'normal';

export interface RatingCounts {
  conform: number;
  partial: number;
  nonconform: number;
  na: number;
  /** conform + partial + nonconform (na excluded) */
  effective: number;
}

export interface DiagnosisItem {
  id: number;
  dimension: string;
  dimension_name: string;
  sub_dimension: string;
  /** Short public problem-location label (module/topic). No rule standards. */
  topic: string;
  severity: DiagnosisSeverity;
  judgment_method: 'objective' | 'subjective';
  rating: DiagnosisRating;
  evidence: string;
  suggestion: string;
}

export interface DiagnosisDimension {
  key: string;
  name: string;
  counts: RatingCounts;
}

export interface RedLineStatus {
  id: number;
  topic: string;
  passed: boolean;
  rating: DiagnosisRating;
  evidence: string;
  suggestion: string;
}

export interface CompetencyModelInfo {
  key: string;
  name: string;
}

/** One selectable model in the catalog picker (e.g. one Java P-level). */
export interface CompetencyModelOption {
  key: string;
  name: string;
  family: string;
  level: string;
}

export interface CompetencyCatalog {
  models: CompetencyModelOption[];
  /** Model the server auto-matched for the queried title; null without a match. */
  matched_key: string | null;
}

export interface DiagnosisReport {
  resume_id: string;
  spec_version: string;
  language: string;
  target_title: string | null;
  competency_model: CompetencyModelInfo | null;
  counts: RatingCounts;
  redline_passed: boolean;
  failed_redline_ids: number[];
  dimensions: DiagnosisDimension[];
  redlines: RedLineStatus[];
  items: DiagnosisItem[];
  warnings: string[];
}

export interface DiagnoseOptions {
  /** Optional target JD; without it the JD-fit items come back rated na. */
  jobDescription?: string;
  /**
   * Explicit diagnosis target title (求职意向). Sent when the resume lists
   * multiple intentions and the user picked one; the backend otherwise
   * defaults to personalInfo.title.
   */
  targetTitle?: string;
  /**
   * Explicit competency-model choice (picker confirmation). Null/omitted:
   * the backend auto-matches the model by target title and runs the base
   * rubric when nothing matches.
   */
  competencyModelKey?: string | null;
  /**
   * The builder's current template/typography choice, plus its offscreen
   * measured render. When present, the objective length/density checks judge
   * against real pagination for THIS template instead of the text-only
   * estimates. Omitted together (measurement failed / old client) and the
   * backend keeps its legacy estimate path.
   */
  templateSettings?: TemplateSettings;
  renderedLayout?: RenderedLayout;
}

/**
 * Run the V4 diagnosis. The semantic items require an LLM call, so this can
 * take a while — use the long default timeout (matches backend 240s limit).
 */
export async function diagnoseResume(
  resumeId: string,
  options?: DiagnoseOptions
): Promise<DiagnosisReport> {
  const jobDescription = options?.jobDescription?.trim();
  const targetTitle = options?.targetTitle?.trim();
  const competencyModelKey = options?.competencyModelKey?.trim();
  const body: Record<string, unknown> = {
    job_description: jobDescription ? jobDescription : null,
    target_title: targetTitle ? targetTitle : null,
    // Omitted when the user never touched the picker: backend auto-matches by
    // title. Explicit values (a model key or NONE_COMPETENCY_MODEL_KEY) win.
    competency_model_key: competencyModelKey ? competencyModelKey : null,
  };
  // Only ship the pair together; a layout without the settings it was
  // rendered with is rejected server-side anyway.
  if (options?.templateSettings && options?.renderedLayout) {
    body.template_settings = options.templateSettings;
    body.rendered_layout = options.renderedLayout;
  }
  const res = await apiPost(`/resumes/${encodeURIComponent(resumeId)}/diagnose`, body);

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to diagnose resume (status ${res.status}).`);
  }

  return res.json();
}

/**
 * Fetch the shipped competency-model catalog plus the server-side auto-match
 * for a target title. The picker calls this on open and whenever the selected
 * target title changes, so title-to-level regexes stay server-side.
 */
export async function fetchCompetencyModels(title?: string): Promise<CompetencyCatalog> {
  const trimmed = title?.trim();
  const query = trimmed ? `?title=${encodeURIComponent(trimmed)}` : '';
  const res = await apiFetch(`/diagnosis/competency-models${query}`);

  if (!res.ok) {
    throw new Error(`Failed to load competency models (status ${res.status}).`);
  }

  return res.json();
}

/**
 * Render an already-computed report into a Word document on the backend.
 * No LLM call — the endpoint only serializes the posted report, so it is fast.
 */
export async function exportDiagnosisDocx(
  resumeId: string,
  report: DiagnosisReport
): Promise<Blob> {
  const res = await apiPost(`/resumes/${encodeURIComponent(resumeId)}/diagnose/document`, report);

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to export diagnosis (status ${res.status}).`);
  }

  return res.blob();
}
