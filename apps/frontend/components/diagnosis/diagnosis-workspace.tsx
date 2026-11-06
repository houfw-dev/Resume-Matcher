'use client';

import * as React from 'react';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import AlertCircle from 'lucide-react/dist/esm/icons/alert-circle';
import Stethoscope from 'lucide-react/dist/esm/icons/stethoscope';
import Download from 'lucide-react/dist/esm/icons/download';
import Eye from 'lucide-react/dist/esm/icons/eye';
import EyeOff from 'lucide-react/dist/esm/icons/eye-off';
import Trash2 from 'lucide-react/dist/esm/icons/trash-2';
import UploadCloud from 'lucide-react/dist/esm/icons/upload-cloud';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useTranslations } from '@/lib/i18n';
import { useLanguage } from '@/lib/context/language-context';
import { useFileUpload } from '@/hooks/use-file-upload';
import { useOperationOwner } from '@/hooks/use-operation-owner';
import { useResumeProcessing } from '@/hooks/use-resume-processing';
import { useSplitPanes } from '@/hooks/use-split-panes';
import { useStatusCache } from '@/lib/context/status-cache';
import { getUploadUrl } from '@/lib/api/client';
import { deleteResume } from '@/lib/api/resume';
import {
  diagnoseResume,
  exportDiagnosisDocx,
  fetchCompetencyModels,
  type DiagnosisReport,
  type DiagnosisRating,
} from '@/lib/api/diagnosis';
import { DiagnosisReportView, type FilterMode } from './diagnosis-report-view';
import { buildDiagnosisReportFilename, downloadBlobAsFile } from '@/lib/utils/download';
import { splitJobIntentions } from '@/lib/utils/job-intentions';
import { withLocalizedDefaultSections } from '@/lib/utils/section-helpers';
import { buildResumeHeadingProps } from '@/lib/utils/resume-headings';
import { loadTemplateSettings } from '@/lib/utils/template-settings-storage';
import { LayoutMeasurementError, measureResumeLayout } from '@/lib/utils/measure-resume-layout';
import type { RenderedLayout } from '@/lib/types/rendered-layout';
import { cn } from '@/lib/utils';
import Resume, { type ResumeData } from '@/components/dashboard/resume-component';

const ACCEPTED_FILE_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
  'application/msword', // .doc
];
const MAX_FILE_SIZE = 4 * 1024 * 1024; // 4MB

// Mirrors NO_COMPETENCY_MODEL_KEY on the backend: explicit opt-out.
const NONE_MODEL_KEY = 'none';

type Phase =
  | 'idle'
  | 'uploading'
  | 'processing'
  | 'measuring'
  | 'diagnosing'
  | 'ready'
  | 'report'
  | 'parseFailed';
type LeftTab = 'structured' | 'raw';

interface DiagnosisWorkspaceProps {
  open: boolean;
  onClose: () => void;
  /** Called whenever the resume list may have changed (upload, delete). */
  onResumeMutated?: () => void;
}

/**
 * Dashboard entry point: upload a resume → automatic base diagnosis → a
 * draggable two-pane comparison (structured/original resume vs. report) with
 * optional JD re-diagnosis and Word export. Uploads persist through the normal
 * resume pipeline; the workspace never stores the source binary.
 */
export function DiagnosisWorkspace({ open, onClose, onResumeMutated }: DiagnosisWorkspaceProps) {
  const { t } = useTranslations();
  const { uiLanguage } = useLanguage();
  const headingProps = React.useMemo(() => buildResumeHeadingProps(t), [t]);
  // Builder template choice is a single global setting; snapshot it for the
  // lifetime of this workspace so screen and measurement never drift apart.
  const templateSettings = React.useState(() => loadTemplateSettings())[0];
  const { incrementResumes, decrementResumes, setHasMasterResume } = useStatusCache();

  const [phase, setPhase] = React.useState<Phase>('idle');
  /** Last run fell back to text estimates (offscreen measurement unavailable). */
  const [layoutSkipped, setLayoutSkipped] = React.useState(false);
  const [resumeId, setResumeId] = React.useState<string | null>(null);
  const [uploadError, setUploadError] = React.useState<string | null>(null);
  const [diagError, setDiagError] = React.useState<string | null>(null);
  const [report, setReport] = React.useState<DiagnosisReport | null>(null);
  const [filter, setFilter] = React.useState<FilterMode>('all');
  const [leftTab, setLeftTab] = React.useState<LeftTab>('structured');
  const [jdOpen, setJdOpen] = React.useState(false);
  const [jdText, setJdText] = React.useState('');
  const [showDeleteDialog, setShowDeleteDialog] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [retryingParse, setRetryingParse] = React.useState(false);
  const [downloading, setDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState(false);
  const [parsedResume, setParsedResume] = React.useState<ResumeData | null>(null);
  const [rawContent, setRawContent] = React.useState('');
  const resolutionRef = React.useRef<{ title: string; modelKey: string }>({
    title: '',
    modelKey: NONE_MODEL_KEY,
  });

  const { begin, isCurrent } = useOperationOwner('diagnosis-workspace');
  const {
    status: procStatus,
    resume: procResume,
    readyGeneration,
    retry: retryProcessingPoll,
  } = useResumeProcessing(resumeId);
  // Destructured at the call site: the react-hooks/refs compiler rule treats
  // the aggregate object (which carries containerRef) as ref-like and flags
  // render-phase member access on it. Plain bindings keep ref access confined
  // to the JSX ref slot and event handlers.
  const {
    leftHidden,
    rightHidden,
    toggleLeft,
    toggleRight,
    reset: resetSplit,
    isDragging: isDividerDragging,
    containerRef,
    dividerProps,
    gridTemplateColumns,
  } = useSplitPanes(45);

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
        current === 'diagnosing' || current === 'measuring' ? current : 'parseFailed'
      );
    } else if (procStatus === 'processing') {
      setPhase((current) =>
        current === 'idle' || current === 'uploading' || current === 'processing'
          ? 'processing'
          : current
      );
    }
  }, [procStatus, resumeId]);

  const runDiagnosisFlow = React.useCallback(
    async (data: ResumeData, jobDescription?: string) => {
      if (!resumeId) return;
      const token = begin();
      if (token === null) return;
      setDiagError(null);
      setDownloadError(false);
      setLayoutSkipped(false);

      // Measure the SAME display-state shape the comparison pane renders.
      const displayData = withLocalizedDefaultSections(data, t);
      let renderedLayout: RenderedLayout | undefined;
      setPhase('measuring');
      try {
        renderedLayout = await measureResumeLayout({
          resumeData: displayData,
          settings: templateSettings,
          headingProps,
          locale: uiLanguage,
        });
      } catch (err) {
        const reason = err instanceof LayoutMeasurementError ? err.message : err;
        console.warn('Layout measurement skipped for diagnosis:', reason);
        setLayoutSkipped(true);
      }
      if (!isCurrent(token)) return;

      setPhase('diagnosing');

      const title = splitJobIntentions(data.personalInfo?.title ?? '')[0] ?? '';
      const withJd = Boolean(jobDescription?.trim());
      let modelKey = NONE_MODEL_KEY;
      let targetTitle = title;
      try {
        if (withJd) {
          // JD re-runs reuse the resolution captured at the automatic run.
          modelKey = resolutionRef.current.modelKey;
          targetTitle = resolutionRef.current.title;
        } else {
          try {
            const catalog = await fetchCompetencyModels(title || undefined);
            modelKey = catalog.matched_key ?? NONE_MODEL_KEY;
          } catch (err) {
            console.error('Competency model catalog failed to load:', err);
            modelKey = NONE_MODEL_KEY;
          }
          resolutionRef.current = { title, modelKey };
        }

        const result = await diagnoseResume(resumeId, {
          jobDescription: jobDescription?.trim() || undefined,
          targetTitle: targetTitle || undefined,
          competencyModelKey: modelKey,
          // Sent together; when measurement failed, both stay undefined and
          // the backend falls back to its text-estimate path.
          templateSettings: renderedLayout ? templateSettings : undefined,
          renderedLayout,
        });
        if (!isCurrent(token)) return;
        setReport(result);
        setFilter('all');
        setPhase('report');
      } catch (err) {
        console.error('Resume diagnosis failed:', err);
        if (!isCurrent(token)) return;
        setDiagError(t('diagnosis.error'));
        // A failed JD re-run keeps the previous report on screen.
        setPhase(withJd && report ? 'report' : 'ready');
      }
    },
    [resumeId, begin, isCurrent, t, report, templateSettings, headingProps, uiLanguage]
  );

  // Always call the latest flow implementation from the auto-run guard.
  const flowRef = React.useRef(runDiagnosisFlow);
  React.useEffect(() => {
    flowRef.current = runDiagnosisFlow;
  }, [runDiagnosisFlow]);

  // Auto-run the base diagnosis exactly once per completed parse (again after
  // a manual retry). The ref guard makes this safe under StrictMode.
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
      setRawContent(procResumeRef.current?.raw_resume?.content ?? '');
      void flowRef.current(data);
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

  const handleRunJd = async () => {
    if (!parsedResume || !jdText.trim() || phase === 'diagnosing' || phase === 'measuring') return;
    await runDiagnosisFlow(parsedResume, jdText);
    setJdOpen(false);
  };

  const handleDownload = async () => {
    if (!report || !resumeId) return;
    setDownloading(true);
    setDownloadError(false);
    try {
      // Export re-serializes the report on screen; the backend makes no LLM call.
      const blob = await exportDiagnosisDocx(resumeId, report);
      // 简历诊断报告-姓名-时间.docx
      const filename = buildDiagnosisReportFilename(
        t('diagnosis.fileStem'),
        parsedResume?.personalInfo?.name
      );
      downloadBlobAsFile(blob, filename);
    } catch (err) {
      console.error('Diagnosis document export failed:', err);
      setDownloadError(true);
    } finally {
      setDownloading(false);
    }
  };

  const resetToIdle = React.useCallback(() => {
    setShowDeleteDialog(false);
    setDeleteError(false);
    setResumeId(null);
    setReport(null);
    setParsedResume(null);
    setRawContent('');
    setDiagError(null);
    setUploadError(null);
    setDownloadError(false);
    setJdText('');
    setJdOpen(false);
    setFilter('all');
    setLayoutSkipped(false);
    setLeftTab('structured');
    resolutionRef.current = { title: '', modelKey: NONE_MODEL_KEY };
    resetSplit();
    uploadActions.clearFiles();
    setPhase('idle');
  }, [resetSplit, uploadActions]);

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
      console.error('Failed to delete diagnosed resume:', err);
      setDeleteError(true);
    } finally {
      setDeleting(false);
    }
  };

  const measuring = phase === 'measuring';
  const diagnosing = phase === 'diagnosing';
  const busy =
    phase === 'uploading' ||
    phase === 'processing' ||
    measuring ||
    diagnosing ||
    isUploadingGlobal ||
    deleting ||
    downloading;
  const showPanes = measuring || diagnosing || phase === 'ready' || phase === 'report';
  const anyPaneHidden = leftHidden || rightHidden;

  const ratingLabel = (rating: DiagnosisRating) => t(`diagnosis.rating.${rating}`);
  const localizedResume = React.useMemo(
    () => (parsedResume ? withLocalizedDefaultSections(parsedResume, t) : null),
    [parsedResume, t]
  );

  const currentFile = files[0];

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !busy) onClose();
      }}
    >
      <DialogContent
        className="flex h-[94vh] w-[min(1400px,96vw)] max-w-[96vw] flex-col gap-0 overflow-hidden rounded-none p-0"
        closeOnEscape={!busy && !showDeleteDialog}
        closeOnBackdrop={!busy && !showDeleteDialog}
        showCloseButton={!busy}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-black px-5 py-3 pr-16">
          <DialogTitle className="flex items-center gap-2">
            <Stethoscope className="h-5 w-5 shrink-0" />
            <span className="truncate">{t('diagnosis.workspace.cta')}</span>
          </DialogTitle>
          <div className="flex shrink-0 items-center gap-1">
            {showPanes && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-none"
                  onClick={toggleLeft}
                  disabled={rightHidden}
                  aria-pressed={!leftHidden}
                  aria-label={t(
                    leftHidden ? 'diagnosis.workspace.showLeft' : 'diagnosis.workspace.hideLeft'
                  )}
                  title={t(
                    leftHidden ? 'diagnosis.workspace.showLeft' : 'diagnosis.workspace.hideLeft'
                  )}
                >
                  {leftHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-none"
                  onClick={toggleRight}
                  disabled={leftHidden}
                  aria-pressed={!rightHidden}
                  aria-label={t(
                    rightHidden ? 'diagnosis.workspace.showRight' : 'diagnosis.workspace.hideRight'
                  )}
                  title={t(
                    rightHidden ? 'diagnosis.workspace.showRight' : 'diagnosis.workspace.hideRight'
                  )}
                >
                  {rightHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
                {report && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-none"
                    onClick={handleDownload}
                    disabled={downloading}
                  >
                    {downloading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    {downloading ? t('diagnosis.workspace.exporting') : t('diagnosis.downloadWord')}
                  </Button>
                )}
              </>
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
                {t('diagnosis.workspace.deleteResume')}
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
                  data-testid="diagnosis-upload-input"
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
                      {t('diagnosis.workspace.dropzoneHint')}
                    </p>
                  </div>
                )}
              </div>

              {currentFile && !isUploadingGlobal && (
                <p className="mt-3 truncate border border-black bg-white px-3 py-2 font-mono text-xs">
                  {currentFile.file.name}
                </p>
              )}

              {(uploadError || errors.length > 0) && (
                <div className="mt-4 border border-black bg-red-50 p-3 shadow-sw-default">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                    <div className="space-y-1 text-sm font-bold text-red-800">
                      {uploadError && <p>{uploadError}</p>}
                      {errors.map((err, idx) => (
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
              {t('diagnosis.workspace.parsing')}
            </p>
          </div>
        ) : phase === 'parseFailed' ? (
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto bg-background p-8">
            <div className="w-full max-w-lg border border-black bg-red-50 p-6 shadow-sw-default">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                <div className="flex-1">
                  <p className="font-bold text-red-800">{t('diagnosis.workspace.parseFailed')}</p>
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
                      {t('diagnosis.workspace.deleteResume')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={resetToIdle}>
                      {t('diagnosis.workspace.backToUpload')}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div
            ref={containerRef}
            className={cn('grid min-h-0 flex-1 bg-black', isDividerDragging && 'select-none')}
            style={{ gridTemplateColumns }}
          >
            {/* Left pane: uploaded resume */}
            <section
              className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-white"
              inert={leftHidden ? true : undefined}
            >
              <div className="flex items-center justify-between gap-2 border-b border-black px-3 py-2">
                <span className="truncate font-mono text-xs font-bold uppercase">
                  {t('diagnosis.workspace.paneResume')}
                </span>
                <div className="flex shrink-0 border border-black">
                  <button
                    type="button"
                    onClick={() => setLeftTab('structured')}
                    className={cn(
                      'px-2 py-1 font-mono text-[10px] uppercase',
                      leftTab === 'structured'
                        ? 'bg-black text-white'
                        : 'bg-white hover:bg-neutral-100'
                    )}
                  >
                    {t('diagnosis.workspace.structuredTab')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setLeftTab('raw')}
                    className={cn(
                      'border-l border-black px-2 py-1 font-mono text-[10px] uppercase',
                      leftTab === 'raw' ? 'bg-black text-white' : 'bg-white hover:bg-neutral-100'
                    )}
                  >
                    {t('diagnosis.workspace.originalTab')}
                  </button>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto bg-background">
                {leftTab === 'structured' && localizedResume ? (
                  <div className="p-4">
                    <div className="resume-print mx-auto w-full max-w-[250mm] border-2 border-black bg-white shadow-sw-lg">
                      <Resume
                        resumeData={localizedResume}
                        template={templateSettings.template}
                        settings={templateSettings}
                        locale={uiLanguage}
                        {...headingProps}
                      />
                    </div>
                  </div>
                ) : (
                  <pre className="whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed">
                    {rawContent}
                  </pre>
                )}
              </div>
            </section>

            {/* Draggable divider */}
            <div
              {...(anyPaneHidden ? { 'aria-hidden': true as const } : dividerProps)}
              aria-label={anyPaneHidden ? undefined : t('diagnosis.workspace.resizeHint')}
              className={cn(
                'flex items-center justify-center',
                !anyPaneHidden && 'z-10 cursor-col-resize touch-none hover:bg-ink-soft'
              )}
            >
              {!anyPaneHidden && <span className="h-10 w-1 bg-white/70" aria-hidden />}
            </div>

            {/* Right pane: diagnosis report */}
            <section
              className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-background"
              inert={rightHidden ? true : undefined}
            >
              <div className="border-b border-black px-4 py-2 font-mono text-xs font-bold uppercase">
                {t('diagnosis.workspace.paneReport')}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                {(phase === 'diagnosing' || phase === 'measuring') && (
                  <div className="flex flex-col items-center gap-4 py-16 text-center">
                    <Loader2 className="h-10 w-10 animate-spin text-primary" />
                    <p className="max-w-md font-mono text-xs uppercase text-ink-soft">
                      {measuring
                        ? t('diagnosis.measuringLayout')
                        : t('diagnosis.workspace.diagnosing')}
                    </p>
                  </div>
                )}

                {phase === 'ready' && diagError && (
                  <div className="border border-black bg-red-50 p-4 shadow-sw-default">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                      <div>
                        <p className="font-bold text-red-800">{diagError}</p>
                        <Button
                          className="mt-3"
                          size="sm"
                          onClick={() => parsedResume && void runDiagnosisFlow(parsedResume)}
                        >
                          {t('common.retry')}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                {phase === 'report' && report && (
                  <div className="flex flex-col gap-4">
                    {layoutSkipped && (
                      <p className="border border-black bg-neutral-100 px-3 py-2 font-mono text-[10px] uppercase text-steel-grey">
                        {t('diagnosis.layoutSkipped')}
                      </p>
                    )}
                    {diagError && (
                      <div className="border border-black bg-red-50 p-3">
                        <p className="flex items-center gap-2 text-sm font-bold text-red-800">
                          <AlertCircle className="h-4 w-4 shrink-0" />
                          {diagError}
                        </p>
                      </div>
                    )}
                    {downloadError && (
                      <p className="font-mono text-xs font-bold text-destructive">
                        {t('diagnosis.downloadFailed')}
                      </p>
                    )}

                    {/* Optional JD re-diagnosis */}
                    <div className="border border-black bg-white">
                      <button
                        type="button"
                        onClick={() => setJdOpen((open0) => !open0)}
                        aria-expanded={jdOpen}
                        className="flex w-full items-center justify-between px-3 py-2 text-left font-mono text-xs font-bold uppercase"
                      >
                        {t('diagnosis.workspace.jdToggle')}
                        <ChevronDown
                          className={cn('h-4 w-4 transition-transform', jdOpen && 'rotate-180')}
                        />
                      </button>
                      {jdOpen && (
                        <div className="border-t border-black p-3">
                          <Textarea
                            value={jdText}
                            onChange={(e) => setJdText(e.target.value)}
                            onKeyDown={(e) => {
                              // Newlines in the JD must not trigger any submit.
                              if (e.key === 'Enter') e.stopPropagation();
                            }}
                            placeholder={t('diagnosis.jobDescriptionPlaceholder')}
                            className="min-h-[120px]"
                          />
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <p className="font-mono text-[10px] text-steel-grey">
                              {t('diagnosis.jdHint')}
                            </p>
                            <Button
                              size="sm"
                              onClick={handleRunJd}
                              disabled={!jdText.trim() || diagnosing}
                            >
                              <Stethoscope className="h-4 w-4" />
                              {t('diagnosis.workspace.jdRun')}
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>

                    <DiagnosisReportView
                      report={report}
                      filter={filter}
                      onFilterChange={setFilter}
                      ratingLabel={ratingLabel}
                      t={t}
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
          title={t('diagnosis.workspace.deleteConfirmTitle')}
          description={t('diagnosis.workspace.deleteConfirmDescription')}
          confirmLabel={t('diagnosis.workspace.deleteResume')}
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
