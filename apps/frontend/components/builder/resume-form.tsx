'use client';

import React, { useMemo } from 'react';
import {
  ResumeData,
  PersonalInfo,
  SectionMeta,
  SectionType,
  CustomSection,
} from '@/components/dashboard/resume-component';
import { PersonalInfoForm } from './forms/personal-info-form';
import { SummaryForm } from './forms/summary-form';
import { ExperienceForm } from './forms/experience-form';
import { EducationForm } from './forms/education-form';
import { ProjectsForm } from './forms/projects-form';
import { AdditionalForm } from './forms/additional-form';
import { SectionHeader } from './section-header';
import { GenericTextForm } from './forms/generic-text-form';
import { GenericItemForm } from './forms/generic-item-form';
import { GenericListForm } from './forms/generic-list-form';
import { AddSectionButton } from './add-section-dialog';
import Lock from 'lucide-react/dist/esm/icons/lock';
import {
  createCustomSection,
  DEFAULT_SECTION_META,
  ensureDefaultSectionMeta,
  migrateTextSectionToSummary,
  withLocalizedDefaultSections,
} from '@/lib/utils/section-helpers';
import {
  DEFAULT_SECTION_KEYS,
  getCanonicalSections,
  isAcceptedDefaultTitle,
  validateSectionName,
} from '@/lib/utils/section-order';
import { customSectionToken } from '@/lib/utils/fine-tune-scope';
import { useTranslations } from '@/lib/i18n';

interface ResumeFormProps {
  resumeData: ResumeData;
  onUpdate: (data: ResumeData) => void;
  /** Open the fine-tune wizard scoped to one section (or all custom blocks). */
  onFineTuneSection?: (sectionId: string) => void;
}

const isDefaultSectionKey = (key: string): boolean =>
  (DEFAULT_SECTION_KEYS as readonly string[]).includes(key);

export const ResumeForm: React.FC<ResumeFormProps> = ({
  resumeData,
  onUpdate,
  onFineTuneSection,
}) => {
  const { t } = useTranslations();

  // Raw meta drives every state mutation; the localized copy only feeds
  // display (locked default titles) and canonical ordering. Missing default
  // rows (e.g. an uploaded resume with no 个人优势 block at all) are inserted
  // for the builder so their forms exist. Builder contract: every built-in
  // block is always listed and visible regardless of content — an empty
  // optional block is hidden downstream (save-time canonicalization →
  // PDF/render), never in the editor.
  const allSections = useMemo(
    () =>
      ensureDefaultSectionMeta(resumeData).map((section) =>
        isDefaultSectionKey(section.key) ? { ...section, isVisible: true } : section
      ),
    [resumeData]
  );
  const localizedData = useMemo(
    () => withLocalizedDefaultSections({ ...resumeData, sectionMeta: allSections }, t),
    [resumeData, allSections, t]
  );
  // Fixed canonical order (degree-branch aware), hidden sections included.
  const sortedAllSections = getCanonicalSections(localizedData, { includeHidden: true });

  // The six default titles in the active locale are reserved custom names.
  const reservedDefaultNames = useMemo(
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

  // Whether renaming this custom block to `name` is the 自我评价 → 个人优势
  // migration: a custom TEXT block taking the summary title is merged into
  // the built-in summary block on save, so the reserved-title rule must not
  // reject it (and no duplicate-title row remains afterwards).
  const isSummaryMigration = (name: string, excludeId?: string): boolean => {
    const trimmed = name.trim();
    const target = excludeId ? allSections.find((s) => s.id === excludeId) : undefined;
    if (!target || target.isDefault || !isAcceptedDefaultTitle('summary', trimmed)) {
      return false;
    }
    return resumeData.customSections?.[target.key]?.sectionType === 'text';
  };

  // Validate a new/renamed custom-section name; returns a localized error
  // string or null. The dialog performs the same check; this is the backstop.
  const validateName = (name: string, excludeId?: string): string | null => {
    if (isSummaryMigration(name, excludeId)) return null;
    const error = validateSectionName(name, allSections, {
      excludeId,
      reservedNames: reservedDefaultNames,
    });
    const trimmed = name.trim();
    if (error === 'duplicate') {
      return t('builder.sectionHeader.duplicateNameError', { name: trimmed });
    }
    if (error === 'reserved') {
      return t('builder.sectionHeader.reservedNameError', { name: trimmed });
    }
    if (error === 'empty') {
      return t('builder.sectionHeader.nameRequiredError');
    }
    return null;
  };

  // Handle section metadata updates
  const handleSectionMetaUpdate = (sections: SectionMeta[]) => {
    onUpdate({
      ...resumeData,
      sectionMeta: sections,
    });
  };

  // Handle adding a new custom section
  const handleAddSection = (displayName: string, sectionType: SectionType) => {
    if (validateName(displayName)) return;

    const newSection = createCustomSection(allSections, displayName.trim(), sectionType);

    // Initialize section metadata if not present
    const currentMeta = resumeData.sectionMeta?.length
      ? resumeData.sectionMeta
      : DEFAULT_SECTION_META;

    // Initialize section data
    const newCustomSection: CustomSection = {
      sectionType,
      text: sectionType === 'text' ? '' : undefined,
      items: sectionType === 'itemList' ? [] : undefined,
      strings: sectionType === 'stringList' ? [] : undefined,
    };

    onUpdate({
      ...resumeData,
      sectionMeta: [...currentMeta, newSection],
      customSections: {
        ...resumeData.customSections,
        [newSection.key]: newCustomSection,
      },
    });
  };

  // Handler for section rename — custom sections only; default titles are locked.
  const handleRename = (sectionId: string, newName: string) => {
    const target = allSections.find((s) => s.id === sectionId);
    if (!target || isDefaultSectionKey(target.key)) return;

    // Renaming a custom text block to the summary title (e.g. 自我评价 →
    // 个人优势) merges it into the built-in summary block instead of keeping
    // a custom block with a reserved name.
    if (isAcceptedDefaultTitle('summary', newName.trim())) {
      const migrated = migrateTextSectionToSummary(resumeData, target.key);
      if (migrated) {
        onUpdate(migrated);
        return;
      }
    }

    if (validateName(newName, sectionId)) return;

    const updatedSections = allSections.map((s) =>
      s.id === sectionId ? { ...s, displayName: newName.trim() } : s
    );
    handleSectionMetaUpdate(updatedSections);
  };

  // Handler for section delete
  const handleDelete = (sectionId: string) => {
    const section = allSections.find((s) => s.id === sectionId);
    if (!section) return;

    if (section.isDefault) {
      // For default sections, just hide them
      handleToggleVisibility(sectionId);
    } else {
      // For custom sections, remove from both sectionMeta and customSections
      const updatedSections = allSections.filter((s) => s.id !== sectionId);
      const updatedCustomSections = { ...resumeData.customSections };
      delete updatedCustomSections[section.key];

      onUpdate({
        ...resumeData,
        sectionMeta: updatedSections,
        customSections: updatedCustomSections,
      });
    }
  };

  // Handler for section visibility toggle
  const handleToggleVisibility = (sectionId: string) => {
    const updatedSections = allSections.map((s) =>
      s.id === sectionId ? { ...s, isVisible: !s.isVisible } : s
    );
    handleSectionMetaUpdate(updatedSections);
  };

  // Render default section forms
  const renderDefaultSection = (section: SectionMeta) => {
    const isPersonalInfo = section.id === 'personalInfo';

    // Render content based on section key
    const renderContent = () => {
      switch (section.key) {
        case 'personalInfo':
          return (
            <PersonalInfoForm
              data={resumeData.personalInfo || ({} as PersonalInfo)}
              onChange={(data) => onUpdate({ ...resumeData, personalInfo: data })}
            />
          );

        case 'summary':
          return (
            <SummaryForm
              value={resumeData.summary || ''}
              onChange={(value) => {
                // The editor always lists built-in blocks (allSections forces
                // them visible), but storage still hides an empty summary.
                // Persist the visibility flip alongside the first typed text;
                // merge meta + content in ONE update (two onUpdate calls would
                // both spread the stale closure and drop the flip).
                const storedSummary = resumeData.sectionMeta?.find((s) => s.key === 'summary');
                const revealedMeta =
                  value.trim() && storedSummary?.isVisible !== true
                    ? allSections.map((s) => (s.key === 'summary' ? { ...s, isVisible: true } : s))
                    : undefined;
                onUpdate({
                  ...resumeData,
                  ...(revealedMeta ? { sectionMeta: revealedMeta } : {}),
                  summary: value,
                });
              }}
            />
          );

        case 'workExperience':
          return (
            <ExperienceForm
              data={resumeData.workExperience || []}
              onChange={(data) => onUpdate({ ...resumeData, workExperience: data })}
            />
          );

        case 'education':
          return (
            <EducationForm
              data={resumeData.education || []}
              onChange={(data) => onUpdate({ ...resumeData, education: data })}
            />
          );

        case 'personalProjects':
          return (
            <ProjectsForm
              data={resumeData.personalProjects || []}
              onChange={(data) => onUpdate({ ...resumeData, personalProjects: data })}
            />
          );

        case 'additional':
          return (
            <AdditionalForm
              data={
                resumeData.additional || {
                  technicalSkills: [],
                  languages: [],
                  certificationsTraining: [],
                  awards: [],
                }
              }
              onChange={(data) => onUpdate({ ...resumeData, additional: data })}
            />
          );

        default:
          return null;
      }
    };

    // PersonalInfo is special - render without wrapper
    if (isPersonalInfo) {
      return renderContent();
    }

    // Other default sections get SectionHeader without hide/delete controls:
    // built-in blocks are always listed in the builder. Titles are locked
    // (lock icon, no rename); order is fixed. Empty optional blocks are
    // hidden from the resume/PDF downstream instead of by the user.
    return (
      <SectionHeader
        section={section}
        onDelete={() => handleDelete(section.id)}
        onToggleVisibility={() => handleToggleVisibility(section.id)}
        canDelete={false}
        visibilityLocked
        onFineTune={onFineTuneSection ? () => onFineTuneSection(section.id) : undefined}
      >
        {renderContent()}
      </SectionHeader>
    );
  };

  // Render custom section forms
  const renderCustomSection = (section: SectionMeta) => {
    const customSection = resumeData.customSections?.[section.key];

    const updateCustomSection = (updates: Partial<CustomSection>) => {
      // Editing a hidden section means the user wants it shown. Merge the
      // visibility flip into the same update (a second onUpdate call would
      // spread the stale closure and overwrite sectionMeta).
      const revealedMeta = !section.isVisible
        ? allSections.map((s) => (s.id === section.id ? { ...s, isVisible: true } : s))
        : undefined;
      onUpdate({
        ...resumeData,
        ...(revealedMeta ? { sectionMeta: revealedMeta } : {}),
        customSections: {
          ...resumeData.customSections,
          [section.key]: {
            ...customSection,
            sectionType: section.sectionType,
            ...updates,
          } as CustomSection,
        },
      });
    };

    const renderContent = () => {
      switch (section.sectionType) {
        case 'text':
          return (
            <GenericTextForm
              value={customSection?.text || ''}
              onChange={(value) => updateCustomSection({ text: value })}
              label={t('builder.customSections.contentLabel')}
              placeholder={t('builder.customSections.contentPlaceholder', {
                name: section.displayName,
              })}
            />
          );

        case 'itemList':
          return (
            <GenericItemForm
              items={customSection?.items || []}
              onChange={(items) => updateCustomSection({ items })}
              itemLabel={t('builder.customSections.entryLabel')}
              addLabel={t('builder.customSections.addEntryLabel')}
            />
          );

        case 'stringList':
          return (
            <GenericListForm
              items={customSection?.strings || []}
              onChange={(strings) => updateCustomSection({ strings })}
              label={t('builder.customSections.itemsLabel')}
              placeholder={t('builder.customSections.itemsPlaceholder')}
            />
          );

        default:
          return (
            <div className="text-steel-grey">
              {t('builder.customSections.unknownSectionType', { type: section.sectionType })}
            </div>
          );
      }
    };

    return (
      <SectionHeader
        section={section}
        onRename={(name) => handleRename(section.id, name)}
        validateName={(name) => validateName(name, section.id)}
        onDelete={() => handleDelete(section.id)}
        onToggleVisibility={() => handleToggleVisibility(section.id)}
        canDelete={true}
        onFineTune={
          onFineTuneSection ? () => onFineTuneSection(customSectionToken(section.key)) : undefined
        }
      >
        {renderContent()}
      </SectionHeader>
    );
  };

  return (
    <div className="space-y-6 pb-20">
      {/* Order lock notice — section order is fixed by the canonical rule */}
      <div className="flex items-center gap-2 border-b border-black pb-2 font-mono text-[10px] uppercase tracking-wider text-steel-grey">
        <Lock className="h-3 w-3" />
        {t('builder.sectionOrder.lockedNotice')}
      </div>

      {sortedAllSections.map((section) => (
        <React.Fragment key={section.id}>
          {section.isDefault ? renderDefaultSection(section) : renderCustomSection(section)}
        </React.Fragment>
      ))}

      {/* Add Section Button */}
      <AddSectionButton onAdd={handleAddSection} existingSections={allSections} />
    </div>
  );
};
