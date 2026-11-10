import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ResumeClean } from '@/components/resume/resume-clean';
import type { ResumeData } from '@/components/dashboard/resume-component';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

const data: ResumeData = {
  personalInfo: { name: 'Saurabh Rai', email: 'a@b.com', phone: '+91-700' },
  workExperience: [
    {
      id: 1,
      title: 'DevRel Engineer',
      company: 'Apideck',
      location: 'Remote',
      years: '2025-Present',
      description: ['Lead client demos.'],
    },
  ],
  additional: { technicalSkills: ['Python', 'TypeScript'] },
} as ResumeData;

describe('ResumeClean', () => {
  it('renders name, company, role and a bullet', () => {
    render(<ResumeClean data={data} />);
    expect(screen.getByText('Saurabh Rai')).toBeInTheDocument();
    expect(screen.getByText('Apideck')).toBeInTheDocument();
    expect(screen.getByText('DevRel Engineer')).toBeInTheDocument();
    expect(screen.getByText('Lead client demos.')).toBeInTheDocument();
  });

  it('renders the phone number as plain text, never a tel: link', () => {
    const { container } = render(<ResumeClean data={data} />);
    expect(screen.getByText('+91-700')).toBeInTheDocument();
    expect(container.querySelector('a[href^="tel:"]')).toBeNull();
  });

  it('prefixes website / linkedin / github links with their localized labels', () => {
    const linkedData: ResumeData = {
      ...(data as object),
      personalInfo: {
        name: '王浩',
        website: 'https://fengba.blog.csdn.net/',
        linkedin: 'linkedin.com/in/wanghao',
        github: 'github.com/wanghao',
      },
    } as ResumeData;

    render(
      <ResumeClean
        data={linkedData}
        personalInfoLabels={{
          website: '个人网站',
          linkedin: '领英',
          github: 'GitHub',
        }}
      />
    );

    // Absolute URLs keep their href and render with protocol stripped as the
    // anchor text; bare hostnames are promoted to clickable https URLs.
    const cases: Array<[string, string, string]> = [
      ['个人网站', 'fengba.blog.csdn.net/', 'https://fengba.blog.csdn.net/'],
      ['领英', 'linkedin.com/in/wanghao', 'https://linkedin.com/in/wanghao'],
      ['GitHub', 'github.com/wanghao', 'https://github.com/wanghao'],
    ];
    for (const [label, anchorName, expectedHref] of cases) {
      const anchor = screen.getByRole('link', { name: anchorName });
      const wrapper = anchor.parentElement!;
      expect(wrapper.textContent).toContain(label);
      expect(wrapper.querySelector('span')?.textContent).toBe(label);
      expect(anchor.getAttribute('href')).toBe(expectedHref);
    }
  });
});
