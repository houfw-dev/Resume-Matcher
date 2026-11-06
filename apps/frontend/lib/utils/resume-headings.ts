import type { ResumeSectionHeadings } from '@/components/dashboard/resume-component';
import type { TranslationFunction } from './section-helpers';

/**
 * Localized label props shared by every `<Resume>` render (viewer page,
 * diagnosis workspace). Centralized so all consumers pass exactly the same
 * localized section headings as the resume viewer.
 */
export interface PersonalInfoLabels {
  gender: string;
  age: string;
  educationLevel: string;
  workYears: string;
  jobIntention: string;
  desiredCity: string;
  phone: string;
  email: string;
  foreignLanguage: string;
}

export interface ResumeHeadingProps {
  personalInfoLabels: PersonalInfoLabels;
  additionalSectionLabels: {
    technicalSkills: string;
    languages: string;
    certifications: string;
    awards: string;
  };
  sectionHeadings: {
    summary: string;
    experience: string;
    education: string;
    projects: string;
    certifications: string;
    skills: string;
    languages: string;
    awards: string;
    links: string;
  };
  fallbackLabels: { name: string };
}

export function buildResumeHeadingProps(t: TranslationFunction): ResumeHeadingProps {
  return {
    personalInfoLabels: {
      gender: t('resume.personalInfo.gender'),
      age: t('resume.personalInfo.age'),
      educationLevel: t('resume.personalInfo.educationLevel'),
      workYears: t('resume.personalInfo.workYears'),
      jobIntention: t('resume.personalInfo.jobIntention'),
      desiredCity: t('resume.personalInfo.desiredCity'),
      phone: t('resume.personalInfo.phone'),
      email: t('resume.personalInfo.email'),
      foreignLanguage: t('resume.personalInfo.foreignLanguage'),
    },
    additionalSectionLabels: {
      technicalSkills: t('resume.additionalLabels.technicalSkills'),
      languages: t('resume.additionalLabels.languages'),
      certifications: t('resume.additionalLabels.certifications'),
      awards: t('resume.additionalLabels.awards'),
    },
    sectionHeadings: {
      summary: t('resume.sections.summary'),
      experience: t('resume.sections.experience'),
      education: t('resume.sections.education'),
      projects: t('resume.sections.projects'),
      certifications: t('resume.sections.certifications'),
      skills: t('resume.sections.skillsOnly'),
      languages: t('resume.sections.languages'),
      awards: t('resume.sections.awards'),
      links: t('resume.sections.links'),
    },
    fallbackLabels: { name: t('resume.defaults.name') },
  };
}

export type LateAdditionalModuleKind = 'certifications' | 'awards';

const LATE_MODULE_FALLBACK_TITLES: Record<LateAdditionalModuleKind, string> = {
  certifications: 'Training & Certifications',
  awards: 'Awards',
};

/**
 * Resolve the independent late-module title (培训与证书 / 荣誉奖项): the
 * localized section heading wins, then the inline label with any trailing
 * colon trimmed, then the English constant. Shared by every template so the
 * four previous copy-pasted resolutions cannot drift.
 */
export function resolveAdditionalModuleTitle(
  kind: LateAdditionalModuleKind,
  headings?: Partial<ResumeSectionHeadings>,
  label?: string
): string {
  const fromLabel = label?.trim().replace(/[：:]\s*$/, '') ?? '';
  return headings?.[kind] || fromLabel || LATE_MODULE_FALLBACK_TITLES[kind];
}
