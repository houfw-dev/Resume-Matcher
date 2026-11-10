/**
 * JD Match Print Page
 *
 * Server-rendered for headless-Chromium PDF capture (never add 'use client').
 * Reuses the same pure keyword-matching utilities as the builder's
 * JDComparisonView so the exported PDF shows identical stats and highlights.
 */

import type { CSSProperties, ReactNode } from 'react';
import { fetchPrintResource } from '@/lib/print/fetch';
import { translate } from '@/lib/i18n/server';
import { resolveLocale } from '@/lib/i18n/locale';
import {
  calculateMatchStats,
  extractKeywords,
  segmentTextByKeywords,
} from '@/lib/utils/keyword-matcher';

const PAGE_DIMENSIONS = {
  A4: { width: 210, height: 297 },
  LETTER: { width: 215.9, height: 279.4 },
} as const;

type PageSize = 'A4' | 'LETTER';

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{
    pageSize?: string;
    lang?: string;
  }>;
};

interface WorkExperience {
  title?: string;
  company?: string;
  years?: string;
  description?: string[];
}

interface Education {
  degree?: string;
  institution?: string;
  years?: string;
}

interface PersonalProject {
  name?: string;
  role?: string;
  years?: string;
  description?: string[];
}

interface Additional {
  technicalSkills?: string[];
  languages?: string[];
  certificationsTraining?: string[];
}

interface ResumeData {
  summary?: string;
  workExperience?: WorkExperience[];
  education?: Education[];
  personalProjects?: PersonalProject[];
  additional?: Additional;
}

interface JdMatchData {
  jobDescription: string;
  resumeData: ResumeData;
}

async function fetchJdMatchData(resumeId: string): Promise<JdMatchData> {
  const [resumeRes, jdRes] = await Promise.all([
    fetchPrintResource(`/resumes?resume_id=${encodeURIComponent(resumeId)}`),
    fetchPrintResource(`/resumes/${encodeURIComponent(resumeId)}/job-description`),
  ]);

  if (!resumeRes.ok) {
    throw new Error(`Failed to load resume (status ${resumeRes.status}).`);
  }
  if (!jdRes.ok) {
    throw new Error(`Failed to load job description (status ${jdRes.status}).`);
  }

  const resumePayload = (await resumeRes.json()) as {
    data: { processed_resume?: ResumeData };
  };
  const jdPayload = (await jdRes.json()) as { content: string };

  return {
    jobDescription: jdPayload.content ?? '',
    resumeData: resumePayload.data.processed_resume ?? {},
  };
}

function parsePageSize(value: string | undefined): PageSize {
  if (value === 'A4' || value === 'LETTER') {
    return value;
  }
  return 'A4';
}

function buildResumeText(resumeData: ResumeData): string {
  const parts: string[] = [];

  if (resumeData.summary) parts.push(resumeData.summary);

  resumeData.workExperience?.forEach((exp) => {
    if (exp.title) parts.push(exp.title);
    if (exp.company) parts.push(exp.company);
    exp.description?.forEach((d) => parts.push(d));
  });

  resumeData.education?.forEach((edu) => {
    if (edu.degree) parts.push(edu.degree);
    if (edu.institution) parts.push(edu.institution);
  });

  resumeData.personalProjects?.forEach((proj) => {
    if (proj.name) parts.push(proj.name);
    if (proj.role) parts.push(proj.role);
    proj.description?.forEach((d) => parts.push(d));
  });

  if (resumeData.additional) {
    resumeData.additional.technicalSkills?.forEach((s) => parts.push(s));
    resumeData.additional.languages?.forEach((l) => parts.push(l));
    resumeData.additional.certificationsTraining?.forEach((c) => parts.push(c));
  }

  return parts.join(' ');
}

function HighlightedText({ text, keywords }: { text: string; keywords: Set<string> }) {
  const segments = segmentTextByKeywords(text, keywords);
  return (
    <>
      {segments.map((segment, i) =>
        segment.isMatch ? (
          <mark key={i} style={{ backgroundColor: '#FEF08A', color: '#000', padding: '0 1px' }}>
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        )
      )}
    </>
  );
}

const sectionTitleStyle: CSSProperties = {
  fontSize: '11pt',
  fontWeight: 'bold',
  fontFamily: 'monospace',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  borderBottom: '1px solid #000',
  paddingBottom: '1.5mm',
  margin: '0 0 3mm 0',
};

const blockStyle: CSSProperties = {
  border: '1px solid #000',
  padding: '4mm',
  marginBottom: '5mm',
};

function ResumeSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={blockStyle}>
      <h3 style={sectionTitleStyle}>{title}</h3>
      {children}
    </section>
  );
}

export default async function PrintJdMatchPage({ params, searchParams }: PageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;

  const pageSize = parsePageSize(resolvedSearchParams?.pageSize);
  const pageDims = PAGE_DIMENSIONS[pageSize];
  const locale = resolveLocale(resolvedSearchParams?.lang);

  const { jobDescription, resumeData } = await fetchJdMatchData(resolvedParams.id);

  const keywords = extractKeywords(jobDescription);
  const stats = calculateMatchStats(buildResumeText(resumeData), keywords);
  const rateColor =
    stats.matchPercentage >= 50 ? '#15803D' : stats.matchPercentage >= 30 ? '#B45309' : '#DC2626';

  const margins = { top: 16, right: 16, bottom: 16, left: 16 };

  return (
    <div
      className="jd-match-print bg-white"
      style={{
        width: `${pageDims.width}mm`,
        minHeight: `${pageDims.height}mm`,
        padding: `${margins.top}mm ${margins.right}mm ${margins.bottom}mm ${margins.left}mm`,
        boxSizing: 'border-box',
        fontFamily: 'Helvetica, Arial, sans-serif',
        color: '#000000',
        fontSize: '10pt',
      }}
    >
      <header
        style={{
          marginBottom: '5mm',
          paddingBottom: '3mm',
          borderBottom: '2px solid #000',
        }}
      >
        <h1 style={{ fontSize: '15pt', fontWeight: 'bold', margin: '0 0 2mm 0' }}>
          {translate(locale, 'builder.jdMatch.aboutTitle')}
        </h1>
        <div
          style={{
            display: 'flex',
            gap: '8mm',
            fontFamily: 'monospace',
            fontSize: '9.5pt',
          }}
        >
          <span>
            {translate(locale, 'builder.jdMatch.stats.keywordsExtracted', {
              count: stats.totalKeywords,
            })}
          </span>
          <span>
            {translate(locale, 'builder.jdMatch.stats.matchesFound', {
              count: stats.matchCount,
            })}
          </span>
          <span>
            {translate(locale, 'builder.jdMatch.stats.matchRateLabel')}{' '}
            <strong style={{ color: rateColor, fontSize: '11pt' }}>{stats.matchPercentage}%</strong>
          </span>
        </div>
      </header>

      <section style={blockStyle}>
        <h3 style={sectionTitleStyle}>
          {translate(locale, 'builder.jdMatch.jobDescriptionTitle')}
        </h3>
        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5, fontSize: '9.5pt' }}>
          {jobDescription}
        </div>
      </section>

      <ResumeSection title={translate(locale, 'builder.jdMatch.yourResume')}>
        {resumeData.summary && (
          <p style={{ margin: '0 0 3mm 0', lineHeight: 1.5 }}>
            <HighlightedText text={resumeData.summary} keywords={keywords} />
          </p>
        )}

        {resumeData.workExperience && resumeData.workExperience.length > 0 && (
          <div style={{ marginBottom: '3mm' }}>
            <h4 style={{ ...sectionTitleStyle, fontSize: '9.5pt' }}>
              {translate(locale, 'resume.sections.experience')}
            </h4>
            {resumeData.workExperience.map((exp, i) => (
              <div key={i} style={{ marginBottom: '2.5mm' }}>
                <div style={{ fontWeight: 'bold' }}>
                  <HighlightedText text={exp.title ?? ''} keywords={keywords} />
                  {exp.company && (
                    <span style={{ fontWeight: 'normal' }}>
                      {translate(locale, 'builder.jdMatch.atSeparator')}
                      <HighlightedText text={exp.company} keywords={keywords} />
                    </span>
                  )}
                  {exp.years && (
                    <span style={{ fontWeight: 'normal', color: '#555', fontSize: '9pt' }}>
                      {' '}
                      ({exp.years})
                    </span>
                  )}
                </div>
                {exp.description && (
                  <ul style={{ margin: '1mm 0 0 0', paddingLeft: '5mm', lineHeight: 1.45 }}>
                    {exp.description.map((bullet, j) => (
                      <li key={j}>
                        <HighlightedText text={bullet} keywords={keywords} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}

        {resumeData.education && resumeData.education.length > 0 && (
          <div style={{ marginBottom: '3mm' }}>
            <h4 style={{ ...sectionTitleStyle, fontSize: '9.5pt' }}>
              {translate(locale, 'resume.sections.education')}
            </h4>
            {resumeData.education.map((edu, i) => (
              <div key={i} style={{ marginBottom: '1.5mm' }}>
                <strong>
                  <HighlightedText text={edu.degree ?? ''} keywords={keywords} />
                </strong>
                {edu.institution && (
                  <span>
                    {' '}
                    — <HighlightedText text={edu.institution} keywords={keywords} />
                  </span>
                )}
                {edu.years && (
                  <span style={{ color: '#555', fontSize: '9pt' }}> ({edu.years})</span>
                )}
              </div>
            ))}
          </div>
        )}

        {resumeData.personalProjects && resumeData.personalProjects.length > 0 && (
          <div style={{ marginBottom: '3mm' }}>
            <h4 style={{ ...sectionTitleStyle, fontSize: '9.5pt' }}>
              {translate(locale, 'resume.sections.projects')}
            </h4>
            {resumeData.personalProjects.map((proj, i) => (
              <div key={i} style={{ marginBottom: '2.5mm' }}>
                <div style={{ fontWeight: 'bold' }}>
                  <HighlightedText text={proj.name ?? ''} keywords={keywords} />
                  {proj.role && (
                    <span style={{ fontWeight: 'normal' }}>
                      {' '}
                      {translate(locale, 'builder.jdMatch.roleSeparator')}{' '}
                      <HighlightedText text={proj.role} keywords={keywords} />
                    </span>
                  )}
                </div>
                {proj.description && (
                  <ul style={{ margin: '1mm 0 0 0', paddingLeft: '5mm', lineHeight: 1.45 }}>
                    {proj.description.map((bullet, j) => (
                      <li key={j}>
                        <HighlightedText text={bullet} keywords={keywords} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}

        {resumeData.additional && (
          <div>
            <h4 style={{ ...sectionTitleStyle, fontSize: '9.5pt' }}>
              {translate(locale, 'resume.sections.skills')}
            </h4>
            {resumeData.additional.technicalSkills &&
              resumeData.additional.technicalSkills.length > 0 && (
                <p style={{ margin: '0 0 1.5mm 0', lineHeight: 1.6 }}>
                  {resumeData.additional.technicalSkills.map((skill, i) => (
                    <span
                      key={i}
                      style={{
                        display: 'inline-block',
                        border: '1px solid #000',
                        padding: '0.5mm 2mm',
                        margin: '0 2mm 1.5mm 0',
                        fontSize: '9pt',
                        backgroundColor: keywords.has(skill.toLowerCase()) ? '#FEF08A' : '#F0F0E8',
                      }}
                    >
                      {skill}
                    </span>
                  ))}
                </p>
              )}
            {resumeData.additional.certificationsTraining &&
              resumeData.additional.certificationsTraining.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: '5mm', lineHeight: 1.45 }}>
                  {resumeData.additional.certificationsTraining.map((cert, i) => (
                    <li key={i}>
                      <HighlightedText text={cert} keywords={keywords} />
                    </li>
                  ))}
                </ul>
              )}
          </div>
        )}
      </ResumeSection>
    </div>
  );
}
