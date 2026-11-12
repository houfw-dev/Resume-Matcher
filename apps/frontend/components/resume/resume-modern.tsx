import React from 'react';
import { Globe, Linkedin, Github, ExternalLink } from 'lucide-react';
import type {
  ResumeData,
  SectionMeta,
  AdditionalSectionLabels,
  ResumeSectionHeadings,
  Experience,
  Education,
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
import { DescriptionList } from './description-list';
import { buildHeaderFactCells, HeaderFactGrid } from './header-fact-grid';
import { stripPointMarker } from './list-format';
import { SkillGroupList } from './skill-list';
import { promoteWorkDepartment } from './work-department';
import { OrderedStringList, PointTextList } from './point-text-list';
import baseStyles from './styles/_base.module.css';
import styles from './styles/modern.module.css';

interface ResumeModernProps {
  data: ResumeData;
  showContactIcons?: boolean;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
  personalInfoLabels?: Partial<PersonalInfoLabels>;
}

/**
 * Modern Resume Template
 *
 * Single-column layout with user-selectable accent colors.
 * Features colored section headers with underline and decorative name underline.
 * ATS-compatible: all visual elements are real DOM text nodes.
 *
 * Section order: Determined by sectionMeta ordering
 */
export const ResumeModern: React.FC<ResumeModernProps> = ({
  data,
  showContactIcons = false,
  additionalSectionLabels,
  sectionHeadings,
  personalInfoLabels,
}) => {
  const { personalInfo, summary, workExperience, education, personalProjects, additional } = data;

  const infoLabels: PersonalInfoLabels = {
    ...DEFAULT_PERSONAL_INFO_LABELS,
    ...personalInfoLabels,
  };

  // Visible sections in canonical order plus the render-only late markers for
  // 培训与证书 / 荣誉奖项 (projected to the back by getRenderSections).
  const renderSections = getRenderSections(data);

  // Only the social-link row remains in the header; phone/email/location are
  // facts in HeaderFactGrid and carry no icons.
  const contactIcons: Record<string, React.ReactNode> = {
    Website: <Globe size={12} />,
    LinkedIn: <Linkedin size={12} />,
    GitHub: <Github size={12} />,
  };

  // Basic-info facts （性别/年龄/学历/工作年限/求职意向/意向城市/电话/邮箱/
  // 外语水平） render in the centered fact grid, mirroring swiss-single's
  // header contract. The old uppercase title h2 / inline contact line are
  // absorbed: title becomes the 求职意向 fact, location/phone/email join it.
  const factCells = buildHeaderFactCells({
    personalInfo,
    education,
    languages: additional?.languages,
    labels: infoLabels,
  });

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
        {displayLabel && <span className={baseStyles['text-muted']}>{displayLabel}</span>}
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

  // Social links keep their own comma-separated row under the fact grid.
  const socialItems = [
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
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            <PointTextList text={summary} />
          </div>
        );

      case 'workExperience':
        if (!workExperience || workExperience.length === 0) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            <div className={`${baseStyles['resume-items']} ${styles.entryGridSection}`}>
              {workExperience.map((exp) => {
                // A legacy plain department line ("全球资金部") is lifted into
                // the department column and removed from the bullet list.
                const promoted = promoteWorkDepartment(exp);
                return (
                  <div
                    key={exp.id}
                    className={`${baseStyles['resume-item']} ${styles.entryGridItem}`}
                  >
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
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {personalProjects.map((project) => (
                <div key={project.id} className={baseStyles['resume-item']}>
                  <div
                    className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
                  >
                    <div className="flex items-baseline gap-2">
                      <h4 className={baseStyles['resume-item-title']}>{project.name}</h4>
                      {(project.github || project.website) && (
                        <span className="flex gap-1.5">
                          {project.github && (
                            <a
                              href={
                                project.github.startsWith('http')
                                  ? project.github
                                  : `https://${project.github}`
                              }
                              target="_blank"
                              rel="noopener noreferrer"
                              className={baseStyles['resume-link-pill']}
                            >
                              <Github size={10} />
                              {project.github
                                .replace(/^https?:\/\//, '')
                                .replace(/^www\./, '')
                                .replace(/\/$/, '')}
                            </a>
                          )}
                          {project.website && (
                            <a
                              href={
                                project.website.startsWith('http')
                                  ? project.website
                                  : `https://${project.website}`
                              }
                              target="_blank"
                              rel="noopener noreferrer"
                              className={baseStyles['resume-link-pill']}
                            >
                              <ExternalLink size={10} />
                              {project.website
                                .replace(/^https?:\/\//, '')
                                .replace(/^www\./, '')
                                .replace(/\/$/, '')}
                            </a>
                          )}
                        </span>
                      )}
                    </div>
                    {project.years && (
                      <span className={`${baseStyles['resume-date']} ml-4`}>
                        {formatDateRange(project.years)}
                      </span>
                    )}
                  </div>
                  {project.role && (
                    <div
                      className={`${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}
                    >
                      <span>{project.role}</span>
                    </div>
                  )}
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
            <h3 className={styles['section-title-accent']}>{section.displayName}</h3>
            <div className={`${baseStyles['resume-items']} ${styles.entryGridSection}`}>
              {education.map((edu) => (
                <div
                  key={edu.id}
                  className={`${baseStyles['resume-item']} ${styles.entryGridItem}`}
                >
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
          return (
            <DynamicResumeSectionModern key={section.id} sectionMeta={section} resumeData={data} />
          );
        }
        return null;
    }
  };

  return (
    <div className={styles.container}>
      {/* Header Section - Centered Layout (always first) */}
      {personalInfo && (
        <header className={`text-center ${baseStyles['resume-header']}`}>
          {/* Name - Centered */}
          {personalInfo.name && (
            <h1 className={`${baseStyles['resume-name']} tracking-tight uppercase mb-1`}>
              {personalInfo.name}
            </h1>
          )}

          {/* Decorative accent underline under name */}
          <div className={styles['name-underline']} aria-hidden="true" />

          {/* Labeled basic-info facts: the former uppercase title h2 becomes
              the 求职意向 cell; location/phone/email join the same grid. */}
          <HeaderFactGrid cells={factCells} />

          {/* Social links - own comma-separated centered row */}
          {socialItems.length > 0 && (
            <div
              className={`flex flex-wrap justify-center items-center gap-x-1 gap-y-1 mt-2 ${baseStyles['resume-meta']}`}
            >
              {socialItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && <span className={baseStyles['text-muted']}>,</span>}
                  {item}
                </React.Fragment>
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

/** Drop blank/whitespace-only entries so empty builder lines never render (issue #763). */
const nonBlankStrings = (items?: string[]): string[] =>
  (items ?? []).filter((item): item is string => typeof item === 'string' && item.trim() !== '');

/**
 * Work entry header as one justified row — time | company · location |
 * department | role — mirroring the swiss-single contract. The title stays an
 * h4 but sits flush right （两端对齐）; with a department the row uses four
 * tracks, without one, three tracks (time | company | role). The date never
 * wraps and long values wrap inside their own minmax(0, …) cell.
 */
const WorkEntryRow: React.FC<{ exp: Experience; department?: string }> = ({
  exp,
  department: departmentProp,
}) => {
  const date = formatDateRange(exp.years ?? '').trim();
  const company = exp.company?.trim() ?? '';
  const location = exp.location?.trim() ?? '';
  const department = (departmentProp ?? '').trim();
  const role = exp.title?.trim() ?? '';

  if (!date && !company && !department && !location && !role) return null;

  const gridClass = department ? styles.entryGrid : styles.entryGridThree;

  return (
    <div className={`${gridClass} ${baseStyles['resume-row-tight']}`}>
      <span className={styles.entryDate}>{date}</span>
      <span className={baseStyles['resume-item-subtitle']}>
        {company}
        {location && <span className={baseStyles['resume-meta-sm']}> · {location}</span>}
      </span>
      {department && <span className={styles.entryDepartment}>{department}</span>}
      <h4 className={`${baseStyles['resume-item-title']} ${styles.entryRoleEnd}`}>{role}</h4>
    </div>
  );
};

/**
 * Education entry header as one four-column row — time | university | major |
 * degree. The optional education.description field is the major column (same
 * convention as swiss-single), so it no longer renders as a separate
 * paragraph. Empty cells still reserve their track, keeping column edges
 * aligned across work and education entries.
 */
const EducationEntryRow: React.FC<{ edu: Education }> = ({ edu }) => {
  const date = formatDateRange(edu.years ?? '').trim();
  const institution = edu.institution?.trim() ?? '';
  const major = edu.description?.trim() ?? '';
  const degree = edu.degree?.trim() ?? '';

  if (!date && !institution && !major && !degree) return null;

  return (
    <div className={`${styles.entryGrid} ${baseStyles['resume-row-tight']}`}>
      <span className={styles.entryDate}>{date}</span>
      <h4 className={baseStyles['resume-item-title']}>{institution}</h4>
      <span className={styles.entryDepartment}>{major}</span>
      <span className={`${baseStyles['resume-item-subtitle']} ${styles.entryRoleEnd}`}>
        {degree}
      </span>
    </div>
  );
};

/**
 * The early `additional` slot renders ONLY the technical-skills block, as an
 * ordered numbered list — group heads are bold unnumbered labels and each
 * group restarts numbering at 1 — with no inline "Technical Skills:" label
 * (the section title already names the block). Languages never render here:
 * per the parsing-rules spec they live only in the header fact grid as the
 * 外语水平 fact. Cert/award lists are projected to the back of the resume by
 * getRenderSections and rendered via <LateAdditionalModule>.
 */
const AdditionalSkillsSection: React.FC<{
  additional: ResumeData['additional'];
  displayName?: string;
}> = ({ additional, displayName = 'Skills' }) => {
  if (!additional) return null;

  const technicalSkills = nonBlankStrings(additional.technicalSkills);
  if (technicalSkills.length === 0) return null;

  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={styles['section-title-accent']}>{displayName}</h3>
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        <SkillGroupList entries={technicalSkills} />
      </div>
    </div>
  );
};

/**
 * 培训与证书 / 荣誉奖项 render as independent accent-titled modules at the
 * BACK of the resume (after custom sections), entries comma-joined.
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
  const fallbackLabel = kind === 'certifications' ? 'Certifications:' : 'Awards:';
  const title = resolveAdditionalModuleTitle(kind, headings, labels?.[kind] ?? fallbackLabel);
  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={styles['section-title-accent']}>{title}</h3>
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        <span>{entries.map(stripPointMarker).join(', ')}</span>
      </div>
    </div>
  );
};

/**
 * Dynamic section wrapper for Modern template
 * Uses accent-colored section titles
 */
const DynamicResumeSectionModern: React.FC<{
  sectionMeta: SectionMeta;
  resumeData: ResumeData;
}> = ({ sectionMeta, resumeData }) => {
  // Get the custom section data
  const customSection = resumeData.customSections?.[sectionMeta.key];

  if (!customSection) return null;

  // Check if section has content
  const hasContent = (() => {
    switch (sectionMeta.sectionType) {
      case 'text':
        return Boolean(customSection.text?.trim());
      case 'itemList':
        return Boolean(customSection.items?.length);
      case 'stringList':
        return Boolean(customSection.strings?.length);
      default:
        return false;
    }
  })();

  if (!hasContent) return null;

  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={styles['section-title-accent']}>{sectionMeta.displayName}</h3>
      {renderDynamicContent(sectionMeta, customSection)}
    </div>
  );
};

/**
 * Render dynamic section content based on type
 */
function renderDynamicContent(
  sectionMeta: SectionMeta,
  customSection: NonNullable<ResumeData['customSections']>[string]
) {
  switch (sectionMeta.sectionType) {
    case 'text':
      if (!customSection.text?.trim()) return null;
      return <PointTextList text={customSection.text} />;

    case 'itemList':
      if (!customSection.items?.length) return null;
      return (
        <div className={baseStyles['resume-items']}>
          {customSection.items.map((item) => (
            <div key={item.id} className={baseStyles['resume-item']}>
              <div className={`${styles.entryLineGrid} ${baseStyles['resume-row-tight']}`}>
                <h4 className={baseStyles['resume-item-title']}>{item.title}</h4>
                {item.years && (
                  <span className={baseStyles['resume-meta-sm']}>
                    {formatDateRange(item.years)}
                  </span>
                )}
              </div>
              {(item.subtitle || item.location) && (
                <div
                  className={`${styles.entryLineGrid} ${baseStyles['resume-row']} ${baseStyles['resume-meta']}`}
                >
                  {item.subtitle ? <span>{item.subtitle}</span> : <span />}
                  {item.location && <span className={styles.entryLocation}>{item.location}</span>}
                </div>
              )}
              <DescriptionList items={item.description} styles={item.descriptionStyles} />
            </div>
          ))}
        </div>
      );

    case 'stringList':
      if (!customSection.strings?.length) return null;
      return (
        <OrderedStringList
          items={customSection.strings}
          textClassName={baseStyles['resume-text-sm']}
        />
      );

    default:
      return null;
  }
}

export default ResumeModern;
