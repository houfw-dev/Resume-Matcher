import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { ResumeForm } from '@/components/builder/resume-form';
import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

function defaultMeta(overrides: Partial<SectionMeta> = {}): SectionMeta {
  return {
    id: 'x',
    key: 'x',
    displayName: 'X',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 0,
    ...overrides,
  };
}

const defaultRows = (): SectionMeta[] => [
  defaultMeta({
    id: 'personalInfo',
    key: 'personalInfo',
    displayName: 'Personal Info',
    sectionType: 'personalInfo',
    isDefault: true,
    order: 0,
  }),
  defaultMeta({
    id: 'education',
    key: 'education',
    displayName: 'Education',
    sectionType: 'itemList',
    isDefault: true,
    order: 1,
  }),
  defaultMeta({
    id: 'additional',
    key: 'additional',
    displayName: '专业技能',
    sectionType: 'stringList',
    isDefault: true,
    order: 3,
  }),
  defaultMeta({
    id: 'workExperience',
    key: 'workExperience',
    displayName: 'Experience',
    sectionType: 'itemList',
    isDefault: true,
    order: 4,
  }),
  defaultMeta({
    id: 'personalProjects',
    key: 'personalProjects',
    displayName: 'Projects',
    sectionType: 'itemList',
    isDefault: true,
    order: 5,
  }),
];

function buildResume(overrides: Partial<ResumeData> = {}): ResumeData {
  return {
    personalInfo: { name: '张三' },
    summary: '',
    education: [],
    workExperience: [],
    personalProjects: [],
    additional: { technicalSkills: [], languages: [], certificationsTraining: [], awards: [] },
    customSections: {},
    sectionMeta: defaultRows(),
    ...overrides,
  };
}

describe('ResumeForm missing 个人优势 block', () => {
  it('offers the summary form even when stored sectionMeta omits it, and saves it visible', () => {
    // As uploaded by the parser for a resume with no summary content:
    // no summary row exists, so previously the builder had no 个人优势 form.
    const onUpdate = vi.fn();
    render(<ResumeForm resumeData={buildResume()} onUpdate={onUpdate} />);

    const summaryField = document.getElementById('summary');
    expect(summaryField).not.toBeNull();
    expect(summaryField!.tagName).toBe('TEXTAREA');

    fireEvent.change(summaryField!, { target: { value: '我的个人优势' } });

    expect(onUpdate).toHaveBeenCalled();
    const saved: ResumeData = onUpdate.mock.calls.at(-1)![0];
    expect(saved.summary).toBe('我的个人优势');
    const summaryMeta = saved.sectionMeta!.find((s) => s.key === 'summary');
    expect(summaryMeta).toBeDefined();
    expect(summaryMeta!.isVisible).toBe(true);
  });
});

describe('ResumeForm rename 自我评价 → 个人优势', () => {
  const selfEvalRow = (): SectionMeta =>
    defaultMeta({
      id: 'self_evaluation',
      key: 'self_evaluation',
      displayName: '自我评价',
      sectionType: 'text',
      isDefault: false,
      order: 6,
    });

  function startRename(card: HTMLElement): HTMLInputElement {
    fireEvent.click(
      within(card).getByRole('button', { name: 'builder.sectionHeader.renameSection' })
    );
    return card.querySelector('input') as HTMLInputElement;
  }

  it('migrates the custom text block into the built-in summary block', () => {
    const onUpdate = vi.fn();
    const data = buildResume({
      sectionMeta: [...defaultRows(), selfEvalRow()],
      customSections: {
        self_evaluation: { sectionType: 'text', text: '学习能力强，乐于技术分享。' },
      },
    });
    render(<ResumeForm resumeData={data} onUpdate={onUpdate} />);

    const card = screen
      .getByRole('heading', { name: '自我评价' })
      .closest('.border') as HTMLElement;
    const input = startRename(card);
    fireEvent.change(input, { target: { value: '个人优势' } });

    // The reserved-title error must not block this migration.
    expect(within(card).queryByText('builder.sectionHeader.reservedNameError')).toBeNull();
    const save = within(card).getByRole('button', { name: 'common.save' });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    expect(onUpdate).toHaveBeenCalled();
    const saved: ResumeData = onUpdate.mock.calls.at(-1)![0];
    expect(saved.summary).toBe('学习能力强，乐于技术分享。');
    expect(saved.customSections!.self_evaluation).toBeUndefined();
    const keys = saved.sectionMeta!.map((s) => s.key);
    expect(keys).toContain('summary');
    expect(keys).not.toContain('self_evaluation');
    expect(saved.sectionMeta!.find((s) => s.key === 'summary')!.isVisible).toBe(true);
  });

  it('keeps the reserved-title block for a non-text custom section', () => {
    const onUpdate = vi.fn();
    const listRow = defaultMeta({
      id: 'custom_1',
      key: 'custom_1',
      displayName: '证书清单',
      sectionType: 'itemList',
      order: 6,
    });
    const data = buildResume({
      sectionMeta: [...defaultRows(), listRow],
      customSections: { custom_1: { sectionType: 'itemList', items: [] } },
    });
    render(<ResumeForm resumeData={data} onUpdate={onUpdate} />);

    const card = screen
      .getByRole('heading', { name: '证书清单' })
      .closest('.border') as HTMLElement;
    const input = startRename(card);
    // "Summary" is the canonical English title, reserved in every locale.
    fireEvent.change(input, { target: { value: 'Summary' } });

    expect(within(card).getByText('builder.sectionHeader.reservedNameError')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'common.save' })).toBeDisabled();
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe('ResumeForm built-in blocks are always listed and cannot be hidden', () => {
  it('lists every built-in block even when empty or stored hidden, without hide/delete controls', () => {
    // Summary is absent from stored meta (empty optional) and every other
    // built-in is empty too: all six must still appear in the editor.
    const onUpdate = vi.fn();
    render(<ResumeForm resumeData={buildResume()} onUpdate={onUpdate} />);

    // The five wrapped defaults + the personal-info form's own heading.
    const builtInHeadings = [
      'resume.sections.education',
      'resume.sections.summary',
      'resume.sections.skills',
      'resume.sections.experience',
      'resume.sections.projects',
    ];
    for (const name of builtInHeadings) {
      const card = screen.getByRole('heading', { name }).closest('.border') as HTMLElement;
      expect(card).not.toBeNull();
      // No eye toggle and no delete for built-in blocks.
      expect(
        within(card).queryByRole('button', { name: 'builder.sectionHeader.hideSection' })
      ).toBeNull();
      expect(
        within(card).queryByRole('button', { name: 'builder.sectionHeader.showSection' })
      ).toBeNull();
      expect(
        within(card).queryByRole('button', { name: 'builder.sectionHeader.deleteSection' })
      ).toBeNull();
    }
  });

  it('shows an explicitly hidden stored built-in block in the editor and makes its form usable', () => {
    const onUpdate = vi.fn();
    const rows = defaultRows();
    const data = buildResume({
      sectionMeta: [
        ...rows,
        defaultMeta({
          id: 'summary',
          key: 'summary',
          displayName: 'Summary',
          isDefault: true,
          isVisible: false,
          order: 6,
        }),
      ],
    });
    render(<ResumeForm resumeData={data} onUpdate={onUpdate} />);

    // Stored hidden, but listed in the builder.
    const heading = screen.getByRole('heading', { name: 'resume.sections.summary' });
    const card = heading.closest('.border') as HTMLElement;
    expect(card.className).not.toMatch(/opacity-60/);

    // First typed text persists the visibility flip.
    fireEvent.change(screen.getByLabelText('resume.sections.summary'), {
      target: { value: '新填写的优势' },
    });
    const saved: ResumeData = onUpdate.mock.calls.at(-1)![0];
    expect(saved.summary).toBe('新填写的优势');
    expect(saved.sectionMeta!.find((s) => s.key === 'summary')!.isVisible).toBe(true);
  });

  it('keeps hide and delete controls on custom sections', () => {
    const hobbyRow = defaultMeta({
      id: 'custom_hobby',
      key: 'custom_hobby',
      displayName: '兴趣爱好',
      order: 6,
    });
    const data = buildResume({
      sectionMeta: [...defaultRows(), hobbyRow],
      customSections: { custom_hobby: { sectionType: 'text', text: '开源贡献' } },
    });
    render(<ResumeForm resumeData={data} onUpdate={vi.fn()} />);

    const card = screen
      .getByRole('heading', { name: '兴趣爱好' })
      .closest('.border') as HTMLElement;
    expect(
      within(card).getByRole('button', { name: 'builder.sectionHeader.hideSection' })
    ).toBeInTheDocument();
    expect(
      within(card).getByRole('button', { name: 'builder.sectionHeader.deleteSection' })
    ).toBeInTheDocument();
  });
});
