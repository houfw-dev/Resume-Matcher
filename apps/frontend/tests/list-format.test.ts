import { describe, expect, it } from 'vitest';

import {
  buildDescriptionBlocks,
  canonicalizeProjectSubLabel,
  canonicalizeProjectSubLabelPrefix,
  isProjectDescriptiveLabel,
  isProjectPlainPrefixRow,
  joinInlineBodyRows,
  looksLikeNestedGroupHead,
  looksLikeSubLabel,
  planNestedGroupHeads,
  splitProjectPlainPrefix,
  stripPointMarker,
  type DescriptionRowStyle,
} from '@/components/resume/list-format';

describe('stripPointMarker', () => {
  it('removes source-carried numbering but keeps the text', () => {
    expect(stripPointMarker('1、配合评审')).toBe('配合评审');
    expect(stripPointMarker('12) 保障稳定')).toBe('保障稳定');
    expect(stripPointMarker('① 主导设计')).toBe('主导设计');
    expect(stripPointMarker('普通正文')).toBe('普通正文');
  });

  it('strips glyph bullets even without following whitespace', () => {
    // Rule 1 symbol unification: "•Java" is still a bullet point.
    expect(stripPointMarker('•Java 并发编程')).toBe('Java 并发编程');
    expect(stripPointMarker('·Redis 缓存')).toBe('Redis 缓存');
    expect(stripPointMarker('●  带多个空格')).toBe('带多个空格');
  });

  it('keeps dash markers when no whitespace follows (minus/ranges)', () => {
    expect(stripPointMarker('-30% 延迟优化')).toBe('-30% 延迟优化');
    expect(stripPointMarker('-1~3 年经验')).toBe('-1~3 年经验');
    expect(stripPointMarker('- 用连字符开头的点')).toBe('用连字符开头的点');
    expect(stripPointMarker('— 破折号开头的点')).toBe('破折号开头的点');
  });
});

describe('looksLikeSubLabel', () => {
  it('recognises curated sub-module headings, with or without a trailing colon', () => {
    expect(looksLikeSubLabel('负责内容')).toBe(true);
    expect(looksLikeSubLabel('项目亮点：')).toBe(true);
    expect(looksLikeSubLabel('难点与解决:')).toBe(true);
    // Personal-duty/result aliases, including legacy rows still stored plain.
    expect(looksLikeSubLabel('个人职责')).toBe(true);
    expect(looksLikeSubLabel('个人职责：')).toBe(true);
    expect(looksLikeSubLabel('项目责任：')).toBe(true);
    expect(looksLikeSubLabel('个人职责与成果')).toBe(true);
    expect(looksLikeSubLabel('个人成果')).toBe(true);
  });

  it('recognises short heading-only rows ending in a colon', () => {
    expect(looksLikeSubLabel('核心产出：')).toBe(true);
  });

  it('does not promote inline content or full sentences', () => {
    expect(looksLikeSubLabel('技术栈： Java、Python')).toBe(false);
    expect(looksLikeSubLabel('负责交易链路的设计与开发工作')).toBe(false);
    expect(looksLikeSubLabel('项目背景：AIGC 系列产品，面向企业客户。')).toBe(false);
  });

  it('recognises short latin-prefixed headings containing a space (model rewrite)', () => {
    expect(looksLikeSubLabel('CPU 飙升问题：')).toBe(true);
    expect(looksLikeSubLabel('JVM 调优：')).toBe(true);
    // A long spaced run is still body text, not a heading.
    expect(looksLikeSubLabel('CPU 飙升导致整条查询链路变慢需要排查：')).toBe(false);
  });
});

describe('looksLikeNestedGroupHead', () => {
  // Shape-only predicate: successor/module checks live in planNestedGroupHeads.
  it('accepts a short bare row in any content style, including bullet', () => {
    expect(looksLikeNestedGroupHead('架构演进与技术债务治理', 'plain')).toBe(true);
    expect(looksLikeNestedGroupHead('主导促销中心组件设计', 'label')).toBe(true);
    // Weak models store group titles as ordinary bullets; shape alone accepts
    // them and the structural planner decides whether they really open a group.
    expect(looksLikeNestedGroupHead('履约层策略化重构', 'bullet')).toBe(true);
    expect(looksLikeNestedGroupHead('系统从 0 到 1 搭建', 'bullet')).toBe(true);
  });

  it('rejects source-numbered enumeration rows', () => {
    expect(looksLikeNestedGroupHead('2）机审', 'plain')).toBe(false);
    expect(looksLikeNestedGroupHead('1、需求调研', 'plain')).toBe(false);
  });

  it('rejects colon headings, long prose and punctuation-bearing sentences', () => {
    expect(looksLikeNestedGroupHead('性能调优：', 'plain')).toBe(false);
    expect(
      looksLikeNestedGroupHead('作为后端技术组长，牵头项目从调研到运维的全流程交付工作。', 'plain')
    ).toBe(false);
    expect(looksLikeNestedGroupHead('高并发架构：缓存与削峰', 'plain')).toBe(false);
    // ASCII colon is treated identically to the full-width colon.
    expect(looksLikeNestedGroupHead('高并发架构: 缓存与削峰', 'bullet')).toBe(false);
  });

  it('rejects blank rows and unknown styles', () => {
    expect(looksLikeNestedGroupHead('  ', 'plain')).toBe(false);
    expect(looksLikeNestedGroupHead('技术方案设计', undefined)).toBe(false);
  });
});

describe('planNestedGroupHeads', () => {
  const projectOptions = { canonicalizeLabels: true } as const;

  it('promotes bullet-styled group titles across every project (generalized rule)', () => {
    // 邹利平.pdf 沃尔沃内领商城 shape: every row stored as a bullet, but the
    // short titles alternate with long detail-shaped points.
    const items = [
      '项目职责',
      '系统从 0 到 1 搭建',
      '主导内领商城架构设计与核心模块开发，负责需求评审与落地。',
      '设计并实现三方系统对接的高可用方案',
      '履约层策略化重构',
      '基于策略模式重构订单履约层，新增履约方式零侵入。',
      '自研轻量级流程编排框架',
      '问题：校验商品信息、库存、下单代码，有大量重复冗余代码',
      '将业务流程拆解为可复用原子节点并支持多流程共享',
      '商品初始化同步方案',
      '通过分类治理与多轮对账，保障商品同步准确率 100%。',
    ];
    const styles: Array<DescriptionRowStyle | null | undefined> = [
      'label',
      ...items.slice(1).map(() => 'bullet' as const),
    ];
    expect([...planNestedGroupHeads(items, styles, projectOptions)].sort((a, b) => a - b)).toEqual([
      1, 4, 6, 9,
    ]);
  });

  it('still promotes plain-styled bare heads interleaved with bullets', () => {
    const items = [
      '核心职责与成果：',
      '架构演进与技术债务治理',
      '担任商城板块技术负责人，主导架构设计与版本迭代。',
      '主导促销中心组件设计',
      '将营销活动流程组件化，提升代码复用性。',
    ];
    const styles = ['label', 'plain', 'bullet', 'plain', 'bullet'] as const;
    expect([...planNestedGroupHeads(items, [...styles], projectOptions)]).toEqual([1, 3]);
  });

  it('never splits a flat peer bullet list (single or adjacent short rows)', () => {
    // 叶宏汉.pdf shape: short "负责…" peer duties, one head-shaped row amid
    // longer peers — no head/detail alternation, nothing qualifies.
    const flat = [
      '项目职责：',
      '负责内网穿透项目单连接多路复用通信架构的设计与实现',
      '负责自定义二进制通信协议设计与帧解析实现',
      '负责高吞吐传输与反压机制建设',
      '负责分布式长连接注册与路由方案设计',
    ];
    const flatStyles = ['label', 'bullet', 'bullet', 'bullet', 'bullet'] as const;
    expect(planNestedGroupHeads(flat, [...flatStyles], projectOptions).size).toBe(0);

    // Two adjacent head-shaped rows are peer points, not head+head.
    const adjacent = [
      '项目职责：',
      '负责消息可靠性与消费位点管理',
      '负责操作审计可靠投递方案设计与实现',
      '负责统一事件协议与渐进式迁移推进服务平滑迁移落地。',
    ];
    const adjacentStyles = ['label', 'bullet', 'bullet', 'bullet'] as const;
    expect(planNestedGroupHeads(adjacent, [...adjacentStyles], projectOptions).size).toBe(0);
  });

  it('rejects an isolated short bullet even between long detail points', () => {
    // 张向科.pdf shape: one short point under an implicit group; the >=2
    // qualified-heads gate keeps it an ordinary point.
    const items = [
      '项目职责：',
      '负责大批量任务执行与可观测建设：XXL-Job 分片产生任务、Kafka 异步派发。',
      'SSE 流式返回话术与任务进度',
      'OpenTelemetry 与 Micrometer 记录 Agent Trace 与 Token 用量。',
    ];
    const styles = ['label', 'bullet', 'bullet', 'bullet'] as const;
    expect(planNestedGroupHeads(items, [...styles], projectOptions).size).toBe(0);
  });

  it('returns nothing at non-project render sites or outside list modules', () => {
    const items = ['架构演进与技术债务治理', '负责架构设计。'];
    const styles = ['plain', 'bullet'] as const;
    expect(planNestedGroupHeads(items, [...styles]).size).toBe(0);
    // Tech-stack/background body spans never nest.
    const body = ['技术栈：', '缓存与消息队列', '负责 Redis 缓存方案设计与落地。'];
    const bodyStyles = ['label', 'plain', 'plain'] as const;
    expect(planNestedGroupHeads(body, [...bodyStyles], projectOptions).size).toBe(0);
  });
});

describe('buildDescriptionBlocks', () => {
  it('puts loose bullets into one non-indented list', () => {
    const blocks = buildDescriptionBlocks(['A', 'B', 'C']);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: 'list', indented: false });
    expect(blocks[0].kind === 'list' && blocks[0].rows).toEqual([
      { desc: 'A', numbered: true },
      { desc: 'B', numbered: true },
      { desc: 'C', numbered: true },
    ]);
  });

  it('gives every label its own indented list that restarts numbering', () => {
    const blocks = buildDescriptionBlocks(
      ['负责内容', 'A', 'B', '难点与解决', 'C', 'D'],
      ['label', 'bullet', 'bullet', 'label', 'bullet', 'bullet']
    );

    expect(blocks.map((b) => b.kind)).toEqual(['label', 'list', 'label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '负责内容' });
    expect(blocks[1]).toMatchObject({ kind: 'list', indented: true });
    expect(blocks[2]).toMatchObject({ kind: 'label', desc: '难点与解决' });
    expect(blocks[3]).toMatchObject({ kind: 'list', indented: true });
  });

  it('keeps plain body rows after a label inside the indented list without numbers', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈', 'Java、Python', '落地改造'],
      ['label', 'plain', 'bullet']
    );

    expect(blocks).toHaveLength(2);
    expect(blocks[1].kind === 'list' && blocks[1].indented).toBe(true);
    expect(blocks[1].kind === 'list' && blocks[1].rows).toEqual([
      { desc: 'Java、Python', numbered: false },
      { desc: '落地改造', numbered: true },
    ]);
  });

  it('promotes legacy plain sub-label rows to labels but keeps plain body rows plain', () => {
    const blocks = buildDescriptionBlocks(
      ['项目背景：AIGC 系列产品，面向企业客户。', '项目职责：', '负责核心模块', '保障稳定性'],
      ['plain', 'plain', 'bullet', 'bullet']
    );

    expect(blocks.map((b) => b.kind)).toEqual(['list', 'label', 'list']);
    expect(blocks[0].kind === 'list' && blocks[0].rows[0]).toEqual({
      desc: '项目背景：AIGC 系列产品，面向企业客户。',
      numbered: false,
    });
    expect(blocks[1]).toMatchObject({ kind: 'label', desc: '项目职责：' });
    expect(blocks[2]).toMatchObject({ kind: 'list', indented: true });
  });

  it('renders consecutive labels (a heading without bullets) without empty lists', () => {
    const blocks = buildDescriptionBlocks(['负责内容', '项目亮点'], ['label', 'label']);
    expect(blocks).toEqual([
      { kind: 'label', desc: '负责内容', descriptive: false },
      { kind: 'label', desc: '项目亮点', descriptive: false },
    ]);
  });

  it('demotes a label-styled content paragraph into its list block', () => {
    const blocks = buildDescriptionBlocks(
      ['项目职责：', '负责整体架构：基于双框架分工，避免配置漂移。'],
      ['label', 'label'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目职责：' });
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].rows).toEqual([
      { desc: '负责整体架构：基于双框架分工，避免配置漂移。', numbered: true },
    ]);
  });

  it('does not demote short standalone headings styled as labels', () => {
    const blocks = buildDescriptionBlocks(['难点/方案/效果：', '表格内容'], ['label', 'plain']);
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '难点/方案/效果：' });
  });

  it('does not canonicalize label names by default (work/custom render sites)', () => {
    const blocks = buildDescriptionBlocks(['工作职责：', 'A'], ['label', 'bullet']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '工作职责：' });
  });

  it('canonicalizes project label aliases when enabled, preserving the colon', () => {
    const blocks = buildDescriptionBlocks(
      ['项目成果：', 'A', '负责内容：', 'B'],
      ['label', 'bullet', 'label', 'bullet'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => (b.kind === 'label' ? b.desc : b.kind))).toEqual([
      '项目亮点：',
      'list',
      '项目职责：',
      'list',
    ]);
  });

  it('canonicalizes legacy plain-promoted project headings too', () => {
    const blocks = buildDescriptionBlocks(['技术难点：', 'A'], ['plain', 'bullet'], {
      canonicalizeLabels: true,
    });
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目亮点：' });
  });

  it('canonicalizes legacy personal-duty/result headings stored as plain', () => {
    // Real upload shape: "个人职责：" and a bare "项目成果" stored with the
    // plain style. Project render sites must promote, rename and keep each
    // module's own list block (duty list vs. highlight list).
    const blocks = buildDescriptionBlocks(
      ['个人职责：', '负责核心模块。', '项目成果', 'QPS 提升 30%。'],
      ['plain', 'plain', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => (b.kind === 'label' ? b.desc : b.kind))).toEqual([
      '项目职责：',
      'list',
      '项目亮点',
      'list',
    ]);
  });

  it('keeps non-alias labels verbatim when canonicalizing', () => {
    const blocks = buildDescriptionBlocks(['项目治理：', '推进风险闭环。'], ['label', 'bullet'], {
      canonicalizeLabels: true,
    });
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目治理：', descriptive: false });
  });

  it('canonicalizes background/tech aliases and flags descriptive labels', () => {
    const blocks = buildDescriptionBlocks(
      ['项目简介：', '面向多子系统场景。', '技术列表：', 'SpringAI、RAG。'],
      ['label', 'plain', 'label', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => (b.kind === 'label' ? b.desc : b.kind))).toEqual([
      '项目背景：',
      'body',
      '技术栈：',
      'body',
    ]);
    expect(blocks[0]).toMatchObject({ kind: 'label', descriptive: true });
    expect(blocks[2]).toMatchObject({ kind: 'label', descriptive: true });
  });

  it('gives descriptive labels an unnumbered body block aligned to the label edge', () => {
    // 熊威 shape: legacy "plain" label rows + plain content, then a duty label
    // with bullets.
    const blocks = buildDescriptionBlocks(
      ['项目背景：', '多个子系统重复建设。', '负责内容：', '负责核心模块。'],
      ['plain', 'plain', 'plain', 'bullet'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'body', 'label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目背景：', descriptive: true });
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['多个子系统重复建设。'],
      inline: false,
    });
    expect(blocks[3]).toMatchObject({ kind: 'list', indented: true });
  });

  it('treats bullet-styled rows under a descriptive label as unnumbered body', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Java', 'Redis'],
      ['label', 'bullet', 'bullet'],
      {
        canonicalizeLabels: true,
      }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'body']);
    expect(blocks[1]).toEqual({ kind: 'body', rows: ['Java', 'Redis'], inline: true });
  });

  it('renders a structured tech stack with category rows as an ordered list', () => {
    const blocks = buildDescriptionBlocks(
      [
        '技术栈：',
        '后端：Java 8、Spring Boot、Spring Cloud',
        '数据库：MySQL、Redis',
        '前端：Vue.js、Element UI',
        '运维/监控：Docker、Prometheus',
      ],
      ['label', 'plain', 'plain', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'list']);
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].indented).toBe(true);
    expect(blocks[1].rows).toEqual([
      { desc: '后端：Java 8、Spring Boot、Spring Cloud', numbered: true },
      { desc: '数据库：MySQL、Redis', numbered: true },
      { desc: '前端：Vue.js、Element UI', numbered: true },
      { desc: '运维/监控：Docker、Prometheus', numbered: true },
    ]);
  });

  it('numbers bare-name rows too when a tech stack mixes categories and names', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', '后端：Java、Go', 'Docker', '监控：Prometheus'],
      ['label', 'plain', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks[1]).toEqual({
      kind: 'list',
      indented: true,
      flush: false,
      rows: [
        { desc: '后端：Java、Go', numbered: true },
        { desc: 'Docker', numbered: true },
        { desc: '监控：Prometheus', numbered: true },
      ],
    });
  });

  it('keeps a glued known sub-module row without sentence punctuation stacked', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Spring Boot、MySQL', '技术难点及亮点：实时时延<50ms'],
      ['label', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'body']);
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['Spring Boot、MySQL', '项目亮点：实时时延<50ms'],
      inline: false,
    });
  });

  it('keeps a glued personal-duty alias under tech stack stacked, not numbered', () => {
    // The short "个人职责：…" shape must not be mistaken for a tech-stack
    // category row ("后端：Java、Go") just because it has no sentence period.
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Spring Boot、MySQL', '个人职责：负责核心模块设计与落地'],
      ['label', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'body']);
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['Spring Boot、MySQL', '项目职责：负责核心模块设计与落地'],
      inline: false,
    });
  });

  it('keeps a glued achievement sentence under tech stack stacked, not numbered', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Spring Boot、Redis。', '项目亮点：实时时延优化到 600ms。'],
      ['label', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['Spring Boot、Redis。', '项目亮点：实时时延优化到 600ms。'],
      inline: false,
    });
  });

  it('marks the tech-stack body inline while background/architecture bodies stay stacked', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Spring Boot', 'Nacos', 'Kafka', '项目背景：', '面向应急管理部的平台。'],
      ['label', 'plain', 'plain', 'plain', 'label', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '技术栈：' });
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['Spring Boot', 'Nacos', 'Kafka'],
      inline: true,
    });
    expect(blocks[2]).toMatchObject({ kind: 'label', desc: '项目背景：' });
    expect(blocks[3]).toEqual({
      kind: 'body',
      rows: ['面向应急管理部的平台。'],
      inline: false,
    });
  });

  it('merges a legacy glued tech alias body into an inline block', () => {
    const blocks = buildDescriptionBlocks(['技术列表：Java、Redis', 'Kafka'], ['bullet', 'plain'], {
      canonicalizeLabels: true,
    });
    expect(blocks).toEqual([
      { kind: 'label', desc: '技术栈：', descriptive: true },
      { kind: 'body', rows: ['Java、Redis', 'Kafka'], inline: true },
    ]);
  });

  it('does not inline at non-project sites (no canonicalization)', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Java', 'Redis'],
      ['label', 'plain', 'plain']
    );
    // Without canonicalization the label is not descriptive: rows join a list,
    // no inline body exists at all.
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'list']);
  });

  it('does not open a body block for descriptive labels at non-project sites', () => {
    const blocks = buildDescriptionBlocks(['技术栈：', 'Java、Python'], ['label', 'plain']);
    expect(blocks[0]).toMatchObject({ kind: 'label', descriptive: false });
    expect(blocks[1]).toMatchObject({ kind: 'list' });
  });

  it('splits legacy glued descriptive rows into a label plus a body block', () => {
    const blocks = buildDescriptionBlocks(
      ['项目简介：面向家庭宽带装维场景。', '技术列表：SpringAI、RAG。'],
      ['bullet', 'bullet'],
      { canonicalizeLabels: true }
    );
    expect(blocks).toEqual([
      { kind: 'label', desc: '项目背景：', descriptive: true },
      { kind: 'body', rows: ['面向家庭宽带装维场景。'], inline: false },
      { kind: 'label', desc: '技术栈：', descriptive: true },
      // Single row ending in 。 is prose-shaped → stacked (rendering identical).
      { kind: 'body', rows: ['SpringAI、RAG。'], inline: false },
    ]);
  });

  it('still unifies a glued duty/highlight alias found inside a descriptive body', () => {
    const blocks = buildDescriptionBlocks(
      ['技术栈：', 'Spring Boot、Redis。', '技术难点及亮点：实时时延优化到 600ms。'],
      ['label', 'plain', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'body']);
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['Spring Boot、Redis。', '项目亮点：实时时延优化到 600ms。'],
      inline: false,
    });
  });

  it('keeps a duty list numbered after a glued descriptive body until a label follows', () => {
    // Rows after the glued descriptive row join its body until the next label;
    // the duty label then opens a fresh numbered list.
    const blocks = buildDescriptionBlocks(
      ['项目简介：面向装维场景。', '补充背景一行。', '项目职责：', '负责核心模块。'],
      ['bullet', 'plain', 'label', 'bullet'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((b) => b.kind)).toEqual(['label', 'body', 'label', 'list']);
    expect(blocks[1]).toEqual({
      kind: 'body',
      rows: ['面向装维场景。', '补充背景一行。'],
      inline: false,
    });
  });
});

describe('canonicalizeProjectSubLabel', () => {
  it('renames all alias groups to their canonical names, colon preserved', () => {
    expect(canonicalizeProjectSubLabel('项目成果：')).toBe('项目亮点：');
    expect(canonicalizeProjectSubLabel('技术难点及亮点:')).toBe('项目亮点:');
    expect(canonicalizeProjectSubLabel('难点与解决：')).toBe('项目亮点：');
    expect(canonicalizeProjectSubLabel('工作职责：')).toBe('项目职责：');
    expect(canonicalizeProjectSubLabel('核心工作：')).toBe('项目职责：');
    expect(canonicalizeProjectSubLabel('负责内容')).toBe('项目职责');
    expect(canonicalizeProjectSubLabel('项目简介：')).toBe('项目背景：');
    expect(canonicalizeProjectSubLabel('需求背景：')).toBe('项目背景：');
    expect(canonicalizeProjectSubLabel('项目概述')).toBe('项目背景');
    expect(canonicalizeProjectSubLabel('技术列表：')).toBe('技术栈：');
    expect(canonicalizeProjectSubLabel('所用技术：')).toBe('技术栈：');
    expect(canonicalizeProjectSubLabel('技术架构')).toBe('技术栈');
    // Personal-duty/result phrasings seen in real uploads.
    expect(canonicalizeProjectSubLabel('个人职责：')).toBe('项目职责：');
    expect(canonicalizeProjectSubLabel('项目责任：')).toBe('项目职责：');
    expect(canonicalizeProjectSubLabel('个人职责与成果')).toBe('项目职责');
    expect(canonicalizeProjectSubLabel('核心职责与成果：')).toBe('项目职责：');
    expect(canonicalizeProjectSubLabel('个人成果：')).toBe('项目亮点：');
  });

  it('strips a source numbering prefix before renaming', () => {
    expect(canonicalizeProjectSubLabel('1、工作内容：')).toBe('项目职责：');
  });

  it('returns non-alias text unchanged', () => {
    expect(canonicalizeProjectSubLabel('技术栈：')).toBe('技术栈：');
    expect(canonicalizeProjectSubLabel('负责核心交易链路设计')).toBe('负责核心交易链路设计');
    expect(canonicalizeProjectSubLabel('项目亮点：')).toBe('项目亮点：');
  });
});

describe('canonicalizeProjectSubLabelPrefix', () => {
  it('renames a curated label glued to its content without splitting', () => {
    expect(canonicalizeProjectSubLabelPrefix('技术难点及亮点：实时端到端时延优化。')).toBe(
      '项目亮点：实时端到端时延优化。'
    );
    expect(canonicalizeProjectSubLabelPrefix('1、负责内容：搭建对账平台')).toBe(
      '项目职责：搭建对账平台'
    );
  });

  it('matches the longest alias first', () => {
    expect(canonicalizeProjectSubLabelPrefix('技术难点：攻克 JVM OOM。')).toBe(
      '项目亮点：攻克 JVM OOM。'
    );
  });

  it('leaves ordinary duty bullets and non-alias labels untouched', () => {
    expect(canonicalizeProjectSubLabelPrefix('负责核心交易链路设计与落地。')).toBe(
      '负责核心交易链路设计与落地。'
    );
    expect(canonicalizeProjectSubLabelPrefix('技术栈：Java、Redis。')).toBe(
      '技术栈：Java、Redis。'
    );
  });
});

describe('isProjectPlainPrefixRow', () => {
  it('recognises glued intro/background/tech-list rows', () => {
    expect(isProjectPlainPrefixRow('项目简介：面向家庭宽带装维场景。')).toBe(true);
    expect(isProjectPlainPrefixRow('技术列表：SpringAI、RAG、Nacos。')).toBe(true);
    expect(isProjectPlainPrefixRow('1、技术栈：Java、Redis')).toBe(true);
  });

  it('does not match heading-only labels, duty rows, or ordinary text', () => {
    expect(isProjectPlainPrefixRow('项目简介：')).toBe(false);
    expect(isProjectPlainPrefixRow('项目职责：负责核心调度模块。')).toBe(false);
    expect(isProjectPlainPrefixRow('负责核心交易链路设计与落地。')).toBe(false);
  });

  it('keeps legacy numbering for glued rows without the project flag', () => {
    // Work/custom render sites never split: the row stays a (numbered) list
    // row and is not canonicalized.
    const row = '项目简介：面向家庭宽带装维场景，SpringAI + RAG。';
    const defaultBlocks = buildDescriptionBlocks([row], ['bullet']);
    expect(defaultBlocks[0]).toMatchObject({
      kind: 'list',
      rows: [{ desc: row, numbered: true }],
    });
  });
});

describe('splitProjectPlainPrefix', () => {
  it('splits a glued descriptive row into a canonical label plus content', () => {
    expect(splitProjectPlainPrefix('项目简介：面向家庭宽带装维场景。')).toEqual({
      label: '项目背景：',
      content: '面向家庭宽带装维场景。',
    });
    expect(splitProjectPlainPrefix('技术列表：SpringAI、RAG、Nacos。')).toEqual({
      label: '技术栈：',
      content: 'SpringAI、RAG、Nacos。',
    });
    expect(splitProjectPlainPrefix('技术架构：Spring Cloud + Redis。')).toEqual({
      label: '技术栈：',
      content: 'Spring Cloud + Redis。',
    });
  });

  it('strips source numbering and preserves an ASCII colon', () => {
    expect(splitProjectPlainPrefix('1、技术栈：Java、Redis')).toEqual({
      label: '技术栈：',
      content: 'Java、Redis',
    });
    expect(splitProjectPlainPrefix('项目概述: 面向职教场景。')).toEqual({
      label: '项目背景:',
      content: '面向职教场景。',
    });
  });

  it('keeps verbatim descriptive labels and returns null for non-descriptive rows', () => {
    expect(splitProjectPlainPrefix('系统架构：读写分离 + 分库分表。')?.label).toBe('系统架构：');
    expect(splitProjectPlainPrefix('项目简介：')).toBeNull();
    expect(splitProjectPlainPrefix('项目职责：负责核心调度模块。')).toBeNull();
    expect(splitProjectPlainPrefix('负责核心交易链路设计与落地。')).toBeNull();
  });
});

describe('isProjectDescriptiveLabel', () => {
  it('recognises canonical descriptive heads and verbatim descriptive names', () => {
    expect(isProjectDescriptiveLabel('项目背景：')).toBe(true);
    expect(isProjectDescriptiveLabel('技术栈')).toBe(true);
    expect(isProjectDescriptiveLabel('项目描述：')).toBe(true);
    expect(isProjectDescriptiveLabel('系统架构')).toBe(true);
  });

  it('rejects duty/highlight labels', () => {
    expect(isProjectDescriptiveLabel('项目职责：')).toBe(false);
    expect(isProjectDescriptiveLabel('项目亮点：')).toBe(false);
  });
});

describe('joinInlineBodyRows', () => {
  it('joins all-ASCII stacks with ", " and CJK stacks with 、', () => {
    expect(joinInlineBodyRows(['Spring Boot', 'Nacos', 'Kafka'])).toBe('Spring Boot, Nacos, Kafka');
    expect(joinInlineBodyRows(['Java', 'Redis 缓存'])).toBe('Java、Redis 缓存');
  });
});

it('canonicalizes inline legacy prefixes inside block rows', () => {
  const blocks = buildDescriptionBlocks(
    ['技术难点及亮点：实时时延从 800ms 降到 600ms。'],
    ['plain'],
    { canonicalizeLabels: true }
  );
  expect(blocks).toHaveLength(1);
  expect(blocks[0]).toMatchObject({
    kind: 'list',
    rows: [{ desc: '项目亮点：实时时延从 800ms 降到 600ms。', numbered: false }],
  });
});

describe('nested heads inside duty/highlight modules', () => {
  const items = [
    '项目亮点：',
    '重大生产环境问题解决：',
    '成功解决明细下载系统卡死问题。',
    '明细下载过程中超时重试机制生效。',
    '性能调优：',
    '通过索引优化和SQL重构降低耗时。',
    '利用Redis做缓存缩短响应时间。',
    'cpu飙升问题：',
    '由于某个省数据量突然飙升。',
    '通过linux命令top、jstack找出慢逻辑。',
  ];
  // Head 1 owns plain details (legacy unnumbered), head 2 owns bullet
  // details (the explicit "render as an ordered list" reformat -> level 2
  // composite markers), head 3 is plain again.
  const styles = [
    'label',
    'label',
    'plain',
    'plain',
    'label',
    'bullet',
    'bullet',
    'label',
    'plain',
    'plain',
  ] as const;

  it('keeps every nested head as a level-1 point and numbers ALL details at level 2', () => {
    const blocks = buildDescriptionBlocks(items, [...styles], { canonicalizeLabels: true });

    // One module label plus ONE list spanning all three nested heads.
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目亮点：' });
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].rows).toEqual([
      // Every head is the bold level-1 point; head numbers run 1, 2, 3.
      { desc: '重大生产环境问题解决：', numbered: true, bold: true },
      // Layered content under a sub-module is always an ordered list: rows
      // stored "plain" still number as level-2 sub-points (1.1, 1.2, …).
      { desc: '成功解决明细下载系统卡死问题。', numbered: true, level: 2 },
      { desc: '明细下载过程中超时重试机制生效。', numbered: true, level: 2 },
      { desc: '性能调优：', numbered: true, bold: true },
      // Bullet details indent as level 2; the renderer composes 2.1 / 2.2.
      { desc: '通过索引优化和SQL重构降低耗时。', numbered: true, level: 2 },
      { desc: '利用Redis做缓存缩短响应时间。', numbered: true, level: 2 },
      { desc: 'cpu飙升问题：', numbered: true, bold: true },
      { desc: '由于某个省数据量突然飙升。', numbered: true, level: 2 },
      { desc: '通过linux命令top、jstack找出慢逻辑。', numbered: true, level: 2 },
    ]);
  });

  it('tags every detail row level 2 when all nested-head details are bullets', () => {
    const bulletStyles = [
      'label',
      'label',
      'bullet',
      'bullet',
      'label',
      'bullet',
      'bullet',
    ] as const;
    const blocks = buildDescriptionBlocks(items.slice(0, 7), [...bulletStyles], {
      canonicalizeLabels: true,
    });

    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list']);
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].rows).toEqual([
      { desc: '重大生产环境问题解决：', numbered: true, bold: true },
      { desc: '成功解决明细下载系统卡死问题。', numbered: true, level: 2 },
      { desc: '明细下载过程中超时重试机制生效。', numbered: true, level: 2 },
      { desc: '性能调优：', numbered: true, bold: true },
      { desc: '通过索引优化和SQL重构降低耗时。', numbered: true, level: 2 },
      { desc: '利用Redis做缓存缩短响应时间。', numbered: true, level: 2 },
    ]);
  });

  it('keeps unknown headings as module labels without canonicalizeLabels (work sites)', () => {
    const blocks = buildDescriptionBlocks(['难点/方案/效果：', '表格内容'], ['label', 'plain']);
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '难点/方案/效果：' });
  });

  it('does not nest an unknown heading before any recognized module label', () => {
    const blocks = buildDescriptionBlocks(
      ['性能调优：', '通过索引优化降低耗时。', '项目亮点：', '另一项成果。'],
      ['label', 'bullet', 'label', 'bullet'],
      { canonicalizeLabels: true }
    );
    // The first unknown heading is a standalone label; only after 项目亮点 is
    // seen could a following unknown heading become a nested head.
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list', 'label', 'list']);
  });

  it('restarts nested-head numbering at each recognized module label', () => {
    const blocks = buildDescriptionBlocks(
      ['项目职责：', '模块一：', '负责核心开发。', '项目亮点：', '重大问题：', '解决卡死问题。'],
      ['label', 'label', 'plain', 'label', 'label', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list', 'label', 'list']);
    if (blocks[1].kind !== 'list' || blocks[3].kind !== 'list') {
      throw new Error('expected two list blocks');
    }
    expect(blocks[1].rows[0]).toEqual({ desc: '模块一：', numbered: true, bold: true });
    expect(blocks[3].rows[0]).toEqual({ desc: '重大问题：', numbered: true, bold: true });
  });

  it('never treats unknown headings inside a descriptive body as nested heads', () => {
    const blocks = buildDescriptionBlocks(
      ['项目背景：', '业务规模：', '日均18亿条明细。'],
      ['label', 'label', 'plain'],
      { canonicalizeLabels: true }
    );
    // The unknown heading becomes a standalone label rather than a numbered
    // point; its content row opens an ordinary list (the body block was
    // never created — body blocks open lazily on their first content row).
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'label', 'list']);
  });

  it('renders bare group headings as level-1 bold points with level-2 details', () => {
    // Real upload shape: a "核心职责与成果：" module whose bold sub-headings
    // carry no colon and are stored as plain rows interleaved with bullets.
    // The renderer must produce 1. head + 1.1/1.2 details, 2. head + ...
    const blocks = buildDescriptionBlocks(
      [
        '核心职责与成果：',
        '架构演进与技术债务治理',
        '担任商城板块技术负责人，主导架构设计与版本迭代。',
        '梳理历史技术债务，建立代码质量规范。',
        '主导促销中心组件设计',
        '将营销活动流程组件化，提升代码复用性。',
        '新活动接入周期缩短 30%，支撑十万级 GMV 交易。',
      ],
      ['label', 'plain', 'bullet', 'bullet', 'plain', 'bullet', 'bullet'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目职责：' });
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].rows).toEqual([
      { desc: '架构演进与技术债务治理', numbered: true, bold: true },
      { desc: '担任商城板块技术负责人，主导架构设计与版本迭代。', numbered: true, level: 2 },
      { desc: '梳理历史技术债务，建立代码质量规范。', numbered: true, level: 2 },
      { desc: '主导促销中心组件设计', numbered: true, bold: true },
      { desc: '将营销活动流程组件化，提升代码复用性。', numbered: true, level: 2 },
      { desc: '新活动接入周期缩短 30%，支撑十万级 GMV 交易。', numbered: true, level: 2 },
    ]);
  });

  it('renders bullet-stored group titles as level-1 bold points (generalized rule)', () => {
    // 邹利平.pdf 沃尔沃内领商城 shape: the weak model stored EVERY row as a
    // bullet, including the bare group titles. The structural planner still
    // turns the titles into bold level-1 heads and their points into 1.1/1.2.
    const blocks = buildDescriptionBlocks(
      [
        '项目职责',
        '系统从 0 到 1 搭建',
        '主导内领商城架构设计与核心模块开发，负责需求评审与落地。',
        '设计并实现三方系统对接的高可用方案',
        '履约层策略化重构',
        '基于策略模式重构订单履约层，新增履约方式零侵入。',
        '自研轻量级流程编排框架',
        '将业务流程拆解为可复用原子节点并支持多流程共享',
        '商品初始化同步方案',
        '通过分类治理与多轮对账，保障商品同步准确率 100%。',
      ],
      [
        'label',
        'bullet',
        'bullet',
        'bullet',
        'bullet',
        'bullet',
        'bullet',
        'bullet',
        'bullet',
        'bullet',
      ],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list']);
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].rows).toEqual([
      { desc: '系统从 0 到 1 搭建', numbered: true, bold: true },
      {
        desc: '主导内领商城架构设计与核心模块开发，负责需求评审与落地。',
        numbered: true,
        level: 2,
      },
      { desc: '设计并实现三方系统对接的高可用方案', numbered: true, level: 2 },
      { desc: '履约层策略化重构', numbered: true, bold: true },
      { desc: '基于策略模式重构订单履约层，新增履约方式零侵入。', numbered: true, level: 2 },
      { desc: '自研轻量级流程编排框架', numbered: true, bold: true },
      { desc: '将业务流程拆解为可复用原子节点并支持多流程共享', numbered: true, level: 2 },
      { desc: '商品初始化同步方案', numbered: true, bold: true },
      { desc: '通过分类治理与多轮对账，保障商品同步准确率 100%。', numbered: true, level: 2 },
    ]);
  });

  it('keeps a flat peer bullet list at level 1 without any bold head', () => {
    // 叶宏汉.pdf shape: no head/detail alternation — every point stays level 1.
    const blocks = buildDescriptionBlocks(
      [
        '项目职责：',
        '负责内网穿透项目单连接多路复用通信架构的设计与实现',
        '负责自定义二进制通信协议设计与帧解析实现',
        '负责高吞吐传输与反压机制建设',
        '负责分布式长连接注册与路由方案设计',
      ],
      ['label', 'bullet', 'bullet', 'bullet', 'bullet'],
      { canonicalizeLabels: true }
    );
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    expect(blocks[1].rows.some((row) => row.bold)).toBe(false);
    expect(blocks[1].rows.map((row) => row.level ?? 1)).toEqual([1, 1, 1, 1]);
  });

  it('does not promote source-numbered rows, long prose, bullets or trailing rows as heads', () => {
    const blocks = buildDescriptionBlocks(
      [
        '项目职责：',
        '2）机审',
        '作为后端技术组长，牵头项目从调研到运维的全流程交付工作。',
        '技术方案设计',
        '收尾工作',
      ],
      ['label', 'plain', 'plain', 'bullet', 'plain'],
      { canonicalizeLabels: true }
    );
    if (blocks[1].kind !== 'list') throw new Error('expected list block');
    // No bold nested heads: the enumeration row, the long sentence, the short
    // bullet-styled point and the trailing plain row all stay ordinary points.
    expect(blocks[1].rows.some((row) => row.bold)).toBe(false);
    expect(blocks[1].rows.map((row) => row.level ?? 1)).toEqual([1, 1, 1, 1]);
  });

  it('does not nest bare headings at non-project render sites', () => {
    // Without canonicalizeLabels (work/custom sites) the bare row stays an
    // unnumbered plain row instead of becoming a numbered bold head.
    const blocks = buildDescriptionBlocks(
      ['架构演进与技术债务治理', '负责架构设计。'],
      ['plain', 'bullet']
    );
    if (blocks[0].kind !== 'list') throw new Error('expected list block');
    expect(blocks[0].rows).toEqual([
      { desc: '架构演进与技术债务治理', numbered: false },
      { desc: '负责架构设计。', numbered: true },
    ]);
  });

  it('renders 项目成效 as a peer module label instead of a nested head of 项目亮点', () => {
    // Real upload (resume de8ce72b): in the source PDF 技术栈/项目背景/我的职责/
    // 项目亮点/项目成效 are same-level headings. The renderer used to treat the
    // unknown 项目成效： heading as a bold numbered point ("4.") inside the
    // 项目亮点 module, with its prose numbered "4.1". Outcome/effectiveness
    // labels are known sub-labels, so they open their own peer module instead.
    const blocks = buildDescriptionBlocks(
      [
        '项目亮点：',
        '使用 Scala 编写 Spark Streaming 作业承接多源数据采集。',
        '用 Spark SQL 构建格式校验与逻辑校验两层规则。',
        '将报送结果写入 HBase，兼顾批量写入性能与秒级查询。',
        '项目成效：',
        '平台稳定支撑多家金融机构的数据报送，错报率下降约 70%。',
      ],
      ['label', 'bullet', 'bullet', 'bullet', 'label', 'plain'],
      { canonicalizeLabels: true }
    );

    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list', 'label', 'list']);
    expect(blocks[0]).toMatchObject({ kind: 'label', desc: '项目亮点：' });
    // The big-four module keeps its numbered list; the peer outcome module
    // opens a FLUSH list whose unnumbered prose aligns with the label edge.
    if (blocks[1].kind !== 'list' || blocks[3].kind !== 'list') {
      throw new Error('expected two list blocks');
    }
    expect(blocks[1].flush).toBe(false);
    expect(blocks[3].flush).toBe(true);
    // 项目成效 keeps its verbatim name: it is a peer label, never canonicalized
    // into 项目亮点.
    expect(blocks[2]).toEqual({ kind: 'label', desc: '项目成效：', descriptive: false });
    // The outcome prose is an ordinary unnumbered row of its own module — not a
    // bold head and not a level-2 sub-point of 项目亮点.
    expect(blocks[3].rows).toEqual([
      { desc: '平台稳定支撑多家金融机构的数据报送，错报率下降约 70%。', numbered: false },
    ]);
    expect(blocks[3].rows.some((row) => row.bold || row.level === 2)).toBe(false);
  });

  it('treats every 成效/效果 outcome alias as a peer module label', () => {
    for (const outcomeLabel of ['项目效果：', '工作成效：', '落地效果：', '量化成效：']) {
      const blocks = buildDescriptionBlocks(
        ['项目亮点：', '完成核心链路重构。', outcomeLabel, '交付周期缩短 40%。'],
        ['label', 'bullet', 'label', 'plain'],
        { canonicalizeLabels: true }
      );
      expect(blocks.map((block) => block.kind)).toEqual(['label', 'list', 'label', 'list']);
      expect(blocks[2]).toMatchObject({ kind: 'label', desc: outcomeLabel });
      if (blocks[3].kind !== 'list') throw new Error('expected list block');
      expect(blocks[3].flush).toBe(true);
      expect(blocks[3].rows).toEqual([{ desc: '交付周期缩短 40%。', numbered: false }]);
    }
  });

  it('keeps numbered rows inside a flush peer module while dropping only the empty gutter', () => {
    // Real upload shape (e.g. 责任描述 peers seen in stored resumes): a
    // non-big-four label can own bullets. Numbered rows keep their markers at
    // the label edge; only unnumbered prose rows go flush.
    const blocks = buildDescriptionBlocks(
      [
        '项目亮点：',
        '完成核心链路重构。',
        '责任描述：',
        '参与异步任务链路重构，基于 RabbitMQ 实现任务异步处理。',
        '参与流程引擎底层设计，支持可插拔的流程扩展。',
      ],
      ['label', 'bullet', 'label', 'bullet', 'plain'],
      { canonicalizeLabels: true }
    );
    expect(blocks.map((block) => block.kind)).toEqual(['label', 'list', 'label', 'list']);
    if (blocks[1].kind !== 'list' || blocks[3].kind !== 'list') {
      throw new Error('expected two list blocks');
    }
    expect(blocks[1].flush).toBe(false);
    expect(blocks[3].flush).toBe(true);
    expect(blocks[3].rows).toEqual([
      { desc: '参与异步任务链路重构，基于 RabbitMQ 实现任务异步处理。', numbered: true },
      { desc: '参与流程引擎底层设计，支持可插拔的流程扩展。', numbered: false },
    ]);
  });

  it('never marks big-four or loose lists flush, and stays non-flush off project sites', () => {
    const projectBlocks = buildDescriptionBlocks(
      ['项目职责：', '负责核心模块。', '项目背景：', '面向多系统重复建设问题。'],
      ['label', 'bullet', 'label', 'plain'],
      { canonicalizeLabels: true }
    );
    // 项目职责 list and the descriptive body are neither peer-flush.
    if (projectBlocks[1].kind !== 'list') throw new Error('expected duty list');
    expect(projectBlocks[1].flush).toBe(false);
    expect(projectBlocks[3].kind).toBe('body');

    // Loose bullets with no label above them are never flush.
    const loose = buildDescriptionBlocks(['第一项。', '第二项。'], ['bullet', 'bullet'], {
      canonicalizeLabels: true,
    });
    if (loose[0].kind !== 'list') throw new Error('expected loose list');
    expect(loose[0].flush).toBe(false);

    // Work/custom sites (no canonicalize flag) keep every list non-flush even
    // when a peer label name appears.
    const workBlocks = buildDescriptionBlocks(
      ['项目成效：', '交付周期缩短 40%。'],
      ['label', 'plain']
    );
    if (workBlocks[1].kind !== 'list') throw new Error('expected work list');
    expect(workBlocks[1].flush).toBe(false);
  });
});
