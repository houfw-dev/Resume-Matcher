'use client';

import { Fragment, useMemo } from 'react';
import { type ResumeData } from '@/components/dashboard/resume-component';
import { segmentTextByKeywords } from '@/lib/utils/keyword-matcher';
import { FileUser, Briefcase, GraduationCap, FolderKanban, Wrench } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import { cn } from '@/lib/utils';
import {
  stripPointMarker,
  looksLikeSubLabel,
  canonicalizeProjectSubLabel,
  canonicalizeProjectSubLabelPrefix,
  isProjectDescriptiveLabel,
  splitProjectPlainPrefix,
} from '@/components/resume/list-format';

interface HighlightedResumeViewProps {
  resumeData: ResumeData;
  keywords: Set<string>;
}

/**
 * Display resume content with matching keywords highlighted.
 * Shows all resume sections with visual highlighting of JD matches.
 */
export function HighlightedResumeView({ resumeData, keywords }: HighlightedResumeViewProps) {
  const { t } = useTranslations();

  // Drop blank/whitespace-only entries so empty lines (e.g. from editing in the
  // builder) never render in the preview (issue #763).
  // Source numbering is stripped everywhere: this preview renders its own
  // markers, so kept prefixes would double-number rows.
  const visibleTechnicalSkills =
    resumeData.additional?.technicalSkills
      ?.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
      .map(stripPointMarker) ?? [];
  const visibleLanguages =
    resumeData.additional?.languages
      ?.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
      .map(stripPointMarker) ?? [];
  const visibleCertificationsTraining =
    resumeData.additional?.certificationsTraining
      ?.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
      .map(stripPointMarker) ?? [];

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 p-4 border-b border-paper-tint bg-paper-tint">
        <FileUser className="w-4 h-4 text-ink-soft" />
        <h3 className="font-mono text-sm font-bold uppercase text-ink-soft">
          {t('builder.jdMatch.yourResume')}
        </h3>
        <span className="text-xs text-steel-grey ml-2">
          {t('builder.jdMatch.matchingKeywordsHighlighted')}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Summary */}
        {resumeData.summary && (
          <Section title={t('resume.sections.summary')} icon={<FileUser className="w-4 h-4" />}>
            <HighlightedText text={resumeData.summary} keywords={keywords} />
          </Section>
        )}

        {/* Work Experience */}
        {resumeData.workExperience && resumeData.workExperience.length > 0 && (
          <Section title={t('resume.sections.experience')} icon={<Briefcase className="w-4 h-4" />}>
            {resumeData.workExperience.map((exp) => (
              <div key={exp.id} className="mb-4 last:mb-0">
                <div className="font-semibold text-ink-soft">
                  <HighlightedText text={exp.title || ''} keywords={keywords} />
                  {exp.company && (
                    <span className="text-ink-soft">
                      {t('builder.jdMatch.atSeparator')}
                      <HighlightedText text={exp.company} keywords={keywords} />
                    </span>
                  )}
                </div>
                {exp.years && <div className="text-xs text-steel-grey mb-1">{exp.years}</div>}
                {exp.description && (
                  <ul className="space-y-1 text-sm">
                    {exp.description.map((bullet, i) => {
                      // M-02: honour the per-row bullet/plain/label setting so
                      // this preview agrees with the resume preview and the
                      // PDF: only bullet rows carry a marker, label rows are
                      // bold sub-module headings (legacy "plain" headings
                      // included).
                      const style = exp.descriptionStyles?.[i];
                      const isLabel =
                        style === 'label' || (style === 'plain' && looksLikeSubLabel(bullet));
                      const showMarker = style !== 'plain' && !isLabel;
                      return (
                        <li
                          key={i}
                          className={cn(
                            'flex text-ink-soft',
                            showMarker && 'ml-4',
                            isLabel && 'font-bold'
                          )}
                        >
                          {showMarker && (
                            <span className="mr-1.5 flex-shrink-0" aria-hidden="true">
                              &bull;&nbsp;
                            </span>
                          )}
                          <span>
                            <HighlightedText text={stripPointMarker(bullet)} keywords={keywords} />
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            ))}
          </Section>
        )}

        {/* Education */}
        {resumeData.education && resumeData.education.length > 0 && (
          <Section
            title={t('resume.sections.education')}
            icon={<GraduationCap className="w-4 h-4" />}
          >
            {resumeData.education.map((edu) => (
              <div key={edu.id} className="mb-3 last:mb-0">
                <div className="font-semibold text-ink-soft">
                  <HighlightedText text={edu.degree || ''} keywords={keywords} />
                </div>
                {edu.institution && (
                  <div className="text-sm text-ink-soft">
                    <HighlightedText text={edu.institution} keywords={keywords} />
                  </div>
                )}
                {edu.years && <div className="text-xs text-steel-grey">{edu.years}</div>}
              </div>
            ))}
          </Section>
        )}

        {/* Projects */}
        {resumeData.personalProjects && resumeData.personalProjects.length > 0 && (
          <Section
            title={t('resume.sections.projects')}
            icon={<FolderKanban className="w-4 h-4" />}
          >
            {resumeData.personalProjects.map((proj) => (
              <div key={proj.id} className="mb-4 last:mb-0">
                <div className="font-semibold text-ink-soft">
                  <HighlightedText text={proj.name || ''} keywords={keywords} />
                  {proj.role && (
                    <span className="text-ink-soft font-normal">
                      {' '}
                      {t('builder.jdMatch.roleSeparator')}{' '}
                      <HighlightedText text={proj.role} keywords={keywords} />
                    </span>
                  )}
                </div>
                {proj.years && <div className="text-xs text-steel-grey mb-1">{proj.years}</div>}
                {proj.description && (
                  <ul className="space-y-1 text-sm">
                    {(() => {
                      // Forward pass: descriptive labels (项目背景/技术栈) own
                      // an unnumbered body until the next label, and legacy
                      // glued rows ("项目简介：面向…") split into a bold
                      // canonical label plus aligned content — mirroring the
                      // PDF/DescriptionList rendering.
                      type RowView =
                        | { kind: 'label'; text: string }
                        | { kind: 'glued'; label: string; content: string }
                        | { kind: 'point'; text: string; showMarker: boolean };
                      const views: RowView[] = [];
                      let descriptiveActive = false;
                      proj.description!.forEach((bullet, i) => {
                        const style = proj.descriptionStyles?.[i];
                        const isLabelRow =
                          style === 'label' || (style === 'plain' && looksLikeSubLabel(bullet));
                        if (isLabelRow) {
                          const text = canonicalizeProjectSubLabel(stripPointMarker(bullet));
                          descriptiveActive = isProjectDescriptiveLabel(text);
                          views.push({ kind: 'label', text });
                          return;
                        }
                        const glued = splitProjectPlainPrefix(bullet);
                        if (glued) {
                          descriptiveActive = true;
                          views.push({ kind: 'glued', label: glued.label, content: glued.content });
                          return;
                        }
                        views.push({
                          kind: 'point',
                          text: canonicalizeProjectSubLabelPrefix(stripPointMarker(bullet)),
                          showMarker: style !== 'plain' && !descriptiveActive,
                        });
                      });
                      return views.map((view, i) => {
                        if (view.kind === 'glued') {
                          return (
                            <Fragment key={i}>
                              <li className="flex text-ink-soft font-bold">
                                <span>
                                  <HighlightedText text={view.label} keywords={keywords} />
                                </span>
                              </li>
                              <li className="flex text-ink-soft">
                                <span>
                                  <HighlightedText text={view.content} keywords={keywords} />
                                </span>
                              </li>
                            </Fragment>
                          );
                        }
                        if (view.kind === 'label') {
                          return (
                            <li key={i} className="flex text-ink-soft font-bold">
                              <span>
                                <HighlightedText text={view.text} keywords={keywords} />
                              </span>
                            </li>
                          );
                        }
                        return (
                          <li key={i} className="flex text-ink-soft">
                            {view.showMarker && (
                              <span className="mr-1.5 flex-shrink-0" aria-hidden="true">
                                &bull;&nbsp;
                              </span>
                            )}
                            <span>
                              <HighlightedText text={view.text} keywords={keywords} />
                            </span>
                          </li>
                        );
                      });
                    })()}
                  </ul>
                )}
              </div>
            ))}
          </Section>
        )}

        {/* Skills */}
        {resumeData.additional && (
          <Section title={t('resume.sections.skills')} icon={<Wrench className="w-4 h-4" />}>
            {visibleTechnicalSkills.length > 0 && (
              <div className="mb-3">
                <div className="text-xs font-mono uppercase text-steel-grey mb-1">
                  {t('resume.additional.technicalSkills')}
                </div>
                <div className="flex flex-wrap gap-1">
                  {visibleTechnicalSkills.map((skill, i) => (
                    <SkillTag key={i} text={skill} keywords={keywords} />
                  ))}
                </div>
              </div>
            )}

            {visibleLanguages.length > 0 && (
              <div className="mb-3">
                <div className="text-xs font-mono uppercase text-steel-grey mb-1">
                  {t('resume.sections.languages')}
                </div>
                <div className="flex flex-wrap gap-1">
                  {visibleLanguages.map((lang, i) => (
                    <SkillTag key={i} text={lang} keywords={keywords} />
                  ))}
                </div>
              </div>
            )}

            {visibleCertificationsTraining.length > 0 && (
              <div className="mb-3">
                <div className="text-xs font-mono uppercase text-steel-grey mb-1">
                  {t('resume.sections.certifications')}
                </div>
                <ul className="list-disc list-inside space-y-1 text-sm">
                  {visibleCertificationsTraining.map((cert, i) => (
                    <li key={i} className="text-ink-soft">
                      <HighlightedText text={cert} keywords={keywords} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Section>
        )}
      </div>
    </div>
  );
}

/**
 * Section wrapper component
 */
function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-paper-tint bg-white rounded-none">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-paper-tint bg-paper-tint">
        {icon}
        <span className="font-mono text-xs font-bold uppercase text-ink-soft">{title}</span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

/**
 * Component to render text with highlighted keywords.
 */
function HighlightedText({ text, keywords }: { text: string; keywords: Set<string> }) {
  const segments = useMemo(() => segmentTextByKeywords(text, keywords), [text, keywords]);

  return (
    <span>
      {segments.map((segment, i) =>
        segment.isMatch ? (
          <mark key={i} className="bg-yellow-200 text-black px-0.5">
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        )
      )}
    </span>
  );
}

/**
 * Skill tag with optional highlighting
 */
function SkillTag({ text, keywords }: { text: string; keywords: Set<string> }) {
  const isMatch = keywords.has(text.toLowerCase());

  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs ${
        isMatch ? 'bg-yellow-200 text-black font-medium' : 'bg-background text-ink-soft'
      }`}
    >
      {text}
    </span>
  );
}
