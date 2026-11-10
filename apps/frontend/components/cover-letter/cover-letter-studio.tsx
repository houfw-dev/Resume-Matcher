'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import ArrowLeft from 'lucide-react/dist/esm/icons/arrow-left';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import Sparkles from 'lucide-react/dist/esm/icons/sparkles';
import Save from 'lucide-react/dist/esm/icons/save';
import Download from 'lucide-react/dist/esm/icons/download';
import Copy from 'lucide-react/dist/esm/icons/copy';
import Check from 'lucide-react/dist/esm/icons/check';
import AlertCircle from 'lucide-react/dist/esm/icons/alert-circle';

import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useTranslations } from '@/lib/i18n';
import { useLanguage } from '@/lib/context/language-context';
import type { ResumeData } from '@/components/dashboard/resume-component';
import {
  fetchResume,
  generateCoverLetterFromResume,
  updateCoverLetter,
  downloadCoverLetterPdf,
  getCoverLetterPdfUrl,
} from '@/lib/api/resume';
import { buildResumeFilename, downloadBlobAsFile, openUrlInNewTab } from '@/lib/utils/download';

export interface CoverLetterStudioProps {
  resumeId: string;
}

export function CoverLetterStudio({ resumeId }: CoverLetterStudioProps) {
  const { t } = useTranslations();
  // Keep the latest translator reachable without retriggering the load effect:
  // test doubles (and some render paths) hand back a fresh `t` each render,
  // which would otherwise refetch and overwrite unsaved generated content.
  const translationsRef = React.useRef(t);
  React.useLayoutEffect(() => {
    translationsRef.current = t;
  }, [t]);
  const router = useRouter();
  const { uiLanguage } = useLanguage();

  const [resumeData, setResumeData] = React.useState<ResumeData | null>(null);
  const [jobDescription, setJobDescription] = React.useState('');
  const [content, setContent] = React.useState('');
  const [baseline, setBaseline] = React.useState('');
  const [isLoading, setIsLoading] = React.useState(true);
  const [isGenerating, setIsGenerating] = React.useState(false);
  const [isSaving, setIsSaving] = React.useState(false);
  const [isDownloading, setIsDownloading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await fetchResume(resumeId);
        if (!active) return;
        setResumeData((data.processed_resume as ResumeData | null) ?? null);
        const existing = data.cover_letter ?? '';
        setContent(existing);
        setBaseline(existing);
      } catch (err) {
        console.error('Failed to load resume for cover letter:', err);
        if (active) setError(translationsRef.current('coverLetter.studio.errors.loadFailed'));
      } finally {
        if (active) setIsLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [resumeId]);

  const isDirty = content !== baseline;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') e.stopPropagation();
  };

  const handleGenerate = async () => {
    setIsGenerating(true);
    setError(null);
    setSaved(false);
    try {
      const generated = await generateCoverLetterFromResume(resumeId, jobDescription.trim());
      setContent(generated);
      // The backend persists the generated letter, so it is the new baseline.
      setBaseline(generated);
    } catch (err) {
      console.error('Failed to generate cover letter:', err);
      setError(t('coverLetter.studio.errors.generateFailed'));
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!isDirty || isSaving) return;
    setIsSaving(true);
    setError(null);
    try {
      await updateCoverLetter(resumeId, content);
      setBaseline(content);
      setSaved(true);
    } catch (err) {
      console.error('Failed to save cover letter:', err);
      setError(t('coverLetter.studio.errors.saveFailed'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleDownload = async () => {
    if (!content.trim()) {
      setError(t('coverLetter.studio.errors.emptyContent'));
      return;
    }
    setIsDownloading(true);
    setError(null);
    try {
      const blob = await downloadCoverLetterPdf(resumeId, 'A4', uiLanguage);
      const name = resumeData?.personalInfo?.name ?? null;
      downloadBlobAsFile(blob, buildResumeFilename(name, null, resumeId, 'cover-letter'));
    } catch (err) {
      console.error('Failed to download cover letter PDF:', err);
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        const fallbackUrl = getCoverLetterPdfUrl(resumeId, 'A4', uiLanguage);
        const didOpen = openUrlInNewTab(fallbackUrl);
        if (!didOpen) {
          setError(t('common.popupBlocked', { url: fallbackUrl }));
        }
        return;
      }
      setError(t('coverLetter.studio.errors.downloadFailed'));
    } finally {
      setIsDownloading(false);
    }
  };

  const handleCopy = async () => {
    if (!content.trim()) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy cover letter:', err);
      setError(t('coverLetter.studio.copyError'));
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background">
        <Loader2 className="w-10 h-10 animate-spin text-primary mb-4" />
        <p className="font-mono text-sm font-bold uppercase text-primary">{t('common.loading')}</p>
      </div>
    );
  }

  const wordCount = content
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0).length;

  return (
    <div className="min-h-screen bg-background py-12 px-4 md:px-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <Button variant="outline" onClick={() => router.push(`/resumes/${resumeId}`)}>
            <ArrowLeft className="w-4 h-4" />
            {t('coverLetter.studio.backToResume')}
          </Button>
          <h1 className="font-serif text-2xl md:text-3xl font-bold">{t('coverLetter.title')}</h1>
        </div>

        {error && (
          <div
            role="alert"
            className="mb-6 border-2 border-destructive bg-red-50 p-4 flex items-start gap-3 shadow-sw-default"
          >
            <AlertCircle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
            <p className="font-mono text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* JD input */}
          <section className="border-2 border-black bg-white shadow-sw-default flex flex-col">
            <div className="flex items-center justify-between p-4 border-b-2 border-black bg-[#F5F5F0]">
              <Label htmlFor="cover-letter-jd" className="text-sm">
                {t('coverLetter.studio.jobDescriptionLabel')}
              </Label>
              <span className="font-mono text-xs uppercase text-steel-grey">
                {t('common.optional')}
              </span>
            </div>
            <div className="p-4 flex flex-col flex-1">
              <p className="font-mono text-xs text-steel-grey mb-3">
                {t('coverLetter.studio.jobDescriptionHint')}
              </p>
              <Textarea
                id="cover-letter-jd"
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t('coverLetter.studio.jobDescriptionPlaceholder')}
                className="min-h-[260px] flex-1 font-mono text-sm leading-relaxed resize-y"
              />
              <p className="font-mono text-xs text-steel-grey mt-2 text-right">
                {t('tailor.charactersCount', { count: jobDescription.length })}
              </p>
              <Button onClick={handleGenerate} disabled={isGenerating} className="mt-3 w-full">
                {isGenerating ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {isGenerating
                  ? t('common.generating')
                  : content
                    ? t('coverLetter.regenerate')
                    : t('coverLetter.generate')}
              </Button>
            </div>
          </section>

          {/* Result */}
          <section className="border-2 border-black bg-white shadow-sw-default flex flex-col">
            <div className="flex items-center justify-between p-4 border-b-2 border-black bg-[#F5F5F0]">
              <Label htmlFor="cover-letter-content" className="text-sm">
                {t('coverLetter.studio.resultLabel')}
              </Label>
              <span className="font-mono text-xs text-steel-grey">
                {t('builder.contentStats.wordsChars', {
                  wordCount,
                  charCount: content.length,
                })}
              </span>
            </div>
            <div className="p-4 flex flex-col flex-1">
              <Textarea
                id="cover-letter-content"
                value={content}
                onChange={(e) => {
                  setContent(e.target.value);
                  setSaved(false);
                }}
                onKeyDown={handleKeyDown}
                placeholder={t('coverLetter.studio.emptyResult')}
                className="min-h-[260px] flex-1 font-mono text-sm leading-relaxed resize-y"
              />
              <div className="flex flex-wrap items-center gap-3 mt-4">
                <Button onClick={handleSave} disabled={!isDirty || isSaving} size="sm">
                  {isSaving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  {isSaving ? t('common.saving') : t('common.save')}
                </Button>
                <Button
                  variant="success"
                  onClick={handleDownload}
                  disabled={isDownloading || !content.trim()}
                  size="sm"
                >
                  {isDownloading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  {t('dashboard.downloadPdf')}
                </Button>
                <Button variant="outline" onClick={handleCopy} disabled={!content.trim()} size="sm">
                  {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  {copied ? t('coverLetter.copied') : t('coverLetter.copyToClipboard')}
                </Button>
                {saved && !isDirty && (
                  <span className="font-mono text-xs text-success">
                    {t('coverLetter.studio.saved')}
                  </span>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
