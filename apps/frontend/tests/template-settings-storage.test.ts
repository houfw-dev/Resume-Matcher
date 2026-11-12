import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_TEMPLATE_SETTINGS, type TemplateSettings } from '@/lib/types/template-settings';
import {
  RESUME_TEMPLATE_SETTINGS_PREFIX,
  TEMPLATE_SETTINGS_STORAGE_KEY,
  getResumeTemplateSettingsStorageKey,
  loadScopedTemplateSettings,
  loadTemplateSettings,
  sanitizeTemplateSettings,
  storeScopedTemplateSettings,
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

describe('per-resume scoped template settings', () => {
  const withTemplate = (template: TemplateSettings['template']): TemplateSettings => ({
    ...DEFAULT_TEMPLATE_SETTINGS,
    template,
  });

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('builds a namespaced per-resume key, never the bare global key', () => {
    const key = getResumeTemplateSettingsStorageKey('resume-xyz');
    expect(key).toBe(`${RESUME_TEMPLATE_SETTINGS_PREFIX}resume-xyz`);
    expect(key.startsWith(TEMPLATE_SETTINGS_STORAGE_KEY)).toBe(true);
    expect(key).not.toBe(TEMPLATE_SETTINGS_STORAGE_KEY);
  });

  it('isolates two resumes: writing one never changes the other or the global key', () => {
    storeTemplateSettings(withTemplate('clean'));
    storeScopedTemplateSettings('resume-1', withTemplate('modern'));
    storeScopedTemplateSettings('resume-2', withTemplate('latex'));

    expect(loadScopedTemplateSettings('resume-1').template).toBe('modern');
    expect(loadScopedTemplateSettings('resume-2').template).toBe('latex');
    // The legacy global choice is untouched by scoped writes.
    expect(loadTemplateSettings().template).toBe('clean');
  });

  it('inherits the global choice once when a resume has no scoped settings yet', () => {
    storeTemplateSettings(withTemplate('vivid'));
    expect(loadScopedTemplateSettings('resume-fresh').template).toBe('vivid');
    // And still resolves to defaults (not a thrown error) when nothing exists.
    localStorage.clear();
    expect(loadScopedTemplateSettings('resume-fresh')).toEqual(DEFAULT_TEMPLATE_SETTINGS);
  });

  it('routes no-id / empty-id / malformed-id sessions to the global key', () => {
    for (const badId of [null, undefined, '', '../escape', 'resume id', 'a'.repeat(129)]) {
      storeTemplateSettings(withTemplate('clean'));
      // A rejected scope reads exactly the global choice.
      expect(loadScopedTemplateSettings(badId).template).toBe(loadTemplateSettings().template);
      storeScopedTemplateSettings(badId, withTemplate('vivid'));
      // Every rejected id writes the GLOBAL key, never an injected key.
      expect(loadTemplateSettings().template).toBe('vivid');
      expect(localStorage.length).toBe(1);
      expect(localStorage.getItem(TEMPLATE_SETTINGS_STORAGE_KEY)).not.toBeNull();
    }
  });

  it('falls back to defaults when the scoped JSON is corrupt', () => {
    localStorage.setItem(getResumeTemplateSettingsStorageKey('resume-1'), '{broken');
    expect(loadScopedTemplateSettings('resume-1')).toEqual(DEFAULT_TEMPLATE_SETTINGS);
  });

  it('sanitizes malformed scoped fields field by field', () => {
    localStorage.setItem(
      getResumeTemplateSettingsStorageKey('resume-1'),
      JSON.stringify({ template: 'nope', pageSize: 'A3', compactMode: true })
    );
    const settings = loadScopedTemplateSettings('resume-1');
    expect(settings.template).toBe(DEFAULT_TEMPLATE_SETTINGS.template);
    expect(settings.pageSize).toBe(DEFAULT_TEMPLATE_SETTINGS.pageSize);
    expect(settings.compactMode).toBe(true);
  });

  it('never throws when storage access is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(loadScopedTemplateSettings('resume-1')).toEqual(DEFAULT_TEMPLATE_SETTINGS);

    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(storeScopedTemplateSettings('resume-1', DEFAULT_TEMPLATE_SETTINGS)).toBe(false);
  });
});
