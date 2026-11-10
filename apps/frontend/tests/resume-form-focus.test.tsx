import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { ResumeForm } from '@/components/builder/resume-form';
import { sectionAnchorId } from '@/lib/utils/section-order';
import type { ResumeData } from '@/components/dashboard/resume-component';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

function makeResume(): ResumeData {
  return {
    personalInfo: { name: '张三', title: '后端工程师' },
    summary: '',
    education: [{ id: 1, institution: '甲大学', degree: '统招本科' }],
    workExperience: [],
    personalProjects: [],
    additional: { technicalSkills: [], languages: [], certificationsTraining: [], awards: [] },
  } as ResumeData;
}

/** jsdom 28 has no scrollIntoView; install an inspectable stub per test. */
const scrollSpy = vi.fn();

beforeEach(() => {
  Element.prototype.scrollIntoView = scrollSpy;
});

afterEach(() => {
  scrollSpy.mockClear();
  delete (Element.prototype as { scrollIntoView?: Element['scrollIntoView'] }).scrollIntoView;
});

describe('ResumeForm — diagnosis deep-link section focus', () => {
  it('scrolls to and highlights the section named by focusSectionKey', () => {
    render(<ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} focusSectionKey="education" />);

    const target = document.getElementById(sectionAnchorId('education'));
    expect(target).not.toBeNull();
    expect(target?.dataset.focus).toBe('true');
    expect(target?.className).toContain('ring-2');
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ block: 'start' });
    // Only the target section is highlighted.
    const highlighted = document.querySelectorAll('[data-focus="true"]');
    expect(highlighted).toHaveLength(1);
  });

  it('renders every canonical section with an anchor id and section key', () => {
    render(<ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} focusSectionKey="summary" />);

    for (const key of [
      'personalInfo',
      'education',
      'summary',
      'additional',
      'workExperience',
      'personalProjects',
    ]) {
      const anchor = document.getElementById(sectionAnchorId(key));
      expect(anchor).not.toBeNull();
      expect(anchor?.dataset.sectionKey).toBe(key);
    }
  });

  it('fades the highlight after the fixed focus window without removing the anchor', () => {
    vi.useFakeTimers();
    try {
      render(
        <ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} focusSectionKey="workExperience" />
      );
      const target = document.getElementById(sectionAnchorId('workExperience'));
      expect(target?.dataset.focus).toBe('true');

      act(() => {
        vi.advanceTimersByTime(2400);
      });

      expect(target?.dataset.focus).toBeUndefined();
      expect(target?.className).not.toContain('ring-2');
      expect(document.getElementById(sectionAnchorId('workExperience'))).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders normally, with no highlight and no scrolling, without a focus target', () => {
    render(<ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} />);

    expect(document.querySelectorAll('[data-focus="true"]')).toHaveLength(0);
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it('moves the highlight when the focus target changes', () => {
    const { rerender } = render(
      <ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} focusSectionKey="education" />
    );
    expect(document.getElementById(sectionAnchorId('education'))?.dataset.focus).toBe('true');

    rerender(<ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} focusSectionKey="summary" />);

    expect(document.getElementById(sectionAnchorId('education'))?.dataset.focus).toBeUndefined();
    expect(document.getElementById(sectionAnchorId('summary'))?.dataset.focus).toBe('true');
    expect(scrollSpy).toHaveBeenCalledTimes(2);
  });

  it('stays quiet when the focus names a block absent from the current resume', () => {
    // All six defaults are always listed in the builder, so this guards the
    // guard itself: a null focus (e.g. rejected ?section= param) is a no-op.
    render(<ResumeForm resumeData={makeResume()} onUpdate={vi.fn()} focusSectionKey={null} />);
    expect(screen.queryAllByText('builder.sectionOrder.lockedNotice')).toHaveLength(1);
    expect(document.querySelectorAll('[data-focus="true"]')).toHaveLength(0);
  });
});
