import React, { useMemo } from 'react';
import {
  ResumeSingleColumn,
  ResumeTwoColumn,
  ResumeModern,
  ResumeModernTwoColumn,
  ResumeLatex,
  ResumeClean,
  ResumeVivid,
} from '@/components/resume';
import { dedupeResumeLists, stripMarkdownEmphasisDeep } from '@/lib/utils/markdown-strip';
import { canonicalizeTechTerms } from '@/lib/utils/tech-terms';
import { normalizeTextHygiene } from '@/lib/utils/text-hygiene';
import {
  type TemplateSettings,
  type TemplateType,
  DEFAULT_TEMPLATE_SETTINGS,
  settingsToCssVars,
} from '@/lib/types/template-settings';
import type { PersonalInfoLabels } from '@/lib/utils/resume-headings';
import baseStyles from '@/components/resume/styles/_base.module.css';

export interface PersonalInfo {
  name?: string;
  title?: string;
  email?: string;
  phone?: string;
  location?: string;
  // Header demographics, copied verbatim from the uploaded source
  // (gender 性别, age 年龄, workYears 工作年限, educationLevel 最高学历).
  gender?: string;
  age?: string;
  workYears?: string;
  educationLevel?: string;
  website?: string;
  linkedin?: string;
  github?: string;
}

export interface Experience {
  id: number;
  title?: string;
  company?: string;
  department?: string;
  location?: string;
  years?: string;
  description?: string[];
  descriptionStyles?: ('bullet' | 'plain' | 'label')[];
}

export interface Education {
  id: number;
  institution?: string;
  degree?: string;
  years?: string;
  description?: string;
}

export interface Project {
  id: number;
  name?: string;
  role?: string;
  years?: string;
  /** 项目规模 / 团队规模, promoted from inline source rows by the parser. */
  scale?: string;
  github?: string;
  website?: string;
  description?: string[];
  descriptionStyles?: ('bullet' | 'plain' | 'label')[];
}

export interface AdditionalInfo {
  technicalSkills?: string[];
  languages?: string[];
  certificationsTraining?: string[];
  awards?: string[];
}

export interface AdditionalSectionLabels {
  technicalSkills: string;
  languages: string;
  certifications: string;
  awards: string;
}

export interface ResumeSectionHeadings {
  summary: string;
  experience: string;
  education: string;
  projects: string;
  certifications: string;
  skills: string;
  languages: string;
  awards: string;
  links: string;
}

export interface ResumeFallbackLabels {
  name: string;
}

// Section Type for dynamic sections
export type SectionType = 'personalInfo' | 'text' | 'itemList' | 'stringList';

// Section Metadata for dynamic section management
export interface SectionMeta {
  id: string; // Unique identifier (e.g., "summary", "custom_1")
  key: string; // Data key (matches ResumeData field or customSections key)
  displayName: string; // User-visible name
  sectionType: SectionType; // Type of section
  isDefault: boolean; // True for built-in sections
  isVisible: boolean; // Whether to show in resume
  order: number; // Display order (0 = first after personalInfo)
}

// Generic item for custom item-based sections
export interface CustomSectionItem {
  id: number;
  title?: string; // Primary title
  subtitle?: string; // Secondary info (company, institution, etc.)
  location?: string;
  years?: string;
  description?: string[];
  descriptionStyles?: ('bullet' | 'plain' | 'label')[];
}

// Custom section data container
export interface CustomSection {
  sectionType: SectionType;
  items?: CustomSectionItem[]; // For itemList type
  strings?: string[]; // For stringList type
  text?: string; // For text type
}

export interface ResumeData {
  personalInfo?: PersonalInfo;
  summary?: string;
  workExperience?: Experience[];
  education?: Education[];
  personalProjects?: Project[];
  additional?: AdditionalInfo;
  // NEW: Section metadata and custom sections
  sectionMeta?: SectionMeta[];
  customSections?: Record<string, CustomSection>;
}

interface ResumeProps {
  resumeData: ResumeData;
  template?: TemplateType;
  settings?: TemplateSettings;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
  personalInfoLabels?: Partial<PersonalInfoLabels>;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
  fallbackLabels?: Partial<ResumeFallbackLabels>;
  /**
   * Content locale ("zh" | "ja" | "ko" | ...). Orders the CJK font fallback
   * stack so a shared codepoint resolves to the right regional face.
   */
  locale?: string;
}

/**
 * Resume Component
 *
 * Main wrapper component that delegates rendering to template-specific components.
 * Applies CSS custom properties from settings for consistent styling.
 *
 * Templates:
 * - swiss-single: Traditional single-column layout (default)
 * - swiss-two-column: Two-column layout with experience sidebar
 * - modern: Single-column with user-selectable accent colors
 * - modern-two-column: Two-column layout with modern colorful accents
 */
const Resume: React.FC<ResumeProps> = ({
  resumeData,
  template = 'swiss-single',
  settings,
  additionalSectionLabels,
  personalInfoLabels,
  sectionHeadings,
  fallbackLabels,
  locale,
}) => {
  // Merge provided settings with defaults
  const mergedSettings: TemplateSettings = {
    ...DEFAULT_TEMPLATE_SETTINGS,
    ...settings,
    margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...settings?.margins },
    spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...settings?.spacing },
    fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...settings?.fontSize },
  };

  // If template is provided as prop but not in settings, use the prop
  if (template && !settings?.template) {
    mergedSettings.template = template;
  }

  // Convert settings to CSS variables
  const cssVars = settingsToCssVars(mergedSettings, locale);

  // Display-only repair, in the same order as the backend read-time heal
  // chain: canonical tech-term casing, then presentation hygiene (trim,
  // blank rows/styles lockstep, unified list endings), then strip leaked
  // Markdown emphasis modifiers (LLM output, old stored rows) and collapse
  // entries that become duplicates once the markers are gone (e.g.
  // "英语四级" / "英语四级**"). Keeps screen, PDF (this component renders the
  // print page too) and DOCX in agreement. The original prop is untouched —
  // builder forms stay raw.
  const displayData = useMemo(
    () =>
      dedupeResumeLists(
        stripMarkdownEmphasisDeep(normalizeTextHygiene(canonicalizeTechTerms(resumeData)))
      ),
    [resumeData]
  );

  return (
    <div
      className={`${baseStyles['resume-body']} bg-white text-black w-full mx-auto resume-template-${mergedSettings.template}`}
      style={cssVars}
    >
      {mergedSettings.template === 'swiss-single' && (
        <ResumeSingleColumn
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={additionalSectionLabels}
          personalInfoLabels={personalInfoLabels}
          sectionHeadings={sectionHeadings}
        />
      )}
      {mergedSettings.template === 'swiss-two-column' && (
        <ResumeTwoColumn
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          sectionHeadings={sectionHeadings}
        />
      )}
      {mergedSettings.template === 'modern' && (
        <ResumeModern
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={additionalSectionLabels}
          sectionHeadings={sectionHeadings}
        />
      )}
      {mergedSettings.template === 'modern-two-column' && (
        <ResumeModernTwoColumn
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          sectionHeadings={sectionHeadings}
          fallbackLabels={fallbackLabels}
        />
      )}
      {mergedSettings.template === 'latex' && (
        <ResumeLatex
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={additionalSectionLabels}
          sectionHeadings={sectionHeadings}
        />
      )}
      {mergedSettings.template === 'clean' && (
        <ResumeClean
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={additionalSectionLabels}
          sectionHeadings={sectionHeadings}
        />
      )}
      {mergedSettings.template === 'vivid' && (
        <ResumeVivid
          data={displayData}
          showContactIcons={mergedSettings.showContactIcons}
          sectionHeadings={sectionHeadings}
          fallbackLabels={fallbackLabels}
        />
      )}
    </div>
  );
};

export default Resume;
