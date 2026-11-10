'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, AlertCircle, Stethoscope, Download, ArrowLeft } from 'lucide-react';
import { buildDiagnosisReportFilename, downloadBlobAsFile } from '@/lib/utils/download';
import { splitJobIntentions } from '@/lib/utils/job-intentions';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { JobDescriptionTextarea } from '@/components/common/job-description-textarea';
import { useTranslations } from '@/lib/i18n';
import { useLanguage } from '@/lib/context/language-context';
import { DiagnosisReportView, type FilterMode, type TFn } from './diagnosis-report-view';
import {
  diagnoseResume,
  exportDiagnosisDocx,
  fetchCompetencyModels,
  type DiagnosisReport,
  type DiagnosisRating,
  type CompetencyModelOption,
} from '@/lib/api/diagnosis';
import type { ResumeData } from '@/components/dashboard/resume-component';
import type { TemplateSettings } from '@/lib/types/template-settings';
import type { RenderedLayout } from '@/lib/types/rendered-layout';
import { loadTemplateSettings } from '@/lib/utils/template-settings-storage';
import { buildResumeHeadingProps } from '@/lib/utils/resume-headings';
import { LayoutMeasurementError, measureResumeLayout } from '@/lib/utils/measure-resume-layout';
import { useAbortController } from '@/hooks/use-abort-controller';
import { isAbortError } from '@/lib/utils/abort';
import { buildDiagnosisFixHref } from '@/lib/utils/diagnosis-fix-link';

// Mirrors NO_COMPETENCY_MODEL_KEY on the backend: an explicit opt-out that
// wins over title auto-matching.
const NONE_MODEL_KEY = 'none';

/**
 * Three mutually exclusive diagnosis modes (product contract — the backend
 * rejects the base+model+JD triple overlap with HTTP 400):
 *  - basic: base rubric only, no model and no JD;
 *  - model: base rubric plus a P3–P8 competency model, no JD;
 *  - jd:    base rubric plus job-fit checks against a pasted JD, no model.
 */
type DiagnosisMode = 'basic' | 'model' | 'jd';

const MODE_OPTIONS: ReadonlyArray<{ value: DiagnosisMode; titleKey: string; descKey: string }> = [
  { value: 'basic', titleKey: 'diagnosis.modeBasicTitle', descKey: 'diagnosis.modeBasicDesc' },
  { value: 'model', titleKey: 'diagnosis.modeModelTitle', descKey: 'diagnosis.modeModelDesc' },
  { value: 'jd', titleKey: 'diagnosis.modeJdTitle', descKey: 'diagnosis.modeJdDesc' },
];

interface DiagnosisModalProps {
  resumeId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Raw 求职意向 string from personalInfo.title (may list several directions). */
  intentionTitle?: string;
  /**
   * Display-state resume (localized, same shape as the on-screen <Resume>).
   * When provided, the modal measures its real render with the builder's
   * chosen template so #1/#2 judge measured pagination, not text estimates.
   */
  resumeData?: ResumeData | null;
}

/**
 * V4 rubric resume diagnosis: deterministic checks + one structured LLM pass.
 * Swiss International Style — square corners, 1px ink borders, hard shadows.
 */
export function DiagnosisModal({
  resumeId,
  open,
  onOpenChange,
  intentionTitle,
  resumeData = null,
}: DiagnosisModalProps) {
  const { t } = useTranslations();
  const { uiLanguage } = useLanguage();
  const router = useRouter();
  const headingProps = React.useMemo(() => buildResumeHeadingProps(t), [t]);
  const intentions = React.useMemo(() => splitJobIntentions(intentionTitle), [intentionTitle]);
  const [mode, setMode] = React.useState<DiagnosisMode>('basic');
  const [selectedTitle, setSelectedTitle] = React.useState('');
  const [jobDescription, setJobDescription] = React.useState('');
  const [catalog, setCatalog] = React.useState<CompetencyModelOption[] | null>(null);
  const [matchedKey, setMatchedKey] = React.useState<string | null>(null);
  const [selectedModelKey, setSelectedModelKey] = React.useState(NONE_MODEL_KEY);
  const [catalogError, setCatalogError] = React.useState(false);
  const [catalogReload, setCatalogReload] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  /** True during the offscreen template-render measurement phase. */
  const [measuring, setMeasuring] = React.useState(false);
  /** Last run fell back to text estimates (measurement unavailable). */
  const [layoutSkipped, setLayoutSkipped] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [report, setReport] = React.useState<DiagnosisReport | null>(null);
  const [filter, setFilter] = React.useState<FilterMode>('all');
  const [downloading, setDownloading] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState(false);

  // Default the diagnosis target to the first listed intention every time the
  // modal opens; the user only has to choose when several directions exist.
  React.useEffect(() => {
    if (open) setSelectedTitle(intentions[0] ?? '');
  }, [open, intentions]);

  // Bumped on every open so a diagnosis run still in flight from the previous
  // session can recognize itself as stale and discard its result.
  const sessionRef = React.useRef(0);
  // Bumped on every run start and on explicit cancel. A run whose seq is no
  // longer current must not flip loading state back off for its successor.
  const runSeqRef = React.useRef(0);
  const { getSignal, abort } = useAbortController();

  // Closing the dialog cancels whatever is still running; the reopened form
  // starts clean from the open-effect reset above.
  React.useEffect(() => {
    if (!open) abort();
  }, [open, abort]);

  // Reopening the modal always starts a fresh diagnosis session: the component
  // stays mounted while Radix only hides/shows its content, so without this
  // reset the previous report (or error) would resurface on the next open.
  React.useEffect(() => {
    if (!open) return;
    sessionRef.current += 1;
    setMode('basic');
    setJobDescription('');
    setCatalog(null);
    setMatchedKey(null);
    setSelectedModelKey(NONE_MODEL_KEY);
    setCatalogError(false);
    setLoading(false);
    setMeasuring(false);
    setLayoutSkipped(false);
    setError(null);
    setReport(null);
    setFilter('all');
    setDownloading(false);
    setDownloadError(false);
  }, [open]);

  // Load the competency-model catalog for the active target title. The server
  // owns the title-to-level regex match; its match preselects model mode,
  // otherwise the modal stays on basic mode. The catalog is only consumed in
  // model mode but loads up front so switching modes feels instant. Deliberately
  // NOT gated on `report`: navigating back from a report reuses the catalog
  // already in memory instead of flashing through a reload.
  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setCatalog(null);
    setMatchedKey(null);
    setCatalogError(false);
    fetchCompetencyModels(selectedTitle || undefined)
      .then((result) => {
        if (cancelled) return;
        setCatalog(result.models);
        setMatchedKey(result.matched_key);
        setSelectedModelKey(result.matched_key ?? NONE_MODEL_KEY);
        // A confident server match upgrades into model mode, but a missing
        // match never downgrades an explicit card choice — otherwise a
        // retry or title change would bounce the user out of model/JD mode.
        if (result.matched_key) setMode('model');
      })
      .catch((err) => {
        console.error('Competency model catalog failed to load:', err);
        if (!cancelled) {
          setCatalogError(true);
          setSelectedModelKey(NONE_MODEL_KEY);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, selectedTitle, catalogReload]);

  const jdTrimmed = jobDescription.trim();
  const modelReady = Boolean(
    catalog && !catalogError && selectedModelKey && selectedModelKey !== NONE_MODEL_KEY
  );
  // JD mode needs a non-empty description; model mode needs a loaded catalog
  // with a concrete level selected. Basic mode can always run.
  const runDisabled =
    loading || measuring || (mode === 'jd' && !jdTrimmed) || (mode === 'model' && !modelReady);

  const runDiagnosis = React.useCallback(async () => {
    // Pin the session: if the modal is closed and reopened while this run is
    // in flight, its late result must not overwrite the fresh session's form.
    const session = sessionRef.current;
    // Each run (and each Cancel) takes a fresh seq so a superseded continuation
    // can never clear the successor run's loading flag.
    const runSeq = ++runSeqRef.current;
    const signal = getSignal();
    setLoading(true);
    setMeasuring(false);
    setError(null);
    setLayoutSkipped(false);
    setDownloadError(false);

    // Stage 1: render the resume with the builder's current template and
    // measure real pagination/wrapping. Failure here must never block a
    // diagnosis — without a snapshot the backend uses its text estimates.
    let templateSettings: TemplateSettings | undefined;
    let renderedLayout: RenderedLayout | undefined;
    if (resumeData) {
      setMeasuring(true);
      try {
        const settings = loadTemplateSettings();
        const layout = await measureResumeLayout({
          resumeData,
          settings,
          headingProps,
          // Same locale the on-screen render and PDF pass to <Resume>, so
          // measured wrapping matches what the user actually sees.
          locale: uiLanguage,
        });
        if (session !== sessionRef.current) return;
        templateSettings = settings;
        renderedLayout = layout;
      } catch (err) {
        if (session !== sessionRef.current) return;
        const reason = err instanceof LayoutMeasurementError ? err.message : err;
        console.warn('Layout measurement skipped for diagnosis:', reason);
        setLayoutSkipped(true);
      } finally {
        if (session === sessionRef.current) setMeasuring(false);
      }
    }

    // Stage 2: the diagnosis call itself. Map the exclusive mode contract to
    // the backend payload — model mode sends a real level key with no JD; JD
    // mode sends the explicit 'none' opt-out so title auto-matching cannot
    // silently turn it into the unsupported triple-overlap mode.
    try {
      const result = await diagnoseResume(
        resumeId,
        {
          jobDescription: mode === 'jd' ? jdTrimmed || undefined : undefined,
          targetTitle: selectedTitle.trim() || undefined,
          competencyModelKey: mode === 'model' ? selectedModelKey : NONE_MODEL_KEY,
          templateSettings,
          renderedLayout,
        },
        signal
      );
      if (session !== sessionRef.current || runSeq !== runSeqRef.current) return;
      setReport(result);
      setFilter('all');
    } catch (err) {
      if (session !== sessionRef.current || runSeq !== runSeqRef.current) return;
      // User-cancelled run: leave the form usable, show no error surface.
      if (isAbortError(err)) return;
      console.error('Resume diagnosis failed:', err);
      setError(t('diagnosis.error'));
    } finally {
      if (session === sessionRef.current && runSeq === runSeqRef.current) setLoading(false);
    }
  }, [
    mode,
    jdTrimmed,
    selectedTitle,
    selectedModelKey,
    resumeId,
    resumeData,
    headingProps,
    uiLanguage,
    t,
    getSignal,
  ]);

  const handleCancelRun = React.useCallback(() => {
    // Retire the in-flight run before aborting so its rejection and finally
    // block cannot clear the loading state of a run started afterwards.
    runSeqRef.current += 1;
    abort();
    setLoading(false);
    setMeasuring(false);
  }, [abort]);

  const handleDownload = React.useCallback(async () => {
    if (!report) return;
    setDownloading(true);
    setDownloadError(false);
    try {
      // Export re-serializes the report already on screen; the backend makes
      // no LLM call for this, so it returns in well under a second.
      const blob = await exportDiagnosisDocx(resumeId, report);
      // 简历诊断报告-姓名-时间.docx (name falls back gracefully when absent).
      const filename = buildDiagnosisReportFilename(
        t('diagnosis.fileStem'),
        resumeData?.personalInfo?.name
      );
      downloadBlobAsFile(blob, filename);
    } catch (err) {
      console.error('Diagnosis document export failed:', err);
      setDownloadError(true);
    } finally {
      setDownloading(false);
    }
  }, [report, resumeId, resumeData, t]);

  const handleBackToForm = React.useCallback(() => {
    // Return to the setup form without losing the chosen mode, target title,
    // JD text or model pick — the user can tweak one field and rerun. The
    // catalog stays in memory, so no reload flashes.
    setReport(null);
    setError(null);
    setFilter('all');
    setLayoutSkipped(false);
    setDownloadError(false);
  }, []);

  // Deep-link from a problem item to the builder section that owns the fix.
  // Closing first means a browser Back gesture returns to the resume page
  // rather than to a stale modal; the route change unmounts this host anyway.
  const handleFixInBuilder = React.useCallback(
    (itemId: number) => {
      const href = buildDiagnosisFixHref(resumeId, itemId);
      if (!href) return;
      onOpenChange(false);
      router.push(href);
    },
    [resumeId, onOpenChange, router]
  );

  const ratingLabel = (rating: DiagnosisRating) => t(`diagnosis.rating.${rating}`);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader className="border-b border-black pr-10 pb-2">
          <DialogTitle className="flex items-center gap-2">
            <Stethoscope className="h-5 w-5" />
            {t('diagnosis.title')}
          </DialogTitle>
          <DialogDescription className="text-xs">{t('diagnosis.subtitle')}</DialogDescription>
        </DialogHeader>

        {/* Compact one-screen form: the scroll container stays only as a
            small-viewport / long-report safety net. */}
        <div className="max-h-[78vh] overflow-y-auto px-5 py-3">
          {loading && (
            <div className="flex flex-col items-center gap-4 py-16 text-center">
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <p className="max-w-md font-mono text-xs uppercase text-ink-soft">
                {measuring ? t('diagnosis.measuringLayout') : t('diagnosis.loading')}
              </p>
              <Button variant="outline" size="sm" onClick={handleCancelRun}>
                {t('common.cancel')}
              </Button>
            </div>
          )}

          {!loading && error && (
            <div className="border border-black bg-red-50 p-4 shadow-sw-default">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                <div>
                  <p className="font-bold text-red-800">{error}</p>
                  <div className="mt-3 flex gap-2">
                    <Button onClick={runDiagnosis} size="sm">
                      {t('common.retry')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setError(null)}>
                      {t('common.back')}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {!loading && !error && !report && (
            <div className="flex flex-col gap-3">
              <p className="text-xs leading-snug text-ink-soft">{t('diagnosis.intro')}</p>
              <fieldset className="flex flex-col gap-1.5">
                <legend className="font-mono text-xs font-bold uppercase">
                  {t('diagnosis.modeLabel')}
                </legend>
                <div className="grid grid-cols-1 gap-1 sm:grid-cols-3">
                  {MODE_OPTIONS.map((option) => (
                    <DiagnosisModeCard
                      key={option.value}
                      title={t(option.titleKey)}
                      desc={t(option.descKey)}
                      checked={mode === option.value}
                      onSelect={() => setMode(option.value)}
                    />
                  ))}
                </div>
                <p className="font-mono text-[11px] text-steel-grey">
                  {t('diagnosis.modeExclusiveHint')}
                </p>
              </fieldset>
              <TargetTitleField
                intentions={intentions}
                selectedTitle={selectedTitle}
                onSelect={setSelectedTitle}
                t={t}
              />
              {mode === 'basic' && (
                <p className="border border-black bg-neutral-100 px-2.5 py-1.5 font-mono text-[11px] text-steel-grey">
                  {t('diagnosis.basicModeHint')}
                </p>
              )}
              {mode === 'model' && (
                <CompetencyModelField
                  models={catalog}
                  loading={!catalog && !catalogError}
                  loadError={catalogError}
                  matchedKey={matchedKey}
                  selectedKey={selectedModelKey}
                  onSelect={setSelectedModelKey}
                  onRetry={() => setCatalogReload((n) => n + 1)}
                  t={t}
                />
              )}
              {mode === 'jd' && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="diagnosis-jd" className="font-mono text-xs font-bold uppercase">
                    {t('diagnosis.jobDescriptionLabel')}
                  </label>
                  <JobDescriptionTextarea
                    id="diagnosis-jd"
                    value={jobDescription}
                    onValueChange={setJobDescription}
                    placeholder={t('diagnosis.jobDescriptionPlaceholder')}
                    className="min-h-[96px]"
                  />
                  <p className="font-mono text-[11px] text-steel-grey">
                    {jdTrimmed ? t('diagnosis.jdHint') : t('diagnosis.jdRequiredHint')}
                  </p>
                </div>
              )}
              <div className="flex justify-end border-t border-black pt-3">
                <Button onClick={runDiagnosis} disabled={runDisabled}>
                  <Stethoscope className="h-4 w-4" />
                  {t('diagnosis.run')}
                </Button>
              </div>
            </div>
          )}

          {!loading && !error && report && (
            <>
              {layoutSkipped && (
                <p className="mb-3 border border-black bg-neutral-100 px-3 py-2 font-mono text-[10px] uppercase text-steel-grey">
                  {t('diagnosis.layoutSkipped')}
                </p>
              )}
              <DiagnosisReportView
                report={report}
                filter={filter}
                onFilterChange={setFilter}
                ratingLabel={ratingLabel}
                onFixInBuilder={handleFixInBuilder}
                t={t}
              />
            </>
          )}
        </div>

        {!loading && !error && report && (
          <div className="border-t border-black px-6 py-3">
            {downloadError && (
              <p className="mb-2 text-xs font-bold text-destructive">
                {t('diagnosis.downloadFailed')}
              </p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" onClick={handleBackToForm}>
                  <ArrowLeft className="h-4 w-4" />
                  {t('common.back')}
                </Button>
                <p className="hidden font-mono text-[10px] uppercase text-steel-grey sm:block">
                  {t('diagnosis.specVersion', { version: report.spec_version })}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={handleDownload} disabled={downloading}>
                  {downloading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                  {t('diagnosis.downloadWord')}
                </Button>
                <Button variant="outline" size="sm" onClick={runDiagnosis}>
                  <Stethoscope className="h-4 w-4" />
                  {t('diagnosis.rerun')}
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

interface DiagnosisModeCardProps {
  title: string;
  desc: string;
  checked: boolean;
  onSelect: () => void;
}

function DiagnosisModeCard({ title, desc, checked, onSelect }: DiagnosisModeCardProps) {
  return (
    <label
      className={`flex h-full cursor-pointer items-start gap-2 border px-2.5 py-1.5 ${
        checked ? 'border-black bg-white shadow-sw-xs' : 'border-black bg-neutral-50'
      }`}
    >
      <input
        type="radio"
        name="diagnosis-mode"
        checked={checked}
        onChange={onSelect}
        className="mt-0.5 shrink-0 accent-black"
      />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className={`text-[13px] leading-tight ${checked ? 'font-bold' : ''}`}>{title}</span>
        <span className="font-mono text-[10px] leading-snug text-steel-grey">{desc}</span>
      </span>
    </label>
  );
}

interface TargetTitleFieldProps {
  intentions: string[];
  selectedTitle: string;
  onSelect: (title: string) => void;
  t: TFn;
}

function TargetTitleField({ intentions, selectedTitle, onSelect, t }: TargetTitleFieldProps) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="font-mono text-xs font-bold uppercase">
        {t('diagnosis.targetLabel')}
      </legend>
      {intentions.length === 0 && (
        <p className="border border-black bg-neutral-100 px-2.5 py-1.5 font-mono text-[11px] text-steel-grey">
          {t('diagnosis.targetEmptyHint')}
        </p>
      )}
      {intentions.length === 1 && (
        <p className="border border-black bg-white px-2.5 py-1.5 text-sm font-bold">
          {intentions[0]}
        </p>
      )}
      {intentions.length >= 2 && (
        <div className="flex flex-col gap-1.5">
          <p className="font-mono text-[11px] text-steel-grey">{t('diagnosis.targetChooseHint')}</p>
          <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {intentions.map((title) => {
              const checked = title === selectedTitle;
              return (
                <label
                  key={title}
                  className={`flex cursor-pointer items-center gap-2 border px-2.5 py-1.5 text-[13px] ${
                    checked ? 'border-black bg-white shadow-sw-xs' : 'border-black bg-neutral-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="diagnosis-target-title"
                    value={title}
                    checked={checked}
                    onChange={() => onSelect(title)}
                    className="accent-black"
                  />
                  <span className={checked ? 'font-bold' : ''}>{title}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </fieldset>
  );
}

interface CompetencyModelFieldProps {
  models: CompetencyModelOption[] | null;
  loading: boolean;
  loadError: boolean;
  matchedKey: string | null;
  selectedKey: string;
  onSelect: (key: string) => void;
  onRetry: () => void;
  t: TFn;
}

function CompetencyModelField({
  models,
  loading,
  loadError,
  matchedKey,
  selectedKey,
  onSelect,
  onRetry,
  t,
}: CompetencyModelFieldProps) {
  const matchedModel = matchedKey
    ? ((models ?? []).find((m) => m.key === matchedKey) ?? null)
    : null;

  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="font-mono text-xs font-bold uppercase">{t('diagnosis.modelLabel')}</legend>
      {loading && (
        <p className="border border-black bg-neutral-100 px-2.5 py-1.5 font-mono text-[11px] text-steel-grey">
          {t('diagnosis.modelLoading')}
        </p>
      )}
      {!loading && loadError && (
        <div className="flex items-center justify-between gap-2 border border-black bg-orange-50 px-2.5 py-1.5">
          <p className="font-mono text-[11px] text-orange-800">{t('diagnosis.modelLoadError')}</p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            {t('diagnosis.modelRetry')}
          </Button>
        </div>
      )}
      {!loading && !loadError && matchedModel && (
        <p className="font-mono text-[11px] text-steel-grey">
          {t('diagnosis.modelMatchedHint', { name: matchedModel.name })}
        </p>
      )}
      {!loading && !loadError && !matchedModel && (
        <p className="font-mono text-[11px] text-steel-grey">{t('diagnosis.modelNoMatchHint')}</p>
      )}
      {!loading && !loadError && (
        <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
          {(models ?? []).map((model) => (
            <ModelRadio
              key={model.key}
              label={
                model.level ? (
                  <>
                    <span className="font-mono text-[10px] uppercase text-steel-grey">
                      {model.level}
                    </span>
                    <span className={selectedKey === model.key ? 'font-bold' : ''}>
                      {model.name}
                    </span>
                  </>
                ) : (
                  model.name
                )
              }
              checked={selectedKey === model.key}
              onSelect={() => onSelect(model.key)}
            />
          ))}
        </div>
      )}
    </fieldset>
  );
}

interface ModelRadioProps {
  label: React.ReactNode;
  checked: boolean;
  onSelect: () => void;
}

function ModelRadio({ label, checked, onSelect }: ModelRadioProps) {
  return (
    <label
      className={`flex cursor-pointer items-center gap-2 border px-2.5 py-1.5 text-[13px] ${
        checked ? 'border-black bg-white shadow-sw-xs' : 'border-black bg-neutral-50'
      }`}
    >
      <input
        type="radio"
        name="diagnosis-competency-model"
        checked={checked}
        onChange={onSelect}
        className="shrink-0 accent-black"
      />
      <span className="flex min-w-0 items-baseline gap-2">{label}</span>
    </label>
  );
}
