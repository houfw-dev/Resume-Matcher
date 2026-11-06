import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, within } from '@testing-library/react';
import {
  DiagnosisReportView,
  type FilterMode,
  type TFn,
} from '@/components/diagnosis/diagnosis-report-view';
import type { DiagnosisReport } from '@/lib/api/diagnosis';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

const t: TFn = (key: string) =>
  key === 'diagnosis.evidenceLabel'
    ? '问题描述'
    : key === 'diagnosis.suggestionLabel'
      ? '优化方案'
      : key;

function makeReport(itemOverrides: Partial<DiagnosisReport['items'][number]>): DiagnosisReport {
  return {
    resume_id: 'r1',
    spec_version: 'V4',
    language: 'zh',
    target_title: null,
    competency_model: null,
    counts: { conform: 0, partial: 1, nonconform: 0, na: 0, effective: 1 },
    redline_passed: true,
    failed_redline_ids: [],
    dimensions: [
      {
        key: 'projects',
        name: '项目经历',
        counts: { conform: 0, partial: 1, nonconform: 0, na: 0, effective: 1 },
      },
    ],
    redlines: [],
    items: [
      {
        id: 9,
        dimension: 'projects',
        dimension_name: '项目经历',
        sub_dimension: '项目经历',
        topic: '项目完整性',
        severity: 'normal',
        judgment_method: 'objective',
        rating: 'partial',
        evidence: '',
        suggestion: '',
        ...itemOverrides,
      },
    ],
    warnings: [],
  } satisfies DiagnosisReport;
}

function renderView(report: DiagnosisReport, filter: FilterMode = 'all') {
  return render(
    <DiagnosisReportView
      report={report}
      filter={filter}
      onFilterChange={vi.fn()}
      ratingLabel={(rating) => rating}
      t={t}
    />
  );
}

describe('DiagnosisReportView — problem description and fix as ordered lists', () => {
  it('renders multi-point evidence and suggestion as ordered lists numbered from 1', () => {
    const { container } = renderView(
      makeReport({
        evidence: '项目 A 缺少技术栈字段。\n项目 B 的职责描述没有量化结果。',
        suggestion: '为每个项目补一行技术栈。\n在职责中补充数字结果。',
      })
    );

    const blocks = container.querySelectorAll('ol');
    expect(blocks).toHaveLength(2);
    blocks.forEach((ol) => {
      const rows = within(ol as HTMLElement).getAllByRole('listitem');
      expect(rows).toHaveLength(2);
      expect(within(rows[0]).getByText('1.')).toBeInTheDocument();
      expect(within(rows[1]).getByText('2.')).toBeInTheDocument();
    });
    expect(container.textContent).toContain('项目 A 缺少技术栈字段。');
    expect(container.textContent).toContain('在职责中补充数字结果。');
    expect(container.textContent).toContain('问题描述：');
    expect(container.textContent).toContain('优化方案：');
  });

  it('numbers a single point as 1. too', () => {
    const { container } = renderView(
      makeReport({ evidence: '缺少必填基本信息：性别。', suggestion: '补齐性别字段。' })
    );

    const blocks = container.querySelectorAll('ol');
    expect(blocks).toHaveLength(2);
    blocks.forEach((ol) => {
      const rows = within(ol as HTMLElement).getAllByRole('listitem');
      expect(rows).toHaveLength(1);
      expect(within(rows[0]).getByText('1.')).toBeInTheDocument();
    });
  });

  it('strips source-carried numbering so points are not numbered twice', () => {
    const { container } = renderView(
      makeReport({ evidence: '1、缺少技术栈字段。\n2、缺少量化结果。' })
    );

    const ol = container.querySelector('ol') as HTMLElement;
    const rows = within(ol).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('缺少技术栈字段。');
    expect(rows[0]).not.toHaveTextContent('1、');
    expect(rows[1]).toHaveTextContent('缺少量化结果。');
  });

  it('renders the N/A notice as plain text without a numbered list', () => {
    const { container } = renderView(
      makeReport({
        rating: 'na',
        evidence: '未提供目标岗位 JD，岗位匹配度检查项不适用。',
      })
    );

    expect(container.querySelectorAll('ol')).toHaveLength(0);
    expect(container.textContent).toContain('未提供目标岗位 JD，岗位匹配度检查项不适用。');
    expect(container.textContent).not.toContain('问题描述');
  });

  it('renders no finding blocks when evidence and suggestion are empty', () => {
    const { container } = renderView(makeReport({ rating: 'conform' }));
    expect(container.querySelectorAll('ol')).toHaveLength(0);
  });
});
