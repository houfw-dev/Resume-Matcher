'use client';

import { Button } from '@/components/ui/button';
import { JobDescriptionTextarea } from '@/components/common/job-description-textarea';
import { Label } from '@/components/ui/label';
import { Sparkles, Loader2, FileText, Mail, MessagesSquare } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTranslations } from '@/lib/i18n';

export interface GeneratePromptProps {
  /** Type of content to generate */
  type: 'cover-letter' | 'outreach' | 'interview-prep';
  /** Whether generation is in progress */
  isGenerating: boolean;
  /** Callback to trigger generation */
  onGenerate: () => void;
  /** Additional class names */
  className?: string;
  /**
   * Show the ad-hoc job-description input. Only standalone (non-tailored)
   * resumes pass this; tailored resumes target their stored JD instead.
   */
  showJobDescription?: boolean;
  /** Pasted job description for role-targeted generation */
  jobDescription?: string;
  /** Called when the pasted job description changes */
  onJobDescriptionChange?: (value: string) => void;
  /** Trigger role-targeted generation using the pasted job description */
  onGenerateWithJobDescription?: () => void;
}

const TYPE_ICONS = {
  'cover-letter': FileText,
  outreach: Mail,
  'interview-prep': MessagesSquare,
} as const;

/**
 * Workbench split card (Swiss International Style): a single bordered white
 * card with a mono header band, a left info rail and a right work zone. The
 * call to action adapts to the JD state — an empty JD shows one always-on
 * primary button, while a pasted JD promotes the role-targeted action to
 * primary and demotes resume-only generation to a quiet text link, so the
 * first thing the user sees is never a disabled button.
 */
export function GeneratePrompt({
  type,
  isGenerating,
  onGenerate,
  className,
  showJobDescription = false,
  jobDescription = '',
  onJobDescriptionChange,
  onGenerateWithJobDescription,
}: GeneratePromptProps) {
  const { t } = useTranslations();
  const isOutreach = type === 'outreach';
  const isInterviewPrep = type === 'interview-prep';
  const Icon = TYPE_ICONS[type];
  const title = isInterviewPrep
    ? t('interviewPrep.title')
    : isOutreach
      ? t('outreach.title')
      : t('coverLetter.title');
  const description = isInterviewPrep
    ? t('builder.generatePrompt.interviewPrepDescription')
    : isOutreach
      ? t('builder.generatePrompt.outreachDescription')
      : t('builder.generatePrompt.coverLetterDescription');
  const footerHint = isInterviewPrep
    ? t('builder.generatePrompt.interviewPrepFooter')
    : isOutreach
      ? t('builder.generatePrompt.outreachFooter')
      : t('builder.generatePrompt.coverLetterFooter');
  const hasJobDescription = jobDescription.trim().length > 0;

  const spinnerOrSparkles = isGenerating ? (
    <Loader2 className="h-4 w-4 animate-spin" />
  ) : (
    <Sparkles className="h-4 w-4" />
  );

  return (
    <div className={cn('flex min-h-[360px] items-center justify-center p-6 md:p-10', className)}>
      <div className="w-full max-w-4xl border border-black bg-white shadow-sw-default">
        {/* Header band: content type + generation status */}
        <div className="flex items-center justify-between gap-3 border-b border-black bg-[#F5F5F0] px-5 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <Icon className="h-4 w-4 shrink-0 text-primary" />
            <span className="truncate font-mono text-xs font-bold uppercase tracking-wider">
              {title}
            </span>
          </div>
          <span className="shrink-0 font-mono text-[11px] uppercase tracking-wide text-steel-grey">
            {t('builder.generatePrompt.statusPending')}
          </span>
        </div>

        <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          {/* Left info rail: what gets generated and the practical hint */}
          <div className="flex flex-col gap-3 border-b border-black p-5 md:border-b-0 md:border-r">
            <h3 className="font-serif text-lg font-bold leading-snug">
              {t('builder.generatePrompt.generateTitle', { title })}
            </h3>
            <p className="text-sm leading-relaxed text-ink-soft">{description}</p>
            <p className="pt-2 font-mono text-[11px] leading-relaxed text-steel-grey md:mt-auto">
              {footerHint}
            </p>
          </div>

          {/* Right work zone: optional JD input plus the adaptive actions */}
          <div className="flex flex-col gap-4 p-5">
            {showJobDescription ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label
                    htmlFor={`${type}-job-description`}
                    className="text-sm normal-case tracking-normal text-ink"
                  >
                    {t('builder.generatePrompt.jobDescriptionLabel')}
                  </Label>
                  <span className="font-mono text-[11px] uppercase text-steel-grey">
                    {t('common.optional')} ·{' '}
                    {t('tailor.charactersCount', { count: jobDescription.length })}
                  </span>
                </div>
                <JobDescriptionTextarea
                  id={`${type}-job-description`}
                  value={jobDescription}
                  onValueChange={(value) => onJobDescriptionChange?.(value)}
                  placeholder={t('builder.generatePrompt.jobDescriptionPlaceholder')}
                  className="min-h-[180px] resize-y"
                />
                <p className="font-mono text-[11px] leading-relaxed text-steel-grey">
                  {t('builder.generatePrompt.jobDescriptionHint')}
                </p>
                <div className="mt-auto flex flex-wrap items-center justify-end gap-4 pt-2">
                  {/* Resume-only generation stays reachable once a JD exists;
                      with an empty JD it IS the primary action. */}
                  {hasJobDescription && (
                    <Button
                      variant="link"
                      onClick={onGenerate}
                      disabled={isGenerating}
                      className="normal-case tracking-normal"
                    >
                      {t('builder.generatePrompt.generateWithoutJd')}
                    </Button>
                  )}
                  {hasJobDescription ? (
                    <Button
                      onClick={onGenerateWithJobDescription}
                      disabled={isGenerating}
                      className="gap-2"
                    >
                      {spinnerOrSparkles}
                      {isGenerating
                        ? t('common.generating')
                        : t('builder.generatePrompt.generateWithJd')}
                    </Button>
                  ) : (
                    <Button onClick={onGenerate} disabled={isGenerating} className="gap-2">
                      {spinnerOrSparkles}
                      {isGenerating
                        ? t('common.generating')
                        : t('builder.generatePrompt.generateButton', { title })}
                    </Button>
                  )}
                </div>
              </>
            ) : (
              <>
                {/* Tailored resumes: the stored JD drives generation, so the
                    panel explains that instead of offering a second input. */}
                <div className="border border-black bg-neutral-50 p-4">
                  <p className="font-mono text-xs leading-relaxed text-ink-soft">
                    {t('builder.generatePrompt.tailoredJdNote')}
                  </p>
                </div>
                <div className="mt-auto flex items-center justify-end pt-2">
                  <Button onClick={onGenerate} disabled={isGenerating} className="gap-2">
                    {spinnerOrSparkles}
                    {isGenerating
                      ? t('common.generating')
                      : t('builder.generatePrompt.generateButton', { title })}
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
