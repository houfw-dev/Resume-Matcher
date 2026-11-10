import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DescriptionList } from '@/components/resume/description-list';

describe('DescriptionList', () => {
  it('renders every point as an ordered numbered list', () => {
    render(<DescriptionList items={['First responsibility', 'Second responsibility']} />);

    const list = screen.getByRole('list');
    expect(list.tagName).toBe('OL');

    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]).getByText('1.')).toBeInTheDocument();
    expect(within(rows[1]).getByText('2.')).toBeInTheDocument();
  });

  it('keeps plain rows unnumbered without consuming a number', () => {
    render(
      <DescriptionList
        items={['Subheading row', 'First numbered point', 'Second numbered point']}
        styles={['plain', 'bullet', 'bullet']}
      />
    );

    const rows = screen.getAllByRole('listitem');

    // The plain row reserves the gutter but carries no visible number.
    expect(rows[0]).toHaveTextContent('Subheading row');
    expect(within(rows[0]).queryByText(/^\d+\.$/)).not.toBeInTheDocument();
    expect(within(rows[1]).getByText('1.')).toBeInTheDocument();
    expect(within(rows[2]).getByText('2.')).toBeInTheDocument();
  });

  it('strips source-carried numbering so lists are not numbered twice', () => {
    render(
      <DescriptionList items={['1、配合产品经理评审', '2) 开发核心模块', '① 保障线上稳定']} />
    );

    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('1.');
    expect(rows[0]).toHaveTextContent('配合产品经理评审');
    expect(rows[0]).not.toHaveTextContent('1、');
    expect(rows[1]).not.toHaveTextContent('2)');
    expect(rows[1]).toHaveTextContent('开发核心模块');
    expect(rows[2]).not.toHaveTextContent('①');
    expect(rows[2]).toHaveTextContent('保障线上稳定');
  });

  it('renders label rows bold, with each sub-module list restarting at 1', () => {
    render(
      <DescriptionList
        items={['负责内容', '第一点', '第二点', '难点与解决', '第三点']}
        styles={['label', 'bullet', 'bullet', 'label', 'bullet']}
      />
    );

    // Bold sub-module headings carry the marker the pagination/print rules
    // bind lists to, and consume no number themselves.
    const firstLabel = screen.getByText('负责内容');
    const labelRow = firstLabel.closest('[data-sub-label]');
    expect(labelRow).not.toBeNull();
    expect(labelRow?.className).toContain('resume-sub-label');
    expect(within(labelRow as HTMLElement).queryByText(/^\d+\.$/)).not.toBeInTheDocument();

    // Two independent <ol> — the second group restarts numbering at 1 instead
    // of continuing the first group's 1..2 as 3.
    const lists = screen.getAllByRole('list');
    expect(lists).toHaveLength(2);
    const firstGroup = within(lists[0]).getAllByRole('listitem');
    expect(within(firstGroup[0]).getByText('1.')).toBeInTheDocument();
    expect(within(firstGroup[1]).getByText('2.')).toBeInTheDocument();
    const secondGroup = within(lists[1]).getAllByRole('listitem');
    expect(within(secondGroup[0]).getByText('1.')).toBeInTheDocument();

    // The owned list is indented one number gutter (markers align with the
    // label's text edge).
    expect(lists[1].className).toContain('resume-list-indented');
  });

  it('keeps work-entry labels verbatim unless canonicalizeLabels is set', () => {
    const { container, rerender } = render(
      <DescriptionList
        items={['工作职责：', 'First point', '项目成果：', 'Outcome point']}
        styles={['label', 'bullet', 'label', 'bullet']}
      />
    );

    // Default (work/custom render sites): source label names are untouched.
    expect(container.textContent).toContain('工作职责：');
    expect(container.textContent).toContain('项目成果：');

    // Project render sites: duty/highlight aliases collapse to two names.
    rerender(
      <DescriptionList
        items={['工作职责：', 'First point', '项目成果：', 'Outcome point']}
        styles={['label', 'bullet', 'label', 'bullet']}
        canonicalizeLabels
      />
    );
    expect(container.textContent).toContain('项目职责：');
    expect(container.textContent).toContain('项目亮点：');
    expect(container.textContent).not.toContain('工作职责：');
    expect(container.textContent).not.toContain('项目成果：');
  });

  it('promotes legacy plain sub-headings to bold labels but leaves prose plain', () => {
    render(
      <DescriptionList
        items={['项目背景：AIGC 系列产品，提供内容生成能力。', '项目职责：', '负责核心模块']}
        styles={['plain', 'plain', 'bullet']}
      />
    );

    // The prose row stays an unnumbered plain row in the loose list…
    const plainRow = screen.getByText('项目背景：AIGC 系列产品，提供内容生成能力。').closest('li');
    expect(within(plainRow as HTMLElement).queryByText(/^\d+\.$/)).not.toBeInTheDocument();

    // …while the heading-only row becomes a bold label owning an indented,
    // restart-numbered list.
    const label = screen.getByText('项目职责：').closest('[data-sub-label]');
    expect(label).not.toBeNull();
    const lists = screen.getAllByRole('list');
    expect(lists[1].className).toContain('resume-list-indented');
    expect(within(lists[1]).getByText('1.')).toBeInTheDocument();
  });

  it('renders descriptive project labels with a flush unnumbered body block', () => {
    const { container } = render(
      <DescriptionList
        items={['项目背景：', '多个子系统重复建设。', '技术栈：', 'SpringBoot + Redis。']}
        styles={['plain', 'plain', 'plain', 'plain']}
        canonicalizeLabels
      />
    );

    const labels = container.querySelectorAll('[data-sub-label]');
    expect(labels).toHaveLength(2);
    labels.forEach((label) => expect(label.hasAttribute('data-descriptive')).toBe(true));
    expect(labels[0]).toHaveTextContent('项目背景：');
    expect(labels[1]).toHaveTextContent('技术栈：');

    // Content sits in body blocks aligned to the label TEXT edge (3ch, one
    // gutter less than indented duty lists), with no number markers.
    const bodies = container.querySelectorAll('[data-sub-body]');
    expect(bodies).toHaveLength(2);
    bodies.forEach((body) => {
      expect(body.className).toContain('resume-sub-body');
      expect(body.className).not.toContain('resume-list-indented');
      expect(body.querySelectorAll('[data-body-row]')).toHaveLength(1);
      expect(body.textContent).not.toMatch(/\d\./);
    });
    expect(bodies[0]).toHaveTextContent('多个子系统重复建设。');
    expect(bodies[1]).toHaveTextContent('SpringBoot + Redis。');
  });

  it('splits glued descriptive rows into a bold canonical label plus body row', () => {
    const { container } = render(
      <DescriptionList
        items={['项目简介：面向家庭宽带装维场景。', '技术列表：SpringAI、RAG。']}
        styles={['bullet', 'bullet']}
        canonicalizeLabels
      />
    );

    const labels = container.querySelectorAll('[data-sub-label]');
    expect(labels).toHaveLength(2);
    expect(labels[0]).toHaveTextContent('项目背景：');
    expect(labels[1]).toHaveTextContent('技术栈：');
    const bodies = container.querySelectorAll('[data-sub-body]');
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toHaveTextContent('面向家庭宽带装维场景。');
    expect(bodies[1]).toHaveTextContent('SpringAI、RAG。');
    // No ordered lists / numbers for descriptive content.
    expect(container.querySelectorAll('ol')).toHaveLength(0);
  });

  it('aligns project labels, duty numbers and body text with the project name edge when flushLabels is set', () => {
    const { container } = render(
      <DescriptionList
        items={[
          '项目背景：',
          '面向装维场景。',
          '项目职责：',
          '负责核心调度模块。',
          '项目亮点：',
          '时延降到 600ms。',
          '技术栈：',
          'SpringAI、RAG。',
        ]}
        styles={['plain', 'plain', 'label', 'bullet', 'label', 'bullet', 'label', 'plain']}
        canonicalizeLabels
        flushLabels
      />
    );

    // Bold labels carry no 3ch number-gutter spacer, so their text starts at
    // the project item (project name) edge.
    const labels = Array.from(container.querySelectorAll('[data-sub-label]'));
    expect(labels).toHaveLength(4);
    labels.forEach((label) => {
      expect(label.querySelector('span[aria-hidden="true"]')).toBeNull();
    });

    // Label-owned duty lists lose the extra indent: their numbers start at
    // the same edge as the bold labels.
    const lists = Array.from(container.querySelectorAll('ol'));
    lists.forEach((list) => expect(list.className).not.toContain('resume-list-indented'));

    // Descriptive bodies are flush too, keeping body text aligned with the
    // 项目背景/技术栈 labels.
    const bodies = Array.from(container.querySelectorAll('[data-sub-body]'));
    expect(bodies).toHaveLength(2);
    bodies.forEach((body) => {
      expect(body.className).toContain('resume-sub-body');
      expect(body.className).toContain('resume-sub-body-flush');
    });
  });

  it('aligns peer-module prose (项目成效) flush with its label and keeps numbered markers', () => {
    const { container } = render(
      <DescriptionList
        items={[
          '项目亮点：',
          '用 Spark SQL 构建两层校验规则。',
          '责任描述：',
          '参与异步任务链路重构，基于 RabbitMQ 实现任务异步处理。',
          '参与流程引擎底层设计，支持可插拔的流程扩展。',
          '项目成效：',
          '错报率下降约 70%，客服核查工作量明显下降。',
        ]}
        styles={['label', 'bullet', 'label', 'bullet', 'plain', 'label', 'plain']}
        canonicalizeLabels
        flushLabels
      />
    );

    const lists = Array.from(container.querySelectorAll('ol'));
    // Three list blocks: 项目亮点 (1 numbered row), the mixed peer module (1
    // numbered + 1 plain row), 项目成效 (1 plain prose row).
    expect(lists).toHaveLength(3);

    // Highlight module keeps its 3ch number marker.
    expect(lists[0].querySelectorAll('span[aria-hidden="true"]')).toHaveLength(1);

    // Mixed peer module: the bullet keeps its marker span, the plain row
    // renders NO gutter span so its text starts at the label edge.
    const mixedItems = lists[1].querySelectorAll('li');
    expect(mixedItems[0].querySelectorAll('span[aria-hidden="true"]')).toHaveLength(1);
    expect(mixedItems[1].querySelectorAll('span[aria-hidden="true"]')).toHaveLength(0);

    // 项目成效 prose: zero gutter spans — exactly aligned with its bold label.
    const outcomeItems = lists[2].querySelectorAll('li');
    expect(outcomeItems).toHaveLength(1);
    expect(outcomeItems[0].querySelectorAll('span[aria-hidden="true"]')).toHaveLength(0);
    expect(outcomeItems[0].textContent).toContain('错报率下降约 70%');
  });

  it('keeps the 3ch label gutter and indented/3ch body layout without flushLabels (work sites)', () => {
    const { container } = render(
      <DescriptionList
        items={['项目背景：', '背景一行。', '负责内容', '负责核心模块。']}
        styles={['plain', 'plain', 'label', 'bullet']}
        canonicalizeLabels
      />
    );

    const label = container.querySelector('[data-sub-label]') as HTMLElement;
    expect(label.querySelector('span[aria-hidden="true"]')).not.toBeNull();
    expect(container.querySelector('ol')?.className).toContain('resume-list-indented');
    const body = container.querySelector('[data-sub-body]') as HTMLElement;
    expect(body.className).toContain('resume-sub-body');
    expect(body.className).not.toContain('resume-sub-body-flush');
  });

  it('keeps content uniformly left-aligned (never justified)', () => {
    render(<DescriptionList items={['Responsibility one', 'Responsibility two']} />);

    const list = screen.getByRole('list');
    expect(list).toHaveClass('text-left');
    for (const row of screen.getAllByRole('listitem')) {
      expect(row).toHaveClass('text-left');
    }
  });
});

describe('DescriptionList tech-stack body', () => {
  it('merges tech-stack rows into one inline-wrapped body row', () => {
    const { container } = render(
      <DescriptionList
        items={['技术栈：', 'Spring Boot', 'Nacos', 'Kafka', 'Redis']}
        styles={['plain', 'plain', 'plain', 'plain', 'plain']}
        canonicalizeLabels
      />
    );

    // All four stack entries live in ONE body block and render as a single
    // inline-wrapped line (", "-joined ASCII stack), not one line per entry.
    const bodies = container.querySelectorAll('[data-sub-body]');
    expect(bodies).toHaveLength(1);
    const bodyRows = bodies[0].querySelectorAll('[data-body-row]');
    expect(bodyRows).toHaveLength(1);
    expect(bodyRows[0]).toHaveTextContent('Spring Boot, Nacos, Kafka, Redis');
    // No list numbers for the merged stack.
    expect(container.querySelectorAll('ol')).toHaveLength(0);
  });

  it('keeps prose background bodies stacked one paragraph per row', () => {
    const { container } = render(
      <DescriptionList
        items={['项目背景：', '多个子系统重复建设。', '应急场景下数据割裂。']}
        styles={['plain', 'plain', 'plain']}
        canonicalizeLabels
      />
    );

    // 项目背景 is prose, not an enumeration: each sentence keeps its own row.
    const bodies = container.querySelectorAll('[data-sub-body]');
    expect(bodies).toHaveLength(1);
    const bodyRows = bodies[0].querySelectorAll('[data-body-row]');
    expect(bodyRows).toHaveLength(2);
    expect(bodyRows[0]).toHaveTextContent('多个子系统重复建设。');
    expect(bodyRows[1]).toHaveTextContent('应急场景下数据割裂。');
  });
});

describe('DescriptionList nested highlight heads', () => {
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

  it('renders heads as level-1 points and ALL details as level-2 sub-points', () => {
    render(<DescriptionList items={items} styles={[...styles]} canonicalizeLabels />);

    // All three heads share the 项目亮点 module's single <ol>; the module
    // label itself is not a list row. Heads are bold level-1 points 1./2./3.;
    // every detail indents and takes a composite marker (1.1/1.2, 2.1/2.2,
    // 3.1/3.2) — layered content under a sub-module is always an ordered
    // list, even when the row is stored "plain".
    const lists = screen.getAllByRole('list');
    expect(lists).toHaveLength(1);
    const rows = screen.getAllByRole('listitem');
    const level1Markers = rows.map(
      (row) => within(row).queryByText(/^\d+\.$/)?.textContent ?? null
    );
    expect(level1Markers).toEqual(['1.', null, null, '2.', null, null, '3.', null, null]);
    const subMarkers = rows.map(
      (row) => within(row).queryByText(/^\d+\.\d+$/)?.textContent ?? null
    );
    expect(subMarkers).toEqual([null, '1.1', '1.2', null, '2.1', '2.2', null, '3.1', '3.2']);

    // Every head text is bold and carries its level-1 number.
    for (const [head, marker] of [
      ['重大生产环境问题解决：', '1.'],
      ['性能调优：', '2.'],
      ['cpu飙升问题：', '3.'],
    ]) {
      const headRow = screen.getByText(head).closest('li');
      expect(headRow?.querySelector('[data-nested-head]')).not.toBeNull();
      expect(within(headRow as HTMLElement).getByText(marker)).toBeInTheDocument();
    }
    expect(
      screen
        .getByText('通过索引优化和SQL重构降低耗时。')
        .closest('li')
        ?.querySelector('[data-nested-head]')
    ).toBeNull();

    // Level-2 rows indent one extra number gutter (two 3ch spacer/marker
    // spans); level-1 rows keep the single gutter.
    const firstSubRow = screen
      .getByText('通过索引优化和SQL重构降低耗时。')
      .closest('li') as HTMLElement;
    expect(firstSubRow.querySelectorAll('span[aria-hidden="true"]')).toHaveLength(2);
    const firstHeadRow = screen.getByText('重大生产环境问题解决：').closest('li') as HTMLElement;
    expect(firstHeadRow.querySelectorAll('span[aria-hidden="true"]')).toHaveLength(1);
  });

  it('composes sub-markers per head when two nested heads both own bullets', () => {
    const bulletItems = [
      '项目亮点：',
      '重大生产环境问题解决：',
      '成功解决明细下载系统卡死问题。',
      '明细下载过程中超时重试机制生效。',
      '性能调优：',
      '通过索引优化和SQL重构降低耗时。',
      '利用Redis做缓存缩短响应时间。',
    ];
    const bulletStyles = [
      'label',
      'label',
      'bullet',
      'bullet',
      'label',
      'bullet',
      'bullet',
    ] as const;
    render(<DescriptionList items={bulletItems} styles={[...bulletStyles]} canonicalizeLabels />);

    const rows = screen.getAllByRole('listitem');
    const level1Markers = rows.map(
      (row) => within(row).queryByText(/^\d+\.$/)?.textContent ?? null
    );
    expect(level1Markers).toEqual(['1.', null, null, '2.', null, null]);
    const subMarkers = rows.map(
      (row) => within(row).queryByText(/^\d+\.\d+$/)?.textContent ?? null
    );
    expect(subMarkers).toEqual([null, '1.1', '1.2', null, '2.1', '2.2']);
  });
});
