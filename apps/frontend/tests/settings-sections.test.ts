import { describe, expect, it } from 'vitest';
import {
  SETTINGS_ANCHOR_PREFIX,
  SETTINGS_SECTIONS,
  SETTINGS_SECTION_IDS,
  buildSectionHash,
  isSettingsSectionId,
  parseSectionHash,
  pickActiveSection,
  sectionAnchorId,
} from '@/lib/utils/settings-sections';

describe('settings section whitelist', () => {
  it('exposes the five fixed sections in tab order', () => {
    expect(SETTINGS_SECTION_IDS).toEqual(['status', 'llm', 'content', 'language', 'danger']);
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([...SETTINGS_SECTION_IDS]);
    expect(SETTINGS_SECTIONS.every((s) => typeof s.labelKey === 'string')).toBe(true);
  });

  it('type-guards only whitelisted ids', () => {
    expect(isSettingsSectionId('llm')).toBe(true);
    expect(isSettingsSectionId('danger')).toBe(true);
    expect(isSettingsSectionId('')).toBe(false);
    expect(isSettingsSectionId('STATUS')).toBe(false);
    expect(isSettingsSectionId('llm "onclick="alert(1)')).toBe(false);
    expect(isSettingsSectionId('javascript:alert(1)')).toBe(false);
  });

  it('builds prefixed anchor ids and hashes', () => {
    expect(sectionAnchorId('status')).toBe(`${SETTINGS_ANCHOR_PREFIX}status`);
    expect(buildSectionHash('danger')).toBe('#danger');
  });
});

describe('parseSectionHash', () => {
  it('accepts hashes with or without the leading #', () => {
    expect(parseSectionHash('#llm')).toBe('llm');
    expect(parseSectionHash('llm')).toBe('llm');
  });

  it('decodes percent-encoding before validating', () => {
    expect(parseSectionHash('%6C%6C%6D')).toBe('llm');
    expect(parseSectionHash('#%63ontent')).toBe('content');
  });

  it('trims surrounding whitespace', () => {
    expect(parseSectionHash('  #status  ')).toBe('status');
  });

  it('rejects null, undefined and empty strings', () => {
    expect(parseSectionHash(null)).toBeNull();
    expect(parseSectionHash(undefined)).toBeNull();
    expect(parseSectionHash('')).toBeNull();
    expect(parseSectionHash('#')).toBeNull();
    expect(parseSectionHash('   ')).toBeNull();
  });

  it('rejects unknown or crafted hashes', () => {
    expect(parseSectionHash('#billing')).toBeNull();
    expect(parseSectionHash('https://evil.example/#llm')).toBeNull();
    expect(parseSectionHash('#llm?x=1')).toBeNull();
  });

  it('survives malformed percent-encoding instead of throwing', () => {
    expect(parseSectionHash('#%E0%A4%A')).toBeNull();
  });
});

describe('pickActiveSection (scroll-spy)', () => {
  const tops = [
    { id: 'status', top: -200 },
    { id: 'llm', top: -80 },
    { id: 'content', top: 240 },
    { id: 'language', top: 600 },
    { id: 'danger', top: 900 },
  ];

  it('returns the last section scrolled under the nav band', () => {
    expect(pickActiveSection(tops, 60)).toBe('llm');
  });

  it('keeps sections with negative tops eligible (page bottom)', () => {
    const allAbove = [
      { id: 'status', top: -900 },
      { id: 'llm', top: -600 },
      { id: 'danger', top: -40 },
    ];
    expect(pickActiveSection(allAbove, 60)).toBe('danger');
  });

  it('returns null when no section has reached the band', () => {
    const allBelow = [
      { id: 'status', top: 100 },
      { id: 'llm', top: 400 },
    ];
    expect(pickActiveSection(allBelow, 60)).toBeNull();
  });

  it('returns null for an empty measurement list', () => {
    expect(pickActiveSection([], 60)).toBeNull();
  });

  it('stops at the first section below the band (document order assumed)', () => {
    const mixed = [
      { id: 'status', top: 10 },
      { id: 'llm', top: 400 },
      { id: 'content', top: 20 },
    ];
    expect(pickActiveSection(mixed, 60)).toBe('status');
  });
});
