'use client';

import * as React from 'react';
import { AlertTriangle, Lightbulb, ListChecks, MessageSquareText, Target } from 'lucide-react';
import { GeneratePrompt } from './generate-prompt';
import type {
  InterviewPrepData,
  InterviewPrepQuestion,
  InterviewPrepSkillGap,
} from '@/components/common/resume_previewer_context';
import { cn } from '@/lib/utils';
import { useTranslations } from '@/lib/i18n';

interface InterviewPrepViewProps {
  interviewPrep: InterviewPrepData | null;
  isGenerating: boolean;
  error?: string | null;
  onGenerate: () => void;
  isTailoredResume: boolean;
  canGenerate?: boolean;
  unavailableMessage?: string | null;
  className?: string;
  /** Standalone resumes can paste an ad-hoc JD for role-targeted generation. */
  showJobDescription?: boolean;
  jobDescription?: string;
  onJobDescriptionChange?: (value: string) => void;
  onGenerateWithJobDescription?: () => void;
}

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <section className="border-2 border-black bg-white p-4 space-y-3">
      <div className="flex items-center gap-2 border-b border-black/10 pb-2">
        <Icon className="w-4 h-4 text-primary" />
        <h3 className="font-mono text-sm font-bold uppercase tracking-wider">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function StringList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={`${item}-${index}`} className="flex gap-2 text-sm leading-relaxed text-ink-soft">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 bg-primary" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function QuestionList({ items }: { items: InterviewPrepQuestion[] }) {
  const { t } = useTranslations();

  if (!items.length) return null;
  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <div key={`${item.question}-${index}`} className="border border-black bg-paper-tint p-3">
          <p className="font-mono text-sm font-bold leading-relaxed">{item.question}</p>
          {item.focus_area && (
            <p className="mt-2 text-xs font-mono uppercase tracking-wide text-primary">
              {t('interviewPrep.focusArea')}: {item.focus_area}
            </p>
          )}
          {item.suggested_answer_points.length > 0 && (
            <div className="mt-3">
              <p className="font-mono text-xs font-bold uppercase text-steel-grey">
                {t('interviewPrep.suggestedAnswerPoints')}
              </p>
              <StringList items={item.suggested_answer_points} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function SkillGapList({ items }: { items: InterviewPrepSkillGap[] }) {
  const { t } = useTranslations();

  if (!items.length) return null;
  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <div key={`${item.skill}-${index}`} className="border border-black bg-paper-tint p-3">
          <p className="font-mono text-sm font-bold uppercase">{item.skill}</p>
          <div className="mt-3 space-y-2 text-sm text-ink-soft">
            <p>
              <span className="font-mono text-xs font-bold uppercase text-steel-grey">
                {t('interviewPrep.whyItMatters')}:{' '}
              </span>
              {item.why_it_matters}
            </p>
            <p>
              <span className="font-mono text-xs font-bold uppercase text-steel-grey">
                {t('interviewPrep.preparationSuggestion')}:{' '}
              </span>
              {item.preparation_suggestion}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function InterviewPrepView({
  interviewPrep,
  isGenerating,
  error,
  onGenerate,
  isTailoredResume,
  canGenerate = true,
  unavailableMessage,
  className,
  showJobDescription = false,
  jobDescription = '',
  onJobDescriptionChange,
  onGenerateWithJobDescription,
}: InterviewPrepViewProps) {
  const { t } = useTranslations();

  if (!interviewPrep) {
    return (
      <div className={className}>
        {error && (
          <div className="mb-4 flex items-start gap-3 border border-destructive bg-[#FEF2F2] p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <p className="font-mono text-sm leading-relaxed text-destructive">{error}</p>
          </div>
        )}
        {isTailoredResume && !canGenerate ? (
          // Same workbench-card shell as GeneratePrompt, so the three
          // attachment tabs share one visual language even when generation is
          // unavailable: header band, info rail, contextual note, no actions.
          <div className="flex min-h-[360px] items-center justify-center p-6 md:p-10">
            <div className="w-full max-w-4xl border border-black bg-white shadow-sw-default">
              <div className="flex items-center gap-2 border-b border-black bg-[#F5F5F0] px-5 py-2.5">
                <MessageSquareText className="h-4 w-4 shrink-0 text-warning" />
                <span className="font-mono text-xs font-bold uppercase tracking-wider">
                  {t('interviewPrep.title')}
                </span>
              </div>
              <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                <div className="flex flex-col gap-3 border-b border-black p-5 md:border-b-0 md:border-r">
                  <AlertTriangle className="h-5 w-5 text-warning" />
                  <h3 className="font-serif text-lg font-bold leading-snug">
                    {t('interviewPrep.unavailableTitle')}
                  </h3>
                </div>
                <div className="p-5">
                  <div className="border border-warning bg-[#FFF7ED] p-4">
                    <p className="font-mono text-xs leading-relaxed text-ink-soft">
                      {unavailableMessage ?? t('interviewPrep.missingContextDescription')}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <GeneratePrompt
            type="interview-prep"
            isGenerating={isGenerating}
            onGenerate={onGenerate}
            showJobDescription={showJobDescription}
            jobDescription={jobDescription}
            onJobDescriptionChange={onJobDescriptionChange}
            onGenerateWithJobDescription={onGenerateWithJobDescription}
          />
        )}
      </div>
    );
  }

  return (
    <div className={cn('space-y-4 p-6', className)}>
      {error && (
        <div className="flex items-start gap-3 border border-destructive bg-[#FEF2F2] p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p className="font-mono text-sm leading-relaxed text-destructive">{error}</p>
        </div>
      )}
      {isTailoredResume && !canGenerate && (
        <div className="flex items-start gap-3 border border-warning bg-[#FFF7ED] p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p className="font-mono text-sm leading-relaxed text-ink-soft">
            {unavailableMessage ?? t('interviewPrep.missingContextDescription')}
          </p>
        </div>
      )}

      <Section title={t('interviewPrep.sections.roleFit')} icon={Target}>
        <StringList items={interviewPrep.role_fit_analysis} />
      </Section>

      <Section title={t('interviewPrep.sections.resumeQuestions')} icon={MessageSquareText}>
        <QuestionList items={interviewPrep.resume_questions} />
      </Section>

      <Section title={t('interviewPrep.sections.projectFollowUps')} icon={ListChecks}>
        <QuestionList items={interviewPrep.project_follow_ups} />
      </Section>

      <Section title={t('interviewPrep.sections.skillGaps')} icon={AlertTriangle}>
        <SkillGapList items={interviewPrep.skill_gaps} />
      </Section>

      <Section title={t('interviewPrep.sections.talkingPoints')} icon={Lightbulb}>
        <StringList items={interviewPrep.talking_points} />
      </Section>
    </div>
  );
}
