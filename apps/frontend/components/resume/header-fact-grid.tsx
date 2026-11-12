import React from 'react';
import type { Education, PersonalInfo } from '@/components/dashboard/resume-component';
import type { PersonalInfoLabels } from '@/lib/utils/resume-headings';
import baseStyles from './styles/_base.module.css';

/** Split a list into consecutive rows of at most `size` items. */
const chunk = <T,>(items: readonly T[], size: number): T[][] => {
  const rows: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    rows.push(items.slice(index, index + size));
  }
  return rows;
};

export interface HeaderFactCell {
  /** Stable fact key, also exposed as the `data-header-fact` test/anchor token. */
  key: string;
  label: string;
  value: React.ReactNode;
}

interface BuildHeaderFactCellsInput {
  personalInfo?: PersonalInfo;
  education?: Education[];
  /** additional.languages; blank/non-string entries are dropped. */
  languages?: string[];
  labels: PersonalInfoLabels;
}

/**
 * Build the basic-info header facts in the fixed Chinese-résumé order used by
 * every template: 性别 / 年龄 / 学历 / 工作年限 / 求职意向 / 意向城市 / 电话 /
 * 邮箱 / 外语水平 — the same contract as swiss-single's infoCells and the
 * resume-parsing-rules 基本信息 spec. Blank fields are omitted. 学历 falls
 * back to the first education entry carrying a degree; 求职意向 / 意向城市
 * read personalInfo.title / .location; 外语水平 joins additional.languages
 * with 、. The phone number stays a plain text fact (NEVER a tel: link, so
 * its digits never render underlined); email renders as a mailto anchor.
 */
export function buildHeaderFactCells({
  personalInfo,
  education,
  languages,
  labels,
}: BuildHeaderFactCellsInput): HeaderFactCell[] {
  const cells: HeaderFactCell[] = [];

  const pushText = (key: string, label: string, value?: string | null): void => {
    const text = value?.trim();
    if (text) cells.push({ key, label, value: text });
  };

  pushText('gender', labels.gender, personalInfo?.gender);
  pushText('age', labels.age, personalInfo?.age);

  const educationLevel =
    personalInfo?.educationLevel?.trim() ||
    education?.find((edu) => edu.degree?.trim())?.degree?.trim();
  pushText('educationLevel', labels.educationLevel, educationLevel);

  pushText('workYears', labels.workYears, personalInfo?.workYears);
  pushText('jobIntention', labels.jobIntention, personalInfo?.title);
  pushText('desiredCity', labels.desiredCity, personalInfo?.location);
  pushText('phone', labels.phone, personalInfo?.phone);

  const email = personalInfo?.email?.trim();
  if (email) {
    cells.push({
      key: 'email',
      label: labels.email,
      value: (
        <a
          href={`mailto:${email}`}
          target="_blank"
          rel="noopener noreferrer"
          className={`${baseStyles['resume-link']} hover:underline`}
        >
          {email}
        </a>
      ),
    });
  }

  const foreignLanguages = (languages ?? []).filter(
    (item): item is string => typeof item === 'string' && item.trim() !== ''
  );
  if (foreignLanguages.length > 0) {
    cells.push({
      key: 'foreignLanguage',
      label: labels.foreignLanguage,
      value: foreignLanguages.join('、'),
    });
  }

  return cells;
}

interface HeaderFactGridProps {
  cells: readonly HeaderFactCell[];
}

/**
 * Centered variant of the basic-info fact grid for the centered-header
 * templates (modern / latex / clean): up to three labeled cells per row,
 * rows centered as a block so the grid keeps each template's centered header
 * language while preserving the shared fact order. Labels use the muted
 * 0.75× meta face and values the 0.92× face (the same sizes swiss-single's
 * left-aligned info grid uses). jsdom performs no layout, so the visual
 * contract is locked via the data-header-fact* tokens and class names.
 */
export const HeaderFactGrid: React.FC<HeaderFactGridProps> = ({ cells }) => {
  if (cells.length === 0) return null;

  return (
    <div data-header-fact-grid="" className="mt-2 flex flex-col items-center gap-y-[0.125rem]">
      {chunk(cells, 3).map((row, rowIndex) => (
        <div
          key={rowIndex}
          data-header-fact-row=""
          className="flex flex-wrap items-baseline justify-center gap-x-5 gap-y-1"
        >
          {row.map((cell) => (
            <div
              key={cell.key}
              data-header-fact={cell.key}
              className="inline-flex items-baseline gap-[0.3rem]"
            >
              <span className={`${baseStyles['resume-meta-sm']} whitespace-nowrap`}>
                {cell.label}
              </span>
              <span className={`${baseStyles['resume-text-sm']} min-w-0 break-words text-left`}>
                {cell.value}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};
