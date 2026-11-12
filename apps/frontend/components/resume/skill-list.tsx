import React from 'react';
import { groupSkillEntries, stripPointMarker } from './list-format';
import baseStyles from './styles/_base.module.css';

interface OrderedEntryListProps {
  /** Pre-split, non-blank entries; callers drop blank builder lines. */
  entries: readonly string[];
}

/**
 * Renders skill/cert entries as an ordered numbered list with the same 3ch
 * hanging number column as PointTextList / DescriptionList, so skill numbers
 * line up with the bullet numbers in work entries below. A single entry
 * renders as one plain line (mirrors the DOCX exporter, which only numbers
 * two or more points). Source numbering/bullet markers are stripped because
 * the list renders its own numbers — double numbering ("1. 1、…") is avoided.
 */
export const OrderedEntryList: React.FC<OrderedEntryListProps> = ({ entries }) => {
  if (entries.length === 0) return null;

  if (entries.length === 1) {
    return (
      <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
        <span>{stripPointMarker(entries[0])}</span>
      </div>
    );
  }

  return (
    <ol
      className={`m-0 list-none text-left flex flex-col gap-[0.1875rem] ${baseStyles['resume-text-sm']}`}
    >
      {entries.map((entry, index) => (
        <li key={index} className="flex items-baseline gap-[0.5ch]">
          <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums">
            {index + 1}.
          </span>
          <span className="min-w-0 flex-1">{stripPointMarker(entry)}</span>
        </li>
      ))}
    </ol>
  );
};

interface SkillGroupListProps {
  /** Flat technicalSkills rows; blank rows must already be dropped. */
  entries: readonly string[];
}

/**
 * Technical skills as an ordered list, honoring standalone group heads
 * planned by groupSkillEntries(): a head renders as a bold UNNUMBERED label
 * (the same look as project sub-module labels, reserving the 3ch number
 * gutter) and each group's items number from 1 in their own <ol>. Ungrouped
 * lists (fewer than two qualified heads) fall back to one OrderedEntryList,
 * so ordinary skill lists render as a single 1..n ordered list. No inline
 * "Technical Skills:" label is emitted — the section's own <h3> heading
 * already names the block, and the DOCX exporter follows the same contract.
 */
export const SkillGroupList: React.FC<SkillGroupListProps> = ({ entries }) => {
  const groups = groupSkillEntries(entries);

  if (groups.length === 1 && groups[0].head === null) {
    return <OrderedEntryList entries={groups[0].items} />;
  }

  return (
    <div className={baseStyles['resume-stack']}>
      {groups.map((group, groupIndex) => (
        <React.Fragment key={groupIndex}>
          {group.head && (
            <div
              data-skill-group=""
              className={`flex items-baseline gap-[0.5ch] text-left ${baseStyles['resume-sub-label']} ${baseStyles['resume-text-sm']}`}
            >
              {/* Reserve the same 3ch number gutter as the item rows. */}
              <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums" />
              <span className="min-w-0 flex-1 text-left">{stripPointMarker(group.head)}</span>
            </div>
          )}
          {group.items.length > 0 && <OrderedEntryList entries={group.items} />}
        </React.Fragment>
      ))}
    </div>
  );
};
