'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Plus, FileText, List, ListOrdered } from 'lucide-react';
import type { SectionMeta, SectionType } from '@/components/dashboard/resume-component';
import { validateSectionName } from '@/lib/utils/section-order';
import { useTranslations } from '@/lib/i18n';

interface AddSectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (displayName: string, sectionType: SectionType) => void;
  existingSections: readonly SectionMeta[];
}

type SelectableSectionType = Exclude<SectionType, 'personalInfo'>;

/**
 * AddSectionDialog Component
 *
 * Dialog for creating new custom sections.
 * Allows user to enter a name and select a section type. Names cannot be
 * blank, duplicate an existing visible section, or reuse a default title.
 */
export const AddSectionDialog: React.FC<AddSectionDialogProps> = ({
  open,
  onOpenChange,
  onAdd,
  existingSections,
}) => {
  const { t } = useTranslations();
  const [displayName, setDisplayName] = useState('');
  const [sectionType, setSectionType] = useState<SelectableSectionType>('text');

  // Default section titles in the active locale are reserved names.
  const reservedNames = useMemo(
    () => [
      t('resume.sections.personalInfo'),
      t('resume.sections.summary'),
      t('resume.sections.experience'),
      t('resume.sections.education'),
      t('resume.sections.projects'),
      t('resume.sections.skills'),
    ],
    [t]
  );

  // Reset inputs whenever the dialog finishes closing.
  useEffect(() => {
    if (!open) {
      setDisplayName('');
      setSectionType('text');
    }
  }, [open]);

  const trimmedName = displayName.trim();
  const validationCode = validateSectionName(displayName, existingSections, {
    reservedNames,
  });
  const nameError =
    trimmedName.length > 0
      ? validationCode === 'duplicate'
        ? t('builder.sectionHeader.duplicateNameError', { name: trimmedName })
        : validationCode === 'reserved'
          ? t('builder.sectionHeader.reservedNameError', { name: trimmedName })
          : null
      : null;
  const canSubmit = validationCode === null;

  const handleSubmit = () => {
    if (!canSubmit) return;
    onAdd(trimmedName, sectionType);
    setDisplayName('');
    setSectionType('text');
    onOpenChange(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && canSubmit) {
      handleSubmit();
    }
  };

  const sectionTypes: {
    type: SelectableSectionType;
    label: string;
    icon: React.ReactNode;
    description: string;
  }[] = [
    {
      type: 'text',
      label: t('builder.customSections.sectionTypes.textBlockLabel'),
      icon: <FileText className="w-5 h-5" />,
      description: t('builder.customSections.sectionTypes.textBlockDescription'),
    },
    {
      type: 'itemList',
      label: t('builder.customSections.sectionTypes.itemListLabel'),
      icon: <ListOrdered className="w-5 h-5" />,
      description: t('builder.customSections.sectionTypes.itemListDescription'),
    },
    {
      type: 'stringList',
      label: t('builder.customSections.sectionTypes.stringListLabel'),
      icon: <List className="w-5 h-5" />,
      description: t('builder.customSections.sectionTypes.stringListDescription'),
    },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] p-0 gap-0 rounded-none">
        <DialogHeader className="p-6 pb-4 border-b border-black">
          <DialogTitle className="font-serif text-xl font-bold uppercase tracking-tight">
            {t('builder.customSections.dialogTitle')}
          </DialogTitle>
          <DialogDescription className="font-mono text-xs text-ink-soft mt-2">
            {t('builder.customSections.dialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <div className="p-6 space-y-6">
          {/* Section Name */}
          <div className="space-y-2">
            <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
              {t('builder.customSections.sectionNameLabel')}
            </Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('builder.customSections.sectionNamePlaceholder')}
              className="rounded-none border-black"
              autoFocus
            />
            {nameError && <p className="font-mono text-xs text-destructive">{nameError}</p>}
          </div>

          {/* Section Type */}
          <div className="space-y-3">
            <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
              {t('builder.customSections.sectionTypeLabel')}
            </Label>
            <div className="space-y-2">
              {sectionTypes.map((item) => (
                <button
                  key={item.type}
                  type="button"
                  onClick={() => setSectionType(item.type)}
                  className={`w-full p-4 border text-left transition-colors ${
                    sectionType === item.type
                      ? 'border-black bg-paper-tint shadow-sw-sm'
                      : 'border-steel-grey hover:border-steel-grey'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className={`p-2 border ${
                        sectionType === item.type
                          ? 'border-black bg-white'
                          : 'border-steel-grey bg-paper-tint'
                      }`}
                    >
                      {item.icon}
                    </div>
                    <div className="flex-1">
                      <div className="font-sans font-medium text-sm">{item.label}</div>
                      <div className="font-mono text-xs text-steel-grey mt-0.5">
                        {item.description}
                      </div>
                    </div>
                    {sectionType === item.type && (
                      <div className="w-4 h-4 border-2 border-black bg-black" />
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter className="p-4 bg-background border-t border-black flex-row justify-end gap-3">
          <DialogClose asChild>
            <Button variant="outline" className="rounded-none border-black">
              {t('common.cancel')}
            </Button>
          </DialogClose>
          <Button onClick={handleSubmit} disabled={!canSubmit} className="rounded-none">
            <Plus className="w-4 h-4 mr-2" />
            {t('builder.addSection')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * AddSectionButton Component
 *
 * Button that triggers the AddSectionDialog.
 */
interface AddSectionButtonProps {
  onAdd: (displayName: string, sectionType: SectionType) => void;
  existingSections: readonly SectionMeta[];
}

export const AddSectionButton: React.FC<AddSectionButtonProps> = ({ onAdd, existingSections }) => {
  const { t } = useTranslations();
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        className="w-full rounded-none border-dashed border-2 border-black py-6 hover:bg-paper-tint hover:border-solid transition-all"
      >
        <Plus className="w-5 h-5 mr-2" />
        {t('builder.customSections.addCustomSectionButton')}
      </Button>
      <AddSectionDialog
        open={open}
        onOpenChange={setOpen}
        onAdd={onAdd}
        existingSections={existingSections}
      />
    </>
  );
};
