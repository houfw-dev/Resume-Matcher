'use client';

import * as React from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import AlertCircle from 'lucide-react/dist/esm/icons/alert-circle';
import Check from 'lucide-react/dist/esm/icons/check';
import UploadCloud from 'lucide-react/dist/esm/icons/upload-cloud';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw';
import Trash2 from 'lucide-react/dist/esm/icons/trash-2';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useTranslations } from '@/lib/i18n';
import { useLanguage } from '@/lib/context/language-context';
import { useFileUpload } from '@/hooks/use-file-upload';
import { useResumeProcessing } from '@/hooks/use-resume-processing';
import { useStatusCache } from '@/lib/context/status-cache';
import { getUploadUrl } from '@/lib/api/client';
import { deleteResume } from '@/lib/api/resume';
import { withLocalizedDefaultSections } from '@/lib/utils/section-helpers';
import { buildResumeHeadingProps } from '@/lib/utils/resume-headings';
import { loadTemplateSettings } from '@/lib/utils/template-settings-storage';
import { cn } from '@/lib/utils';
import Resume, { type ResumeData } from '@/components/dashboard/resume-component';

const ACCEPTED_FILE_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
  'application/msword', // .doc
];
const MAX_FILE_SIZE = 4 * 1024 * 1024; // 4MB

type Phase = 'idle' | 'uploading' | 'processing' | 'ready' | 'parseFailed';

interface ResumeImportWorkspaceProps {
  open: boolean;
  onClose: () => void;
  /** Called whenever the resume list may have changed (upload, delete). */
  onResumeMutated?: () => void;
}

/**
 * Dashboard "简历导入" entry point: upload a resume → wait for the server-side
 * parse → persist through the normal resume pipeline. The workspace only
 * imports and previews; it never runs a diagnosis (the per-resume diagnosis
 * modal stays available from the resume viewer) and never stores the source
 * binary.
 */
export function ResumeImportWorkspace({
  open,
  onClose,
  onResumeMutated,
}: ResumeImportWorkspaceProps) {
  const { t } = useTranslations();
  const { uiLanguage } = useLanguage();
  const headingProps = React.useMemo(() => buildResumeHeadingProps(t), [t]);
  // Builder template choice is a single global setting; snapshot it for the
  // lifetime of this workspace so the preview never drifts mid-session.
  const templateSettings = React.useState(() => loadTemplateSettings())[0];
  const { incrementResumes, decrementResumes, setHasMasterResume } = useStatusCache();

  const [phase, setPhase] = React.useState<Phase>('idle');
  const [resumeId, setResumeId] = React.useState<string | null>(null);
  const [uploadError, setUploadError] = React.useState<string | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [retryingParse, setRetryingParse] = React.useState(false);
  const [parsedResume, setParsedResume] = React.useState<ResumeData | null>(null);

  const {
    status: procStatus,
    resume: procResume,
    readyGeneration,
    retry: retryProcessingPoll,
  } = useResumeProcessing(resumeId);

  const [{ files, isDragging, errors, isUploadingGlobal }, uploadActions] = useFileUpload({
    maxSize: MAX_FILE_SIZE,
    accept: ACCEPTED_FILE_TYPES.join(','),
    multiple: false,
    uploadUrl: getUploadUrl(),
    onFilesAdded: () => {
      setUploadError(null);
      setPhase('uploading');
    },
    onUploadSuccess: (_file, response) => {
      const data = response as {
        resume_id?: string;
        is_master?: boolean;
        processing_status?: string;
      };
      if (!data.resume_id) {
        setUploadError(t('dashboard.uploadDialog.successMissingId'));
        setPhase('idle');
        return;
      }
      setResumeId(data.resume_id);
      incrementResumes();
      if (data.is_master) {
        localStorage.setItem('master_resume_id', data.resume_id);
        setHasMasterResume(true);
      }
      onResumeMutated?.();
      setPhase('processing');
    },
    onUploadError: (_file, message, metadata) => {
      // A 4xx can still carry the saved row — observe it (typically failed).
      if (metadata?.resume_id) {
        setResumeId(metadata.resume_id);
        if (metadata.is_master) {
          localStorage.setItem('master_resume_id', metadata.resume_id);
          setHasMasterResume(true);
        }
        setPhase('processing');
      } else {
        setUploadError(message || t('dashboard.uploadDialog.failed'));
        setPhase('idle');
      }
    },
  });

  // Reflect parse-pipeline observations into the workspace state machine.
  React.useEffect(() => {
    if (!resumeId) return;
    if (procStatus === 'failed') {
      setPhase((current) =>
        current === 'idle' || current === 'uploading' || current === 'processing'
          ? 'parseFailed'
          : current
      );
    } else if (procStatus === 'processing') {
      setPhase((current) =>
        current === 'idle' || current === 'uploading' ? 'processing' : current
      );
    }
  }, [procStatus, resumeId]);

  // Store the parsed resume exactly once per completed parse (again after a
  // manual retry). The ref guard makes this safe under StrictMode.
  const autoRanGenRef = React.useRef(0);
  const procResumeRef = React.useRef(procResume);
  React.useEffect(() => {
    procResumeRef.current = procResume;
  }, [procResume]);
  React.useEffect(() => {
    if (readyGeneration === 0 || autoRanGenRef.current === readyGeneration) return;
    autoRanGenRef.current = readyGeneration;
    const data = procResumeRef.current?.processed_resume as ResumeData | null | undefined;
    if (data) {
      setParsedResume(data);
      setPhase('ready');
    }
  }, [readyGeneration]);

  const handleRetryParse = async () => {
    setRetryingParse(true);
    try {
      await retryProcessingPoll();
    } catch {
      // The hook already maps the failure to its `failed` observation.
    } finally {
      setRetryingParse(false);
    }
  };

  const resetToIdle = React.useCallback(() => {
    setShowDeleteDialog(false);
    setDeleteError(false);
    setResumeId(null);
    setParsedResume(null);
    setUploadError(null);
    // Rearm the one-shot ready guard so a later import of a fresh row (which
    // restarts readyGeneration at 1) is not mistaken for an already-handled run.
    autoRanGenRef.current = 0;
    uploadActions.clearFiles();
    setPhase('idle');
  }, [uploadActions]);

  const confirmDelete = async () => {
    if (!resumeId) return;
    setDeleting(true);
    setDeleteError(false);
    try {
      await deleteResume(resumeId);
      const wasMaster = localStorage.getItem('master_resume_id') === resumeId;
      decrementResumes();
      if (wasMaster) {
        localStorage.removeItem('master_resume_id');
        setHasMasterResume(false);
      }
      resetToIdle();
      onResumeMutated?.();
    } catch (err) {
      console.error('Failed to delete imported resume:', err);
      setDeleteError(true);
    } finally {
      setDeleting(false);
    }
  };

  const busy = phase === 'uploading' || phase === 'processing' || isUploadingGlobal || deleting;
  const localizedResume = React.useMemo(
    () => (parsedResume ? withLocalizedDefaultSections(parsedResume, t) : null),
    [parsedResume, t]
  );

  const currentFile = files[0];

  // useFileUpload stores a failure both in its errors array and echoes the
  // same message through onUploadError; render one source so it never appears
  // twice in the red panel.
  const displayErrors = uploadError ? [uploadError] : errors;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !busy) onClose();
      }}
    >
      <DialogContent
        className="flex h-[94vh] w-[min(1100px,96vw)] max-w-[96vw] flex-col gap-0 overflow-hidden rounded-none p-0"
        closeOnEscape={!busy && !showDeleteDialog}
        closeOnBackdrop={!busy && !showDeleteDialog}
        showCloseButton={!busy}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-black px-5 py-3 pr-16">
          <DialogTitle className="flex items-center gap-2">
            <UploadCloud className="h-5 w-5 shrink-0" />
            <span className="truncate">{t('importWorkspace.cta')}</span>
          </DialogTitle>
          <div className="flex shrink-0 items-center gap-1">
            {phase === 'ready' && (
              <Button variant="outline" size="sm" className="rounded-none" onClick={resetToIdle}>
                <UploadCloud className="h-4 w-4" />
                {t('importWorkspace.backToUpload')}
              </Button>
            )}
            {resumeId && (
              <Button
                variant="outline"
                size="sm"
                className="rounded-none border-red-600 text-red-600 hover:bg-red-50"
                onClick={() => setShowDeleteDialog(true)}
                disabled={busy}
              >
                <Trash2 className="h-4 w-4" />
                {t('importWorkspace.deleteResume')}
              </Button>
            )}
          </div>
        </div>

        {/* Body */}
        {phase === 'idle' || phase === 'uploading' ? (
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto bg-background p-8">
            <div className="w-full max-w-xl">
              <div
                role="button"
                tabIndex={0}
                aria-label={t('dashboard.uploadResume')}
                className={cn(
                  'relative cursor-pointer border-2 border-dashed p-10 text-center transition-all',
                  isDragging
                    ? 'border-primary bg-blue-50'
                    : 'border-steel-grey hover:border-black hover:bg-white'
                )}
                onClick={isUploadingGlobal ? undefined : uploadActions.openFileDialog}
                onKeyDown={(e) => {
                  if (isUploadingGlobal) return;
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    uploadActions.openFileDialog();
                  }
                }}
                onDragEnter={uploadActions.handleDragEnter}
                onDragLeave={uploadActions.handleDragLeave}
                onDragOver={uploadActions.handleDragOver}
                onDrop={uploadActions.handleDrop}
              >
                <input
                  {...uploadActions.getInputProps()}
                  accept={ACCEPTED_FILE_TYPES.join(',')}
                  data-testid="resume-import-upload-input"
                />
                {isUploadingGlobal ? (
                  <div className="flex flex-col items-center py-4">
                    <Loader2 className="mb-4 h-10 w-10 animate-spin text-primary" />
                    <p className="font-mono text-sm font-bold uppercase text-primary">
                      {t('common.uploading')}
                    </p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center py-4">
                    <div className="mb-4 flex h-12 w-12 items-center justify-center border border-black bg-white shadow-sw-default">
                      <UploadCloud className="h-6 w-6" />
                    </div>
                    <p className="mb-1 font-bold text-lg">
                      {t('dashboard.uploadDialog.dropzoneTitle')}
                    </p>
                    <p className="font-mono text-xs uppercase text-steel-grey">
                      {t('dashboard.uploadDialog.dropzoneSubtitle')}
                    </p>
                    <p className="mt-3 font-mono text-xs text-steel-grey">
                      {t('importWorkspace.dropzoneHint')}
                    </p>
                  </div>
                )}
              </div>

              {currentFile && !isUploadingGlobal && (
                <p className="mt-3 truncate border border-black bg-white px-3 py-2 font-mono text-xs">
                  {currentFile.file.name}
                </p>
              )}

              {displayErrors.length > 0 && (
                <div className="mt-4 border border-black bg-red-50 p-3 shadow-sw-default">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                    <div className="space-y-1 text-sm font-bold text-red-800">
                      {displayErrors.map((err, idx) => (
                        <p key={idx}>{err}</p>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : phase === 'processing' ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 bg-background text-center">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
            <p className="max-w-md font-mono text-xs uppercase text-ink-soft">
              {t('importWorkspace.parsing')}
            </p>
          </div>
        ) : phase === 'parseFailed' ? (
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto bg-background p-8">
            <div className="w-full max-w-lg border border-black bg-red-50 p-6 shadow-sw-default">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                <div className="flex-1">
                  <p className="font-bold text-red-800">{t('importWorkspace.parseFailed')}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" onClick={handleRetryParse} disabled={retryingParse}>
                      {retryingParse ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                      {t('dashboard.retryProcessing')}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-none border-red-600 text-red-600 hover:bg-red-50"
                      onClick={() => setShowDeleteDialog(true)}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t('importWorkspace.deleteResume')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={resetToIdle}>
                      {t('importWorkspace.backToUpload')}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
            {/* Import success banner */}
            <div className="flex items-center justify-between gap-3 border-b border-black bg-green-50 px-5 py-3">
              <p className="flex items-center gap-2 font-mono text-xs font-bold uppercase text-success">
                <Check className="h-4 w-4 shrink-0" />
                {t('importWorkspace.importSuccess')}
              </p>
              <Button size="sm" onClick={onClose}>
                {t('importWorkspace.done')}
              </Button>
            </div>

            {/* Preview panel: the parsed structured resume */}
            <section className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
              <div className="flex items-center gap-2 border-b border-black px-3 py-2">
                <span className="truncate font-mono text-xs font-bold uppercase">
                  {t('importWorkspace.paneResume')}
                </span>
              </div>
              <div className="min-h-0 flex-1 overflow-auto bg-background p-4">
                {localizedResume && (
                  <div className="resume-print mx-auto w-full max-w-[250mm] border-2 border-black bg-white shadow-sw-lg">
                    <Resume
                      resumeData={localizedResume}
                      template={templateSettings.template}
                      settings={templateSettings}
                      locale={uiLanguage}
                      {...headingProps}
                    />
                  </div>
                )}
              </div>
            </section>
          </div>
        )}

        <ConfirmDialog
          open={showDeleteDialog}
          onOpenChange={(nextOpen) => {
            setShowDeleteDialog(nextOpen);
            if (!nextOpen) setDeleteError(false);
          }}
          title={t('importWorkspace.deleteConfirmTitle')}
          description={t('importWorkspace.deleteConfirmDescription')}
          confirmLabel={t('importWorkspace.deleteResume')}
          cancelLabel={t('common.cancel')}
          errorMessage={deleteError ? t('dashboard.errors.deleteFailed') : undefined}
          confirmDisabled={deleting}
          onConfirm={confirmDelete}
          variant="danger"
        />
      </DialogContent>
    </Dialog>
  );
}
