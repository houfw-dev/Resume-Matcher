'use client';

import ShieldAlert from 'lucide-react/dist/esm/icons/shield-alert';
import ShieldCheck from 'lucide-react/dist/esm/icons/shield-check';
import Wrench from 'lucide-react/dist/esm/icons/wrench';
import { stripPointMarker } from '@/components/resume/list-format';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { getDiagnosisFixSection } from '@/lib/utils/diagnosis-fix-link';
import type {
  DiagnosisItem,
  DiagnosisRating,
  DiagnosisReport,
  RatingCounts,
} from '@/lib/api/diagnosis';

export type FilterMode = 'all' | 'problems';
export type TFn = (key: string, params?: Record<string, string | number>) => string;

const RATING_BADGE: Record<DiagnosisRating, string> = {
  conform: 'border-black bg-green-100 text-green-800',
  partial: 'border-black bg-orange-100 text-orange-800',
  nonconform: 'border-black bg-red-100 text-red-800',
  na: 'border-black bg-neutral-100 text-steel-grey',
};

const RATING_BAR: Record<DiagnosisRating, string> = {
  conform: 'bg-success',
  partial: 'bg-warning',
  nonconform: 'bg-destructive',
  na: 'bg-neutral-300',
};

// Filled pips out of 5: conform 5, partial 3, nonconform 0, na renders none.
const RATING_PIPS: Record<DiagnosisRating, number> = {
  conform: 5,
  partial: 3,
  nonconform: 0,
  na: 0,
};

interface ReportViewProps {
  report: DiagnosisReport;
  filter: FilterMode;
  onFilterChange: (mode: FilterMode) => void;
  ratingLabel: (rating: DiagnosisRating) => string;
  /**
   * When provided, problem items with a single owning builder section render
   * a "fix in builder" deep-link button. Unmappable/non-problem items never
   * show it. Omitted in contexts without a builder (e.g. static exports).
   */
  onFixInBuilder?: (itemId: number) => void;
  t: TFn;
}

export function countsParams(counts: RatingCounts): Record<string, number> {
  return {
    effective: counts.effective,
    conform: counts.conform,
    partial: counts.partial,
    nonconform: counts.nonconform,
    na: counts.na,
  };
}

export function DiagnosisReportView({
  report,
  filter,
  onFilterChange,
  ratingLabel,
  onFixInBuilder,
  t,
}: ReportViewProps) {
  const itemsByDimension = new Map<string, DiagnosisItem[]>();
  for (const item of report.items) {
    const list = itemsByDimension.get(item.dimension) ?? [];
    list.push(item);
    itemsByDimension.set(item.dimension, list);
  }
  const visibleItems = (items: DiagnosisItem[]) =>
    filter === 'problems'
      ? items.filter((i) => i.rating === 'nonconform' || i.rating === 'partial')
      : items;

  return (
    <div className="flex flex-col gap-6">
      {/* Checklist counts — no score, no band */}
      <div className="flex flex-col gap-2 border border-black bg-white p-4 shadow-sw-default">
        <p className="font-mono text-xs uppercase text-ink-soft">{t('diagnosis.countsLabel')}</p>
        <p className="font-mono text-sm">
          {t('diagnosis.countsSummary', countsParams(report.counts))}
        </p>
        {report.target_title && (
          <p className="font-mono text-xs text-steel-grey">
            {t('diagnosis.targetValue', { title: report.target_title })}
          </p>
        )}
        {report.competency_model && (
          <p className="font-mono text-xs text-steel-grey">
            {t('diagnosis.competencyValue', { name: report.competency_model.name })}
          </p>
        )}
      </div>

      {/* Red-line status */}
      {report.redline_passed ? (
        <div className="flex items-start gap-3 border border-black bg-green-50 p-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-success" />
          <p className="text-sm font-bold text-green-800">{t('diagnosis.redlinePassed')}</p>
        </div>
      ) : (
        <div className="border border-black bg-red-50 p-3 shadow-sw-default">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <div>
              <p className="text-sm font-bold text-red-800">{t('diagnosis.redlineFailed')}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-red-800">
                {report.redlines
                  .filter((r) => !r.passed)
                  .map((r) => (
                    <li key={r.id}>
                      <span className="font-mono">#{r.id}</span> {r.topic}
                    </li>
                  ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Warnings (e.g. LLM missed an item) */}
      {report.warnings.length > 0 && (
        <div className="border border-black bg-orange-50 p-3">
          <ul className="space-y-1 font-mono text-xs text-orange-800">
            {report.warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Per-dimension checklist counts */}
      <div className="flex flex-col gap-2">
        <h3 className="font-mono text-xs font-bold uppercase">{t('diagnosis.dimensionsTitle')}</h3>
        <div className="border border-black">
          {report.dimensions.map((dim, idx) => (
            <div
              key={dim.key}
              className={`flex flex-wrap items-center justify-between gap-2 px-3 py-2 ${
                idx > 0 ? 'border-t border-black' : ''
              }`}
            >
              <span className="text-sm font-bold">{dim.name}</span>
              <span className="font-mono text-[10px] text-steel-grey">
                {t('diagnosis.countsSummary', countsParams(dim.counts))}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Item filters */}
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-mono text-xs font-bold uppercase">{t('diagnosis.itemsTitle')}</h3>
        <div className="flex border border-black">
          <button
            type="button"
            onClick={() => onFilterChange('all')}
            className={`px-3 py-1 font-mono text-xs uppercase ${
              filter === 'all' ? 'bg-black text-white' : 'bg-white hover:bg-neutral-100'
            }`}
          >
            {t('diagnosis.filterAll')}
          </button>
          <button
            type="button"
            onClick={() => onFilterChange('problems')}
            className={`border-l border-black px-3 py-1 font-mono text-xs uppercase ${
              filter === 'problems' ? 'bg-black text-white' : 'bg-white hover:bg-neutral-100'
            }`}
          >
            {t('diagnosis.filterProblems')}
          </button>
        </div>
      </div>

      {/* Items grouped by dimension */}
      <div className="flex flex-col gap-5">
        {report.dimensions.map((dim) => {
          const items = visibleItems(itemsByDimension.get(dim.key) ?? []);
          if (items.length === 0) return null;
          return (
            <section key={dim.key} className="flex flex-col gap-2">
              <h4 className="font-serif text-base font-bold">{dim.name}</h4>
              {items.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  ratingLabel={ratingLabel}
                  onFixInBuilder={onFixInBuilder}
                  t={t}
                />
              ))}
            </section>
          );
        })}
        {filter === 'problems' &&
          report.items.every((i) => i.rating === 'conform' || i.rating === 'na') && (
            <p className="border border-black bg-green-50 p-3 text-sm font-bold text-green-800">
              {t('diagnosis.allConform')}
            </p>
          )}
      </div>
    </div>
  );
}

interface FindingPointsProps {
  label: string;
  text: string;
  borderClassName: string;
  textClassName?: string;
  topClassName?: string;
}

/**
 * Problem description (evidence) / optimization action (suggestion) rendered
 * as an ordered list: one point per backend-provided line, numbered in the
 * viewer — matching the PDF/Word export, where the same strings render as a
 * numbered list. Source-carried markers ("1.", "①", "- ") are stripped so
 * numbering never doubles.
 */
function FindingPoints({
  label,
  text,
  borderClassName,
  textClassName,
  topClassName,
}: FindingPointsProps) {
  const points = text
    .split('\n')
    .map((line) => stripPointMarker(line).trim())
    .filter(Boolean);
  if (points.length === 0) return null;
  const colon = /[一-鿿]/.test(label) ? '：' : ': ';

  return (
    <div className={cn('border-l-2 pl-2 text-sm', borderClassName, textClassName, topClassName)}>
      <p className="font-bold">
        {label}
        {colon}
      </p>
      <ol className="m-0 list-none">
        {points.map((point, index) => (
          <li key={index} className="flex items-baseline gap-[0.5ch]">
            <span aria-hidden="true" className="w-[3ch] flex-none font-mono tabular-nums">
              {index + 1}.
            </span>
            <span className="min-w-0 flex-1 text-left">{point}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

interface ItemRowProps {
  item: DiagnosisItem;
  ratingLabel: (rating: DiagnosisRating) => string;
  onFixInBuilder?: (itemId: number) => void;
  t: TFn;
}

function ItemRow({ item, ratingLabel, onFixInBuilder, t }: ItemRowProps) {
  // The CTA exists only for problem ratings whose remedy has one canonical
  // owning builder section; holistic/unmappable items render nothing.
  const canFix =
    typeof onFixInBuilder === 'function' &&
    (item.rating === 'nonconform' || item.rating === 'partial') &&
    getDiagnosisFixSection(item.id) !== null;
  return (
    <article className="border border-black bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-steel-grey">#{item.id}</span>
        {item.sub_dimension && item.sub_dimension !== item.dimension_name && (
          <span className="font-mono text-[10px] uppercase text-steel-grey">
            {item.sub_dimension}
          </span>
        )}
        <p className="min-w-[12rem] flex-1 text-sm font-bold">{item.topic}</p>
        {item.severity === 'redline' && (
          <span className="border border-black bg-destructive px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-white">
            {t('diagnosis.severity.redline')}
          </span>
        )}
        <span className="font-mono text-[10px] uppercase text-steel-grey">
          {t(`diagnosis.method.${item.judgment_method}`)}
        </span>
        <span
          className={`border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${RATING_BADGE[item.rating]}`}
        >
          {ratingLabel(item.rating)}
        </span>
      </div>
      {item.evidence && item.rating !== 'na' && (
        <FindingPoints
          label={t('diagnosis.evidenceLabel')}
          text={item.evidence}
          borderClassName="border-black"
          textClassName="text-ink-soft"
          topClassName="mt-2"
        />
      )}
      {/* N/A items carry a why-not-applicable notice, not a problem point. */}
      {item.evidence && item.rating === 'na' && (
        <p className="mt-2 border-l-2 border-black pl-2 text-sm text-ink-soft">{item.evidence}</p>
      )}
      {item.suggestion && (
        <FindingPoints
          label={t('diagnosis.suggestionLabel')}
          text={item.suggestion}
          borderClassName="border-orange-400"
          topClassName="mt-1"
        />
      )}
      {canFix && (
        <div className="mt-2 flex justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onFixInBuilder?.(item.id)}
          >
            <Wrench className="h-4 w-4" />
            {t('diagnosis.fixInBuilder')}
          </Button>
        </div>
      )}
      {item.rating !== 'na' && (
        <div className="mt-1 flex gap-1" aria-hidden>
          {Array.from({ length: 5 }, (_, i) => (
            <span
              key={i}
              className={`h-1 w-6 ${i < RATING_PIPS[item.rating] ? RATING_BAR[item.rating] : 'bg-neutral-200'}`}
            />
          ))}
        </div>
      )}
    </article>
  );
}
