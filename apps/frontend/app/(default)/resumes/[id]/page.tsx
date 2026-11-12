'use client';

import React, { useEffect, useMemo, useState, useRef, useLayoutEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import Resume, { ResumeData } from '@/components/dashboard/resume-component';
import {
  fetchResume,
  downloadResumePdf,
  getResumePdfUrl,
  downloadResumeDocx,
  getResumeDocxUrl,
  deleteResume,
  retryProcessing,
  renameResume,
} from '@/lib/api/resume';
import { useStatusCache } from '@/lib/context/status-cache';
import {
  ArrowLeft,
  Edit,
  Download,
  FileText,
  Loader2,
  AlertCircle,
  Sparkles,
  Pencil,
  Stethoscope,
  Target,
} from 'lucide-react';
import Kanban from 'lucide-react/dist/esm/icons/kanban';
import { EnrichmentModal } from '@/components/enrichment/enrichment-modal';
import { DiagnosisModal } from '@/components/diagnosis/diagnosis-modal';
import { listApplications } from '@/lib/api/tracker';
import { countApplications } from '@/lib/utils/tracker-resume-filter';
import { useTranslations } from '@/lib/i18n';
import { withLocalizedDefaultSections } from '@/lib/utils/section-helpers';
import { buildResumeHeadingProps } from '@/lib/utils/resume-headings';
import { loadScopedTemplateSettings } from '@/lib/utils/template-settings-storage';
import { useLanguage } from '@/lib/context/language-context';
import { buildResumeFactFilename, downloadBlobAsFile, openUrlInNewTab } from '@/lib/utils/download';
import { useOperationOwner } from '@/hooks/use-operation-owner';

type ProcessingStatus = 'pending' | 'processing' | 'ready' | 'failed';

// Two parallel resume exports. DOCX chrome follows the resume CONTENT
// language (auto-detected server-side), so its request carries no lang.
type DownloadKind = 'pdf' | 'docx';

type DownloadErrorState = { kind: DownloadKind; message: string } | null;

export default function ResumeViewerPage() {
  const { t } = useTranslations();
  const translationsRef = useRef(t);
  useLayoutEffect(() => {
    translationsRef.current = t;
  }, [t]);
  const { uiLanguage } = useLanguage();
  const params = useParams();
  const router = useRouter();
  const { decrementResumes, setHasMasterResume } = useStatusCache();
  const [resumeData, setResumeData] = useState<ResumeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [isMasterResume, setIsMasterResume] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showDeleteSuccessDialog, setShowDeleteSuccessDialog] = useState(false);
  const [showDownloadSuccessDialog, setShowDownloadSuccessDialog] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<DownloadErrorState>(null);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [showEnrichmentModal, setShowEnrichmentModal] = useState(false);
  const [showDiagnosisModal, setShowDiagnosisModal] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [downloadingKind, setDownloadingKind] = useState<DownloadKind | null>(null);
  const [resumeTitle, setResumeTitle] = useState<string | null>(null);
  const renameBusyRef = useRef(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editingTitleValue, setEditingTitleValue] = useState('');
  const [isTailoredResume, setIsTailoredResume] = useState(false);
  // Null = count still loading (or the secondary fetch failed — the tracker
  // entry stays usable, only the badge is omitted).
  const [applicationCount, setApplicationCount] = useState<number | null>(null);

  const resumeId = params?.id as string;
  const {
    begin: beginResumeLoad,
    isCurrent: isCurrentResumeLoad,
    invalidate: invalidateResumeLoad,
  } = useOperationOwner(resumeId);
  const { begin: beginRetry, isCurrent: isCurrentRetry } = useOperationOwner(resumeId);
  const { begin: beginRename, isCurrent: isCurrentRename } = useOperationOwner(resumeId);
  const { begin: beginDownload, isCurrent: isCurrentDownload } = useOperationOwner(resumeId);
  const { begin: beginDelete, isCurrent: isCurrentDelete } = useOperationOwner(resumeId);

  const localizedResumeData = useMemo(() => {
    if (!resumeData) return null;
    return withLocalizedDefaultSections(resumeData, t);
  }, [resumeData, t]);

  // Template/typography settings are scoped per resume: screen preview, PDF
  // and diagnosis all read this resume's own snapshot (with the legacy global
  // choice as the one-time fallback), so another resume's template never
  // leaks into this one.
  const templateSettings = useMemo(() => loadScopedTemplateSettings(resumeId), [resumeId]);

  useEffect(() => {
    if (!resumeId) return;
    setShowEnrichmentModal(false);
    setShowDiagnosisModal(false);
    setIsRetrying(false);
    setDownloadingKind(null);
    renameBusyRef.current = false;
    setIsEditingTitle(false);
    setEditingTitleValue('');
    setRenameError(null);
    setDownloadError(null);
    setDeleteError(null);
    setShowDeleteDialog(false);
    setShowDeleteSuccessDialog(false);
    setShowDownloadSuccessDialog(false);
    const token = beginResumeLoad();
    if (token === null) return;

    const loadResume = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await fetchResume(resumeId);
        if (!isCurrentResumeLoad(token)) return;

        // Get processing status
        const status = (data.raw_resume?.processing_status || 'pending') as ProcessingStatus;
        setProcessingStatus(status);

        // Capture title for editable display (always set to clear stale state)
        setResumeTitle(data.title ?? null);
        setIsTailoredResume(Boolean(data.parent_id));

        // Prioritize processed_resume if available (structured JSON)
        if (data.processed_resume) {
          setResumeData(data.processed_resume as ResumeData);
          setError(null);
        } else if (status === 'failed') {
          setError(translationsRef.current('resumeViewer.errors.processingFailed'));
        } else if (status === 'processing') {
          setError(translationsRef.current('resumeViewer.errors.stillProcessing'));
        } else if (data.raw_resume?.content) {
          // Try to parse raw_resume content as JSON (for tailored resumes stored as JSON)
          try {
            const parsed = JSON.parse(data.raw_resume.content);
            setResumeData(parsed as ResumeData);
          } catch {
            setError(translationsRef.current('resumeViewer.errors.notProcessedYet'));
          }
        } else {
          setError(translationsRef.current('resumeViewer.errors.noDataAvailable'));
        }
      } catch (err) {
        if (!isCurrentResumeLoad(token)) return;
        console.error('Failed to load resume:', err);
        setError(translationsRef.current('resumeViewer.errors.failedToLoad'));
      } finally {
        if (isCurrentResumeLoad(token)) setLoading(false);
      }
    };

    loadResume();
    setIsMasterResume(localStorage.getItem('master_resume_id') === resumeId);
  }, [resumeId, beginResumeLoad, isCurrentResumeLoad]);

  // Tracker reverse-link count: how many cards apply this resume directly or
  // descend from it (server-side resume_id OR master_resume_id match). A
  // failure here must never block the viewer — log and leave the badge off.
  useEffect(() => {
    if (!resumeId) {
      setApplicationCount(null);
      return;
    }
    let cancelled = false;
    listApplications({ resumeId })
      .then((data) => {
        if (!cancelled) setApplicationCount(countApplications(data.columns));
      })
      .catch((err) => {
        console.error('Failed to load application count:', err);
        if (!cancelled) setApplicationCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [resumeId]);

  const handleRetryProcessing = async () => {
    if (!resumeId) return;
    const token = beginRetry();
    if (token === null) return;
    setIsRetrying(true);
    try {
      const result = await retryProcessing(resumeId);
      if (!isCurrentRetry(token)) return;
      setProcessingStatus(result.processing_status);
      if (result.processing_status === 'ready') {
        // Reload the page to show the processed resume
        window.location.reload();
      } else {
        setError(
          t(
            result.processing_status === 'failed'
              ? 'resumeViewer.errors.processingFailed'
              : 'resumeViewer.errors.stillProcessing'
          )
        );
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes('status 404')) {
        if (localStorage.getItem('master_resume_id') === resumeId) {
          localStorage.removeItem('master_resume_id');
          setHasMasterResume(false);
        }
        if (!isCurrentRetry(token)) return;
        setProcessingStatus(null);
        setError(t('common.resumeDeleted'));
      } else {
        if (!isCurrentRetry(token)) return;
        console.error('Retry processing failed:', err);
        setError(t('resumeViewer.errors.processingFailed'));
      }
    } finally {
      if (isCurrentRetry(token)) setIsRetrying(false);
    }
  };

  const handleEdit = () => {
    router.push(`/builder?id=${resumeId}`);
  };

  const handleTitleSave = async () => {
    if (renameBusyRef.current) return;
    const trimmed = editingTitleValue.trim();
    if (!trimmed || trimmed === resumeTitle) {
      setIsEditingTitle(false);
      return;
    }
    const token = beginRename();
    if (token === null) return;
    renameBusyRef.current = true;
    setIsEditingTitle(false);
    try {
      setRenameError(null);
      await renameResume(resumeId, trimmed);
      if (!isCurrentRename(token)) return;
      setResumeTitle(trimmed);
      setIsEditingTitle(false);
    } catch (err) {
      if (!isCurrentRename(token)) return;
      console.error('Failed to rename resume:', err);
      setRenameError(t('resumeViewer.errors.failedToRename'));
    } finally {
      if (isCurrentRename(token)) renameBusyRef.current = false;
    }
  };

  const handleTitleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleTitleSave();
    } else if (e.key === 'Escape') {
      setIsEditingTitle(false);
    }
  };

  // Reload resume data after enrichment
  const reloadResumeData = async (): Promise<boolean> => {
    const token = beginResumeLoad();
    if (token === null) return false;
    try {
      const data = await fetchResume(resumeId);
      if (!isCurrentResumeLoad(token)) return false;
      if (!data.processed_resume) throw new Error('Refreshed resume has no processed data');
      setResumeData(data.processed_resume as ResumeData);
      setError(null);
      return true;
    } catch (err) {
      if (!isCurrentResumeLoad(token)) return false;
      console.error('Failed to reload resume:', err);
      throw err;
    }
  };

  const handleEnrichmentComplete = async (): Promise<boolean> => {
    const refreshed = await reloadResumeData();
    if (refreshed) setShowEnrichmentModal(false);
    return refreshed;
  };

  const handleEnrichmentClose = () => {
    invalidateResumeLoad();
    setShowEnrichmentModal(false);
  };

  const handleDownload = async (kind: DownloadKind = 'pdf') => {
    const token = beginDownload();
    if (token === null) return;
    setDownloadingKind(kind);
    try {
      setDownloadError(null);
      const blob =
        kind === 'pdf'
          ? await downloadResumePdf(resumeId, templateSettings, uiLanguage)
          : // DOCX chrome follows the content language (server auto-detect).
            await downloadResumeDocx(resumeId);
      // Filename: 姓名-年龄-工作年限-学历-求职意向 for both PDF and Word.
      const personalInfo = resumeData?.personalInfo;
      const educationLevel =
        personalInfo?.educationLevel?.trim() ||
        resumeData?.education?.find((edu) => edu.degree?.trim())?.degree?.trim() ||
        null;
      const filename = buildResumeFactFilename(
        {
          name: personalInfo?.name,
          age: personalInfo?.age,
          workYears: personalInfo?.workYears,
          educationLevel,
          title: personalInfo?.title,
        },
        resumeId,
        kind
      );
      downloadBlobAsFile(blob, filename);
      if (!isCurrentDownload(token)) return;
      setShowDownloadSuccessDialog(true);
    } catch (err) {
      if (!isCurrentDownload(token)) return;
      console.error(`Failed to download resume ${kind}:`, err);
      if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
        const fallbackUrl =
          kind === 'pdf'
            ? getResumePdfUrl(resumeId, templateSettings, uiLanguage)
            : getResumeDocxUrl(resumeId);
        const didOpen = openUrlInNewTab(fallbackUrl);
        if (!didOpen) {
          setDownloadError({ kind, message: t('common.popupBlocked', { url: fallbackUrl }) });
        }
        return;
      }
      setDownloadError({ kind, message: t('resumeViewer.errors.failedToDownload') });
    } finally {
      if (isCurrentDownload(token)) setDownloadingKind(null);
    }
  };

  const handleDeleteResume = async () => {
    const token = beginDelete();
    if (token === null) return;
    try {
      setDeleteError(null);
      await deleteResume(resumeId);
      // Update cached counters
      decrementResumes();
      if (localStorage.getItem('master_resume_id') === resumeId) {
        localStorage.removeItem('master_resume_id');
        setHasMasterResume(false);
      }
      if (!isCurrentDelete(token)) return;
      setShowDeleteDialog(false);
      setShowDeleteSuccessDialog(true);
    } catch (err) {
      if (!isCurrentDelete(token)) return;
      console.error('Failed to delete resume:', err);
      setDeleteError(t('resumeViewer.errors.failedToDelete'));
      setShowDeleteDialog(false);
    }
  };

  const handleDeleteSuccessConfirm = () => {
    setShowDeleteSuccessDialog(false);
    router.push('/dashboard');
  };

  const handleDownloadSuccessConfirm = () => {
    setShowDownloadSuccessDialog(false);
  };

  // Delete-related dialogs, shared by the failed-processing error branch and the
  // main viewer branch so the "Delete & Start Over" recovery action works in the
  // error state. Previously these lived only in the main branch, so on the error
  // path the confirm dialog never mounted and the delete request was never sent.
  // (The loading branch omits them — it has no delete affordance.)
  const deleteDialogs = (
    <>
      <ConfirmDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title={
          isMasterResume ? t('confirmations.deleteMasterResumeTitle') : t('dashboard.deleteResume')
        }
        description={
          isMasterResume
            ? t('confirmations.deleteMasterResumeDescription')
            : t('confirmations.deleteResumeFromSystemDescription')
        }
        confirmLabel={t('confirmations.deleteResumeConfirmLabel')}
        cancelLabel={t('confirmations.keepResumeCancelLabel')}
        onConfirm={handleDeleteResume}
        variant="danger"
      />

      <ConfirmDialog
        open={showDeleteSuccessDialog}
        onOpenChange={setShowDeleteSuccessDialog}
        title={t('resumeViewer.deletedTitle')}
        description={
          isMasterResume
            ? t('resumeViewer.deletedDescriptionMaster')
            : t('resumeViewer.deletedDescriptionRegular')
        }
        confirmLabel={t('resumeViewer.returnToDashboard')}
        onConfirm={handleDeleteSuccessConfirm}
        variant="success"
        showCancelButton={false}
      />

      {deleteError && (
        <ConfirmDialog
          open={!!deleteError}
          onOpenChange={() => setDeleteError(null)}
          title={t('resumeViewer.deleteFailedTitle')}
          description={deleteError}
          confirmLabel={t('common.retry')}
          cancelLabel={t('common.cancel')}
          onConfirm={handleDeleteResume}
          onCancel={() => setDeleteError(null)}
          variant="danger"
        />
      )}
    </>
  );

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background">
        <Loader2 className="w-10 h-10 animate-spin text-primary mb-4" />
        <p className="font-mono text-sm font-bold uppercase text-primary">
          {t('resumeViewer.loading')}
        </p>
      </div>
    );
  }

  if (error || !resumeData) {
    const isProcessing = processingStatus === 'processing';
    const isFailed = processingStatus === 'failed';

    return (
      <>
        <div className="min-h-screen flex flex-col items-center justify-center bg-background p-4">
          <div
            className={`border p-6 text-center max-w-md shadow-sw-default ${
              isProcessing
                ? 'bg-blue-50 border-blue-200'
                : isFailed
                  ? 'bg-orange-50 border-orange-200'
                  : 'bg-red-50 border-red-200'
            }`}
          >
            <div className="flex justify-center mb-4">
              {isProcessing ? (
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
              ) : isFailed ? (
                <AlertCircle className="w-8 h-8 text-orange-600" />
              ) : (
                <AlertCircle className="w-8 h-8 text-destructive" />
              )}
            </div>
            <p
              className={`font-bold mb-4 ${
                isProcessing ? 'text-primary' : isFailed ? 'text-orange-700' : 'text-red-700'
              }`}
            >
              {error || t('resumeViewer.resumeNotFound')}
            </p>
            <div className="flex flex-col gap-2">
              {isFailed && (
                <>
                  <Button onClick={handleRetryProcessing} disabled={isRetrying}>
                    {isRetrying ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        {t('common.processing')}
                      </>
                    ) : (
                      t('resumeViewer.retryProcessing')
                    )}
                  </Button>
                  <Button variant="destructive" onClick={() => setShowDeleteDialog(true)}>
                    {t('resumeViewer.deleteAndStartOver')}
                  </Button>
                </>
              )}
              <Button variant="outline" onClick={() => router.push('/dashboard')}>
                {t('resumeViewer.returnToDashboard')}
              </Button>
            </div>
          </div>
        </div>
        {deleteDialogs}
      </>
    );
  }

  return (
    <div className="min-h-screen bg-background py-12 px-4 md:px-8 overflow-y-auto">
      <div className="max-w-7xl mx-auto">
        {/* Header Actions */}
        <div className="mb-8 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 no-print">
          <Button variant="outline" onClick={() => router.push('/dashboard')}>
            <ArrowLeft className="w-4 h-4" />
            {t('nav.backToDashboard')}
          </Button>

          <div className="flex gap-3">
            {isMasterResume && (
              <Button onClick={() => setShowEnrichmentModal(true)} className="gap-2">
                <Sparkles className="w-4 h-4" />
                {t('resumeViewer.enhanceResume')}
              </Button>
            )}
            <Button variant="outline" onClick={() => setShowDiagnosisModal(true)}>
              <Stethoscope className="w-4 h-4" />
              {t('resumeViewer.diagnoseResume')}
            </Button>
            <Button variant="outline" onClick={handleEdit}>
              <Edit className="w-4 h-4" />
              {t('dashboard.editResume')}
            </Button>
            {!isTailoredResume && processingStatus === 'ready' && (
              <Button
                variant="outline"
                onClick={() => router.push(`/tailor?source=${encodeURIComponent(resumeId)}`)}
              >
                <Target className="w-4 h-4" />
                {t('resumeViewer.tailorFromThis')}
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => router.push(`/tracker?resume=${encodeURIComponent(resumeId)}`)}
            >
              <Kanban className="w-4 h-4" />
              {t('resumeViewer.trackApplications')}
              {applicationCount !== null && applicationCount > 0 && (
                <span
                  data-testid="tracker-count"
                  className="ml-1 border border-black bg-paper-tint px-1 font-mono text-[10px]"
                >
                  {applicationCount}
                </span>
              )}
            </Button>
            <Button
              variant="success"
              onClick={() => handleDownload('pdf')}
              disabled={downloadingKind === 'pdf'}
            >
              {downloadingKind === 'pdf' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              {downloadingKind === 'pdf' ? t('common.generating') : t('dashboard.downloadPdf')}
            </Button>
            <Button
              variant="outline"
              onClick={() => handleDownload('docx')}
              disabled={downloadingKind === 'docx'}
            >
              {downloadingKind === 'docx' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FileText className="w-4 h-4" />
              )}
              {downloadingKind === 'docx' ? t('common.generating') : t('resumeViewer.downloadWord')}
            </Button>
          </div>
        </div>

        {/* Editable Title (tailored resumes only) */}
        {!isMasterResume && (
          <div className="mb-6 no-print">
            {isEditingTitle ? (
              <input
                type="text"
                value={editingTitleValue}
                onChange={(e) => setEditingTitleValue(e.target.value)}
                onBlur={handleTitleSave}
                onKeyDown={handleTitleKeyDown}
                autoFocus
                maxLength={80}
                placeholder={t('resumeViewer.titlePlaceholder')}
                className="font-serif text-2xl font-bold border-b-2 border-black bg-transparent outline-none w-full max-w-xl px-0 py-1"
              />
            ) : (
              <button
                onClick={() => {
                  setEditingTitleValue(resumeTitle || '');
                  setIsEditingTitle(true);
                }}
                className="group flex items-center gap-2 cursor-pointer bg-transparent border-none p-0"
              >
                <h2
                  className={`font-serif text-2xl font-bold border-b-2 border-transparent group-hover:border-black transition-colors ${!resumeTitle ? 'text-steel-grey' : ''}`}
                >
                  {resumeTitle || t('resumeViewer.titlePlaceholder')}
                </h2>
                <Pencil
                  className={`w-4 h-4 transition-opacity ${resumeTitle ? 'opacity-0 group-hover:opacity-60' : 'opacity-40 group-hover:opacity-60'}`}
                />
              </button>
            )}
          </div>
        )}

        {/* Resume Viewer */}
        <div className="flex justify-center pb-4">
          <div className="resume-print w-full max-w-[250mm] shadow-sw-lg border-2 border-black bg-white">
            <Resume
              resumeData={localizedResumeData || resumeData}
              template={templateSettings.template}
              settings={templateSettings}
              locale={uiLanguage}
              {...buildResumeHeadingProps(t)}
            />
          </div>
        </div>

        <div className="flex justify-end pt-4 no-print">
          <Button variant="destructive" onClick={() => setShowDeleteDialog(true)}>
            {isMasterResume
              ? t('confirmations.deleteMasterResumeTitle')
              : t('dashboard.deleteResume')}
          </Button>
        </div>
      </div>

      {deleteDialogs}

      <ConfirmDialog
        open={downloadError !== null}
        onOpenChange={(open) => !open && setDownloadError(null)}
        title={t('resumeViewer.downloadFailedTitle')}
        description={downloadError?.message ?? ''}
        confirmLabel={t('common.retry')}
        cancelLabel={t('common.cancel')}
        onConfirm={() => downloadError && handleDownload(downloadError.kind)}
        onCancel={() => setDownloadError(null)}
        variant="danger"
      />

      <ConfirmDialog
        open={renameError !== null}
        onOpenChange={(open) => !open && setRenameError(null)}
        title={t('resumeViewer.renameFailedTitle')}
        description={renameError ?? ''}
        confirmLabel={t('common.retry')}
        cancelLabel={t('common.cancel')}
        onConfirm={handleTitleSave}
        onCancel={() => setRenameError(null)}
        variant="danger"
      />

      <ConfirmDialog
        open={showDownloadSuccessDialog}
        onOpenChange={setShowDownloadSuccessDialog}
        title={t('common.success')}
        description={t('builder.alerts.downloadSuccess')}
        confirmLabel={t('common.ok')}
        onConfirm={handleDownloadSuccessConfirm}
        variant="success"
        showCancelButton={false}
      />

      {/* Enrichment Modal - Only for master resume */}
      {isMasterResume && (
        <EnrichmentModal
          resumeId={resumeId}
          isOpen={showEnrichmentModal}
          onClose={handleEnrichmentClose}
          onComplete={handleEnrichmentComplete}
        />
      )}

      <DiagnosisModal
        resumeId={resumeId}
        open={showDiagnosisModal}
        onOpenChange={setShowDiagnosisModal}
        intentionTitle={resumeData?.personalInfo?.title ?? ''}
        resumeData={localizedResumeData || resumeData}
      />
    </div>
  );
}
