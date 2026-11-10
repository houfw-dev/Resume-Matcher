'use client';

import * as React from 'react';

import { Textarea } from '@/components/ui/textarea';
import { MAX_JOB_DESCRIPTION_LENGTH } from '@/lib/constants/limits';
import { cn } from '@/lib/utils';

export type JobDescriptionTextareaProps = Omit<
  React.TextareaHTMLAttributes<HTMLTextAreaElement>,
  'onChange' | 'defaultValue'
> & {
  value: string;
  onValueChange: (value: string) => void;
};

/**
 * Shared job-description input used by every JD entry point (tailor,
 * generation prompt, standalone regeneration, diagnosis). Centralizes three
 * rules that were previously copy-pasted (or missing) at each call site:
 *
 *  1. Hard `maxLength` mirroring the backend `MAX_JOB_CHARACTERS` bound, so
 *     oversized input is rejected in the UI instead of failing server-side.
 *  2. Enter `stopPropagation` — dialogs/forms must not submit while the user
 *     types a newline into the JD (the project-wide textarea contract).
 *  3. Swiss mono typography baseline; layout classes (min-height, resize)
 *     stay per call site via `className` (merged with tailwind-merge).
 */
export function JobDescriptionTextarea({
  value,
  onValueChange,
  onKeyDown,
  maxLength = MAX_JOB_DESCRIPTION_LENGTH,
  className,
  ...rest
}: JobDescriptionTextareaProps) {
  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter') event.stopPropagation();
    onKeyDown?.(event);
  };

  return (
    <Textarea
      value={value}
      maxLength={maxLength}
      onChange={(event) => onValueChange(event.target.value)}
      onKeyDown={handleKeyDown}
      className={cn('font-mono text-sm leading-relaxed', className)}
      {...rest}
    />
  );
}
