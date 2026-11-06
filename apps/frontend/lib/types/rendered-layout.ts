/**
 * Rendered-layout snapshot — the result of really rendering a resume with the
 * builder's chosen {@link TemplateSettings} in an offscreen A4/Letter viewport.
 *
 * The frontend measures this right before running a diagnosis and uploads it
 * alongside the request. The backend then judges appearance items (#1 density,
 * #2 length) against measured reality instead of the legacy chars-per-line /
 * chars-per-page estimates, and gives the LLM a per-page text mirror as the
 * ground truth for layout questions.
 */
import type { MarginSettings, PageSize, TemplateType } from '@/lib/types/template-settings';

export const RENDERED_LAYOUT_SCHEMA_VERSION = 1;

/**
 * Stable address of a measured text point inside the structured resume.
 * Mirrors the backend `_iter_text_blocks` enumeration in diagnosis_checks.py:
 * summary; work/project description points (after splitting on \n); custom
 * text sections and custom item descriptions.
 */
export type LayoutLocator =
  | { kind: 'summary'; point_index: number }
  | {
      kind: 'entry';
      section: 'workExperience' | 'personalProjects';
      entry_index: number;
      point_index: number;
    }
  | { kind: 'custom_text'; key: string; point_index: number }
  | {
      kind: 'custom_item';
      key: string;
      entry_index: number;
      point_index: number;
    };

export interface LayoutPoint {
  locator: LayoutLocator;
  /** Human location assembled from rendered headings, e.g. 工作经历 / 某公司 / 工程师. */
  location: string;
  /** Point text (trimmed, capped) for backend cross-checking/evidence. */
  text: string;
  /** Character count of the rendered point (markers/emphasis stripped). */
  chars: number;
  /** Visual lines the point occupies after real wrapping (Range row clusters). */
  visual_lines: number;
  height_px: number;
  /** 1-based page the point starts on. */
  page: number;
}

export interface LayoutSection {
  /** Canonical section key (personalInfo/summary/workExperience/… or custom key). */
  key: string;
  /** Rendered display title. */
  title: string;
  visible: boolean;
  /** 0-based visual order. */
  index: number;
  height_px: number;
  /** 1-based pages the section touches. */
  pages: number[];
}

export interface LayoutHeaderRow {
  /** Number of fact cells rendered on this row of the header grid. */
  cells: number;
}

export interface LayoutHeader {
  height_px: number;
  cell_count: number;
  rows: LayoutHeaderRow[];
}

export interface LayoutPageMirror {
  page: number;
  /** Plain-text mirror of the page in real reading order (block-level). */
  text: string;
}

export interface RenderedLayout {
  schema_version: typeof RENDERED_LAYOUT_SCHEMA_VERSION;
  /** ISO timestamp; diagnostics only. */
  measured_at: string;
  template: TemplateType;
  page_size: PageSize;
  /** Logical margins the user chose (the offscreen render itself used 0). */
  margins: MarginSettings;
  content_width_px: number;
  content_height_px: number;
  page_count: number;
  total_height_px: number;
  two_column: boolean;
  header: LayoutHeader;
  sections: LayoutSection[];
  points: LayoutPoint[];
  page_mirror: LayoutPageMirror[];
  /** Client-side notes (truncation etc.); the backend never echoes these. */
  warnings: string[];
}

/** Hard caps keep the uploaded snapshot small; mirrors the Pydantic bounds. */
export const LAYOUT_LIMITS = {
  maxPages: 12,
  maxSections: 40,
  maxPoints: 300,
  pointText: 120,
  locationText: 120,
  pageText: 6000,
  maxWarnings: 20,
  /** Whole JSON payload ceiling (UTF-8 bytes). */
  payloadBytes: 48_000,
} as const;
