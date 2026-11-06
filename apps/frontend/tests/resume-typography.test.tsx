import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { render } from '@testing-library/react';
import React from 'react';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

/**
 * Rule: 简历中的数字用与文字一样的字体风格 — digits must never switch the
 * resume document to a monospace face. Dates, header facts, pills and list
 * markers inherit the body font; only the vivid template keeps its designed
 * monospace accent.
 */
describe('resume number/meta typography', () => {
  const data = {
    personalInfo: { name: '王浩', phone: '133-8910-8926', workYears: '9年' },
    sectionMeta: [
      {
        id: 'workExperience',
        key: 'workExperience',
        displayName: '工作经历',
        sectionType: 'itemList',
        isDefault: true,
        isVisible: true,
        order: 1,
      },
    ],
    workExperience: [
      {
        id: 1,
        title: 'Java 开发',
        company: '甲公司',
        years: '2020.06~2023.09',
        description: ['负责支付系统', '负责清结算系统'],
        descriptionStyles: ['bullet', 'bullet'],
      },
    ],
  } as unknown as ResumeData;

  it('renders list-number markers in the document font, not monospace', () => {
    const { container } = render(<ResumeSingleColumn data={data} />);

    // The 3ch number-gutter spans (markers + level indent spacers).
    const markers = container.querySelectorAll('span[class*="3ch"]');
    expect(markers.length).toBeGreaterThan(0);
    for (const marker of markers) {
      expect(marker.className).not.toContain('font-mono');
      // Alignment still uses tabular figures.
      expect(marker.className).toContain('tabular-nums');
    }
  });

  it('keeps dates and header facts off the mono token in base/swiss stylesheets', () => {
    const stylesDir = path.resolve(
      path.dirname(new URL(import.meta.url).pathname),
      '../components/resume/styles'
    );
    for (const file of ['_base.module.css', 'swiss-single.module.css']) {
      const css = readFileSync(path.join(stylesDir, file), 'utf8');
      expect(css).not.toContain('--resume-font-mono');
    }
  });

  it('leaves the mono token defined for the vivid template accent', () => {
    const stylesDir = path.resolve(
      path.dirname(new URL(import.meta.url).pathname),
      '../components/resume/styles'
    );
    const tokens = readFileSync(path.join(stylesDir, '_tokens.css'), 'utf8');
    expect(tokens).toContain('--resume-font-mono');
  });
});
