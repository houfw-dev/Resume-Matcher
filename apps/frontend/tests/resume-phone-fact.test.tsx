import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';
import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeModern } from '@/components/resume/resume-modern';
import { ResumeModernTwoColumn } from '@/components/resume/resume-modern-two-column';
import { ResumeTwoColumn } from '@/components/resume/resume-two-column';
import { ResumeVivid } from '@/components/resume/resume-vivid';
import { ResumeLatex } from '@/components/resume/resume-latex';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * Rule: the phone number is a plain header fact, same face as the other
 * facts — it must never render as an underlined tel: hyperlink. Locks every
 * resume template (PDF/print share these components).
 */
const data: ResumeData = {
  personalInfo: {
    name: '王浩',
    phone: '133-8910-8926',
    email: 'wang@example.com',
  },
  workExperience: [
    {
      id: 1,
      title: 'Java 开发',
      company: '甲公司',
      years: '2020.06~至今',
      description: ['负责核心系统开发。'],
      descriptionStyles: ['bullet'],
    },
  ],
} as ResumeData;

const templates = {
  'swiss-single': ResumeSingleColumn,
  clean: ResumeClean,
  modern: ResumeModern,
  'modern-two-column': ResumeModernTwoColumn,
  'two-column': ResumeTwoColumn,
  vivid: ResumeVivid,
  latex: ResumeLatex,
} as const;

describe.each(Object.entries(templates))('resume template %s — phone fact', (_name, Template) => {
  it('renders the phone number as plain text without a tel: anchor', () => {
    const { container } = render(<Template data={data} />);
    expect(screen.getByText('133-8910-8926')).toBeInTheDocument();
    expect(container.querySelector('a[href^="tel:"]')).toBeNull();
  });
});
