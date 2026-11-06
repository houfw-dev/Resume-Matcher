'use client';

import * as React from 'react';
import { Loader2, AlertCircle, Stethoscope, Download } from 'lucide-react';
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
import { Textarea } from '@/components/ui/textarea';
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

// Mirrors NO_COMPETENCY_MODEL_KEY on the backend: an explicit opt-out that
// wins over title auto-matching ('' before the catalog loads means "auto").
const NONE_MODEL_KEY = 'none';

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
  const headingProps = React.useMemo(() => buildResumeHeadingProps(t), [t]);
  const intentions = React.useMemo(() => splitJobIntentions(intentionTitle), [intentionTitle]);
  const [selectedTitle, setSelectedTitle] = React.useState('');
  const [jobDescription, setJobDescription] = React.useState('');
  const [catalog, setCatalog] = React.useState<CompetencyModelOption[] | null>(null);
  const [matchedKey, setMatchedKey] = React.useState<string | null>(null);
  const [selectedModelKey, setSelectedModelKey] = React.useState('');
  const [catalogError, setCatalogError] = React.useState(false);
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

  // Load the competency-model catalog for the active target title. The server
  // owns the title-to-level regex match; its match is preselected, otherwise
  // the user confirms a manual pick or explicitly runs without a model.
  React.useEffect(() => {
    if (!open || report) return;
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
  }, [open, selectedTitle, report]);

  const runDiagnosis = React.useCallback(async () => {
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
        templateSettings = settings;
        renderedLayout = layout;
      } catch (err) {
        const reason = err instanceof LayoutMeasurementError ? err.message : err;
        console.warn('Layout measurement skipped for diagnosis:', reason);
        setLayoutSkipped(true);
      } finally {
        setMeasuring(false);
      }
    }

    // Stage 2: the diagnosis call itself.
    try {
      const result = await diagnoseResume(resumeId, {
        jobDescription: jobDescription.trim() || undefined,
        targetTitle: selectedTitle.trim() || undefined,
        // '' while the catalog is still loading: let the backend auto-match.
        competencyModelKey: selectedModelKey || null,
        templateSettings,
        renderedLayout,
      });
      setReport(result);
      setFilter('all');
    } catch (err) {
      console.error('Resume diagnosis failed:', err);
      setError(t('diagnosis.error'));
    } finally {
      setLoading(false);
    }
  }, [
    jobDescription,
    selectedTitle,
    selectedModelKey,
    resumeId,
    resumeData,
    headingProps,
    uiLanguage,
    t,
  ]);

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

  const handleJdKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // The dialog must not submit while the user types newlines into the JD.
    if (e.key === 'Enter') e.stopPropagation();
  };

  const ratingLabel = (rating: DiagnosisRating) => t(`diagnosis.rating.${rating}`);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader className="border-b border-black pr-10 pb-3">
          <DialogTitle className="flex items-center gap-2">
            <Stethoscope className="h-5 w-5" />
            {t('diagnosis.title')}
          </DialogTitle>
          <DialogDescription>{t('diagnosis.subtitle')}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[75vh] overflow-y-auto px-6 py-4">
          {loading && (
            <div className="flex flex-col items-center gap-4 py-16 text-center">
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <p className="max-w-md font-mono text-xs uppercase text-ink-soft">
                {measuring ? t('diagnosis.measuringLayout') : t('diagnosis.loading')}
              </p>
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
            <div className="flex flex-col gap-4">
              <p className="text-sm text-ink-soft">{t('diagnosis.intro')}</p>
              <TargetTitleField
                intentions={intentions}
                selectedTitle={selectedTitle}
                onSelect={setSelectedTitle}
                t={t}
              />
              <CompetencyModelField
                models={catalog}
                loading={!catalog && !catalogError}
                loadError={catalogError}
                matchedKey={matchedKey}
                selectedKey={selectedModelKey}
                onSelect={setSelectedModelKey}
                t={t}
              />
              <div className="flex flex-col gap-2">
                <label htmlFor="diagnosis-jd" className="font-mono text-xs font-bold uppercase">
                  {t('diagnosis.jobDescriptionLabel')}
                </label>
                <Textarea
                  id="diagnosis-jd"
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  onKeyDown={handleJdKeyDown}
                  placeholder={t('diagnosis.jobDescriptionPlaceholder')}
                  className="min-h-[140px]"
                />
                <p className="font-mono text-xs text-steel-grey">{t('diagnosis.jdHint')}</p>
              </div>
              <div className="flex justify-end border-t border-black pt-4">
                <Button onClick={runDiagnosis}>
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
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-[10px] uppercase text-steel-grey">
                {t('diagnosis.specVersion', { version: report.spec_version })}
              </p>
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

interface TargetTitleFieldProps {
  intentions: string[];
  selectedTitle: string;
  onSelect: (title: string) => void;
  t: TFn;
}

function TargetTitleField({ intentions, selectedTitle, onSelect, t }: TargetTitleFieldProps) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="font-mono text-xs font-bold uppercase">
        {t('diagnosis.targetLabel')}
      </legend>
      {intentions.length === 0 && (
        <p className="border border-black bg-neutral-100 px-3 py-2 font-mono text-xs text-steel-grey">
          {t('diagnosis.targetEmptyHint')}
        </p>
      )}
      {intentions.length === 1 && (
        <p className="border border-black bg-white px-3 py-2 text-sm font-bold">{intentions[0]}</p>
      )}
      {intentions.length >= 2 && (
        <div className="flex flex-col gap-2">
          <p className="font-mono text-xs text-steel-grey">{t('diagnosis.targetChooseHint')}</p>
          <div className="flex flex-col gap-1">
            {intentions.map((title) => {
              const checked = title === selectedTitle;
              return (
                <label
                  key={title}
                  className={`flex cursor-pointer items-center gap-2 border px-3 py-2 text-sm ${
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
  t: TFn;
}

function CompetencyModelField({
  models,
  loading,
  loadError,
  matchedKey,
  selectedKey,
  onSelect,
  t,
}: CompetencyModelFieldProps) {
  const matchedModel = matchedKey
    ? ((models ?? []).find((m) => m.key === matchedKey) ?? null)
    : null;

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="font-mono text-xs font-bold uppercase">{t('diagnosis.modelLabel')}</legend>
      {loading && (
        <p className="border border-black bg-neutral-100 px-3 py-2 font-mono text-xs text-steel-grey">
          {t('diagnosis.modelLoading')}
        </p>
      )}
      {!loading && loadError && (
        <p className="border border-black bg-orange-50 px-3 py-2 font-mono text-xs text-orange-800">
          {t('diagnosis.modelLoadError')}
        </p>
      )}
      {!loading && !loadError && matchedModel && (
        <p className="font-mono text-xs text-steel-grey">
          {t('diagnosis.modelMatchedHint', { name: matchedModel.name })}
        </p>
      )}
      {!loading && !loadError && !matchedModel && (
        <p className="font-mono text-xs text-steel-grey">{t('diagnosis.modelNoMatchHint')}</p>
      )}
      {!loading && (
        <div className="flex flex-col gap-1">
          <ModelRadio
            label={t('diagnosis.modelNone')}
            checked={selectedKey === NONE_MODEL_KEY}
            onSelect={() => onSelect(NONE_MODEL_KEY)}
          />
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
      className={`flex cursor-pointer items-center gap-2 border px-3 py-2 text-sm ${
        checked ? 'border-black bg-white shadow-sw-xs' : 'border-black bg-neutral-50'
      }`}
    >
      <input
        type="radio"
        name="diagnosis-competency-model"
        checked={checked}
        onChange={onSelect}
        className="accent-black"
      />
      <span className="flex items-baseline gap-2">{label}</span>
    </label>
  );
}
