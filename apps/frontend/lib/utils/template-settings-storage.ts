/**
 * Persisted reader/writer for the builder's template & typography settings.
 *
 * The settings live under a single global localStorage key (they are not
 * per-resume and never sync to the backend). Both the builder and the
 * diagnosis flow read the *current* choice at action time, so the viewer,
 * PDF export and diagnosis all honour what the user picked in the editor.
 *
 * Every function here is total: SSR, blocked storage and corrupt JSON all
 * fall back to {@link DEFAULT_TEMPLATE_SETTINGS} instead of throwing.
 */
import {
  DEFAULT_TEMPLATE_SETTINGS,
  type AccentColor,
  type BodyFontFamily,
  type HeaderFontFamily,
  type PageSize,
  type SpacingLevel,
  type TemplateSettings,
  type TemplateType,
} from '@/lib/types/template-settings';
import { safeStorage } from '@/lib/utils/resume-draft-storage';

export const TEMPLATE_SETTINGS_STORAGE_KEY = 'resume_builder_settings';

const TEMPLATE_TYPES: readonly TemplateType[] = [
  'swiss-single',
  'swiss-two-column',
  'modern',
  'modern-two-column',
  'latex',
  'clean',
  'vivid',
];

const PAGE_SIZES: readonly PageSize[] = ['A4', 'LETTER'];
const ACCENT_COLORS: readonly AccentColor[] = ['blue', 'green', 'orange', 'red'];
const FONT_FAMILIES: readonly HeaderFontFamily[] = ['serif', 'sans-serif', 'mono'];
const MARGIN_MIN_MM = 5;
const MARGIN_MAX_MM = 25;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pickEnum<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

/** Integer 1-5 typography level; booleans/NaN/floats/out-of-range all rejected. */
function pickLevel(value: unknown): SpacingLevel | undefined {
  if (typeof value !== 'number' || !Number.isInteger(value)) return undefined;
  return value >= 1 && value <= 5 ? (value as SpacingLevel) : undefined;
}

/** Integer margin in millimetres within the backend PDF endpoint's 5-25 range. */
function pickMargin(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isInteger(value)) return undefined;
  return value >= MARGIN_MIN_MM && value <= MARGIN_MAX_MM ? value : undefined;
}

function pickBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

/**
 * Merge an untrusted persisted/network value onto the default settings,
 * rejecting individual malformed fields (bad enum, NaN, out-of-range, wrong
 * type) while keeping every valid field. Non-object input yields defaults.
 */
export function sanitizeTemplateSettings(input: unknown): TemplateSettings {
  const defaults = DEFAULT_TEMPLATE_SETTINGS;
  if (!isRecord(input)) {
    return {
      ...defaults,
      margins: { ...defaults.margins },
      spacing: { ...defaults.spacing },
      fontSize: { ...defaults.fontSize },
    };
  }

  const margins = { ...defaults.margins };
  if (isRecord(input.margins)) {
    margins.top = pickMargin(input.margins.top) ?? margins.top;
    margins.bottom = pickMargin(input.margins.bottom) ?? margins.bottom;
    margins.left = pickMargin(input.margins.left) ?? margins.left;
    margins.right = pickMargin(input.margins.right) ?? margins.right;
  }

  const spacing = { ...defaults.spacing };
  if (isRecord(input.spacing)) {
    spacing.section = pickLevel(input.spacing.section) ?? spacing.section;
    spacing.item = pickLevel(input.spacing.item) ?? spacing.item;
    spacing.lineHeight = pickLevel(input.spacing.lineHeight) ?? spacing.lineHeight;
  }

  const fontSize = { ...defaults.fontSize };
  if (isRecord(input.fontSize)) {
    fontSize.base = pickLevel(input.fontSize.base) ?? fontSize.base;
    fontSize.headerScale = pickLevel(input.fontSize.headerScale) ?? fontSize.headerScale;
    fontSize.headerFont =
      pickEnum<HeaderFontFamily>(input.fontSize.headerFont, FONT_FAMILIES) ?? fontSize.headerFont;
    fontSize.bodyFont =
      pickEnum<BodyFontFamily>(input.fontSize.bodyFont, FONT_FAMILIES) ?? fontSize.bodyFont;
  }

  return {
    template: pickEnum<TemplateType>(input.template, TEMPLATE_TYPES) ?? defaults.template,
    pageSize: pickEnum<PageSize>(input.pageSize, PAGE_SIZES) ?? defaults.pageSize,
    margins,
    spacing,
    fontSize,
    compactMode: pickBoolean(input.compactMode) ?? defaults.compactMode,
    showContactIcons: pickBoolean(input.showContactIcons) ?? defaults.showContactIcons,
    accentColor: pickEnum<AccentColor>(input.accentColor, ACCENT_COLORS) ?? defaults.accentColor,
  };
}

function cloneDefaultSettings(): TemplateSettings {
  return {
    ...DEFAULT_TEMPLATE_SETTINGS,
    margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins },
    spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing },
    fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize },
  };
}

/** Read the current template settings from localStorage; defaults on any failure. */
export function loadTemplateSettings(): TemplateSettings {
  if (typeof window === 'undefined') return cloneDefaultSettings();
  const raw = safeStorage.get(TEMPLATE_SETTINGS_STORAGE_KEY);
  if (!raw) return cloneDefaultSettings();
  try {
    return sanitizeTemplateSettings(JSON.parse(raw));
  } catch {
    return cloneDefaultSettings();
  }
}

/** Persist template settings; returns false (never throws) when storage is blocked. */
export function storeTemplateSettings(settings: TemplateSettings): boolean {
  if (typeof window === 'undefined') return false;
  return safeStorage.set(TEMPLATE_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
}
