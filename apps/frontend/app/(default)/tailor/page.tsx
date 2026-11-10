'use client';

import React, { Suspense, useState, useEffect, useRef, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { JobDescriptionTextarea } from '@/components/common/job-description-textarea';
import { useResumePreview } from '@/components/common/resume_previewer_context';
import type { ImprovedResult } from '@/components/common/resume_previewer_context';
import type { ResumeData } from '@/components/dashboard/resume-component';
import {
  uploadJobDescriptions,
  previewImproveResume,
  confirmImproveResume,
  fetchResumeList,
  type ResumeListItem,
} from '@/lib/api/resume';
import { fetchPromptConfig, type PromptOption } from '@/lib/api/config';
import { getPreviewErrorMessage } from '@/lib/utils/preview-error';
import { selectTailorSource } from '@/lib/utils/tailor-source';
import { Dropdown } from '@/components/ui/dropdown';
import { useStatusCache } from '@/lib/context/status-cache';
import { Loader2, ArrowLeft, AlertTriangle, Settings } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import { DiffPreviewModal } from '@/components/tailor/diff-preview-modal';
import { ATSScoreCard } from '@/components/tailor/ats-score-card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useOperationOwner } from '@/hooks/use-operation-owner';
import { useAbortController } from '@/hooks/use-abort-controller';
import { isAbortError } from '@/lib/utils/abort';

function TailorPageContent() {
  const { t } = useTranslations();
  const { begin, isCurrent, invalidate } = useOperationOwner('tailor');
  const { getSignal, abort } = useAbortController();
  const confirmedResponses = useRef(new WeakMap<ImprovedResult, ImprovedResult>());
  const countedResumes = useRef(new Set<string>());
  const confirmationBusy = useRef(false);
  const [jobDescription, setJobDescription] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceResumeId, setSourceResumeId] = useState<string | null>(null);
  const [sourceOptions, setSourceOptions] = useState<ResumeListItem[]>([]);
  const [promptOptions, setPromptOptions] = useState<PromptOption[]>([]);
  const [selectedPromptId, setSelectedPromptId] = useState('keywords');
  const [promptLoading, setPromptLoading] = useState(false);
  const hasUserSelectedPrompt = useRef(false);
  const missingDiffConfirmInFlight = useRef(false);

  // Diff preview modal state
  const [showDiffModal, setShowDiffModal] = useState(false);
  const [pendingResult, setPendingResult] = useState<ImprovedResult | null>(null);
  const [diffConfirmError, setDiffConfirmError] = useState<string | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false);
  const [showMissingDiffDialog, setShowMissingDiffDialog] = useState(false);
  const [missingDiffResult, setMissingDiffResult] = useState<ImprovedResult | null>(null);
  const [missingDiffError, setMissingDiffError] = useState<string | null>(null);

  // Elapsed timer for long operations
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    setElapsed(0);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const router = useRouter();
  const searchParams = useSearchParams();
  const { setImprovedData } = useResumePreview();
  const {
    status: systemStatus,
    isLoading: statusLoading,
    incrementJobs,
    incrementImprovements,
    incrementResumes,
  } = useStatusCache();

  // Check if LLM is configured
  const isLlmConfigured = !statusLoading && systemStatus?.llm_configured;

  // Any master/standalone resume (parent_id NULL, ready) is an eligible
  // tailoring source. Selection priority: ?source= query param → master →
  // localStorage master → first eligible resume; none → back to dashboard.
  useEffect(() => {
    let cancelled = false;
    const requestedSource = searchParams.get('source');

    const loadSources = async () => {
      try {
        const list = await fetchResumeList(true);
        if (cancelled) return;
        const { eligible, selectedId } = selectTailorSource(
          list,
          requestedSource,
          localStorage.getItem('master_resume_id')
        );
        setSourceOptions(eligible);
        if (!selectedId) {
          router.push('/dashboard');
          return;
        }
        setSourceResumeId(selectedId);
      } catch (err) {
        // Network failure: preserve the old master-only fallback rather than
        // blocking a user whose master id is still cached locally.
        console.error('Failed to load tailoring source resumes', err);
        if (cancelled) return;
        const storedId = localStorage.getItem('master_resume_id');
        if (!storedId) {
          router.push('/dashboard');
        } else {
          setSourceResumeId(storedId);
        }
      }
    };

    loadSources();
    return () => {
      cancelled = true;
    };
  }, [router, searchParams]);

  useEffect(() => {
    let cancelled = false;

    const loadPromptConfig = async () => {
      setPromptLoading(true);
      try {
        const config = await fetchPromptConfig();
        if (!cancelled) {
          setPromptOptions(config.prompt_options || []);
          if (!hasUserSelectedPrompt.current) {
            setSelectedPromptId(config.default_prompt_id || 'keywords');
          }
        }
      } catch (err) {
        console.error('Failed to load prompt config', err);
      } finally {
        if (!cancelled) {
          setPromptLoading(false);
        }
      }
    };

    loadPromptConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const buildConfirmPayload = (result: ImprovedResult) => {
    if (!sourceResumeId) {
      throw new Error('Master resume ID is missing.');
    }
    const resumePreview = result.data.resume_preview;
    if (!resumePreview || typeof resumePreview !== 'object' || Array.isArray(resumePreview)) {
      throw new Error('Resume preview data is invalid.');
    }
    const previewRecord = resumePreview as unknown as Record<string, unknown>;
    if (
      !previewRecord.personalInfo ||
      typeof previewRecord.personalInfo !== 'object' ||
      Array.isArray(previewRecord.personalInfo)
    ) {
      throw new Error('Resume preview data is invalid.');
    }
    return {
      resume_id: sourceResumeId,
      job_id: result.data.job_id,
      preview_id: result.data.preview_id ?? null,
      improved_data: resumePreview as ResumeData,
      improvements:
        result.data.improvements?.map((item) => ({
          suggestion: item.suggestion,
          lineNumber: typeof item.lineNumber === 'number' ? item.lineNumber : null,
        })) ?? [],
    };
  };

  const confirmAndNavigate = async (result: ImprovedResult, token: number) => {
    let confirmed = confirmedResponses.current.get(result);
    if (!confirmed) {
      const expiresAt = Date.parse(result.data.preview_expires_at ?? '');
      if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
        throw new Error('Preview expired');
      }
      confirmed = await confirmImproveResume(buildConfirmPayload(result));
      // Acknowledgement is durable even if a later client effect fails.
      confirmedResponses.current.set(result, confirmed);
    }
    if (!isCurrent(token)) return;
    const newResumeId = confirmed?.data?.resume_id;
    if (newResumeId && !countedResumes.current.has(newResumeId)) {
      countedResumes.current.add(newResumeId);
      incrementImprovements();
      incrementResumes();
    }
    setImprovedData(confirmed);
    router.push(newResumeId ? `/resumes/${newResumeId}` : '/builder');
  };

  const offerFreshPreview = (failure: unknown): boolean => {
    if (!(failure instanceof Error) || !/preview expired|status (400|409)\b/i.test(failure.message))
      return false;
    invalidate();
    confirmationBusy.current = false;
    missingDiffConfirmInFlight.current = false;
    setIsConfirming(false);
    setIsLoading(false);
    setShowDiffModal(false);
    setShowMissingDiffDialog(false);
    setPendingResult(null);
    setMissingDiffResult(null);
    setDiffConfirmError(null);
    setMissingDiffError(null);
    setError(t('tailor.errors.previewUnavailable'));
    setShowRegenerateDialog(true);
    return true;
  };

  const getGenerateValidationError = (trimmedDescription: string) => {
    if (!trimmedDescription) return null;
    if (trimmedDescription.length < 50) {
      return t('tailor.errors.jobDescriptionTooShort');
    }
    return null;
  };

  const runGenerate = async (resumeId: string, description: string, token: number) => {
    // One controller spans the upload + preview legs so a single Cancel stops
    // whichever leg is in flight.
    const signal = getSignal();
    try {
      // 1. Upload Job Description
      // The API expects an array of strings
      const jobId = await uploadJobDescriptions([description], resumeId, signal);
      if (!isCurrent(token)) return;
      incrementJobs(); // Update cached counter

      // 2. Preview Resume
      const result = await previewImproveResume(resumeId, jobId, selectedPromptId, signal);
      if (!isCurrent(token)) return;

      if (!result?.data?.diff_summary || !result?.data?.detailed_changes) {
        console.warn('Diff data missing for tailor preview; requesting user confirmation.');
        setDiffConfirmError(null);
        setPendingResult(null);
        setShowDiffModal(false);
        setMissingDiffError(null);
        setMissingDiffResult(result);
        setShowMissingDiffDialog(true);
        return;
      }

      // 3. Show diff preview modal
      setDiffConfirmError(null);
      setMissingDiffError(null);
      setPendingResult(result);
      setShowDiffModal(true);
    } catch (err) {
      // User-initiated cancel: stay silent on the form instead of surfacing
      // the AbortError as a failure (handleCancel resets the loading state).
      if (isAbortError(err)) return;
      if (!isCurrent(token)) return;
      console.error(err);
      setError(getPreviewErrorMessage(err, t));
    }
  };

  const handleGenerate = async () => {
    const trimmedDescription = jobDescription.trim();
    if (!trimmedDescription || !sourceResumeId) return;
    const validationError = getGenerateValidationError(trimmedDescription);
    if (validationError) {
      setError(validationError);
      return;
    }
    const resumeId = sourceResumeId;
    const token = begin();
    if (token === null) return;
    setIsLoading(true);
    setError(null);
    startTimer();
    try {
      await runGenerate(resumeId, trimmedDescription, token);
    } finally {
      if (isCurrent(token)) {
        setIsLoading(false);
        stopTimer();
      }
    }
  };

  // Explicit user cancel: abort the in-flight upload/preview and retire the
  // operation token so the rejected continuation cannot touch state. No error
  // banner — stopping a job you asked to stop is not a failure.
  const handleCancel = () => {
    abort();
    invalidate();
    setIsLoading(false);
    stopTimer();
    setError(null);
  };

  // User confirms changes
  const handleConfirmChanges = async () => {
    if (!pendingResult || confirmationBusy.current) return;
    const token = begin();
    if (token === null) return;
    confirmationBusy.current = true;

    setIsConfirming(true);
    setError(null);
    setDiffConfirmError(null);

    try {
      await confirmAndNavigate(pendingResult, token);
      if (!isCurrent(token)) return;
      setShowDiffModal(false);
      setPendingResult(null);
    } catch (err) {
      if (!isCurrent(token)) return;
      console.error(err);
      if (offerFreshPreview(err)) return;
      const errorMessage = t('tailor.errors.failedToConfirm');
      setError(errorMessage);
      setDiffConfirmError(errorMessage);
    } finally {
      if (isCurrent(token)) {
        confirmationBusy.current = false;
        setIsConfirming(false);
      }
    }
  };

  // User rejects changes
  const handleRejectChanges = () => {
    if (confirmationBusy.current) return;
    invalidate();
    confirmationBusy.current = false;
    setIsConfirming(false);
    setShowDiffModal(false);
    setPendingResult(null);
    setDiffConfirmError(null);
    setShowRegenerateDialog(true);
  };

  const handleCloseDiffModal = () => {
    if (confirmationBusy.current) return;
    invalidate();
    confirmationBusy.current = false;
    setIsConfirming(false);
    setShowDiffModal(false);
    setPendingResult(null);
    setDiffConfirmError(null);
  };

  const handleCloseMissingDiffDialog = () => {
    invalidate();
    setIsLoading(false);
    setShowMissingDiffDialog(false);
    setMissingDiffResult(null);
    setMissingDiffError(null);
    missingDiffConfirmInFlight.current = false;
  };

  const handleMissingDiffConfirm = async () => {
    if (!missingDiffResult || isLoading || missingDiffConfirmInFlight.current) return;
    const token = begin();
    if (token === null) return;
    missingDiffConfirmInFlight.current = true;
    setIsLoading(true);
    setError(null);
    setMissingDiffError(null);
    try {
      await confirmAndNavigate(missingDiffResult, token);
      if (!isCurrent(token)) return;
      handleCloseMissingDiffDialog();
    } catch (err) {
      if (!isCurrent(token)) return;
      console.error(err);
      if (offerFreshPreview(err)) return;
      const errorMessage = t('tailor.errors.failedToConfirm');
      setError(errorMessage);
      setMissingDiffError(errorMessage);
    } finally {
      if (isCurrent(token)) {
        missingDiffConfirmInFlight.current = false;
        setIsLoading(false);
      }
    }
  };

  const handleRegenerateConfirm = async () => {
    setShowRegenerateDialog(false);
    const trimmedDescription = jobDescription.trim();
    if (!trimmedDescription || !sourceResumeId) return;
    const validationError = getGenerateValidationError(trimmedDescription);
    if (validationError) {
      setError(validationError);
      return;
    }
    const resumeId = sourceResumeId;
    const token = begin();
    if (token === null) return;
    setIsLoading(true);
    setError(null);
    startTimer();
    try {
      await runGenerate(resumeId, trimmedDescription, token);
    } finally {
      if (isCurrent(token)) {
        setIsLoading(false);
        stopTimer();
      }
    }
  };

  return (
    <div className="min-h-screen w-full bg-[#F6F5EE] flex flex-col items-center justify-center p-4 md:p-8 font-sans">
      <div className="w-full max-w-4xl bg-white border border-black shadow-sw-lg p-8 md:p-12 lg:p-14 relative">
        {/* Back Button */}
        <Button variant="link" className="absolute top-4 left-4" onClick={() => router.back()}>
          <ArrowLeft className="w-4 h-4" />
          {t('common.back')}
        </Button>

        <div className="mb-8 mt-4 text-center">
          <h1 className="font-serif text-4xl font-bold uppercase tracking-tight mb-2">
            {t('tailor.heroTitle')}
          </h1>
          <p className="font-mono text-sm text-primary font-bold uppercase">
            {'// '}
            {t('tailor.pasteJobDescriptionBelow')}
          </p>
        </div>

        {/* LLM Not Configured Warning */}
        {!statusLoading && !isLlmConfigured && (
          <div className="mb-6 border-2 border-amber-500 bg-amber-50 p-4 shadow-sw-default">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="font-mono text-sm font-bold uppercase tracking-wider text-amber-800">
                  {t('tailor.setupRequiredTitle')}
                </p>
                <p className="font-mono text-xs text-amber-700 mt-1">
                  {t('tailor.noApiKeyMessage')}
                </p>
                <Link
                  href="/settings"
                  className="inline-flex items-center gap-2 mt-3 text-amber-700 hover:text-amber-900 transition-colors"
                >
                  <Settings className="w-4 h-4" />
                  <span className="font-mono text-xs font-bold uppercase underline">
                    {t('tailor.configureApiKey')}
                  </span>
                </Link>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-6">
          <Dropdown
            options={sourceOptions.map((item) => ({
              id: item.resume_id,
              label: item.title?.trim() || item.filename || item.resume_id,
              description: item.is_master ? t('tailor.sourceMaster') : t('tailor.sourceStandalone'),
            }))}
            value={sourceResumeId ?? ''}
            onChange={(value) => setSourceResumeId(value)}
            label={t('tailor.selectResume')}
            description={t('tailor.sourceDescription')}
            disabled={isLoading || sourceOptions.length === 0}
          />

          <Dropdown
            options={
              promptOptions.length > 0
                ? promptOptions.map((opt) => ({
                    id: opt.id,
                    label: t(`tailor.promptOptions.${opt.id}.label`),
                    description: t(`tailor.promptOptions.${opt.id}.description`),
                  }))
                : [
                    {
                      id: 'nudge',
                      label: t('tailor.promptOptions.nudge.label'),
                      description: t('tailor.promptOptions.nudge.description'),
                    },
                    {
                      id: 'keywords',
                      label: t('tailor.promptOptions.keywords.label'),
                      description: t('tailor.promptOptions.keywords.description'),
                    },
                    {
                      id: 'full',
                      label: t('tailor.promptOptions.full.label'),
                      description: t('tailor.promptOptions.full.description'),
                    },
                  ]
            }
            value={selectedPromptId}
            onChange={(value) => {
              hasUserSelectedPrompt.current = true;
              setSelectedPromptId(value);
            }}
            label={t('tailor.promptLabel')}
            description={t('tailor.promptDescription')}
            disabled={isLoading || promptLoading}
          />

          <div className="relative">
            <JobDescriptionTextarea
              placeholder={t('tailor.jobDescriptionPlaceholder')}
              className="min-h-[300px] bg-background border-2 border-black focus:ring-0 focus:border-primary resize-none p-4 rounded-none"
              value={jobDescription}
              onValueChange={setJobDescription}
              disabled={isLoading}
            />
            <div className="absolute bottom-2 right-2 text-xs font-mono text-steel-grey pointer-events-none">
              {t('tailor.charactersCount', { count: jobDescription.length })}
            </div>
          </div>

          {error && (
            <div className="p-4 bg-red-100 border-2 border-destructive text-destructive text-sm font-mono flex items-center gap-2">
              <span>!</span> {error}
            </div>
          )}

          <Button
            size="lg"
            onClick={handleGenerate}
            disabled={isLoading || statusLoading || !jobDescription.trim() || !isLlmConfigured}
            className="w-full"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {t('common.processing')}
                {elapsed > 0 && (
                  <span className="font-mono text-xs opacity-70 ml-2">{elapsed}s</span>
                )}
              </>
            ) : statusLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {t('common.checking')}
              </>
            ) : !isLlmConfigured ? (
              t('tailor.configureApiKeyFirst')
            ) : (
              t('tailor.generateTailored')
            )}
          </Button>

          {/* Only the generation phase is cancelable: while a diff/missing-diff
              dialog is open, isLoading may describe a confirmation save instead,
              whose controller belongs to an already-finished request. */}
          {isLoading && !showDiffModal && !showMissingDiffDialog && !showRegenerateDialog && (
            <Button variant="outline" size="lg" onClick={handleCancel} className="mt-3 w-full">
              {t('common.cancel')}
            </Button>
          )}
        </div>
      </div>

      {/* ATS Score Breakdown — shown once a preview result is available */}
      {pendingResult?.data?.ats_score && (
        <div className="w-full max-w-4xl mt-6">
          <ATSScoreCard atsScore={pendingResult.data.ats_score} />
        </div>
      )}

      {/* Diff preview modal */}
      {showDiffModal && pendingResult && (
        <DiffPreviewModal
          isOpen={showDiffModal}
          isConfirming={isConfirming}
          onClose={handleCloseDiffModal}
          onReject={handleRejectChanges}
          onConfirm={handleConfirmChanges}
          diffSummary={pendingResult?.data?.diff_summary}
          detailedChanges={pendingResult?.data?.detailed_changes}
          errorMessage={diffConfirmError ?? undefined}
        />
      )}

      <ConfirmDialog
        open={showRegenerateDialog}
        onOpenChange={setShowRegenerateDialog}
        title={t('tailor.regenerateDialog.title')}
        description={t('tailor.regenerateDialog.description')}
        confirmLabel={t('tailor.regenerateDialog.confirmLabel')}
        cancelLabel={t('common.cancel')}
        variant="warning"
        onConfirm={handleRegenerateConfirm}
      />

      <ConfirmDialog
        open={showMissingDiffDialog}
        onOpenChange={(open) => {
          if (!open && !missingDiffConfirmInFlight.current) {
            handleCloseMissingDiffDialog();
          }
        }}
        title={t('tailor.missingDiffDialog.title')}
        description={t('tailor.missingDiffDialog.description')}
        confirmLabel={t('tailor.missingDiffDialog.confirmLabel')}
        cancelLabel={t('common.cancel')}
        variant="warning"
        closeOnConfirm={false}
        onConfirm={handleMissingDiffConfirm}
        onCancel={() => {
          if (!missingDiffConfirmInFlight.current) handleCloseMissingDiffDialog();
        }}
        confirmDisabled={isLoading || !missingDiffResult}
        cancelDisabled={isLoading}
        errorMessage={missingDiffError ?? undefined}
      />
    </div>
  );
}

export default function TailorPage() {
  const { t } = useTranslations();
  return (
    <Suspense fallback={<div className="p-8 font-mono text-sm">{t('common.loading')}</div>}>
      <TailorPageContent />
    </Suspense>
  );
}
