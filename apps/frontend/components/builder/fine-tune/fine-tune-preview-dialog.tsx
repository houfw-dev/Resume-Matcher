'use client';

import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { RetroTabs } from '@/components/ui/retro-tabs';
import { PaginatedPreview } from '@/components/preview';
import { AlertTriangle, Check, Plus, Minus, RefreshCw, Save, Files } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import type { TemplateSettings } from '@/lib/types/template-settings';
import type { FineTuneFieldDiff, FineTuneMode, FineTunePreviewResponse } from '@/lib/api/fine-tune';
import type { ResumeData } from '@/components/dashboard/resume-component';
import {
  customHeadingLabels,
  headingMatches,
  parseRegionToken,
  targetsToHeadingKeys,
  type FineTuneHeadingKey,
} from '@/lib/utils/fine-tune-scope';
import { extractEntryRegions, type RegionId } from '@/lib/utils/description-regions';
import { canonicalizeProjectSubLabel, stripPointMarker } from '@/components/resume/list-format';

interface FineTunePreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preview: FineTunePreviewResponse;
  settings: TemplateSettings;
  isConfirming: boolean;
  error: string | null;
  onConfirm: (mode: FineTuneMode, title?: string) => void;
}

type PreviewTab = 'rendered' | 'changes';

/** Normalize a label heading for DOM matching: strip numbering/colon; project
 * labels are matched after the same canonicalization the renderer applies. */
function labelCore(text: string, kind: 'work' | 'project'): string {
  const stripped = stripPointMarker(text)
    .trim()
    .replace(/[：:]\s*$/u, '')
    .trim();
  return kind === 'project'
    ? canonicalizeProjectSubLabel(stripped)
        .replace(/[：:]\s*$/u, '')
        .trim()
    : stripped;
}

/** Map backend warning codes/prefixes to localized copy; unknown ones pass through. */
function localizeWarning(raw: string, t: (key: string, params?: Record<string, string>) => string) {
  const grounding = /GROUNDING_REVIEW[^:]*:\s*(.+)$/.exec(raw);
  if (grounding) {
    return t('fineTune.preview.groundingWarning', { detail: grounding[1] });
  }
  const ignored = /Ignored out-of-range target:\s*(\S+)/.exec(raw);
  if (ignored) {
    return t('fineTune.preview.ignoredTarget', { target: ignored[1] });
  }
  if (raw.startsWith('SCOPE_RELOCATION_HINT')) {
    return t('fineTune.preview.relocationHint');
  }
  if (raw.startsWith('REGION_APPEND_DROPPED')) {
    return t('fineTune.preview.regionAppendDropped');
  }
  if (/temporarily unavailable/i.test(raw)) {
    return t('fineTune.preview.diffUnavailable');
  }
  return raw;
}

/**
 * FineTunePreviewDialog — rendered preview (with blue scope outlines) and a
 * change-comparison tab; persistence mode is chosen here.
 */
export const FineTunePreviewDialog: React.FC<FineTunePreviewDialogProps> = ({
  open,
  onOpenChange,
  preview,
  settings,
  isConfirming,
  error,
  onConfirm,
}) => {
  const { t } = useTranslations();
  const [tab, setTab] = React.useState<PreviewTab>('rendered');
  const [copyPanelOpen, setCopyPanelOpen] = React.useState(false);
  const [copyTitle, setCopyTitle] = React.useState('');
  const [overwriteConfirmOpen, setOverwriteConfirmOpen] = React.useState(false);
  const previewRootRef = React.useRef<HTMLDivElement>(null);

  const moduleScoped = preview.scope.kind === 'modules';

  // Custom blocks present in the improved result, key + real heading, in
  // stored (canonical) order. The outline frames only blocks the scope token
  // actually selects, so labels are derived from the preview's own data.
  const customBlocks = React.useMemo(() => {
    const data = preview.improved_data as ResumeData;
    const customSections = data.customSections;
    if (!customSections || typeof customSections !== 'object') return [];
    return (data.sectionMeta ?? [])
      .filter(
        (row) =>
          row.isDefault === false &&
          typeof row.key === 'string' &&
          typeof row.displayName === 'string' &&
          Object.prototype.hasOwnProperty.call(customSections, row.key)
      )
      .map((row) => ({ key: row.key, displayName: row.displayName }));
  }, [preview.improved_data]);

  // Region tokens (project_N:<region>) grouped by entry; each entry keeps the
  // label sub-modules the scope actually selected, in token order.
  const regionTargets = React.useMemo(() => {
    const groups = new Map<
      string,
      { kind: 'work' | 'project'; index: number; regionIds: RegionId[] }
    >();
    for (const token of preview.scope.targets) {
      const parsed = parseRegionToken(token);
      if (!parsed) continue;
      const key = `${parsed.kind}:${parsed.index}`;
      const group = groups.get(key) ?? {
        kind: parsed.kind,
        index: parsed.index,
        regionIds: [],
      };
      group.regionIds.push(parsed.regionId);
      groups.set(key, group);
    }
    return groups;
  }, [preview.scope.targets]);

  // Expected rendered heading labels for whole-section frames. Region tokens
  // alone must NOT frame the whole section: they get the tighter region frame.
  const expectedLabels = React.useMemo(() => {
    const labels: Record<FineTuneHeadingKey, string[]> = {
      summary: [t('resume.sections.summary')],
      experience: [t('resume.sections.experience')],
      education: [t('resume.sections.education')],
      projects: [t('resume.sections.projects')],
      additional: [
        t('resume.sections.skillsOnly'),
        t('resume.sections.certifications'),
        t('resume.sections.languages'),
        t('resume.sections.awards'),
        t('resume.additionalLabels.technicalSkills'),
      ],
      custom: customHeadingLabels(preview.scope.targets, customBlocks),
    };
    const coarseTargets = preview.scope.targets.filter((token) => parseRegionToken(token) === null);
    return targetsToHeadingKeys(coarseTargets).flatMap((key) => labels[key]);
  }, [preview.scope.targets, customBlocks, t]);

  // Heading labels and canonical data per entry, used to locate region DOM.
  const regionDomPlan = React.useMemo(() => {
    const data = preview.improved_data as ResumeData;
    const plan: Array<{
      heading: FineTuneHeadingKey;
      headingLabels: string[];
      index: number;
      labels: string[];
    }> = [];
    const labelDefs: Record<
      'experience' | 'projects',
      { labels: string[]; entries: unknown[]; kind: 'work' | 'project' }
    > = {
      experience: {
        labels: [t('resume.sections.experience')],
        entries: data.workExperience ?? [],
        kind: 'work',
      },
      projects: {
        labels: [t('resume.sections.projects')],
        entries: data.personalProjects ?? [],
        kind: 'project',
      },
    };
    regionTargets.forEach((group) => {
      const heading: 'experience' | 'projects' = group.kind === 'work' ? 'experience' : 'projects';
      const def = labelDefs[heading];
      const entry = def.entries[group.index] as
        { description?: string[]; descriptionStyles?: string[] } | undefined;
      if (!entry) return;
      // Coarser tokens (whole section / whole entry) already frame the entry.
      const coarse = preview.scope.targets.some(
        (token) =>
          parseRegionToken(token) === null &&
          (token === (group.kind === 'work' ? 'workExperience' : 'personalProjects') ||
            token === `${group.kind}_${group.index}`)
      );
      if (coarse) return;
      // Repeat ids (two duty blocks) must all frame, so read the ordered list.
      const labels = extractEntryRegions(def.kind, entry)
        .filter((region) => group.regionIds.includes(region.regionId))
        .map((region) => labelCore(region.labelText, def.kind));
      plan.push({
        heading,
        headingLabels: def.labels,
        index: group.index,
        labels,
      });
    });
    return plan;
  }, [regionTargets, preview.improved_data, preview.scope.targets, t]);

  // Tag in-scope rendered sections with the highlight attribute. The preview
  // paginates asynchronously, so observe mutations and re-scan for a short
  // window after opening / switching to the rendered tab.
  React.useEffect(() => {
    if (!open || tab !== 'rendered' || !moduleScoped) return;
    const root = previewRootRef.current;
    if (!root) return;

    const REGION_MARK = 'region';

    const findSection = (headingLabels: string[]): Element[] => {
      const matched: Element[] = [];
      root.querySelectorAll("[class*='resume-section']").forEach((element) => {
        const heading = element.querySelector('h1, h2, h3, h4');
        if (headingMatches(heading?.textContent ?? '', headingLabels)) matched.push(element);
      });
      return matched;
    };

    const scan = () => {
      // Clear region marks from a previous pass before re-framing.
      root
        .querySelectorAll(`[data-fine-tune-highlight="${REGION_MARK}"]`)
        .forEach((element) => element.removeAttribute('data-fine-tune-highlight'));

      const sections = root.querySelectorAll("[class*='resume-section']");
      sections.forEach((element) => {
        const heading = element.querySelector('h1, h2, h3, h4');
        const matched = headingMatches(heading?.textContent ?? '', expectedLabels);
        if (matched) element.setAttribute('data-fine-tune-highlight', '');
        else element.removeAttribute('data-fine-tune-highlight');
      });

      // Region frame: the label row plus its list/body block, scoped to the
      // Nth entry wrapper in the matching section, across all template styles.
      regionDomPlan.forEach((plan) => {
        findSection(plan.headingLabels).forEach((sectionElement) => {
          const entries: Element[] = [];
          sectionElement.querySelectorAll("[class*='resume-items']").forEach((container) => {
            Array.from(container.children).forEach((child) => {
              if (
                child.className &&
                String(child.className).includes('resume-item') &&
                !String(child.className).includes('resume-items')
              ) {
                entries.push(child);
              }
            });
          });
          const entryElement = entries[plan.index];
          if (!entryElement) return;
          const wantedCores = new Set(plan.labels);
          if (wantedCores.size === 0) return;
          const kind = plan.heading === 'projects' ? 'project' : 'work';
          const labelElements = Array.from(entryElement.querySelectorAll('[data-sub-label]'));
          labelElements.forEach((labelElement) => {
            const core = labelCore(labelElement.textContent ?? '', kind);
            if (!wantedCores.has(core)) return;
            labelElement.setAttribute('data-fine-tune-highlight', REGION_MARK);
            let sibling = labelElement.nextElementSibling;
            while (sibling && !sibling.hasAttribute('data-sub-label')) {
              sibling.setAttribute('data-fine-tune-highlight', REGION_MARK);
              sibling = sibling.nextElementSibling;
            }
          });
        });
      });
    };

    scan();
    const timers = [window.setTimeout(scan, 150), window.setTimeout(scan, 500)];
    const observer = new MutationObserver(scan);
    observer.observe(root, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      timers.forEach(window.clearTimeout);
    };
  }, [open, tab, moduleScoped, expectedLabels, regionDomPlan]);

  // Reset transient mode UI whenever a new preview is shown.
  React.useEffect(() => {
    setTab('rendered');
    setCopyPanelOpen(false);
    setOverwriteConfirmOpen(false);
    setCopyTitle('');
  }, [preview.preview_id]);

  const changes = preview.detailed_changes ?? [];
  const warnings = preview.warnings ?? [];
  const closeAllowed = !isConfirming;

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !closeAllowed) return;
          onOpenChange(nextOpen);
        }}
      >
        <DialogContent
          className="sm:max-w-[1040px] w-[94vw] h-[92vh] p-0 gap-0 rounded-none overflow-hidden flex flex-col"
          closeOnEscape={closeAllowed}
          closeOnBackdrop={closeAllowed}
          showCloseButton={closeAllowed}
        >
          <DialogHeader className="p-6 pb-4 border-b border-black shrink-0">
            <DialogTitle className="font-serif text-xl font-bold uppercase tracking-tight">
              {t('fineTune.preview.title')}
            </DialogTitle>
            <DialogDescription className="font-mono text-xs text-ink-soft mt-2">
              {moduleScoped ? t('fineTune.preview.highlightHint') : t('fineTune.preview.subtitle')}
            </DialogDescription>
          </DialogHeader>

          <div className="px-6 pt-3 border-b border-black shrink-0">
            <RetroTabs
              tabs={[
                { id: 'rendered', label: t('fineTune.preview.tabRendered') },
                { id: 'changes', label: t('fineTune.preview.tabChanges') },
              ]}
              activeTab={tab}
              onTabChange={(id) => setTab(id as PreviewTab)}
            />
          </div>

          {warnings.length > 0 && (
            <div className="px-6 pt-3 shrink-0">
              <div
                role="alert"
                className="border-2 border-orange-500 bg-orange-50 px-4 py-3 flex items-start gap-2"
              >
                <AlertTriangle className="w-4 h-4 text-orange-600 mt-0.5 shrink-0" />
                <div className="space-y-1">
                  <p className="font-mono text-xs uppercase tracking-wider text-orange-700">
                    {t('fineTune.preview.warningsTitle')}
                  </p>
                  <ul className="space-y-0.5">
                    {warnings.map((warning, index) => (
                      <li key={index} className="text-xs text-orange-800">
                        {localizeWarning(warning, t)}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="px-6 pt-3 shrink-0">
              <div
                role="alert"
                className="border-2 border-red-600 bg-red-50 px-4 py-3 text-sm text-red-800"
              >
                {error}
              </div>
            </div>
          )}

          <div className="flex-1 min-h-0">
            {tab === 'rendered' ? (
              // Dialog has a definite height (h-[92vh]), so the h-full chain
              // resolves and PaginatedPreview scrolls inside this box.
              <div ref={previewRootRef} className="h-full">
                <PaginatedPreview
                  resumeData={preview.improved_data as ResumeData}
                  settings={settings}
                />
              </div>
            ) : (
              <div className="h-full overflow-y-auto p-6 space-y-4 bg-[#D5D5D0]">
                {preview.diff_summary && (
                  <div className="flex flex-wrap gap-2 font-mono text-xs">
                    <span className="border border-black bg-white px-2 py-1">
                      {t('fineTune.preview.changesCount', {
                        count: String(preview.diff_summary.total_changes),
                      })}
                    </span>
                    <span className="border border-black bg-white px-2 py-1">
                      {t('fineTune.preview.descriptionsModified', {
                        count: String(preview.diff_summary.descriptions_modified),
                      })}
                    </span>
                    <span className="border border-black bg-white px-2 py-1">
                      {t('fineTune.preview.skillsAdded', {
                        count: String(preview.diff_summary.skills_added),
                      })}
                    </span>
                    <span className="border border-black bg-white px-2 py-1">
                      {t('fineTune.preview.skillsRemoved', {
                        count: String(preview.diff_summary.skills_removed),
                      })}
                    </span>
                  </div>
                )}

                {changes.length === 0 ? (
                  <div className="border border-black bg-white p-6 text-center font-mono text-sm text-steel-grey">
                    {t('fineTune.preview.noChanges')}
                  </div>
                ) : (
                  changes.map((change, index) => (
                    <DiffCard key={`${change.field_path}-${index}`} change={change} />
                  ))
                )}
              </div>
            )}
          </div>

          <DialogFooter className="p-4 bg-secondary border-t border-black flex-row justify-between gap-3 items-center shrink-0">
            {copyPanelOpen ? (
              <div className="flex flex-1 flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <Input
                  value={copyTitle}
                  onChange={(event) => setCopyTitle(event.target.value.slice(0, 200))}
                  placeholder={t('fineTune.preview.copyTitlePlaceholder')}
                  maxLength={200}
                  aria-label={t('fineTune.preview.copyTitleLabel')}
                  className="rounded-none border-black h-9"
                  autoFocus
                />
                <Button
                  variant="outline"
                  onClick={() => setCopyPanelOpen(false)}
                  disabled={isConfirming}
                  className="rounded-none border-black"
                >
                  {t('fineTune.dialog.cancel')}
                </Button>
                <Button
                  variant="success"
                  onClick={() => onConfirm('copy', copyTitle.trim() || undefined)}
                  disabled={isConfirming}
                  className="rounded-none"
                >
                  {isConfirming ? (
                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Files className="w-4 h-4 mr-2" />
                  )}
                  {t('fineTune.preview.createCopy')}
                </Button>
              </div>
            ) : (
              <>
                <Button
                  variant="outline"
                  onClick={() => onOpenChange(false)}
                  disabled={isConfirming}
                  className="rounded-none border-black"
                >
                  {t('fineTune.preview.cancel')}
                </Button>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={() => setOverwriteConfirmOpen(true)}
                    disabled={isConfirming}
                    className="rounded-none border-red-700 text-red-700 hover:bg-red-50"
                  >
                    {t('fineTune.preview.overwrite')}
                  </Button>
                  <Button
                    variant="success"
                    onClick={() => setCopyPanelOpen(true)}
                    disabled={isConfirming}
                    className="rounded-none"
                  >
                    <Save className="w-4 h-4 mr-2" />
                    {t('fineTune.preview.saveCopy')}
                  </Button>
                </div>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={overwriteConfirmOpen}
        onOpenChange={setOverwriteConfirmOpen}
        title={t('fineTune.preview.overwriteConfirmTitle')}
        description={t('fineTune.preview.overwriteConfirmBody')}
        confirmLabel={
          isConfirming ? t('fineTune.preview.applying') : t('fineTune.preview.overwrite')
        }
        variant="warning"
        onConfirm={() => onConfirm('overwrite')}
      />
    </>
  );
};

const CHANGE_META: Record<
  FineTuneFieldDiff['change_type'],
  { labelKey: string; className: string; icon: React.ReactNode }
> = {
  added: {
    labelKey: 'fineTune.preview.changeAdded',
    className: 'border-green-700 text-green-800 bg-green-50',
    icon: <Plus className="w-3 h-3" />,
  },
  removed: {
    labelKey: 'fineTune.preview.changeRemoved',
    className: 'border-red-700 text-red-800 bg-red-50',
    icon: <Minus className="w-3 h-3" />,
  },
  modified: {
    labelKey: 'fineTune.preview.changeModified',
    className: 'border-blue-700 text-blue-800 bg-blue-50',
    icon: <RefreshCw className="w-3 h-3" />,
  },
};

const DiffCard: React.FC<{ change: FineTuneFieldDiff }> = ({ change }) => {
  const { t } = useTranslations();
  const meta = CHANGE_META[change.change_type];
  return (
    <div className="border border-black bg-white">
      <div className="flex items-center justify-between gap-2 border-b border-black px-4 py-2">
        <span className="font-mono text-xs break-all">{change.field_path}</span>
        <span
          className={`inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${meta.className}`}
        >
          {meta.icon}
          {t(meta.labelKey)}
        </span>
      </div>
      {change.original_value && (
        <div className="px-4 py-2 border-b border-black">
          <div className="font-mono text-[10px] uppercase tracking-wider text-steel-grey mb-1">
            {t('fineTune.preview.originalLabel')}
          </div>
          <p className="text-sm text-red-800 line-through whitespace-pre-line">
            {change.original_value}
          </p>
        </div>
      )}
      {change.new_value && (
        <div className="px-4 py-2">
          <div className="font-mono text-[10px] uppercase tracking-wider text-steel-grey mb-1">
            {t('fineTune.preview.newLabel')}
          </div>
          <p className="text-sm text-green-800 whitespace-pre-line">
            <Check className="inline w-3 h-3 mr-1" />
            {change.new_value}
          </p>
        </div>
      )}
    </div>
  );
};

export default FineTunePreviewDialog;
