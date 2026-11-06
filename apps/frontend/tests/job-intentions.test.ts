import { describe, expect, it } from 'vitest';
import { splitJobIntentions } from '@/lib/utils/job-intentions';

describe('splitJobIntentions', () => {
  it('returns an empty list for blank input', () => {
    expect(splitJobIntentions('')).toEqual([]);
    expect(splitJobIntentions(null)).toEqual([]);
    expect(splitJobIntentions(undefined)).toEqual([]);
    expect(splitJobIntentions('   ')).toEqual([]);
  });

  it('returns the single trimmed intention without splitting conjunctions', () => {
    expect(splitJobIntentions('  Java 开发工程师  ')).toEqual(['Java 开发工程师']);
    // 和/与 must not be treated as separators (compound titles).
    expect(splitJobIntentions('研发与管理')).toEqual(['研发与管理']);
    expect(splitJobIntentions('产品和运营')).toEqual(['产品和运营']);
  });

  it('splits on all supported separators and dedupes', () => {
    const result = splitJobIntentions(
      'Java 开发/大数据开发、后端架构，测试；运维 | 前端｜Java 开发\nGo 开发'
    );
    // The second "Java 开发" is removed by dedupe; order is preserved.
    expect(result).toEqual([
      'Java 开发',
      '大数据开发',
      '后端架构',
      '测试',
      '运维',
      '前端',
      'Go 开发',
    ]);
    expect(new Set(result).size).toBe(result.length);
  });

  it('keeps architect/lead slash titles intact', () => {
    // A single slash between two seniority variants of one technical line is
    // still a separator per the backend rule; the user confirms via the picker.
    // This test pins the splitting behaviour, not the quality heuristic.
    expect(splitJobIntentions('架构师/技术负责人')).toEqual(['架构师', '技术负责人']);
  });
});
