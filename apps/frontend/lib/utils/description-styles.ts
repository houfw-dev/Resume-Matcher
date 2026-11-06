export type DescriptionStyle = 'bullet' | 'plain' | 'label';

export function alignDescriptionStyles(
  descriptions: string[] | undefined,
  styles: (DescriptionStyle | null | undefined)[] | undefined
): DescriptionStyle[] {
  return (descriptions || []).map((_, index) => {
    const style = styles?.[index];
    return style === 'plain' || style === 'label' ? style : 'bullet';
  });
}

/**
 * Cycle one row's presentation: numbered bullet → unnumbered plain body →
 * bold sub-module label → bullet. Plain stays one click away (the common
 * "prose row" toggle); label is the long-press-free third stop. "label" rows
 * restart the bullet numbering of the rows below them
 * (see buildDescriptionBlocks).
 */
export function toggleDescriptionStyle(
  descriptions: string[] | undefined,
  styles: (DescriptionStyle | null | undefined)[] | undefined,
  index: number
): DescriptionStyle[] {
  const alignedStyles = alignDescriptionStyles(descriptions, styles);

  if (index < 0 || index >= alignedStyles.length) {
    return alignedStyles;
  }

  const next: Record<DescriptionStyle, DescriptionStyle> = {
    bullet: 'plain',
    plain: 'label',
    label: 'bullet',
  };
  alignedStyles[index] = next[alignedStyles[index]];
  return alignedStyles;
}
