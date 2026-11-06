import React from 'react';
import { cn } from '@/lib/utils';
import { SafeHtml } from './safe-html';
import {
  buildDescriptionBlocks,
  joinInlineBodyRows,
  stripPointMarker,
  type DescriptionRowStyle,
} from './list-format';
import baseStyles from './styles/_base.module.css';

export type DescriptionStyle = DescriptionRowStyle;

interface DescriptionListProps {
  items?: string[];
  styles?: DescriptionStyle[];
  textClassName?: string;
  /**
   * Rename project sub-labels (项目成果/技术亮点/… → 项目亮点，
   * 工作职责/负责内容/… → 项目职责）. Set ONLY at project render sites; work
   * and custom items keep their source labels.
   */
  canonicalizeLabels?: boolean;
  /**
   * Align sub-module labels (项目背景/技术栈/项目职责/项目亮点） with the
   * project NAME edge: no 3ch number gutter on labels, label-owned lists are
   * not indented (numbers start at the label edge), descriptive body rows are
   * flush too. Set ONLY at project render sites.
   */
  flushLabels?: boolean;
}

/**
 * Renders description points with sub-module support:
 *
 * - "label" rows （项目职责 / 负责内容 / 项目亮点 / …) render bold and own the
 *   bullet group that follows them.
 * - Descriptive project labels （项目背景 / 技术栈 / …) render bold and own an
 *   unnumbered BODY block: each content row sits below the label, aligned to
 *   its text edge, with no markers.
 * - Each sub-module's bullets render as their OWN <ol>, so numbering restarts
 *   at 1 for every sub-module, and the group is indented one number gutter so
 *   its markers start at the label's text edge. At project sites
 *   (flushLabels) labels align with the project NAME edge instead, and their
 *   lists/bodies are flush with it.
 * - Loose bullets (no label above them) render as one continuous list.
 * - "plain" rows are unnumbered body text; legacy "plain" headings are
 *   promoted to bold labels by looksLikeSubLabel().
 * - At project sites, unknown bold colon headings inside a duty/highlight
 *   module （项目亮点 > "重大生产环境问题解决：") are nested bold heads. The
 *   head itself is always the level-1 numbered point (1. 2. 3.); its detail
 *   rows stay unnumbered when they are plain paragraphs, and when they are
 *   bullets (e.g. after an explicit "render as an ordered list" reformat)
 *   they indent one extra gutter and number hierarchically (1.1, 1.2 …),
 *   restarting at each head.
 *
 * Blocks are returned as direct-child fragments (no wrapper element) so the
 * print CSS in _base.module.css can bind each label to its list/body
 * (`> *:not(ul):not(ol):has(+ ol)`) and fragment tall entries between rows.
 *
 * This is intentionally the same number-column design as PointTextList and
 * the skills list so on-screen and PDF/export rendering stay identical.
 */
export const DescriptionList: React.FC<DescriptionListProps> = ({
  items,
  styles,
  textClassName = baseStyles['resume-text-sm'],
  canonicalizeLabels = false,
  flushLabels = false,
}) => {
  if (!items || items.length === 0) return null;

  const blocks = buildDescriptionBlocks(items, styles, { canonicalizeLabels });

  return (
    <>
      {blocks.map((block, blockIndex) => {
        if (block.kind === 'label') {
          return (
            <div
              key={`label-${blockIndex}`}
              data-sub-label=""
              {...(block.descriptive ? { 'data-descriptive': '' } : {})}
              className={cn(
                'flex items-baseline gap-[0.5ch] text-left',
                baseStyles['resume-sub-label'],
                textClassName
              )}
            >
              {/* Reserve the same 3ch number gutter as bullet rows so the
                  bold label aligns with ordinary point text. At project
                  render sites (flushLabels) labels align with the project
                  name edge. */}
              {!flushLabels && (
                <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums" />
              )}
              <span className="min-w-0 flex-1 text-left">
                <SafeHtml html={stripPointMarker(block.desc)} />
              </span>
            </div>
          );
        }

        if (block.kind === 'body') {
          return (
            <div
              key={`body-${blockIndex}`}
              data-sub-body=""
              className={cn(
                'm-0 text-left',
                baseStyles['resume-list'],
                baseStyles['resume-sub-body'],
                flushLabels && baseStyles['resume-sub-body-flush'],
                textClassName
              )}
            >
              {block.inline ? (
                // Tech-stack enumeration: merge rows into one wrapping line.
                <div data-body-row="">
                  <SafeHtml
                    html={joinInlineBodyRows(block.rows.map((row) => stripPointMarker(row)))}
                  />
                </div>
              ) : (
                block.rows.map((row, rowIndex) => (
                  <div key={rowIndex} data-body-row="">
                    <SafeHtml html={stripPointMarker(row)} />
                  </div>
                ))
              )}
            </div>
          );
        }

        // Numbering is local to each <ol>, so every sub-module restarts at 1.
        // Bold nested heads own level 1 (1. 2. 3.); their bullet details own
        // level 2 with composite markers (1.1, 1.2 …) that restart per head.
        let level1 = 0;
        let level2 = 0;
        return (
          <ol
            key={`list-${blockIndex}`}
            className={cn(
              'm-0 list-none text-left',
              baseStyles['resume-list'],
              block.indented && !flushLabels && baseStyles['resume-list-indented'],
              textClassName
            )}
          >
            {block.rows.map((row, rowIndex) => {
              const level = row.level ?? 1;
              let marker = '';
              if (level === 2) {
                if (row.numbered) {
                  level2 += 1;
                  marker = `${level1}.${level2}`;
                }
              } else {
                if (row.bold) level2 = 0;
                if (row.numbered) {
                  level1 += 1;
                  marker = `${level1}.`;
                }
              }
              return (
                <li key={rowIndex} className="flex items-baseline gap-[0.5ch] text-left">
                  {/* Level-2 sub-points indent one extra number gutter. */}
                  {level === 2 && (
                    <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums" />
                  )}
                  <span aria-hidden="true" className="w-[3ch] flex-none tabular-nums">
                    {marker}
                  </span>
                  <span
                    className={cn('min-w-0 flex-1 text-left', row.bold && 'font-bold')}
                    data-nested-head={row.bold ? '' : undefined}
                  >
                    <SafeHtml html={stripPointMarker(row.desc)} />
                  </span>
                </li>
              );
            })}
          </ol>
        );
      })}
    </>
  );
};
