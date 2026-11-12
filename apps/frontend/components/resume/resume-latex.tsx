import React from 'react';
import { Mail, Phone, Globe, Linkedin, Github, ExternalLink } from 'lucide-react';
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
import { stripPointMarker } from './list-format';
import { SkillGroupList } from './skill-list';
import { promoteWorkDepartment } from './work-department';
import { OrderedStringList, PointTextList } from './point-text-list';
import baseStyles from './styles/_base.module.css';
import styles from './styles/latex.module.css';

interface ResumeLatexProps {
  data: ResumeData;
  showContactIcons?: boolean;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
  personalInfoLabels?: Partial<PersonalInfoLabels>;
}

/**
 * LaTeX Resume Template
 *
 * Classic serif academic layout reminiscent of the popular LaTeX résumé templates:
 * centered small-caps name, Title-Case section headers with a full-width rule, and
 * company-first two-line entries (company + dates, then italic role + location).
 *
 * Single-typeface design: all text inherits `--header-font` (serif by default), so the
 * Header Font control drives the whole template. ATS-safe (all text is real DOM nodes).
 *
 * Section order: Determined by sectionMeta ordering.
 */
export const ResumeLatex: React.FC<ResumeLatexProps> = ({
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

  // LaTeX renders location as its own centered line, so it is not a contact-row item.
  const contactIcons: Record<string, React.ReactNode> = {
    Email: <Mail size={12} />,
    Phone: <Phone size={12} />,
    Website: <Globe size={12} />,
    LinkedIn: <Linkedin size={12} />,
    GitHub: <Github size={12} />,
  };

  // `displayLabel` renders a muted label before the value (e.g. 个人网站： …).
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
          <span>{displayText}</span>
        )}
      </span>
    );
  };

  // Build the contact row (phone, email, linkedin, github, website) joined by middots.
  const contactItems = [
    renderContactDetail('Phone', personalInfo?.phone),
    renderContactDetail('Email', personalInfo?.email, 'mailto:'),
    renderContactDetail('LinkedIn', personalInfo?.linkedin, '', infoLabels.linkedin),
    renderContactDetail('GitHub', personalInfo?.github, '', infoLabels.github),
    renderContactDetail('Website', personalInfo?.website, '', infoLabels.website),
  ].filter(Boolean);

  const renderBullets = (
    items?: string[],
    pointStyles?: ('bullet' | 'plain' | 'label')[],
    canonicalizeLabels = false
  ) => (
    <DescriptionList
      items={items}
      styles={pointStyles}
      canonicalizeLabels={canonicalizeLabels}
      flushLabels={canonicalizeLabels}
    />
  );

  const renderSection = (section: SectionMeta) => {
    switch (section.key) {
      case 'personalInfo':
        return null;

      case 'summary':
        if (!summary) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            <PointTextList text={summary} />
          </div>
        );

      case 'workExperience':
        if (!workExperience || workExperience.length === 0) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {workExperience.map((exp) => {
                // A legacy plain department line ("全球资金部") is lifted into
                // the department column and removed from the bullet list.
                const promoted = promoteWorkDepartment(exp);
                return (
                  <div key={exp.id} className={baseStyles['resume-item']}>
                    <WorkEntryRow exp={exp} department={promoted.department} />
                    {renderBullets(promoted.description, promoted.descriptionStyles)}
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
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {personalProjects.map((project) => (
                <div key={project.id} className={baseStyles['resume-item']}>
                  <div
                    className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className={styles.entryPrimary}>{project.name}</span>
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
                      <span className={`${styles.entryDates} ml-4`}>
                        {formatDateRange(project.years)}
                      </span>
                    )}
                  </div>
                  {project.role && (
                    <div className={baseStyles['resume-row']}>
                      <span className={styles.entrySecondary}>{project.role}</span>
                    </div>
                  )}
                  {renderBullets(project.description, project.descriptionStyles, true)}
                </div>
              ))}
            </div>
          </div>
        );

      case 'education':
        if (!education || education.length === 0) return null;
        return (
          <div key={section.id} className={baseStyles['resume-section']}>
            <h3 className={styles.sectionTitle}>{section.displayName}</h3>
            <div className={baseStyles['resume-items']}>
              {education.map((edu) => (
                <div key={edu.id} className={baseStyles['resume-item']}>
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
            labels={additionalSectionLabels}
          />
        );

      default:
        if (!section.isDefault) {
          return (
            <DynamicResumeSectionLatex
              key={section.id}
              sectionMeta={section}
              resumeData={data}
              renderBullets={renderBullets}
            />
          );
        }
        return null;
    }
  };

  return (
    <div className={styles.container}>
      {personalInfo && (
        <header className={`text-center ${baseStyles['resume-header']}`}>
          {personalInfo.name && <h1 className={`${styles.name} mb-1`}>{personalInfo.name}</h1>}
          {personalInfo.title && (
            <div className={`${styles.tagline} mb-1`}>{personalInfo.title}</div>
          )}
          {personalInfo.location && (
            <div className={`${styles.locationLine} mb-1`}>{personalInfo.location}</div>
          )}
          {contactItems.length > 0 && (
            <div
              className={`flex flex-wrap justify-center items-center gap-x-2 gap-y-1 ${styles.contactRow}`}
            >
              {contactItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && <span className={styles.contactSep}>·</span>}
                  {item}
                </React.Fragment>
              ))}
            </div>
          )}
        </header>
      )}

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
 * Work entry header as one justified serif row — time | company · location |
 * department | role — mirroring the swiss-single contract. Bold date/company
 * on the left, italic role flush right （两端对齐）. With a department it uses
 * four tracks; without one, three tracks (time | company | role). The date
 * never wraps and long values wrap inside their own minmax(0, …) cell.
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
      <span className={styles.entryPrimary}>
        {company}
        {location && <span className={baseStyles['resume-meta-sm']}> · {location}</span>}
      </span>
      {department && <span className={styles.entryDepartment}>{department}</span>}
      <span className={styles.entryRoleEnd}>{role}</span>
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
      <span className={styles.entryPrimary}>{institution}</span>
      <span className={styles.entryDepartment}>{major}</span>
      <span className={styles.entryRoleEnd}>{degree}</span>
    </div>
  );
};

/**
 * The early `additional` slot renders ONLY the skills block (technical skills
 * + languages). Technical skills render as an ordered numbered list — group
 * heads are bold unnumbered labels and each group restarts numbering at 1 —
 * with no inline "Technical Skills:" label (the section title already names
 * the block). Languages keep their bold inline label + comma-joined line.
 * Cert/award lists are projected to the back of the resume by
 * getRenderSections and rendered via <LateAdditionalModule>.
 */
const AdditionalSkillsSection: React.FC<{
  additional: ResumeData['additional'];
  displayName?: string;
  labels?: Partial<AdditionalSectionLabels>;
}> = ({ additional, displayName = 'Skills', labels }) => {
  if (!additional) return null;

  const technicalSkills = nonBlankStrings(additional.technicalSkills);
  const languages = nonBlankStrings(additional.languages);
  if (technicalSkills.length === 0 && languages.length === 0) return null;

  const languagesLabel = labels?.languages ?? 'Languages:';

  const line = (label: string, items: string[]) =>
    items.length > 0 ? (
      <div>
        <span className="font-bold">{label}</span> {items.map(stripPointMarker).join(', ')}
      </div>
    ) : null;

  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={styles.sectionTitle}>{displayName}</h3>
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        {technicalSkills.length > 0 && <SkillGroupList entries={technicalSkills} />}
        {line(languagesLabel, languages)}
      </div>
    </div>
  );
};

/**
 * 培训与证书 / 荣誉奖项 render as independent titled modules at the BACK of
 * the resume (after custom sections), entries comma-joined.
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
      <h3 className={styles.sectionTitle}>{title}</h3>
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        <span>{entries.map(stripPointMarker).join(', ')}</span>
      </div>
    </div>
  );
};

/**
 * Dynamic (custom) section wrapper for the LaTeX template.
 */
const DynamicResumeSectionLatex: React.FC<{
  sectionMeta: SectionMeta;
  resumeData: ResumeData;
  renderBullets: (
    items?: string[],
    pointStyles?: ('bullet' | 'plain' | 'label')[]
  ) => React.ReactNode;
}> = ({ sectionMeta, resumeData, renderBullets }) => {
  const customSection = resumeData.customSections?.[sectionMeta.key];
  if (!customSection) return null;

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
      <h3 className={styles.sectionTitle}>{sectionMeta.displayName}</h3>
      {sectionMeta.sectionType === 'text' && customSection.text?.trim() && (
        <PointTextList text={customSection.text} />
      )}
      {sectionMeta.sectionType === 'itemList' && customSection.items?.length ? (
        <div className={baseStyles['resume-items']}>
          {customSection.items.map((item) => (
            <div key={item.id} className={baseStyles['resume-item']}>
              <div className={`${styles.entryLineGrid} ${baseStyles['resume-row-tight']}`}>
                <span className={styles.entryPrimary}>{item.title}</span>
                {item.years && (
                  <span className={styles.entryDates}>{formatDateRange(item.years)}</span>
                )}
              </div>
              {(item.subtitle || item.location) && (
                <div className={`${styles.entryLineGrid} ${baseStyles['resume-row']}`}>
                  {item.subtitle ? (
                    <span className={styles.entrySecondary}>{item.subtitle}</span>
                  ) : (
                    <span />
                  )}
                  {item.location && <span className={styles.entryLocation}>{item.location}</span>}
                </div>
              )}
              {renderBullets(item.description, item.descriptionStyles)}
            </div>
          ))}
        </div>
      ) : null}
      {sectionMeta.sectionType === 'stringList' && customSection.strings?.length ? (
        <OrderedStringList
          items={customSection.strings}
          textClassName={baseStyles['resume-text-sm']}
        />
      ) : null}
    </div>
  );
};

export default ResumeLatex;
