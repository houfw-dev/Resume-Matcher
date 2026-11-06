/**
 * Label-region spans inside one work/project description entry.
 *
 * Frontend mirror of app/services/description_regions.py — the two sides
 * share a parity test fixture matrix (tests/description-regions.test.ts vs
 * apps/backend/tests/unit/test_description_regions.py). Keep them in sync.
 *
 * A region is the set of content rows owned by a label heading
 * ("项目亮点：" → the rows until the next heading); the label row itself is
 * excluded. Fine-tune region tokens (project_2:highlights) edit only those
 * rows. Projects canonicalize label aliases; work labels are recognized from
 * a curated list but never renamed.
 */

import {
  canonicalProjectLabelCore,
  isKnownSubLabel,
  looksLikeSubLabel,
  stripPointMarker,
  type DescriptionRowStyle,
} from '@/components/resume/list-format';

export type RegionEntryKind = 'work' | 'project';

export const REGION_TECH_STACK = 'techStack';
export const REGION_BACKGROUND = 'background';
export const REGION_DUTIES = 'duties';
export const REGION_HIGHLIGHTS = 'highlights';
export const REGION_ACHIEVEMENTS = 'achievements';
export const REGION_ROLE = 'role';

export const REGION_IDS = [
  REGION_TECH_STACK,
  REGION_BACKGROUND,
  REGION_DUTIES,
  REGION_HIGHLIGHTS,
  REGION_ACHIEVEMENTS,
  REGION_ROLE,
] as const;

export type RegionId = (typeof REGION_IDS)[number];

const PROJECT_REGION_IDS: Record<string, RegionId> = {
  技术栈: REGION_TECH_STACK,
  项目背景: REGION_BACKGROUND,
  项目职责: REGION_DUTIES,
  项目亮点: REGION_HIGHLIGHTS,
};

// Work labels are free-form and never renamed; curated cores map to a region
// id verbatim. Mirrors _WORK_REGION_IDS in the backend.
const WORK_REGION_IDS: Record<string, RegionId> = {
  技术栈: REGION_TECH_STACK,
  技术列表: REGION_TECH_STACK,
  技术选型: REGION_TECH_STACK,
  所用技术: REGION_TECH_STACK,
  技术清单: REGION_TECH_STACK,
  技术架构: REGION_TECH_STACK,
  系统架构: REGION_TECH_STACK,
  工作职责: REGION_DUTIES,
  工作内容: REGION_DUTIES,
  主要职责: REGION_DUTIES,
  核心职责: REGION_DUTIES,
  责任描述: REGION_DUTIES,
  负责内容: REGION_DUTIES,
  核心工作: REGION_DUTIES,
  // Combined duty + result headings ("项目职责与成果：") are duty regions;
  // project sites resolve them through canonicalProjectLabelCore instead.
  项目职责与成果: REGION_DUTIES,
  项目职责和成果: REGION_DUTIES,
  项目职责及成果: REGION_DUTIES,
  工作职责与成果: REGION_DUTIES,
  工作职责和成果: REGION_DUTIES,
  工作职责及成果: REGION_DUTIES,
  职责与成果: REGION_DUTIES,
  职责和成果: REGION_DUTIES,
  职责及成果: REGION_DUTIES,
  工作业绩: REGION_ACHIEVEMENTS,
  项目业绩: REGION_ACHIEVEMENTS,
  主要成果: REGION_ACHIEVEMENTS,
  核心成果: REGION_ACHIEVEMENTS,
  工作成果: REGION_ACHIEVEMENTS,
  项目角色: REGION_ROLE,
  担任角色: REGION_ROLE,
};

export interface LabelRegion {
  regionId: RegionId;
  /** Row index of the label heading itself (never overlaid by fine-tune). */
  labelIndex: number;
  /** Content row indices owned by the label, until the next separator. */
  contentIndices: number[];
  /** Stored label text, e.g. "项目亮点：". */
  labelText: string;
}

interface RegionEntryShape {
  description?: unknown;
  descriptionStyles?: unknown;
}

const VALID_STYLES = new Set<DescriptionRowStyle>(['bullet', 'plain', 'label']);

function alignedStyle(styles: unknown, index: number): DescriptionRowStyle {
  if (Array.isArray(styles) && index < styles.length) {
    const style = styles[index];
    if (typeof style === 'string' && VALID_STYLES.has(style as DescriptionRowStyle)) {
      return style as DescriptionRowStyle;
    }
  }
  return 'bullet';
}

/**
 * Heading test mirroring the backend: only label/plain rows can be headings;
 * a curated label name is a heading with or without a trailing colon, any
 * other heading must be a short standalone colon-terminated title. Returns
 * the row's label core or null.
 */
function headingCore(row: unknown, style: DescriptionRowStyle): string | null {
  if ((style !== 'label' && style !== 'plain') || typeof row !== 'string') return null;
  const text = stripPointMarker(row).trim();
  if (!text) return null;
  const endsWithColon = /[：:]\s*$/u.test(text);
  const core = text.replace(/[：:]\s*$/u, '').trim();
  if (isKnownSubLabel(row)) return core;
  if (!endsWithColon) return null;
  // For an unknown row looksLikeSubLabel is exactly the standalone-heading
  // test (short colon title, no sentence punctuation).
  return looksLikeSubLabel(row) ? core : null;
}

/**
 * Partition an entry's rows into selectable label regions. Boundary rules
 * mirror buildDescriptionBlocks render semantics — see the backend module.
 */
export function extractEntryRegions(
  kind: RegionEntryKind,
  entry: RegionEntryShape | null | undefined
): LabelRegion[] {
  const description = entry?.description;
  if (!Array.isArray(description)) return [];
  const styles = entry?.descriptionStyles;

  const regions: LabelRegion[] = [];
  let openRegion: LabelRegion | null = null;
  // Nested numbered heads exist only inside a project duty/highlight region.
  let inBulletRegion = false;

  const regionIdFor = (core: string): RegionId | null => {
    if (kind === 'project') {
      return PROJECT_REGION_IDS[canonicalProjectLabelCore(core)] ?? null;
    }
    return WORK_REGION_IDS[core] ?? null;
  };

  description.forEach((row, index) => {
    if (typeof row !== 'string') return;
    const style = alignedStyle(styles, index);
    const core = headingCore(row, style);
    if (core !== null) {
      const regionId = regionIdFor(core);
      if (regionId !== null) {
        openRegion = {
          regionId,
          labelIndex: index,
          contentIndices: [],
          labelText: row.trim(),
        };
        regions.push(openRegion);
        inBulletRegion =
          kind === 'project' && (regionId === REGION_DUTIES || regionId === REGION_HIGHLIGHTS);
        return;
      }
      const known = isKnownSubLabel(row);
      if (kind === 'project' && inBulletRegion && !known) {
        // Nested numbered point head inside duties/highlights: part of the
        // open region, as are its detail rows.
      } else {
        // Unmapped heading: close the region; its own rows are frozen.
        openRegion = null;
        inBulletRegion = false;
        return;
      }
    }
    if (openRegion !== null) {
      openRegion.contentIndices.push(index);
    }
  });

  return regions;
}

/**
 * Merge same-id regions (two duty blocks) into one span union; first label
 * occurrence provides labelIndex/labelText.
 */
export function mergedEntryRegions(
  kind: RegionEntryKind,
  entry: RegionEntryShape | null | undefined
): Map<RegionId, LabelRegion> {
  const merged = new Map<RegionId, LabelRegion>();
  for (const region of extractEntryRegions(kind, entry)) {
    const existing = merged.get(region.regionId);
    if (existing === undefined) {
      merged.set(region.regionId, region);
      continue;
    }
    merged.set(region.regionId, {
      regionId: region.regionId,
      labelIndex: existing.labelIndex,
      contentIndices: Array.from(
        new Set([...existing.contentIndices, ...region.contentIndices])
      ).sort((a, b) => a - b),
      labelText: existing.labelText,
    });
  }
  return merged;
}
