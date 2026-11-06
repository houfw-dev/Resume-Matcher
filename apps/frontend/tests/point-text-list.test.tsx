import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OrderedStringList, PointTextList, splitPoints } from '@/components/resume/point-text-list';
import { DynamicResumeSection } from '@/components/resume/dynamic-resume-section';
import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';

describe('splitPoints', () => {
  it('splits on newlines, trims whitespace, and drops empty lines', () => {
    expect(splitPoints('第一点\n 第二点 \r\n\n第三点\r\n')).toEqual(['第一点', '第二点', '第三点']);
  });

  it('returns an empty array for blank text', () => {
    expect(splitPoints('')).toEqual([]);
    expect(splitPoints('  \n \r\n ')).toEqual([]);
  });
});

describe('PointTextList', () => {
  it('renders nothing for empty text', () => {
    const { container } = render(<PointTextList text="" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a single point as a left-aligned paragraph', () => {
    render(<PointTextList text={'多年后端开发经验，熟悉分布式系统。'} />);
    const paragraph = screen.getByText('多年后端开发经验，熟悉分布式系统。');
    expect(paragraph.tagName).toBe('P');
    expect(paragraph).toHaveClass('text-left');
    expect(paragraph.closest('ol')).toBeNull();
  });

  it('renders multiple points as an ordered, left-aligned list', () => {
    const { container } = render(<PointTextList text={'沟通能力强\n学习能力强\n抗压能力强'} />);

    const list = screen.getByRole('list');
    expect(list.tagName).toBe('OL');
    expect(list).toHaveClass('text-left');

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toMatch(/^1\./);
    expect(items[0].textContent).toContain('沟通能力强');
    expect(items[1].textContent).toMatch(/^2\./);
    expect(items[2].textContent).toMatch(/^3\./);
    expect(container.textContent).not.toContain('text-justify');
  });

  it('strips source-carried numbering so points are not numbered twice', () => {
    render(
      <PointTextList text={'1、大厂背景，熟悉高并发\n2) 主导支付链路重构\n③ Java/Go 双技术栈'} />
    );

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).not.toContain('1、');
    expect(items[0].textContent).toContain('大厂背景，熟悉高并发');
    expect(items[1].textContent).not.toContain('2)');
    expect(items[1].textContent).toContain('主导支付链路重构');
    expect(items[2].textContent).not.toContain('③');
    expect(items[2].textContent).toContain('Java/Go 双技术栈');
  });

  it('strips Chinese ordinal and bullet markers carried from the source', () => {
    render(<PointTextList text={'一、踏实稳重\n• 持续学习'} />);

    const items = screen.getAllByRole('listitem');
    expect(items[0].textContent).not.toContain('一、');
    expect(items[0].textContent).toContain('踏实稳重');
    expect(items[1].textContent).not.toContain('•');
    expect(items[1].textContent).toContain('持续学习');
  });
});

describe('PointTextList in custom sections', () => {
  const selfEvalMeta: SectionMeta = {
    id: 'custom_eval',
    key: 'custom_eval',
    displayName: '自我评价',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 6,
  };

  const otherTextMeta: SectionMeta = {
    id: 'custom_volunteer',
    key: 'custom_volunteer',
    displayName: '志愿服务',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 7,
  };

  it('renders 自我评价 as an ordered list', () => {
    const data = {
      customSections: {
        custom_eval: { sectionType: 'text', text: '1、踏实稳重\n2、持续学习' },
      },
    } as ResumeData;

    const { container } = render(
      <DynamicResumeSection sectionMeta={selfEvalMeta} resumeData={data} />
    );

    const list = container.querySelector('ol');
    expect(list).not.toBeNull();
    expect(list).toHaveClass('text-left');
    expect(list?.querySelectorAll('li')).toHaveLength(2);
    expect(container.textContent).toContain('踏实稳重');
  });

  it('keeps single-line custom text as a left-aligned paragraph', () => {
    const data = {
      customSections: {
        custom_volunteer: { sectionType: 'text', text: '长期参与社区志愿服务。' },
      },
    } as ResumeData;

    const { container } = render(
      <DynamicResumeSection sectionMeta={otherTextMeta} resumeData={data} />
    );

    expect(container.querySelector('ol')).toBeNull();
    const paragraph = screen.getByText('长期参与社区志愿服务。');
    expect(paragraph.tagName).toBe('P');
    expect(paragraph).toHaveClass('text-left');
  });

  it('renders multi-line custom text (any section) as an ordered list', () => {
    const data = {
      customSections: {
        custom_volunteer: {
          sectionType: 'text',
          text: '2024 社区代码贡献者\n组织线下技术分享 6 场',
        },
      },
    } as ResumeData;

    const { container } = render(
      <DynamicResumeSection sectionMeta={otherTextMeta} resumeData={data} />
    );

    const list = container.querySelector('ol');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(2);
    expect(container.textContent).toContain('组织线下技术分享 6 场');
  });
});

describe('OrderedStringList', () => {
  it('renders nothing for an empty list', () => {
    const { container } = render(<OrderedStringList items={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a single entry as a paragraph', () => {
    render(<OrderedStringList items={['PMP 认证']} />);
    const paragraph = screen.getByText('PMP 认证');
    expect(paragraph.tagName).toBe('P');
  });

  it('renders several entries as an ordered list and drops blank entries', () => {
    render(<OrderedStringList items={['计算机三级', '  ', 'CET-6']} />);

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toMatch(/^1\./);
    expect(items[1].textContent).toMatch(/^2\./);
    expect(items[1].textContent).toContain('CET-6');
  });

  it('renders a custom stringList section as an ordered list', () => {
    const meta: SectionMeta = {
      id: 'honors',
      key: 'honors',
      displayName: '荣誉证书',
      sectionType: 'stringList',
      isDefault: false,
      isVisible: true,
      order: 8,
    };
    const data = {
      customSections: {
        honors: { sectionType: 'stringList', strings: ['证书 A', '证书 B'] },
      },
    } as ResumeData;

    const { container } = render(<DynamicResumeSection sectionMeta={meta} resumeData={data} />);

    const list = container.querySelector('ol');
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll('li')).toHaveLength(2);
    expect(container.textContent).not.toContain(',');
  });
});
