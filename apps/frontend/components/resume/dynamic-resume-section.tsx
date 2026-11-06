import React from 'react';
import type {
  ResumeData,
  SectionMeta,
  CustomSection,
  CustomSectionItem,
} from '@/components/dashboard/resume-component';
import { formatDateRange } from '@/lib/utils';
import { DescriptionList } from './description-list';
import { OrderedStringList, PointTextList } from './point-text-list';
import baseStyles from './styles/_base.module.css';

interface DynamicResumeSectionProps {
  sectionMeta: SectionMeta;
  resumeData: ResumeData;
}

/**
 * DynamicResumeSection Component
 *
 * Renders custom sections in resume templates based on section type.
 * Uses the same CSS classes as built-in sections for consistent styling.
 */
export const DynamicResumeSection: React.FC<DynamicResumeSectionProps> = ({
  sectionMeta,
  resumeData,
}) => {
  // Get the custom section data
  const customSection = resumeData.customSections?.[sectionMeta.key];

  if (!customSection) return null;

  // Check if section has content
  const hasContent = (() => {
    switch (sectionMeta.sectionType) {
      case 'text':
        return Boolean(customSection.text?.trim());
      case 'itemList':
        return Boolean(customSection.items?.length);
      case 'stringList':
        return Boolean(customSection.strings?.length);
      default:
        return false;
    }
  })();

  if (!hasContent) return null;

  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={baseStyles['resume-section-title']}>{sectionMeta.displayName}</h3>
      {renderContent(sectionMeta, customSection)}
    </div>
  );
};

/**
 * Render section content based on type
 */
function renderContent(sectionMeta: SectionMeta, customSection: CustomSection) {
  switch (sectionMeta.sectionType) {
    case 'text':
      // Every custom text block keeps the source line structure: one source
      // line per numbered point, single-line blocks render as a paragraph.
      return <PointTextList text={customSection.text || ''} />;
    case 'itemList':
      return <ItemListSectionContent items={customSection.items || []} />;
    case 'stringList':
      return <StringListSectionContent strings={customSection.strings || []} />;
    default:
      return null;
  }
}

/**
 * Item List Section Content (like Experience)
 */
const ItemListSectionContent: React.FC<{ items: CustomSectionItem[] }> = ({ items }) => {
  if (items.length === 0) return null;

  return (
    <div className={baseStyles['resume-items']}>
      {items.map((item) => (
        <div key={item.id} className={baseStyles['resume-item']}>
          {/* Title and Years Row */}
          <div className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}>
            <h4 className={baseStyles['resume-item-title']}>{item.title}</h4>
            {item.years && (
              <span className={`${baseStyles['resume-meta-sm']} shrink-0 ml-4`}>
                {formatDateRange(item.years)}
              </span>
            )}
          </div>

          {/* Subtitle and Location Row */}
          {(item.subtitle || item.location) && (
            <div
              className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}
            >
              {item.subtitle && <span>{item.subtitle}</span>}
              {item.location && <span>{item.location}</span>}
            </div>
          )}

          {/* Description Points */}
          <DescriptionList items={item.description} styles={item.descriptionStyles} />
        </div>
      ))}
    </div>
  );
};

/**
 * String List Section Content (honors/certificates/hobbies)
 */
const StringListSectionContent: React.FC<{ strings: string[] }> = ({ strings }) => (
  <OrderedStringList items={strings} textClassName={baseStyles['resume-text-sm']} />
);

export default DynamicResumeSection;
