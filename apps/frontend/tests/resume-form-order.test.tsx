import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ResumeForm } from '@/components/builder/resume-form';
import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

function meta(over: Partial<SectionMeta>): SectionMeta {
  return {
    id: 'x',
    key: 'x',
    displayName: 'X',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 0,
    ...over,
  };
}

/**
 * Scrambled stored order (formal-branch degree): work → projects → custom →
 * personalInfo → education → summary(hidden) → additional. The builder must
 * display the canonical formal sequence regardless of these `order` values.
 */
function scrambledResume(): ResumeData {
  return {
    personalInfo: { name: '李四', title: '后端工程师' },
    summary: '',
    education: [{ id: 1, institution: '甲大学', degree: '统招本科' }],
    workExperience: [],
    personalProjects: [],
    additional: { technicalSkills: [], languages: [], certificationsTraining: [], awards: [] },
    customSections: {
      custom_hobby: { sectionType: 'text', text: '长期参与开源社区活动。' },
      custom_empty: { sectionType: 'text', text: '' },
    },
    sectionMeta: [
      meta({
        id: 'workExperience',
        key: 'workExperience',
        displayName: 'Experience',
        sectionType: 'itemList',
        isDefault: true,
        order: 0,
      }),
      meta({
        id: 'personalProjects',
        key: 'personalProjects',
        displayName: 'Projects',
        sectionType: 'itemList',
        isDefault: true,
        order: 1,
      }),
      meta({ id: 'custom_hobby', key: 'custom_hobby', displayName: '志愿者', order: 2 }),
      meta({
        id: 'personalInfo',
        key: 'personalInfo',
        displayName: 'Personal Info',
        sectionType: 'personalInfo',
        isDefault: true,
        order: 3,
      }),
      meta({
        id: 'education',
        key: 'education',
        displayName: 'Education',
        sectionType: 'itemList',
        isDefault: true,
        order: 4,
      }),
      meta({
        id: 'custom_empty',
        key: 'custom_empty',
        displayName: '兴趣爱好',
        isVisible: false,
        order: 5,
      }),
      meta({
        id: 'summary',
        key: 'summary',
        displayName: 'Summary',
        isDefault: true,
        isVisible: false,
        order: 6,
      }),
      meta({
        id: 'additional',
        key: 'additional',
        displayName: 'Skills & Awards',
        sectionType: 'stringList',
        isDefault: true,
        order: 7,
      }),
    ],
  } as ResumeData;
}

describe('ResumeForm section-order lock', () => {
  it('renders sections in canonical formal-branch order regardless of stored order', () => {
    const { container } = render(<ResumeForm resumeData={scrambledResume()} onUpdate={vi.fn()} />);

    const titles = Array.from(container.querySelectorAll('h3')).map((el) => el.textContent);
    expect(titles).toEqual([
      'builder.personalInfo', // PersonalInfoForm's own heading (no SectionHeader wrapper)
      'resume.sections.education',
      'resume.sections.summary',
      'resume.sections.skills',
      'resume.sections.experience',
      'resume.sections.projects',
      '志愿者',
      '兴趣爱好', // hidden rows keep their dense-order slot in the builder
    ]);
  });

  it('shows the fixed-order lock notice and no section-level reorder controls', () => {
    render(<ResumeForm resumeData={scrambledResume()} onUpdate={vi.fn()} />);

    expect(screen.getByText('builder.sectionOrder.lockedNotice')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /moveUp|moveDown/ })).toBeNull();
    // Default blocks carry the lock affordance; exactly the two customs rename.
    expect(
      screen.getAllByRole('img', { name: 'builder.sectionHeader.titleLocked' }).length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole('button', { name: 'builder.sectionHeader.renameSection' })
    ).toHaveLength(2);
  });

  it('reveals the hidden summary block in the same update that carries the typed text', () => {
    const onUpdate = vi.fn();
    render(<ResumeForm resumeData={scrambledResume()} onUpdate={onUpdate} />);

    fireEvent.change(screen.getByLabelText('resume.sections.summary'), {
      target: { value: '新增的个人优势' },
    });

    expect(onUpdate).toHaveBeenCalledTimes(1);
    const next = onUpdate.mock.calls[0][0] as ResumeData;
    expect(next.summary).toBe('新增的个人优势');
    const summaryMeta = next.sectionMeta?.find((s) => s.key === 'summary');
    expect(summaryMeta?.isVisible).toBe(true);
  });

  it('adds a new custom section through the locked builder dialog', () => {
    const onUpdate = vi.fn();
    render(<ResumeForm resumeData={scrambledResume()} onUpdate={onUpdate} />);

    fireEvent.click(
      screen.getByRole('button', { name: 'builder.customSections.addCustomSectionButton' })
    );
    fireEvent.change(screen.getByPlaceholderText('builder.customSections.sectionNamePlaceholder'), {
      target: { value: '资格证书' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'builder.addSection' }));

    const next = onUpdate.mock.calls[0][0] as ResumeData;
    const created = next.sectionMeta?.find((s) => s.displayName === '资格证书');
    expect(created).toBeDefined();
    expect(created?.isDefault).toBe(false);
    expect(next.customSections?.[created!.key]).toMatchObject({ sectionType: 'text' });
  });
});
