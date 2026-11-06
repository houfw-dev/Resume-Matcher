import { describe, expect, it } from 'vitest';
import {
  dedupeResumeLists,
  stripMarkdownEmphasis,
  stripMarkdownEmphasisDeep,
} from '@/lib/utils/markdown-strip';

describe('stripMarkdownEmphasis', () => {
  it.each([
    ['**Python**', 'Python'],
    ['统招本科（**985&211)**', '统招本科（985&211)'],
    ['__bold__', 'bold'],
    ['*italic*', 'italic'],
    ['_italic_', 'italic'],
    ['`code`', 'code'],
    ['~~removed~~', 'removed'],
    ['mixed **bold** and *italic*', 'mixed bold and italic'],
    // Orphan fragments — including the surviving half of a pair split across fields
    ['英语四级**', '英语四级'],
    ['**5年大型医院项目，3年电商）**', '5年大型医院项目，3年电商）'],
    ['**', ''],
    ['__', ''],
    ['~~', ''],
  ])('unwraps paired markers and deletes orphans: %s -> %s', (source, expected) => {
    expect(stripMarkdownEmphasis(source)).toBe(expected);
  });

  it('keeps single asterisks and identifier underscores intact', () => {
    expect(stripMarkdownEmphasis('A*')).toBe('A*');
    expect(stripMarkdownEmphasis('5*8')).toBe('5*8');
    expect(stripMarkdownEmphasis('my_var')).toBe('my_var');
    expect(stripMarkdownEmphasis('2 * 3 * 4')).toBe('2 * 3 * 4');
  });

  it('passes non-strings through unchanged', () => {
    expect(stripMarkdownEmphasis(3)).toBe(3);
    expect(stripMarkdownEmphasis(null)).toBeNull();
    expect(stripMarkdownEmphasis(undefined)).toBeUndefined();
  });
});

describe('stripMarkdownEmphasisDeep', () => {
  it('rebuilds nested containers without mutating keys', () => {
    const data = {
      personalInfo: { name: '**李勇**', age: 38 },
      additional: {
        technicalSkills: ['**Java**', 'Python'],
        languages: ['英语四级**'],
      },
      workExperience: [{ company: '某**公司**', description: ['**负责**架构'] }],
    };

    expect(stripMarkdownEmphasisDeep(data)).toEqual({
      personalInfo: { name: '李勇', age: 38 },
      additional: {
        technicalSkills: ['Java', 'Python'],
        languages: ['英语四级'],
      },
      workExperience: [{ company: '某公司', description: ['负责架构'] }],
    });
  });

  it('does not mutate the input', () => {
    const data = { a: ['**x**'], b: { c: 'y__' } };
    const snapshot = structuredClone(data);
    stripMarkdownEmphasisDeep(data);
    expect(data).toEqual(snapshot);
  });

  it('leaves primitives and arrays of primitives clean', () => {
    expect(stripMarkdownEmphasisDeep(['a**', 1, null])).toEqual(['a', 1, null]);
  });
});

describe('dedupeResumeLists', () => {
  it('deduplicates the additional fact lists after marker collapse', () => {
    const data = {
      additional: {
        languages: ['英语四级**', '英语四级', '日语N2'],
        technicalSkills: ['Java', ' Java ', 'Python'],
        certificationsTraining: ['PMP', 'PMP'],
      },
    };

    const cleaned = stripMarkdownEmphasisDeep(data);
    dedupeResumeLists(cleaned);

    expect(cleaned).toEqual({
      additional: {
        languages: ['英语四级', '日语N2'],
        technicalSkills: ['Java', 'Python'],
        certificationsTraining: ['PMP'],
      },
    });
  });

  it('deduplicates custom section stringLists and keeps empty entries', () => {
    const data = {
      customSections: {
        hobbies: { sectionType: 'stringList', strings: ['阅读', ' 阅读', ''] },
      },
    };

    dedupeResumeLists(data);

    expect(data.customSections.hobbies.strings).toEqual(['阅读', '']);
  });

  it('does not collapse index-aligned description arrays', () => {
    const data = {
      workExperience: [
        { description: ['负责架构', '负责架构'], descriptionStyles: ['bullet', 'bullet'] },
      ],
    };

    dedupeResumeLists(data);

    expect(data.workExperience[0].description).toEqual(['负责架构', '负责架构']);
    expect(data.workExperience[0].descriptionStyles).toEqual(['bullet', 'bullet']);
  });

  it('ignores non-object input', () => {
    expect(dedupeResumeLists(null)).toBeNull();
    expect(dedupeResumeLists(['英语四级', '英语四级'])).toEqual(['英语四级', '英语四级']);
  });
});
