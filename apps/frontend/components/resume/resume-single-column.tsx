import React from 'react';
import { Mail, Phone, MapPin, Globe, Linkedin, Github, ExternalLink } from 'lucide-react';
import type {
  ResumeData,
  SectionMeta,
  Experience,
  Education,
  Project,
  AdditionalSectionLabels,
  ResumeSectionHeadings,
} from '@/components/dashboard/resume-component';
import {
  getRenderSections,
  LATE_AWARDS_KEY,
  LATE_CERTIFICATIONS_KEY,
} from '@/lib/utils/section-order';
import {
  DEFAULT_PERSONAL_INFO_LABELS,
  resolveAdditionalModuleTitle,
  type LateAdditionalModuleKind,
  type PersonalInfoLabels,
} from '@/lib/utils/resume-headings';
import { formatDateRange } from '@/lib/utils';
import { DynamicResumeSection } from './dynamic-resume-section';
import { promoteWorkDepartment } from './work-department';
import { DescriptionList } from './description-list';
import { PointTextList } from './point-text-list';
import { groupSkillEntries, stripPointMarker } from './list-format';
import baseStyles from './styles/_base.module.css';
import styles from './styles/swiss-single.module.css';

interface ResumeSingleColumnProps {
  data: ResumeData;
  showContactIcons?: boolean;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
  personalInfoLabels?: Partial<PersonalInfoLabels>;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
}

/** Split a list into consecutive rows of at most `size` items. */
const chunk = <T,>(items: T[], size: number): T[][] => {
  const rows: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    rows.push(items.slice(index, index + size));
  }
  return rows;
};

/**
 * Swiss Single-Column Resume Template
 *
 * Traditional full-width layout with sections stacked vertically.
 * Best for detailed experience descriptions and maximum content density.
 *
 * Section order: Determined by sectionMeta ordering
 */
export const ResumeSingleColumn: React.FC<ResumeSingleColumnProps> = ({
  data,
  showContactIcons = false,
  additionalSectionLabels,
  personalInfoLabels,
  sectionHeadings,
}) => {
  const { personalInfo, summary, workExperience, education, personalProjects, additional } = data;

  const infoLabels: PersonalInfoLabels = {
    ...DEFAULT_PERSONAL_INFO_LABELS,
    ...personalInfoLabels,
  };

  // Visible sections in canonical order plus the render-only late markers for
  // 培训与证书 / 荣誉奖项 (projected to the back by getRenderSections).
  const renderSections = getRenderSections(data);

  // Icon mapping for contact types
  const contactIcons: Record<string, React.ReactNode> = {
    Email: <Mail size={12} />,
    Phone: <Phone size={12} />,
    Location: <MapPin size={12} />,
    Website: <Globe size={12} />,
    LinkedIn: <Linkedin size={12} />,
    GitHub: <Github size={12} />,
  };

  // Helper function to render contact details. `displayLabel` renders a muted
  // label before the value (e.g. 个人网站： https://…) for personal links.
  const renderContactDetail = (
    label: string,
    value?: string,
    hrefPrefix: string = '',
    displayLabel?: string
  ) => {
    if (!value) return null;

    let finalHrefPrefix = hrefPrefix;
    if (
      ['Website', 'LinkedIn', 'GitHub'].includes(label) &&
      !value.startsWith('http') &&
      !value.startsWith('//')
    ) {
      finalHrefPrefix = 'https://';
    }

    const href = finalHrefPrefix + value;
    // Test the composed href (not just the prefix): an already-absolute
    // "https://…" value with an empty prefix must still render as a link.
    const isLink = href.startsWith('http') || href.startsWith('mailto:') || href.startsWith('tel:');

    let displayText = value;
    if (isLink && (label === 'LinkedIn' || label === 'GitHub' || label === 'Website')) {
      displayText = value.replace(/^https?:\/\//, '').replace(/^www\./, '');
    }

    return (
      <span className="inline-flex items-center gap-1">
        {showContactIcons && contactIcons[label]}
        {displayLabel && <span className={styles.infoLabel}>{displayLabel}</span>}
        {isLink ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className={`${baseStyles['resume-link']} hover:underline`}
          >
            {displayText}
          </a>
        ) : (
          <span style={{ color: 'var(--resume-text-primary)' }}>{displayText}</span>
        )}
      </span>
    );
  };

  // Basic-info facts shown after the name, in the order Chinese resumes use:
  // 性别 / 年龄 / 学历 / 工作年限 / 求职意向 / 意向城市 / 电话 / 邮箱 / 外语水平.
  // 学历 falls back to the most recent degree; 外语水平 to additional.languages.
  const foreignLanguages =
    additional?.languages?.filter(
      (item): item is string => typeof item === 'string' && item.trim() !== ''
    ) ?? [];
  const educationLevel =
    personalInfo?.educationLevel?.trim() ||
    education?.find((edu) => edu.degree?.trim())?.degree?.trim();

  const infoCells: Array<{ key: string; label: string; value: React.ReactNode }> = [];
  const pushInfoCell = (key: string, label: string, value?: string | null) => {
    const text = value?.trim();
    if (text) infoCells.push({ key, label, value: text });
  };
  pushInfoCell('gender', infoLabels.gender, personalInfo?.gender);
  pushInfoCell('age', infoLabels.age, personalInfo?.age);
  pushInfoCell('educationLevel', infoLabels.educationLevel, educationLevel);
  pushInfoCell('workYears', infoLabels.workYears, personalInfo?.workYears);
  pushInfoCell('jobIntention', infoLabels.jobIntention, personalInfo?.title);
  pushInfoCell('desiredCity', infoLabels.desiredCity, personalInfo?.location);
  // Phone is a plain fact (same face/style as 性别/工作年限), never a
  // tel: link — its digits must not render underlined like a hyperlink.
  pushInfoCell('phone', infoLabels.phone, personalInfo?.phone);
  if (personalInfo?.email?.trim()) {
    infoCells.push({
      key: 'email',
      label: infoLabels.email,
      value: renderContactDetail('Email', personalInfo.email, 'mailto:'),
    });
  }
  if (foreignLanguages.length > 0) {
    infoCells.push({
      key: 'foreignLanguage',
      label: infoLabels.foreignLanguage,
      value: foreignLanguages.join('、'),
    });
  }

  // Website / social links stay on their own row, each prefixed with its
  // localized label (个人网站 / 领英 / GitHub) so imported links are named.
  const linkItems = [
    renderContactDetail('Website', personalInfo?.website, '', infoLabels.website),
    renderContactDetail('LinkedIn', personalInfo?.linkedin, '', infoLabels.linkedin),
    renderContactDetail('GitHub', personalInfo?.github, '', infoLabels.github),
  ].filter(Boolean);

  // Render a section based on its key
  const renderSection = (section: SectionMeta) => {
    switch (section.key) {
      case 'personalInfo':
        // Personal info is the header - handled separately
        return null;

      case 'summary':
        if (!summary) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{section.displayName}</h3>
            <PointTextList text={summary} />
          </div>
        );

      case 'workExperience':
        if (!workExperience || workExperience.length === 0) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{section.displayName}</h3>
            <div className={`${baseStyles['resume-items']} ${styles.entrySectionWork}`}>
              {workExperience.map((exp) => {
                // A legacy plain department line ("全球资金部") is lifted into
                // the department column and removed from the bullet list.
                const promoted = promoteWorkDepartment(exp);
                return (
                  <div
                    key={exp.id}
                    className={`${baseStyles['resume-item']} ${styles.entrySubgridItem}`}
                  >
                    {/* Four columns with a department, three without. */}
                    <WorkEntryRow exp={exp} department={promoted.department} />
                    <DescriptionList
                      items={promoted.description}
                      styles={promoted.descriptionStyles}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        );

      case 'personalProjects':
        if (!personalProjects || personalProjects.length === 0) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {personalProjects.map((project) => (
                <div key={project.id} className={baseStyles['resume-item']}>
                  {/* Four columns, left-aligned: name | time | scale | role */}
                  <ProjectEntryRow project={project} />
                  <DescriptionList
                    items={project.description}
                    styles={project.descriptionStyles}
                    canonicalizeLabels
                    flushLabels
                  />
                </div>
              ))}
            </div>
          </div>
        );

      case 'education':
        if (!education || education.length === 0) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={baseStyles['resume-section-title']}>{section.displayName}</h3>
            <div className={`${baseStyles['resume-items']} ${styles.entrySectionEdu}`}>
              {education.map((edu) => (
                <div
                  key={edu.id}
                  className={`${baseStyles['resume-item']} ${styles.entrySubgridItem}`}
                >
                  {/* Four columns, left-aligned: time | university | major | degree */}
                  <EducationEntryRow edu={edu} />
                </div>
              ))}
            </div>
          </div>
        );

      case 'additional':
        if (!additional) return null;
        return (
          <AdditionalSkillsSection
            key={section.id}
            additional={additional}
            displayName={section.displayName}
          />
        );

      default:
        // Custom section - render using DynamicResumeSection
        if (!section.isDefault) {
          return <DynamicResumeSection key={section.id} sectionMeta={section} resumeData={data} />;
        }
        return null;
    }
  };

  return (
    <div className={styles.container}>
      {/* Header Section - left-aligned name plus labeled basic-info facts */}
      {personalInfo && (
        <header
          className={`text-left ${baseStyles['resume-header']} border-b`}
          style={{ borderColor: 'var(--resume-border-primary)' }}
        >
          {/* Name */}
          {personalInfo.name && (
            <h1 className={`${baseStyles['resume-name']} tracking-tight uppercase mb-1`}>
              {personalInfo.name}
            </h1>
          )}

          {/* 性别 / 年龄 / 学历 / 工作年限 / 求职意向 / 意向城市 / 电话 / 邮箱 / 外语水平.
              Fixed three columns; every row is justified (first cell flush
              left, last flush right), including a partial final row. */}
          {infoCells.length > 0 && (
            <div className={styles.infoGrid}>
              {chunk(infoCells, 3).map((row, rowIndex) => (
                <div key={rowIndex} className={styles.infoRow}>
                  {row.map((cell) => (
                    <div
                      key={cell.key}
                      className={`text-left ${styles.infoCell} ${
                        row.length < 3 ? styles.infoCellSparse : ''
                      }`}
                    >
                      <span className={styles.infoLabel}>{cell.label}</span>
                      <span className={`text-left ${styles.infoValue}`}>{cell.value}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* Website / social links stay on their own row but share the
              facts grid's three column tracks, so a two-link row keeps the
              second link (GitHub) aligned under column 2. */}
          {linkItems.length > 0 && (
            <div className={`${baseStyles['resume-meta']} ${styles.infoLinkRow}`}>
              {linkItems.map((item, index) => (
                <div key={index} className={styles.infoLinkCell}>
                  {item}
                </div>
              ))}
            </div>
          )}
        </header>
      )}

      {/* Render sections in canonical order, with the late cert/award
          modules projected after the custom sections */}
      {renderSections
        .filter((item) => !(item.kind === 'meta' && item.meta.key === 'personalInfo'))
        .map((item) => {
          if (item.kind === 'meta') return renderSection(item.meta);
          return (
            <LateAdditionalModule
              key={item.kind === 'certifications' ? LATE_CERTIFICATIONS_KEY : LATE_AWARDS_KEY}
              additional={additional}
              kind={item.kind}
              labels={additionalSectionLabels}
              headings={sectionHeadings}
            />
          );
        })}
    </div>
  );
};

/**
 * Work entry header as a justified column row, date flush left and role
 * flush right (两端对齐), rendered in regular (non-bold) weight:
 * - with a department: four columns — time | company | department | role,
 *   and the department always reserves its track so columns line up across
 *   entries;
 * - without a department: THREE columns — time | company | role — so the
 *   three available fields fill the row instead of leaving an empty track.
 */
const WorkEntryRow: React.FC<{ exp: Experience; department?: string }> = ({
  exp,
  department: departmentProp,
}) => {
  const date = formatDateRange(exp.years).trim();
  const company = exp.company?.trim() ?? '';
  const department = (departmentProp ?? exp.department ?? '').trim();
  const location = exp.location?.trim() ?? '';
  const role = exp.title?.trim() ?? '';

  if (!date && !company && !department && !location && !role) return null;

  const columnsClass = department ? styles.entryColumnsWork : styles.entryColumnsWorkThree;

  return (
    <div className={`text-left ${columnsClass} ${baseStyles['resume-row-tight']}`}>
      <span className={`text-left ${styles.entryDate}`}>{date}</span>
      <span className={`text-left ${baseStyles['resume-text-sm']} ${styles.entryDetail}`}>
        {company}
        {location && <span className={baseStyles['resume-meta-sm']}> · {location}</span>}
      </span>
      {department && (
        <span className={`text-left ${baseStyles['resume-text-sm']} ${styles.entryDetail}`}>
          {department}
        </span>
      )}
      <h4
        className={`${baseStyles['resume-text-sm']} ${styles.entryDetail} ${styles.entryRole} ${
          department ? '' : styles.entryRoleThree
        }`}
      >
        {role}
      </h4>
    </div>
  );
};

/**
 * Project entry header as a fixed four-column row — name | time | scale |
 * role — with every cell left-aligned. 项目规模/团队规模 is a parser-promoted
 * field; empty cells still occupy their track so columns line up across
 * entries. GitHub/website pills stay inside the name cell.
 */
const ProjectEntryRow: React.FC<{ project: Project }> = ({ project }) => {
  const date = formatDateRange(project.years ?? '').trim();
  const scale = project.scale?.trim() ?? '';
  const role = project.role?.trim() ?? '';
  const name = project.name?.trim() ?? '';
  const github = project.github?.trim() ?? '';
  const website = project.website?.trim() ?? '';

  if (!name && !date && !scale && !role && !github && !website) return null;

  const nameCell = (
    <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 text-left">
      {name && <h4 className={baseStyles['resume-item-title']}>{name}</h4>}
      {github && (
        <a
          href={github.startsWith('http') ? github : `https://${github}`}
          target="_blank"
          rel="noopener noreferrer"
          className={baseStyles['resume-link-pill']}
        >
          <Github size={10} />
          {github
            .replace(/^https?:\/\//, '')
            .replace(/^www\./, '')
            .replace(/\/$/, '')}
        </a>
      )}
      {website && (
        <a
          href={website.startsWith('http') ? website : `https://${website}`}
          target="_blank"
          rel="noopener noreferrer"
          className={baseStyles['resume-link-pill']}
        >
          <ExternalLink size={10} />
          {website
            .replace(/^https?:\/\//, '')
            .replace(/^www\./, '')
            .replace(/\/$/, '')}
        </a>
      )}
    </span>
  );

  // No metadata at all: keep the name on a full-width row instead of wasting
  // three empty grid tracks (imported projects often lack dates/roles).
  if (!date && !scale && !role) {
    return <div className={baseStyles['resume-row-tight']}>{nameCell}</div>;
  }

  return (
    <div className={`text-left ${styles.entryColumnsProject} ${baseStyles['resume-row-tight']}`}>
      {nameCell}
      <span className={`text-left ${styles.entryDate}`}>{date}</span>
      <span className={`text-left ${styles.entryScale}`}>{scale}</span>
      <span className={`text-left ${styles.entryDetail} ${baseStyles['resume-item-subtitle']}`}>
        {role}
      </span>
    </div>
  );
};

/**
 * Education entry header as a fixed four-column row — time | university |
 * major | degree — with every cell left-aligned.
 */
const EducationEntryRow: React.FC<{ edu: Education }> = ({ edu }) => {
  const date = formatDateRange(edu.years).trim();
  const institution = edu.institution?.trim() ?? '';
  const major = edu.description?.trim() ?? '';
  const degree = edu.degree?.trim() ?? '';

  if (!date && !institution && !major && !degree) return null;

  return (
    <div className={`text-left ${styles.entryColumns4} ${baseStyles['resume-row-tight']}`}>
      <span className={`text-left ${styles.entryDate}`}>{date}</span>
      <h4 className={`text-left ${baseStyles['resume-item-title']} ${styles.entryDetail}`}>
        {institution}
      </h4>
      <span className={`text-left ${baseStyles['resume-text-sm']} ${styles.entryDetail}`}>
        {major}
      </span>
      <span className={`text-left ${baseStyles['resume-text-sm']} ${styles.entryDetail}`}>
        {degree}
      </span>
    </div>
  );
};

/**
 * Ordered entries sharing the skills-list look: 2+ entries number from 1,
 * a single entry renders as a plain paragraph (mirrors PointTextList and the
 * DOCX export).
 */
const OrderedEntryList: React.FC<{ entries: string[] }> = ({ entries }) => {
  if (entries.length === 1) {
    return (
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        <span className={styles.skillText}>{stripPointMarker(entries[0])}</span>
      </div>
    );
  }
  return (
    <ol className={styles.skillOrderedList}>
      {entries.map((entry, index) => (
        <li key={index} className={styles.skillOrderedItem}>
          <span className={styles.skillNumber} aria-hidden="true">
            {index + 1}.
          </span>
          <span className={styles.skillText}>{stripPointMarker(entry)}</span>
        </li>
      ))}
    </ol>
  );
};

/**
 * Technical skills with standalone group headers ("AI 大模型" /
 * "Java 工程落地能力"): a head renders as a bold unnumbered label — the same
 * look as the project 项目职责 sub-module labels — and each group's items
 * number from 1 in their own <ol>. Ungrouped lists (the planner finds fewer
 * than two qualified heads) fall back to OrderedEntryList, so ordinary skill
 * lists render byte-identically.
 */
const SkillGroupList: React.FC<{ entries: string[] }> = ({ entries }) => {
  const groups = groupSkillEntries(entries);
  if (groups.length === 1 && groups[0].head === null) {
    return <OrderedEntryList entries={groups[0].items} />;
  }
  return (
    <div className={baseStyles['resume-stack']}>
      {groups.map((group, groupIndex) => (
        <React.Fragment key={groupIndex}>
          {group.head && (
            <div
              data-skill-group=""
              className={`flex items-baseline gap-[0.5ch] text-left ${baseStyles['resume-sub-label']} ${baseStyles['resume-text-sm']}`}
            >
              {/* Reserve the same 3ch number gutter as item rows. */}
              <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums" />
              <span className="min-w-0 flex-1 text-left">{stripPointMarker(group.head)}</span>
            </div>
          )}
          {group.items.length > 0 && (
            <ol className={styles.skillOrderedList}>
              {group.items.map((entry, index) => (
                <li key={index} className={styles.skillOrderedItem}>
                  <span className={styles.skillNumber} aria-hidden="true">
                    {index + 1}.
                  </span>
                  <span className={styles.skillText}>{stripPointMarker(entry)}</span>
                </li>
              ))}
            </ol>
          )}
        </React.Fragment>
      ))}
    </div>
  );
};

/** Drop blank/whitespace-only entries so empty builder lines never render (issue #763). */
const nonBlankStrings = (items?: string[]): string[] =>
  (items ?? []).filter((item): item is string => typeof item === 'string' && item.trim() !== '');

/**
 * The early `additional` slot renders ONLY 专业技能. Languages are
 * intentionally absent — the header fact grid shows them as 外语水平.
 * Cert/award lists are projected to the back by getRenderSections and
 * rendered via <LateAdditionalModule>.
 */
const AdditionalSkillsSection: React.FC<{
  additional: ResumeData['additional'];
  displayName?: string;
}> = ({ additional, displayName = 'Skills' }) => {
  const technicalSkills = nonBlankStrings(additional?.technicalSkills);
  if (technicalSkills.length === 0) return null;
  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={baseStyles['resume-section-title']}>{displayName}</h3>
      <SkillGroupList entries={technicalSkills} />
    </div>
  );
};

/**
 * 培训与证书 / 荣誉奖项 render as independent titled modules at the BACK of
 * the resume (after custom sections), so certs/awards are never folded into
 * the skill numbering. A single entry renders as a plain paragraph.
 */
const LateAdditionalModule: React.FC<{
  additional: ResumeData['additional'] | undefined;
  kind: LateAdditionalModuleKind;
  labels?: Partial<AdditionalSectionLabels>;
  headings?: Partial<ResumeSectionHeadings>;
}> = ({ additional, kind, labels, headings }) => {
  const field = kind === 'certifications' ? 'certificationsTraining' : 'awards';
  const entries = nonBlankStrings(additional?.[field]);
  if (entries.length === 0) return null;
  const title = resolveAdditionalModuleTitle(kind, headings, labels?.[kind]);
  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={baseStyles['resume-section-title']}>{title}</h3>
      <OrderedEntryList entries={entries} />
    </div>
  );
};

export default ResumeSingleColumn;
