import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_TEMPLATE_SETTINGS, type TemplateSettings } from '@/lib/types/template-settings';
import {
  TEMPLATE_SETTINGS_STORAGE_KEY,
  loadTemplateSettings,
  sanitizeTemplateSettings,
  storeTemplateSettings,
} from '@/lib/utils/template-settings-storage';

describe('sanitizeTemplateSettings', () => {
  it('returns fresh defaults for non-object input', () => {
    const settings = sanitizeTemplateSettings('nope');
    expect(settings).toEqual(DEFAULT_TEMPLATE_SETTINGS);
    // Fresh nested objects — never a shared reference.
    expect(settings.margins).not.toBe(DEFAULT_TEMPLATE_SETTINGS.margins);
    expect(settings).toEqual(sanitizeTemplateSettings(null));
  });

  it('deep-merges valid fields onto defaults', () => {
    const settings = sanitizeTemplateSettings({
      template: 'vivid',
      pageSize: 'LETTER',
      margins: { top: 20, left: 8 },
      compactMode: true,
    });
    expect(settings.template).toBe('vivid');
    expect(settings.pageSize).toBe('LETTER');
    expect(settings.margins.top).toBe(20);
    expect(settings.margins.left).toBe(8);
    // Untouched sides keep defaults.
    expect(settings.margins.bottom).toBe(DEFAULT_TEMPLATE_SETTINGS.margins.bottom);
    expect(settings.compactMode).toBe(true);
    expect(settings.accentColor).toBe(DEFAULT_TEMPLATE_SETTINGS.accentColor);
  });

  it('rejects bad enum values field by field', () => {
    const settings = sanitizeTemplateSettings({
      template: 'not-a-template',
      pageSize: 'A3',
      accentColor: 'rainbow',
      fontSize: { headerFont: 'Comic Sans', bodyFont: 'mono' },
    });
    expect(settings.template).toBe(DEFAULT_TEMPLATE_SETTINGS.template);
    expect(settings.pageSize).toBe(DEFAULT_TEMPLATE_SETTINGS.pageSize);
    expect(settings.accentColor).toBe(DEFAULT_TEMPLATE_SETTINGS.accentColor);
    expect(settings.fontSize.headerFont).toBe(DEFAULT_TEMPLATE_SETTINGS.fontSize.headerFont);
    expect(settings.fontSize.bodyFont).toBe('mono');
  });

  it('rejects margins/levels outside range and wrong types', () => {
    const settings = sanitizeTemplateSettings({
      margins: { top: 4, bottom: 26, left: '10mm', right: 12.5 },
      spacing: { section: 0, item: 6, lineHeight: 3 },
    });
    expect(settings.margins).toEqual(DEFAULT_TEMPLATE_SETTINGS.margins);
    expect(settings.spacing.section).toBe(DEFAULT_TEMPLATE_SETTINGS.spacing.section);
    expect(settings.spacing.item).toBe(DEFAULT_TEMPLATE_SETTINGS.spacing.item);
    expect(settings.spacing.lineHeight).toBe(3);
  });

  it('rejects non-boolean flags', () => {
    const settings = sanitizeTemplateSettings({ compactMode: 'yes' });
    expect(settings.compactMode).toBe(DEFAULT_TEMPLATE_SETTINGS.compactMode);
  });
});

describe('loadTemplateSettings / storeTemplateSettings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads defaults when nothing is stored', () => {
    expect(loadTemplateSettings()).toEqual(DEFAULT_TEMPLATE_SETTINGS);
  });

  it('round-trips stored settings under the shared global key', () => {
    const settings: TemplateSettings = {
      ...DEFAULT_TEMPLATE_SETTINGS,
      template: 'modern-two-column',
      margins: { top: 15, bottom: 12, left: 15, right: 12 },
      compactMode: true,
    };
    expect(storeTemplateSettings(settings)).toBe(true);
    expect(localStorage.getItem(TEMPLATE_SETTINGS_STORAGE_KEY)).not.toBeNull();
    expect(loadTemplateSettings().template).toBe('modern-two-column');
    expect(loadTemplateSettings().compactMode).toBe(true);
  });

  it('falls back to defaults on corrupt JSON', () => {
    localStorage.setItem(TEMPLATE_SETTINGS_STORAGE_KEY, '{not json');
    expect(loadTemplateSettings()).toEqual(DEFAULT_TEMPLATE_SETTINGS);
  });

  it('never throws when storage access is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(loadTemplateSettings()).toEqual(DEFAULT_TEMPLATE_SETTINGS);

    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(storeTemplateSettings(DEFAULT_TEMPLATE_SETTINGS)).toBe(false);
  });
});
