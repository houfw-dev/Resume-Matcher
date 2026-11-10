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
import {
  Briefcase,
  FolderKanban,
  GraduationCap,
  Lightbulb,
  AlignLeft,
  Blocks,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import type { FineTuneKind } from '@/lib/api/fine-tune';
import {
  customSectionToken,
  isWholeSectionSelected,
  itemToken,
  regionToken,
  toggleItemToken,
  toggleRegionToken,
  toggleSectionToken,
} from '@/lib/utils/fine-tune-scope';
import type { RegionId } from '@/lib/utils/description-regions';

export interface FineTuneEntryOption {
  title: string;
  subtitle?: string;
  /** Label sub-modules actually present in this entry, in source order. */
  regions?: RegionId[];
}

/** One non-empty custom section, listed as its own selectable module row. */
export interface FineTuneCustomModule {
  key: string;
  displayName: string;
}

interface FineTuneDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kind: FineTuneKind;
  targets: string[];
  onKindChange: (kind: FineTuneKind) => void;
  onTargetsChange: (targets: string[]) => void;
  instruction: string;
  onInstructionChange: (instruction: string) => void;
  experienceEntries: FineTuneEntryOption[];
  projectEntries: FineTuneEntryOption[];
  hasSummary: boolean;
  hasWorkExperience: boolean;
  hasEducation: boolean;
  hasProjects: boolean;
  hasAdditional: boolean;
  customModules: FineTuneCustomModule[];
  isGenerating: boolean;
  error: string | null;
  onGenerate: () => void;
}

const MAX_INSTRUCTION_LENGTH = 2000;

/**
 * FineTuneDialog — scope + instruction step of the fine-tune wizard, and the
 * non-closable generating state. Scope grammar lives in fine-tune-scope.ts.
 */
export const FineTuneDialog: React.FC<FineTuneDialogProps> = ({
  open,
  onOpenChange,
  kind,
  targets,
  onKindChange,
  onTargetsChange,
  instruction,
  onInstructionChange,
  experienceEntries,
  projectEntries,
  hasSummary,
  hasWorkExperience,
  hasEducation,
  hasProjects,
  hasAdditional,
  customModules,
  isGenerating,
  error,
  onGenerate,
}) => {
  const { t } = useTranslations();
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const modulesMode = kind === 'modules';
  const canGenerate = (!modulesMode || targets.length > 0) && !isGenerating;

  const toggleExpanded = (key: string) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleInstructionKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter') event.stopPropagation();
  };

  const moduleRows: Array<{
    token: string;
    label: string;
    icon: React.ReactNode;
    entries?: { section: 'workExperience' | 'personalProjects'; items: FineTuneEntryOption[] };
  }> = [
    ...(hasSummary
      ? [
          {
            token: 'summary',
            label: t('fineTune.dialog.modules.summary'),
            icon: <AlignLeft className="w-4 h-4" />,
          },
        ]
      : []),
    ...(hasWorkExperience
      ? [
          {
            token: 'workExperience',
            label: t('fineTune.dialog.modules.workExperience'),
            icon: <Briefcase className="w-4 h-4" />,
            entries:
              experienceEntries.length > 0
                ? { section: 'workExperience' as const, items: experienceEntries }
                : undefined,
          },
        ]
      : []),
    ...(hasEducation
      ? [
          {
            token: 'education',
            label: t('fineTune.dialog.modules.education'),
            icon: <GraduationCap className="w-4 h-4" />,
          },
        ]
      : []),
    ...(hasProjects
      ? [
          {
            token: 'personalProjects',
            label: t('fineTune.dialog.modules.personalProjects'),
            icon: <FolderKanban className="w-4 h-4" />,
            entries:
              projectEntries.length > 0
                ? { section: 'personalProjects' as const, items: projectEntries }
                : undefined,
          },
        ]
      : []),
    ...(hasAdditional
      ? [
          {
            token: 'additional',
            label: t('fineTune.dialog.modules.additional'),
            icon: <Lightbulb className="w-4 h-4" />,
          },
        ]
      : []),
    // Every non-empty custom section gets its own row, labeled with its real
    // heading; the legacy aggregated "customSections" token is no longer
    // produced by the UI (the backend still accepts it for old previews).
    ...customModules.map((module) => ({
      token: customSectionToken(module.key),
      label: module.displayName,
      icon: <Blocks className="w-4 h-4" />,
    })),
  ];

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && isGenerating) return;
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent
        className="sm:max-w-[640px] max-h-[90vh] p-0 gap-0 rounded-none overflow-hidden flex flex-col"
        closeOnEscape={!isGenerating}
        closeOnBackdrop={!isGenerating}
        showCloseButton={!isGenerating}
      >
        <DialogHeader className="p-6 pb-4 border-b border-black">
          <DialogTitle className="font-serif text-xl font-bold uppercase tracking-tight">
            {isGenerating ? t('fineTune.generating.title') : t('fineTune.dialog.title')}
          </DialogTitle>
          {!isGenerating && (
            <DialogDescription className="font-mono text-xs text-ink-soft mt-2">
              {t('fineTune.dialog.subtitle')}
            </DialogDescription>
          )}
        </DialogHeader>

        {isGenerating ? (
          <div className="p-10 flex flex-col items-center gap-4" role="status" aria-live="polite">
            <Loader2 className="w-8 h-8 animate-spin text-primary" aria-hidden="true" />
            <p className="font-mono text-xs uppercase tracking-wider text-ink-soft text-center">
              {t('fineTune.generating.body')}
            </p>
          </div>
        ) : (
          <>
            <div className="p-6 space-y-4 overflow-y-auto">
              {/* Scope radio cards */}
              <div className="space-y-2">
                <ScopeOption
                  checked={!modulesMode}
                  onChange={() => onKindChange('all')}
                  label={t('fineTune.dialog.scopeAll')}
                  hint={t('fineTune.dialog.scopeAllHint')}
                />
                <ScopeOption
                  checked={modulesMode}
                  onChange={() => onKindChange('modules')}
                  label={t('fineTune.dialog.scopeModules')}
                  hint={t('fineTune.dialog.scopeModulesHint')}
                />
              </div>

              {modulesMode && (
                <div className="border border-black">
                  {moduleRows.map((row, rowIndex) => {
                    const wholeSelected =
                      row.entries !== undefined &&
                      isWholeSectionSelected(targets, row.entries.section);
                    const sectionChecked = targets.includes(row.token) || wholeSelected;
                    const isExpanded = expanded.has(row.token);
                    return (
                      <div key={row.token} className={rowIndex > 0 ? 'border-t border-black' : ''}>
                        <div className="flex items-center bg-white">
                          <CheckRow
                            checked={sectionChecked}
                            onToggle={() => onTargetsChange(toggleSectionToken(targets, row.token))}
                          >
                            <span className="flex items-center gap-2 font-mono text-sm uppercase tracking-wider">
                              {row.icon}
                              {row.label}
                            </span>
                          </CheckRow>
                          {row.entries && (
                            <button
                              type="button"
                              onClick={() => toggleExpanded(row.token)}
                              aria-expanded={isExpanded}
                              aria-label={t('fineTune.dialog.selectEntries', {
                                module: row.label,
                              })}
                              className="px-3 py-3 text-steel-grey hover:text-black disabled:opacity-40"
                              disabled={wholeSelected}
                            >
                              {isExpanded ? (
                                <ChevronDown className="w-4 h-4" />
                              ) : (
                                <ChevronRight className="w-4 h-4" />
                              )}
                            </button>
                          )}
                        </div>

                        {row.entries && isExpanded && !wholeSelected && (
                          <div className="border-t border-black">
                            {row.entries.items.map((entry, index) => {
                              const entryKind =
                                row.entries!.section === 'workExperience' ? 'work' : 'project';
                              const token = itemToken(entryKind, index);
                              const checked = targets.includes(token);
                              const entryRegions = entry.regions ?? [];
                              const selectedRegions = entryRegions.filter((regionId) =>
                                targets.includes(regionToken(entryKind, index, regionId))
                              );
                              const partial = !checked && selectedRegions.length > 0;
                              const regionsExpanded = expanded.has(token);
                              return (
                                <div key={token} className="border-t border-black first:border-t-0">
                                  <div className="flex items-center bg-white">
                                    <CheckRow
                                      checked={checked}
                                      partial={partial}
                                      onToggle={() =>
                                        onTargetsChange(
                                          toggleItemToken(targets, row.entries!.section, index)
                                        )
                                      }
                                    >
                                      <span className="flex-1 min-w-0">
                                        <span className="block text-sm truncate">
                                          {entry.title || token}
                                        </span>
                                        {entry.subtitle && (
                                          <span className="block font-mono text-xs text-steel-grey truncate">
                                            {entry.subtitle}
                                          </span>
                                        )}
                                      </span>
                                    </CheckRow>
                                    {entryRegions.length > 0 && (
                                      <button
                                        type="button"
                                        onClick={() => toggleExpanded(token)}
                                        aria-expanded={regionsExpanded}
                                        aria-label={t('fineTune.dialog.selectRegions', {
                                          module: entry.title || token,
                                        })}
                                        className="px-3 py-3 text-steel-grey hover:text-black disabled:opacity-40"
                                        disabled={checked}
                                      >
                                        {regionsExpanded ? (
                                          <ChevronDown className="w-4 h-4" />
                                        ) : (
                                          <ChevronRight className="w-4 h-4" />
                                        )}
                                      </button>
                                    )}
                                  </div>

                                  {entryRegions.length > 0 && regionsExpanded && !checked && (
                                    <div className="border-t border-black bg-paper-tint">
                                      {entryRegions.map((regionId) => {
                                        const regionTok = regionToken(entryKind, index, regionId);
                                        const regionChecked = targets.includes(regionTok);
                                        return (
                                          <button
                                            key={regionTok}
                                            type="button"
                                            onClick={() =>
                                              onTargetsChange(
                                                toggleRegionToken(
                                                  targets,
                                                  entryKind,
                                                  index,
                                                  regionId
                                                )
                                              )
                                            }
                                            aria-pressed={regionChecked}
                                            className={`w-full flex items-center gap-3 pl-10 pr-4 py-2.5 text-left border-t border-black first:border-t-0 ${
                                              regionChecked ? 'bg-blue-50' : 'hover:bg-white'
                                            }`}
                                          >
                                            <CheckboxMark checked={regionChecked} />
                                            <span className="flex-1 min-w-0 text-sm truncate">
                                              {t(`fineTune.dialog.regions.${regionId}`)}
                                            </span>
                                          </button>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {targets.length === 0 && (
                    <p className="mt-2 font-mono text-xs text-orange-600">
                      {t('fineTune.dialog.selectAtLeastOne')}
                    </p>
                  )}
                </div>
              )}

              {/* Instruction */}
              <div className="space-y-1">
                <label
                  htmlFor="fine-tune-instruction"
                  className="block font-mono text-xs uppercase tracking-wider"
                >
                  {t('fineTune.dialog.instructionLabel')}
                </label>
                <textarea
                  id="fine-tune-instruction"
                  value={instruction}
                  onChange={(event) =>
                    onInstructionChange(event.target.value.slice(0, MAX_INSTRUCTION_LENGTH))
                  }
                  onKeyDown={handleInstructionKeyDown}
                  maxLength={MAX_INSTRUCTION_LENGTH}
                  rows={3}
                  placeholder={t('fineTune.dialog.instructionPlaceholder')}
                  className="w-full rounded-none border border-black bg-white p-3 text-sm font-sans resize-y focus:outline-none focus:ring-2 focus:ring-primary"
                />
                <div className="text-right font-mono text-[10px] text-steel-grey">
                  {instruction.length}/{MAX_INSTRUCTION_LENGTH}
                </div>
              </div>

              {error && (
                <div
                  role="alert"
                  className="border-2 border-destructive bg-red-50 px-4 py-3 flex items-start gap-2"
                >
                  <AlertTriangle className="w-4 h-4 text-red-700 mt-0.5 shrink-0" />
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              )}
            </div>

            <DialogFooter className="p-4 bg-secondary border-t border-black flex-row justify-between gap-3">
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                className="rounded-none border-black"
              >
                {t('fineTune.dialog.cancel')}
              </Button>
              <Button onClick={onGenerate} disabled={!canGenerate} className="rounded-none">
                {t('fineTune.dialog.generate')}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};

const ScopeOption: React.FC<{
  checked: boolean;
  onChange: () => void;
  label: string;
  hint: string;
}> = ({ checked, onChange, label, hint }) => (
  <label
    className={`flex items-start gap-3 border p-3 cursor-pointer transition-colors ${
      checked ? 'border-black bg-blue-50' : 'border-steel-grey bg-white hover:bg-paper-tint'
    }`}
  >
    <input
      type="radio"
      name="fine-tune-scope"
      checked={checked}
      onChange={onChange}
      className="mt-1 h-4 w-4 accent-primary"
    />
    <span>
      <span className="block font-sans text-sm font-medium">{label}</span>
      <span className="block font-mono text-xs text-ink-soft mt-0.5">{hint}</span>
    </span>
  </label>
);

const CheckboxMark: React.FC<{ checked: boolean; partial?: boolean }> = ({
  checked,
  partial = false,
}) => (
  <span
    aria-hidden="true"
    className={`w-5 h-5 border-2 shrink-0 flex items-center justify-center ${
      checked
        ? 'border-primary bg-primary'
        : partial
          ? 'border-primary bg-white'
          : 'border-black bg-white'
    }`}
  >
    {checked && (
      <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
      </svg>
    )}
    {/* Partial selection: some label sub-modules of this entry are checked. */}
    {!checked && partial && <span className="w-2 h-2 bg-primary" aria-hidden="true" />}
  </span>
);

/** Full-width clickable row that behaves as a checkbox. */
const CheckRow: React.FC<{
  checked: boolean;
  partial?: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}> = ({ checked, partial = false, onToggle, children }) => (
  <button
    type="button"
    onClick={onToggle}
    aria-pressed={checked}
    className="flex-1 flex items-center gap-3 px-4 py-3 text-left"
  >
    <CheckboxMark checked={checked} partial={partial} />
    <span className="flex-1 min-w-0">{children}</span>
  </button>
);

export default FineTuneDialog;
