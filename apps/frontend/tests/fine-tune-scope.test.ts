import { describe, expect, it } from 'vitest';
import {
  FINE_TUNE_SECTION_TOKENS,
  MAX_FINE_TUNE_TARGETS,
  buildScope,
  customHeadingLabels,
  customKeyFromToken,
  customSectionKeysFromTargets,
  customSectionToken,
  headingMatches,
  isCustomSectionToken,
  isSectionToken,
  isValidTargetToken,
  isWholeSectionSelected,
  itemToken,
  normalizeHeading,
  normalizeTargets,
  parseItemToken,
  parseRegionToken,
  regionToken,
  targetsToHeadingKeys,
  targetsWholeCustomSections,
  toggleItemToken,
  toggleRegionToken,
  toggleSectionToken,
} from '@/lib/utils/fine-tune-scope';

describe('fine-tune scope token grammar', () => {
  it('accepts the six section tokens and work/project item tokens', () => {
    for (const token of FINE_TUNE_SECTION_TOKENS) {
      expect(isSectionToken(token)).toBe(true);
      expect(isValidTargetToken(token)).toBe(true);
    }
    expect(isValidTargetToken('work_0')).toBe(true);
    expect(isValidTargetToken('project_12')).toBe(true);
  });

  it('rejects frozen modules, the all-keyword, and malformed tokens', () => {
    // personalInfo / sectionMeta never have tokens; "all" is expressed via an
    // empty target list, not a target token.
    expect(isValidTargetToken('personalInfo')).toBe(false);
    expect(isValidTargetToken('sectionMeta')).toBe(false);
    expect(isValidTargetToken('all')).toBe(false);
    expect(isValidTargetToken('exp_0')).toBe(false);
    expect(isValidTargetToken('proj_0')).toBe(false);
    expect(isValidTargetToken('work_-1')).toBe(false);
    expect(isValidTargetToken('WORK_0')).toBe(false);
    expect(isValidTargetToken('work_0 ')).toBe(false);
    expect(isValidTargetToken('')).toBe(false);
    expect(isSectionToken('work_0')).toBe(false);
  });

  it('builds and parses item tokens on the canonical 0-based index', () => {
    expect(itemToken('work', 0)).toBe('work_0');
    expect(itemToken('project', 2)).toBe('project_2');
    expect(parseItemToken('work_3')).toEqual({ kind: 'work', index: 3 });
    expect(parseItemToken('project_0')).toEqual({ kind: 'project', index: 0 });
    expect(parseItemToken('summary')).toBeNull();
    expect(parseItemToken('workExperience')).toBeNull();
  });

  it('normalizes targets: drops unknown, dedupes, preserves order, caps length', () => {
    expect(
      normalizeTargets(['work_1', 'summary', 'work_1', 'bogus', 'summary', 'project_0'])
    ).toEqual(['work_1', 'summary', 'project_0']);

    const tooMany = Array.from({ length: MAX_FINE_TUNE_TARGETS + 5 }, (_, i) =>
      i < MAX_FINE_TUNE_TARGETS
        ? itemToken('work', i)
        : itemToken('project', i - MAX_FINE_TUNE_TARGETS)
    );
    const normalized = normalizeTargets(tooMany);
    expect(normalized).toHaveLength(MAX_FINE_TUNE_TARGETS);
  });
});

describe('fine-tune scope toggles', () => {
  it('adds and removes a plain section token', () => {
    const added = toggleSectionToken([], 'summary');
    expect(added).toEqual(['summary']);
    expect(toggleSectionToken(added, 'summary')).toEqual([]);
  });

  it('ignores a non-section token when toggling', () => {
    expect(toggleSectionToken(['summary', 'work_0'], 'work_0')).toEqual(['summary', 'work_0']);
  });

  it('selecting a whole work/project section clears its per-item tokens', () => {
    const selected = toggleSectionToken(['work_0', 'work_2', 'summary'], 'workExperience');
    expect(selected).toEqual(['summary', 'workExperience']);

    const projects = toggleSectionToken(['project_1'], 'personalProjects');
    expect(projects).toEqual(['personalProjects']);
  });

  it('deselecting a whole section also removes its stale item tokens', () => {
    expect(toggleSectionToken(['workExperience', 'summary'], 'workExperience')).toEqual([
      'summary',
    ]);
  });

  it('toggles individual entries while the whole section is unselected', () => {
    expect(toggleItemToken([], 'workExperience', 1)).toEqual(['work_1']);
    expect(toggleItemToken(['work_1'], 'workExperience', 1)).toEqual([]);
    expect(toggleItemToken(['project_0'], 'personalProjects', 2)).toEqual([
      'project_0',
      'project_2',
    ]);
  });

  it('refuses item toggles once the whole section is selected', () => {
    expect(toggleItemToken(['workExperience'], 'workExperience', 0)).toEqual(['workExperience']);
  });

  it('reports whole-section selection', () => {
    expect(isWholeSectionSelected(['work_0'], 'workExperience')).toBe(false);
    expect(isWholeSectionSelected(['workExperience'], 'workExperience')).toBe(true);
  });
});

describe('fine-tune region tokens (project_N:<region>)', () => {
  it('accepts well-formed region tokens and rejects malformed ones', () => {
    expect(isValidTargetToken('project_0:highlights')).toBe(true);
    expect(isValidTargetToken('work_2:achievements')).toBe(true);
    for (const token of [
      'work_0:bogus',
      'project_x:highlights',
      'project_:highlights',
      'project_0:',
      'education_0:duties',
      'project_0:highlights:extra',
      'PROJECT_0:HIGHLIGHTS',
    ]) {
      expect(isValidTargetToken(token)).toBe(false);
    }
  });

  it('builds and parses region tokens', () => {
    expect(regionToken('project', 2, 'highlights')).toBe('project_2:highlights');
    expect(parseRegionToken('project_2:highlights')).toEqual({
      kind: 'project',
      index: 2,
      regionId: 'highlights',
    });
    expect(parseRegionToken('work_0')).toBeNull();
    expect(parseRegionToken('personalProjects')).toBeNull();
    expect(parseRegionToken('custom_a')).toBeNull();
  });

  it('adds and removes a region token', () => {
    expect(toggleRegionToken([], 'project', 0, 'highlights')).toEqual(['project_0:highlights']);
    expect(toggleRegionToken(['project_0:highlights'], 'project', 0, 'highlights')).toEqual([]);
    // Two regions of the same entry coexist.
    expect(toggleRegionToken(['project_0:techStack'], 'project', 0, 'highlights')).toEqual([
      'project_0:techStack',
      'project_0:highlights',
    ]);
  });

  it('is a no-op when the whole entry or whole section is selected', () => {
    expect(toggleRegionToken(['project_0'], 'project', 0, 'highlights')).toEqual(['project_0']);
    expect(toggleRegionToken(['personalProjects'], 'project', 0, 'highlights')).toEqual([
      'personalProjects',
    ]);
  });

  it('selecting the whole entry sweeps its region tokens; deselect keeps them', () => {
    expect(
      toggleItemToken(['project_0:highlights', 'project_0:techStack'], 'personalProjects', 0)
    ).toEqual(['project_0']);
    // Unchecking the entry removes only the item token.
    expect(toggleItemToken(['project_0:highlights', 'project_0'], 'personalProjects', 0)).toEqual([
      'project_0:highlights',
    ]);
  });

  it('selecting the whole section sweeps region tokens via the item prefix', () => {
    expect(
      toggleSectionToken(['project_0:highlights', 'project_1:duties'], 'personalProjects')
    ).toEqual(['personalProjects']);
  });

  it('maps region tokens to the same rendered heading groups as item tokens', () => {
    expect(targetsToHeadingKeys(['project_0:highlights'])).toEqual(['projects']);
    expect(targetsToHeadingKeys(['work_2:achievements'])).toEqual(['experience']);
  });

  it('normalizes region tokens through dedupe, filter and the 30-target cap', () => {
    expect(normalizeTargets(['project_0:highlights', 'project_0:highlights', 'x:y'])).toEqual([
      'project_0:highlights',
    ]);
  });
});

describe('fine-tune rendered-heading mapping', () => {
  it('maps section and item tokens to rendered heading groups', () => {
    expect(targetsToHeadingKeys(['summary', 'education'])).toEqual(['summary', 'education']);
    expect(targetsToHeadingKeys(['workExperience'])).toEqual(['experience']);
    expect(targetsToHeadingKeys(['work_0', 'work_1'])).toEqual(['experience']);
    expect(targetsToHeadingKeys(['personalProjects', 'project_4'])).toEqual(['projects']);
    expect(targetsToHeadingKeys(['additional', 'customSections'])).toEqual([
      'additional',
      'custom',
    ]);
    expect(targetsToHeadingKeys([])).toEqual([]);
  });

  it('normalizes headings ignoring case, trailing colons (incl. CJK) and spaces', () => {
    expect(normalizeHeading('  Experience:  ')).toBe('experience');
    expect(normalizeHeading('工作经历：')).toBe('工作经历');
    expect(headingMatches('Technical Skills:', ['Technical Skills'])).toBe(true);
    expect(headingMatches('EXPERIENCE', ['experience'])).toBe(true);
    expect(headingMatches('  Projects：', ['Projects'])).toBe(true);
    expect(headingMatches('Awards', ['Skills'])).toBe(false);
    expect(headingMatches('', ['Skills'])).toBe(false);
  });
});

describe('buildScope', () => {
  it('encodes an all-resume scope with an empty target list', () => {
    expect(buildScope('all', ['summary'])).toEqual({ kind: 'all', targets: [] });
  });

  it('passes normalized targets for module scope', () => {
    expect(buildScope('modules', ['work_0', 'work_0', 'nope'])).toEqual({
      kind: 'modules',
      targets: ['work_0'],
    });
  });

  it('keeps per-block custom tokens but drops malformed lookalikes', () => {
    expect(
      buildScope('modules', ['custom_publications', 'custom_publications', 'custom_'])
    ).toEqual({ kind: 'modules', targets: ['custom_publications'] });
  });
});

describe('fine-tune custom_<key> tokens', () => {
  const CUSTOM_BLOCKS = [
    { key: 'publications', displayName: 'Publications' },
    { key: 'custom_1', displayName: '兴趣爱好' },
  ];

  it('accepts parser/builder keys incl. double prefix and CJK, rejects malformed', () => {
    expect(isValidTargetToken('custom_self_evaluation')).toBe(true);
    expect(isValidTargetToken('custom_custom_1')).toBe(true);
    expect(isValidTargetToken('custom_兴趣爱好')).toBe(true);
    expect(isValidTargetToken('customSections')).toBe(true);
    expect(isSectionToken('custom_x')).toBe(false);
    for (const bad of ['custom_', 'custom', 'customSections_x', 'custom_foo bar']) {
      expect(isValidTargetToken(bad)).toBe(false);
      expect(isCustomSectionToken(bad)).toBe(false);
    }
    expect(isCustomSectionToken('custom_publications')).toBe(true);
    expect(isCustomSectionToken('customSections')).toBe(false);
  });

  it('accepts every supported-locale script in custom keys without unicode property escapes', () => {
    // The ES2017 build cannot use \p{L}/\p{N}; these lock the explicit
    // character ranges that replaced them (Latin accents, kana, Hangul, CJK).
    for (const token of [
      'custom_café_2',
      'custom_やる気',
      'custom_이력서_1',
      'custom_Опыт.1',
      'custom_Εμπειρία-α',
    ]) {
      expect(isValidTargetToken(token)).toBe(true);
      expect(customKeyFromToken(token)).toBe(token.slice('custom_'.length));
    }
    // Whitespace and emoji stay outside the key grammar, mirroring the
    // backend custom_[\w.-]+ gate.
    for (const bad of ['custom_foo bar', 'custom_⭐️']) {
      expect(isValidTargetToken(bad)).toBe(false);
    }
  });

  it('builds tokens and decodes the key exactly once (double prefix round-trip)', () => {
    expect(customSectionToken('publications')).toBe('custom_publications');
    expect(customSectionToken('custom_1')).toBe('custom_custom_1');
    expect(customKeyFromToken('custom_custom_1')).toBe('custom_1');
    expect(customKeyFromToken('custom_publications')).toBe('publications');
    expect(customKeyFromToken('customSections')).toBeNull();
    expect(customKeyFromToken('work_0')).toBeNull();
  });

  it('toggles one block independently, mutually exclusive with the whole token', () => {
    expect(toggleSectionToken([], 'custom_publications')).toEqual(['custom_publications']);
    expect(toggleSectionToken(['custom_publications'], 'custom_publications')).toEqual([]);

    // Checking a single block while the aggregated token is present drops it.
    expect(toggleSectionToken(['summary', 'customSections'], 'custom_publications')).toEqual([
      'summary',
      'custom_publications',
    ]);

    // Checking the aggregated token clears per-block tokens...
    expect(
      toggleSectionToken(['custom_publications', 'custom_custom_1'], 'customSections')
    ).toEqual(['customSections']);
    // ...and unchecking it defensively sweeps any stale per-block tokens.
    expect(toggleSectionToken(['customSections', 'custom_publications'], 'customSections')).toEqual(
      []
    );
  });

  it('normalizes custom targets with order, dedupe and the 30-target cap', () => {
    expect(normalizeTargets(['custom_b', 'custom_a', 'custom_b', 'bogus', 'custom_'])).toEqual([
      'custom_b',
      'custom_a',
    ]);

    const tooMany = Array.from(
      { length: MAX_FINE_TUNE_TARGETS + 4 },
      (_, i) => `custom_section_${i}`
    );
    expect(normalizeTargets(tooMany)).toHaveLength(MAX_FINE_TUNE_TARGETS);
  });

  it('extracts selected keys in first-seen order and detects the whole token', () => {
    expect(customSectionKeysFromTargets(['summary', 'custom_b', 'custom_a', 'custom_b'])).toEqual([
      'b',
      'a',
    ]);
    expect(customSectionKeysFromTargets(['customSections'])).toEqual([]);
    expect(targetsWholeCustomSections(['custom_publications'])).toBe(false);
    expect(targetsWholeCustomSections(['customSections'])).toBe(true);
  });

  it('maps per-block tokens to the rendered custom heading group', () => {
    expect(targetsToHeadingKeys(['summary', 'custom_self_evaluation'])).toEqual([
      'summary',
      'custom',
    ]);
    expect(targetsToHeadingKeys(['custom_custom_1'])).toEqual(['custom']);
  });

  it('resolves outline labels: whole token, per-block subset, missing-key fallback', () => {
    expect(customHeadingLabels(['customSections'], CUSTOM_BLOCKS)).toEqual([
      'Publications',
      '兴趣爱好',
    ]);
    expect(customHeadingLabels(['custom_custom_1'], CUSTOM_BLOCKS)).toEqual(['兴趣爱好']);
    // Target order drives label order.
    expect(customHeadingLabels(['custom_custom_1', 'custom_publications'], CUSTOM_BLOCKS)).toEqual([
      '兴趣爱好',
      'Publications',
    ]);
    // A syntactically valid key absent from the resume falls back to the raw key;
    // it simply cannot match a rendered heading.
    expect(customHeadingLabels(['custom_ghost'], CUSTOM_BLOCKS)).toEqual(['ghost']);
    expect(customHeadingLabels(['summary'], CUSTOM_BLOCKS)).toEqual([]);
  });
});
