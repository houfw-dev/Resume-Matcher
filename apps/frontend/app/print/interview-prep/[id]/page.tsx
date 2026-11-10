/**
 * Interview Preparation Print Page
 *
 * Server-rendered for headless-Chromium PDF capture (never add 'use client').
 * Mirrors the five sections shown by the builder's InterviewPrepView using
 * inline styles so rendering is independent of the app's Tailwind pipeline.
 */

import type { CSSProperties } from 'react';
import { fetchPrintResource } from '@/lib/print/fetch';
import { translate } from '@/lib/i18n/server';
import { resolveLocale } from '@/lib/i18n/locale';
import type { Locale } from '@/i18n/config';

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

interface InterviewPrepQuestion {
  question: string;
  focus_area?: string | null;
  suggested_answer_points?: string[];
}

interface InterviewPrepSkillGap {
  skill: string;
  why_it_matters: string;
  preparation_suggestion: string;
}

interface InterviewPrepData {
  role_fit_analysis: string[];
  resume_questions: InterviewPrepQuestion[];
  project_follow_ups: InterviewPrepQuestion[];
  skill_gaps: InterviewPrepSkillGap[];
  talking_points: string[];
}

interface PersonalInfo {
  name?: string;
}

async function fetchInterviewPrep(
  resumeId: string
): Promise<{ interviewPrep: InterviewPrepData | null; name: string }> {
  const res = await fetchPrintResource(`/resumes?resume_id=${encodeURIComponent(resumeId)}`);
  if (!res.ok) {
    throw new Error(`Failed to load resume (status ${res.status}).`);
  }
  const payload = (await res.json()) as {
    data: {
      interview_prep?: InterviewPrepData | null;
      processed_resume?: {
        personalInfo?: PersonalInfo;
      };
    };
  };

  return {
    interviewPrep: payload.data.interview_prep ?? null,
    name: payload.data.processed_resume?.personalInfo?.name ?? '',
  };
}

function parsePageSize(value: string | undefined): PageSize {
  if (value === 'A4' || value === 'LETTER') {
    return value;
  }
  return 'A4';
}

const sectionTitleStyle: CSSProperties = {
  fontSize: '12pt',
  fontWeight: 'bold',
  fontFamily: 'monospace',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  borderBottom: '1px solid #000',
  paddingBottom: '2mm',
  margin: '0 0 4mm 0',
};

const sectionStyle: CSSProperties = {
  border: '1px solid #000',
  padding: '5mm',
  marginBottom: '6mm',
  breakInside: 'avoid',
};

function BulletList({ items }: { items: string[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: '5mm', fontSize: '10.5pt', lineHeight: 1.5 }}>
      {items.map((item, index) => (
        <li key={`${item}-${index}`} style={{ marginBottom: '1.5mm' }}>
          {item}
        </li>
      ))}
    </ul>
  );
}

function QuestionList({ items, locale }: { items: InterviewPrepQuestion[]; locale: Locale }) {
  return (
    <div>
      {items.map((item, index) => (
        <div
          key={`${item.question}-${index}`}
          style={{
            border: '1px solid #000',
            padding: '3mm',
            marginBottom: '3mm',
            breakInside: 'avoid',
          }}
        >
          <p style={{ fontWeight: 'bold', fontSize: '10.5pt', margin: '0 0 2mm 0' }}>
            {item.question}
          </p>
          {item.focus_area && (
            <p
              style={{
                fontSize: '9pt',
                fontFamily: 'monospace',
                textTransform: 'uppercase',
                color: '#1D4ED8',
                margin: '0 0 2mm 0',
              }}
            >
              {translate(locale, 'interviewPrep.focusArea')}: {item.focus_area}
            </p>
          )}
          {item.suggested_answer_points && item.suggested_answer_points.length > 0 && (
            <>
              <p
                style={{
                  fontSize: '8.5pt',
                  fontFamily: 'monospace',
                  textTransform: 'uppercase',
                  color: '#555',
                  margin: '0 0 1.5mm 0',
                }}
              >
                {translate(locale, 'interviewPrep.suggestedAnswerPoints')}
              </p>
              <BulletList items={item.suggested_answer_points} />
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function SkillGapList({ items, locale }: { items: InterviewPrepSkillGap[]; locale: Locale }) {
  return (
    <div>
      {items.map((item, index) => (
        <div
          key={`${item.skill}-${index}`}
          style={{
            border: '1px solid #000',
            padding: '3mm',
            marginBottom: '3mm',
            breakInside: 'avoid',
          }}
        >
          <p style={{ fontWeight: 'bold', fontSize: '10.5pt', margin: '0 0 2mm 0' }}>
            {item.skill}
          </p>
          <p style={{ fontSize: '10pt', margin: '0 0 1.5mm 0' }}>
            <span
              style={{ fontFamily: 'monospace', fontSize: '8.5pt', textTransform: 'uppercase' }}
            >
              {translate(locale, 'interviewPrep.whyItMatters')}:{' '}
            </span>
            {item.why_it_matters}
          </p>
          <p style={{ fontSize: '10pt', margin: 0 }}>
            <span
              style={{ fontFamily: 'monospace', fontSize: '8.5pt', textTransform: 'uppercase' }}
            >
              {translate(locale, 'interviewPrep.preparationSuggestion')}:{' '}
            </span>
            {item.preparation_suggestion}
          </p>
        </div>
      ))}
    </div>
  );
}

export default async function PrintInterviewPrepPage({ params, searchParams }: PageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;

  const pageSize = parsePageSize(resolvedSearchParams?.pageSize);
  const pageDims = PAGE_DIMENSIONS[pageSize];
  const locale = resolveLocale(resolvedSearchParams?.lang);

  const { interviewPrep, name } = await fetchInterviewPrep(resolvedParams.id);
  const today = new Date().toLocaleDateString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  const margins = { top: 18, right: 18, bottom: 18, left: 18 };

  return (
    <div
      className="interview-prep-print bg-white"
      style={{
        width: `${pageDims.width}mm`,
        minHeight: `${pageDims.height}mm`,
        padding: `${margins.top}mm ${margins.right}mm ${margins.bottom}mm ${margins.left}mm`,
        boxSizing: 'border-box',
        fontFamily: 'Helvetica, Arial, sans-serif',
        color: '#000000',
      }}
    >
      <header
        style={{
          marginBottom: '6mm',
          paddingBottom: '3mm',
          borderBottom: '2px solid #000',
        }}
      >
        <h1 style={{ fontSize: '16pt', fontWeight: 'bold', margin: 0 }}>
          {translate(locale, 'interviewPrep.title')}
          {name ? ` — ${name}` : ''}
        </h1>
        <div style={{ marginTop: '2mm', fontSize: '9pt', fontFamily: 'monospace', color: '#555' }}>
          {today}
        </div>
      </header>

      {interviewPrep ? (
        <>
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>{translate(locale, 'interviewPrep.sections.roleFit')}</h2>
            <BulletList items={interviewPrep.role_fit_analysis} />
          </section>

          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>
              {translate(locale, 'interviewPrep.sections.resumeQuestions')}
            </h2>
            <QuestionList items={interviewPrep.resume_questions} locale={locale} />
          </section>

          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>
              {translate(locale, 'interviewPrep.sections.projectFollowUps')}
            </h2>
            <QuestionList items={interviewPrep.project_follow_ups} locale={locale} />
          </section>

          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>
              {translate(locale, 'interviewPrep.sections.skillGaps')}
            </h2>
            <SkillGapList items={interviewPrep.skill_gaps} locale={locale} />
          </section>

          <section style={{ ...sectionStyle, marginBottom: 0 }}>
            <h2 style={sectionTitleStyle}>
              {translate(locale, 'interviewPrep.sections.talkingPoints')}
            </h2>
            <BulletList items={interviewPrep.talking_points} />
          </section>
        </>
      ) : (
        <p style={{ fontSize: '11pt', color: '#666' }}>
          {translate(locale, 'interviewPrep.unavailableTitle')}
        </p>
      )}
    </div>
  );
}
