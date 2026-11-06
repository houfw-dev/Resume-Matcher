import React from 'react';
import { cn } from '@/lib/utils';
import { SafeHtml } from './safe-html';
import { stripPointMarker } from './list-format';
import baseStyles from './styles/_base.module.css';

export { stripPointMarker };

/** Split newline-separated text into trimmed, non-empty point strings. */
export function splitPoints(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

interface PointTextListProps {
  /** Newline-separated points (parser keeps one point per source line). */
  text: string;
  /** Optional size class (e.g. baseStyles['resume-text-sm']). */
  textClassName?: string;
}

/**
 * Renders multi-point text (个人优势 / 自我评价) as an ordered numbered list
 * with a hanging number column. A single-line text block renders as one
 * left-aligned paragraph (prose summaries stay prose). Content is never
 * justified.
 */
export const PointTextList: React.FC<PointTextListProps> = ({
  text,
  textClassName = baseStyles['resume-text'],
}) => {
  const points = splitPoints(text);
  if (points.length === 0) return null;

  if (points.length === 1) {
    return <p className={cn('text-left', textClassName)}>{points[0]}</p>;
  }

  return (
    <ol className={cn('m-0 list-none text-left flex flex-col gap-[0.1875rem]', textClassName)}>
      {points.map((point, index) => (
        <li key={index} className="flex items-baseline gap-[0.5ch]">
          <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums">
            {index + 1}.
          </span>
          <span className="min-w-0 flex-1">
            <SafeHtml html={stripPointMarker(point)} />
          </span>
        </li>
      ))}
    </ol>
  );
};

interface OrderedStringListProps {
  /** Pre-split list entries (e.g. a custom stringList section). */
  items?: readonly string[];
  /** Optional size class (e.g. baseStyles['resume-text-sm']). */
  textClassName?: string;
}

/**
 * Renders a custom stringList section as an ordered numbered list — the same
 * number-column design as PointTextList and DescriptionList. A single entry
 * renders as one left-aligned paragraph. Blank entries are dropped.
 */
export const OrderedStringList: React.FC<OrderedStringListProps> = ({
  items,
  textClassName = baseStyles['resume-text-sm'],
}) => {
  const points = (items ?? []).map((item) => item.trim()).filter(Boolean);
  if (points.length === 0) return null;

  if (points.length === 1) {
    return <p className={cn('text-left', textClassName)}>{points[0]}</p>;
  }

  return (
    <ol className={cn('m-0 list-none text-left flex flex-col gap-[0.1875rem]', textClassName)}>
      {points.map((point, index) => (
        <li key={index} className="flex items-baseline gap-[0.5ch]">
          <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums">
            {index + 1}.
          </span>
          <span className="min-w-0 flex-1">{stripPointMarker(point)}</span>
        </li>
      ))}
    </ol>
  );
};
