/**
 * Settings page section navigation (RetroTabs + hash anchors).
 *
 * Framework-free so the whitelist, hash parsing and scroll-spy decision can be
 * unit-tested without a DOM. The settings page owns the actual DOM wiring
 * (scrollIntoView, scroll/hashchange listeners).
 */

export const SETTINGS_SECTION_IDS = ['status', 'llm', 'content', 'language', 'danger'] as const;

export type SettingsSectionId = (typeof SETTINGS_SECTION_IDS)[number];

export interface SettingsSectionDef {
  id: SettingsSectionId;
  /** i18n key resolved by the settings page via t(). */
  labelKey: string;
}

/** Tab order doubles as the scroll-spy section order (top → bottom). */
export const SETTINGS_SECTIONS: ReadonlyArray<SettingsSectionDef> = [
  { id: 'status', labelKey: 'settings.systemStatus.title' },
  { id: 'llm', labelKey: 'settings.llmConfigurationTitle' },
  { id: 'content', labelKey: 'settings.contentGeneration.title' },
  { id: 'language', labelKey: 'settings.nav.language' },
  { id: 'danger', labelKey: 'settings.dangerZone' },
];

const SECTION_ID_SET: ReadonlySet<string> = new Set(SETTINGS_SECTION_IDS);

export const SETTINGS_ANCHOR_PREFIX = 'settings-section-';

export function isSettingsSectionId(value: string): value is SettingsSectionId {
  return SECTION_ID_SET.has(value);
}

export function sectionAnchorId(id: SettingsSectionId): string {
  return `${SETTINGS_ANCHOR_PREFIX}${id}`;
}

export function buildSectionHash(id: SettingsSectionId): string {
  return `#${id}`;
}

/**
 * Parse a location.hash-style value (with or without the leading '#').
 * Unknown/empty/URL-like values resolve to null so a crafted hash can never
 * drive an arbitrary element id into getElementById.
 */
export function parseSectionHash(hash: string | null | undefined): SettingsSectionId | null {
  if (!hash) return null;
  // Trim before stripping '#' — otherwise leading whitespace defeats the check.
  const trimmed = hash.trim();
  const raw = trimmed.startsWith('#') ? trimmed.slice(1) : trimmed;
  const decoded = (() => {
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  })();
  const id = decoded.trim();
  return id && isSettingsSectionId(id) ? id : null;
}

export interface SectionOffset {
  id: string;
  /** Viewport-relative top offset (getBoundingClientRect().top). */
  top: number;
}

/**
 * Pure scroll-spy: given each section's viewport-relative top, the active
 * section is the LAST one already scrolled under the sticky-nav band
 * (`top <= offset`). Sections above the band (negative top) stay eligible, so
 * the last section remains active at the page bottom. Returns null when no
 * section qualifies — the caller keeps the default (first tab).
 */
export function pickActiveSection(
  sectionTops: ReadonlyArray<SectionOffset>,
  offset: number
): string | null {
  let active: string | null = null;
  for (const section of sectionTops) {
    if (section.top <= offset) active = section.id;
    else break;
  }
  return active;
}
