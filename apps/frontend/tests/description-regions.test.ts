import { describe, expect, it } from 'vitest';
import {
  REGION_ACHIEVEMENTS,
  REGION_BACKGROUND,
  REGION_DUTIES,
  REGION_HIGHLIGHTS,
  REGION_TECH_STACK,
  extractEntryRegions,
  mergedEntryRegions,
  type RegionEntryKind,
} from '@/lib/utils/description-regions';

// Mirrors apps/backend/tests/unit/test_description_regions.py — the same
// fixture matrix; spans must agree on both sides.

const PROJECT_DESCRIPTION = [
  '技术栈：',
  'Java',
  'Spring Boot',
  'Redis',
  '项目背景：',
  '面向连锁健身场景的数字化平台。',
  '项目职责：',
  '负责核心模块的后端设计与开发。',
  '统筹需求拆解与版本交付。',
  '项目亮点：',
  '订单重构方案落地，降低迁移风险。',
  '核心接口响应耗时降低40%。',
];
const PROJECT_STYLES = [
  'label',
  'plain',
  'plain',
  'plain',
  'label',
  'plain',
  'label',
  'bullet',
  'bullet',
  'label',
  'bullet',
  'bullet',
] as const;

function regions(description: readonly string[], styles: readonly string[], kind: RegionEntryKind) {
  return extractEntryRegions(kind, {
    description: [...description],
    descriptionStyles: [...styles],
  });
}

describe('extractEntryRegions — project', () => {
  it('covers rows between labels, excluding the label row itself', () => {
    const found = regions(PROJECT_DESCRIPTION, PROJECT_STYLES, 'project');
    expect(found.map((r) => [r.regionId, r.labelIndex])).toEqual([
      [REGION_TECH_STACK, 0],
      [REGION_BACKGROUND, 4],
      [REGION_DUTIES, 6],
      [REGION_HIGHLIGHTS, 9],
    ]);
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_TECH_STACK)?.contentIndices).toEqual([1, 2, 3]);
    expect(byId.get(REGION_TECH_STACK)?.labelText).toBe('技术栈：');
    expect(byId.get(REGION_BACKGROUND)?.contentIndices).toEqual([5]);
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([7, 8]);
    expect(byId.get(REGION_HIGHLIGHTS)?.contentIndices).toEqual([10, 11]);
  });

  it('excludes preamble rows before the first label', () => {
    const found = regions(
      ['项目一句话简介。', ...PROJECT_DESCRIPTION],
      ['plain', ...PROJECT_STYLES],
      'project'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_TECH_STACK)?.contentIndices).toEqual([2, 3, 4]);
    expect(byId.get(REGION_HIGHLIGHTS)?.contentIndices).toEqual([11, 12]);
  });

  it('canonicalizes alias labels to region ids without renaming the stored label', () => {
    const found = regions(
      ['技术选型：', 'Java', '项目成果：', '核心接口耗时降低40%。'],
      ['label', 'plain', 'label', 'bullet'],
      'project'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect([...byId.keys()]).toEqual([REGION_TECH_STACK, REGION_HIGHLIGHTS]);
    expect(byId.get(REGION_TECH_STACK)?.contentIndices).toEqual([1]);
    expect(byId.get(REGION_HIGHLIGHTS)?.contentIndices).toEqual([3]);
    expect(byId.get(REGION_TECH_STACK)?.labelText).toBe('技术选型：');
  });

  it('opens a duties region for a combined 项目职责与成果 heading', () => {
    const found = regions(
      [
        '项目背景：',
        '面向应急管理部的大数据应用平台。',
        '技术栈：',
        'Spring Boot, Kafka, Redis',
        '项目职责与成果：',
        '负责智搜核心模块的设计与落地，QPS 提升 10 倍以上。',
        '基于 PaddleNLP 完成查询词实体抽取与语义匹配。',
      ],
      ['label', 'plain', 'label', 'plain', 'label', 'bullet', 'bullet'],
      'project'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect([...byId.keys()]).toEqual([REGION_BACKGROUND, REGION_TECH_STACK, REGION_DUTIES]);
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([5, 6]);
    expect(byId.get(REGION_DUTIES)?.labelText).toBe('项目职责与成果：');
    expect(byId.get(REGION_TECH_STACK)?.contentIndices).toEqual([3]);
  });

  it.each(['项目职责和成果：', '项目职责及成果：', '工作职责与成果：', '职责与成果：'])(
    'maps the compound variant %s to duties',
    (label) => {
      const found = regions([label, '负责后端开发。'], ['label', 'bullet'], 'project');
      const byId = new Map(found.map((r) => [r.regionId, r]));
      expect([...byId.keys()]).toEqual([REGION_DUTIES]);
      expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([1]);
    }
  );

  it('closes the current region at an unknown standalone heading', () => {
    const found = regions(
      [
        '项目职责：',
        '负责后端开发。',
        '解决方案：',
        '采用补偿事务保证一致性。',
        '项目亮点：',
        '接口耗时降低40%。',
      ],
      ['label', 'bullet', 'label', 'bullet', 'label', 'bullet'],
      'project'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([1]);
    expect(byId.get(REGION_HIGHLIGHTS)?.contentIndices).toEqual([5]);
    expect(byId.get(REGION_DUTIES)?.contentIndices).not.toContain(3);
  });

  it('keeps nested bold heads inside a bullet region in-region', () => {
    const found = regions(
      [
        '项目亮点：',
        '重大生产问题解决：',
        '通过补偿机制恢复数据。',
        '性能优化：',
        '核心接口耗时降低40%。',
      ],
      ['label', 'label', 'plain', 'label', 'plain'],
      'project'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_HIGHLIGHTS)?.contentIndices).toEqual([1, 2, 3, 4]);
  });

  it('treats descriptive-only label names as separators without a region id', () => {
    const found = regions(
      [
        '项目职责：',
        '负责后端开发。',
        '项目描述：',
        '一套数字化平台。',
        '项目亮点：',
        '耗时降低40%。',
      ],
      ['label', 'bullet', 'label', 'plain', 'label', 'bullet'],
      'project'
    );
    expect(found.map((r) => r.regionId)).toEqual([REGION_DUTIES, REGION_HIGHLIGHTS]);
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([1]);
    expect(byId.get(REGION_HIGHLIGHTS)?.contentIndices).toEqual([5]);
  });

  it('does not treat a bullet-styled label-shaped row as a heading', () => {
    const found = regions(
      ['项目职责：', '项目亮点：客户端零故障。'],
      ['label', 'bullet'],
      'project'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.has(REGION_HIGHLIGHTS)).toBe(false);
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([1]);
  });
});

describe('extractEntryRegions — work', () => {
  it('recognizes curated labels without renaming', () => {
    const found = regions(
      ['工作职责：', '完成日常开发。', '工作业绩：', '年度优秀员工。'],
      ['label', 'bullet', 'label', 'bullet'],
      'work'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([1]);
    expect(byId.get(REGION_DUTIES)?.labelText).toBe('工作职责：');
    expect(byId.get(REGION_ACHIEVEMENTS)?.contentIndices).toEqual([3]);
    expect(byId.get(REGION_ACHIEVEMENTS)?.labelText).toBe('工作业绩：');
  });

  it('recognizes a combined 工作职责与成果 heading verbatim', () => {
    const found = regions(['工作职责与成果：', '负责核心系统。'], ['label', 'bullet'], 'work');
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([1]);
    expect(byId.get(REGION_DUTIES)?.labelText).toBe('工作职责与成果：');
  });

  it('closes a region at unknown headings and maps tech aliases', () => {
    const found = regions(
      ['技术栈：', 'Java', '带团队：', '管理5人小组。', '主要职责：', '负责架构设计。'],
      ['label', 'plain', 'label', 'bullet', 'label', 'bullet'],
      'work'
    );
    const byId = new Map(found.map((r) => [r.regionId, r]));
    expect(byId.get(REGION_TECH_STACK)?.contentIndices).toEqual([1]);
    expect(byId.get(REGION_DUTIES)?.contentIndices).toEqual([5]);
    for (const region of byId.values()) {
      expect(region.contentIndices).not.toContain(3);
    }
  });
});

describe('mergedEntryRegions and edge cases', () => {
  it('unions blocks sharing an id and keeps the first label text', () => {
    const merged = mergedEntryRegions('project', {
      description: [
        '项目职责：',
        '负责A模块。',
        '项目职责：',
        '负责B模块。',
        '项目亮点：',
        '零故障。',
      ],
      descriptionStyles: ['label', 'bullet', 'label', 'bullet', 'label', 'bullet'],
    });
    expect([...merged.keys()]).toEqual([REGION_DUTIES, REGION_HIGHLIGHTS]);
    expect(merged.get(REGION_DUTIES)?.contentIndices).toEqual([1, 3]);
    expect(merged.get(REGION_DUTIES)?.labelIndex).toBe(0);
    expect(merged.get(REGION_DUTIES)?.labelText).toBe('项目职责：');
  });

  it('returns no regions for missing, empty or unlabeled descriptions', () => {
    expect(extractEntryRegions('project', null)).toEqual([]);
    expect(extractEntryRegions('work', { description: [], descriptionStyles: [] })).toEqual([]);
    expect(
      extractEntryRegions('project', {
        description: ['普通条目，没有标签。'],
        descriptionStyles: ['bullet'],
      })
    ).toEqual([]);
  });
});
