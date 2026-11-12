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
import styles from './styles/clean.module.css';

interface ResumeCleanProps {
  data: ResumeData;
  showContactIcons?: boolean;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
  personalInfoLabels?: Partial<PersonalInfoLabels>;
}

/**
 * Clean Resume Template
 *
 * Minimal modern sans layout: centered light-weight name, a single pipe-separated
 * contact line, large understated gray UPPERCASE section headers with a thin rule,
 * and single-line entries (COMPANY | Role on the left, Location | Dates on the right).
 *
 * Single-typeface design: all text inherits `--body-font` (sans by default), so the
 * Body Font control drives the whole template. ATS-safe (all text is real DOM nodes).
 *
 * Section order: Determined by sectionMeta ordering.
 */
export const ResumeClean: React.FC<ResumeCleanProps> = ({
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

  // Basic-info facts （性别/年龄/学历/工作年限/求职意向/意向城市/电话/邮箱/
  // 外语水平） render in the centered fact grid, mirroring swiss-single's
  // header contract. The contact row therefore keeps only the labeled social
  // links (location/phone/email live as facts above it).
  const factCells = buildHeaderFactCells({
    personalInfo,
    education,
    languages: additional?.languages,
    labels: infoLabels,
  });

  const contactItems = [
    renderContactDetail('LinkedIn', personalInfo?.linkedin, '', infoLabels.linkedin),
    renderContactDetail('GitHub', personalInfo?.github, '', infoLabels.github),
    renderContactDetail('Website', personalInfo?.website, '', infoLabels.website),
  ].filter(Boolean);

  // Dynamic custom itemList sections keep the company-first four-track row.
  const renderItemHeader = (primary?: string, role?: string, location?: string, dates?: string) => (
    <div className={`${styles.entryItemGrid} ${baseStyles['resume-row-tight']}`}>
      <span className={styles.entryCompany}>{primary}</span>
      <span className={styles.entryRole}>{role}</span>
      <span className={styles.entryLocation}>{location}</span>
      <span className={styles.entryMeta}>{dates ? formatDateRange(dates) : ''}</span>
    </div>
  );

  const renderBullets = (items?: string[], pointStyles?: ('bullet' | 'plain' | 'label')[]) => (
    <DescriptionList items={items} styles={pointStyles} />
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
                    className={`flex justify-between items-baseline gap-3 ${baseStyles['resume-row-tight']}`}
                  >
                    <span className="flex items-baseline gap-2 min-w-0">
                      <span className={styles.entryCompany}>{project.name}</span>
                      {project.role && (
                        <>
                          <span className={styles.sep}>|</span>
                          <span className={styles.entryRole}>{project.role}</span>
                        </>
                      )}
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
                    </span>
                    {project.years && (
                      <span className={styles.entryMeta}>{formatDateRange(project.years)}</span>
                    )}
                  </div>
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
          />
        );

      default:
        if (!section.isDefault) {
          return (
            <DynamicResumeSectionClean
              key={section.id}
              sectionMeta={section}
              resumeData={data}
              renderBullets={renderBullets}
              renderItemHeader={renderItemHeader}
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
          {/* 求职意向（title）/ 意向城市（location）/ 电话 / 邮箱 join the
              labeled fact grid; no standalone tagline line remains. */}
          <HeaderFactGrid cells={factCells} />
          {contactItems.length > 0 && (
            <div
              className={`flex flex-wrap justify-center items-center gap-x-2 gap-y-1 mt-2 ${styles.contactRow}`}
            >
              {contactItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && <span className={styles.sep}>|</span>}
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
      <h3 className={styles.sectionTitle}>{displayName}</h3>
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        <SkillGroupList entries={technicalSkills} />
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
 * Work entry header as one justified row — time | company · location |
 * department | role — mirroring the swiss-single contract. With a department
 * it uses four tracks; without one, three tracks (time | company | role) so
 * the role still ends flush with the right content edge （两端对齐）. The date
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
      <span className={styles.entryCompany}>
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
 * convention as swiss-single), so it no longer renders as a separate paragraph.
 * Empty cells still reserve their track, keeping column edges aligned.
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
      <span className={styles.entryCompany}>{institution}</span>
      <span className={styles.entryDepartment}>{major}</span>
      <span className={styles.entryRoleEnd}>{degree}</span>
    </div>
  );
};

/**
 * Dynamic (custom) section wrapper for the Clean template.
 */
const DynamicResumeSectionClean: React.FC<{
  sectionMeta: SectionMeta;
  resumeData: ResumeData;
  renderBullets: (
    items?: string[],
    pointStyles?: ('bullet' | 'plain' | 'label')[]
  ) => React.ReactNode;
  renderItemHeader: (
    primary?: string,
    role?: string,
    location?: string,
    dates?: string
  ) => React.ReactNode;
}> = ({ sectionMeta, resumeData, renderBullets, renderItemHeader }) => {
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
              {renderItemHeader(item.title, item.subtitle, item.location, item.years)}
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

export default ResumeClean;
