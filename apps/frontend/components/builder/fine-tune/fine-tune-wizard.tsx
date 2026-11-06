'use client';

import React from 'react';
import {
  FineTuneDialog,
  type FineTuneCustomModule,
  type FineTuneEntryOption,
} from './fine-tune-dialog';
import { FineTunePreviewDialog } from './fine-tune-preview-dialog';
import type { useFineTuneWizard } from '@/hooks/use-fine-tune-wizard';
import type { TemplateSettings } from '@/lib/types/template-settings';

type FineTuneWizard = ReturnType<typeof useFineTuneWizard>;

interface FineTuneWizardProps {
  wizard: FineTuneWizard;
  experienceEntries: FineTuneEntryOption[];
  projectEntries: FineTuneEntryOption[];
  hasSummary: boolean;
  hasWorkExperience: boolean;
  hasEducation: boolean;
  hasProjects: boolean;
  hasAdditional: boolean;
  customModules: FineTuneCustomModule[];
  settings: TemplateSettings;
}

/**
 * FineTuneWizard binds the selecting/generating/previewing dialogs to the
 * useFineTuneWizard state machine (same shape as RegenerateWizard).
 */
export const FineTuneWizardView: React.FC<FineTuneWizardProps> = ({
  wizard,
  experienceEntries,
  projectEntries,
  hasSummary,
  hasWorkExperience,
  hasEducation,
  hasProjects,
  hasAdditional,
  customModules,
  settings,
}) => {
  const dialogOpen = wizard.step === 'selecting' || wizard.step === 'generating';

  return (
    <>
      <FineTuneDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open) wizard.close();
        }}
        kind={wizard.kind}
        targets={wizard.targets}
        onKindChange={wizard.setKind}
        onTargetsChange={wizard.setTargets}
        instruction={wizard.instruction}
        onInstructionChange={wizard.setInstruction}
        experienceEntries={experienceEntries}
        projectEntries={projectEntries}
        hasSummary={hasSummary}
        hasWorkExperience={hasWorkExperience}
        hasEducation={hasEducation}
        hasProjects={hasProjects}
        hasAdditional={hasAdditional}
        customModules={customModules}
        isGenerating={wizard.isGenerating}
        error={wizard.step === 'selecting' ? wizard.error : null}
        onGenerate={() => void wizard.generate()}
      />

      {wizard.step === 'previewing' && wizard.preview && (
        <FineTunePreviewDialog
          open
          onOpenChange={(open) => {
            if (!open) wizard.close();
          }}
          preview={wizard.preview}
          settings={settings}
          isConfirming={wizard.isConfirming}
          error={wizard.error}
          onConfirm={(mode, title) => void wizard.confirm(mode, title)}
        />
      )}
    </>
  );
};

export default FineTuneWizardView;
