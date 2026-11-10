import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { JobDescriptionTextarea } from '@/components/common/job-description-textarea';
import { MAX_JOB_DESCRIPTION_LENGTH } from '@/lib/constants/limits';

/** Every JD entry point must load its textarea through the shared component. */
const JD_CALL_SITES = [
  'app/(default)/tailor/page.tsx',
  'components/builder/generate-prompt.tsx',
  'components/builder/resume-builder.tsx',
  'components/diagnosis/diagnosis-modal.tsx',
];

/**
 * The shared JD input must enforce the three contracts that were previously
 * copy-pasted (or missing) at the four call sites: backend-mirrored maxLength,
 * Enter stopPropagation for dialog/form safety, and string-based onChange.
 */
describe('JobDescriptionTextarea', () => {
  it('renders the controlled value, placeholder and id', () => {
    render(
      <JobDescriptionTextarea
        id="diagnosis-jd"
        value="Senior Python engineer"
        onValueChange={vi.fn()}
        placeholder="Paste the job description"
      />
    );
    const textarea = screen.getByPlaceholderText('Paste the job description');
    expect(textarea).toHaveValue('Senior Python engineer');
    expect(textarea).toHaveAttribute('id', 'diagnosis-jd');
  });

  it('reports typed input through onValueChange as a string', () => {
    const onValueChange = vi.fn();
    render(<JobDescriptionTextarea value="" onValueChange={onValueChange} />);
    const textarea = screen.getByRole('textbox');

    fireEvent.change(textarea, { target: { value: 'Platform engineer' } });

    expect(onValueChange).toHaveBeenCalledTimes(1);
    expect(onValueChange).toHaveBeenCalledWith('Platform engineer');
  });

  it('hard-caps input at the backend MAX_JOB_CHARACTERS mirror', () => {
    render(<JobDescriptionTextarea value="" onValueChange={vi.fn()} />);
    expect(screen.getByRole('textbox')).toHaveAttribute(
      'maxlength',
      String(MAX_JOB_DESCRIPTION_LENGTH)
    );
    expect(MAX_JOB_DESCRIPTION_LENGTH).toBe(100_000);
  });

  it('stops Enter propagation so dialogs never submit on a newline', () => {
    const parentKeyDown = vi.fn();
    render(
      <div onKeyDown={parentKeyDown}>
        <JobDescriptionTextarea value="" onValueChange={vi.fn()} />
      </div>
    );
    const textarea = screen.getByRole('textbox');

    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(parentKeyDown).not.toHaveBeenCalled();

    // Non-Enter keys must still bubble normally.
    fireEvent.keyDown(textarea, { key: 'a' });
    expect(parentKeyDown).toHaveBeenCalledTimes(1);
  });

  it('still invokes a caller-supplied onKeyDown after the Enter guard', () => {
    const externalKeyDown = vi.fn();
    render(<JobDescriptionTextarea value="" onValueChange={vi.fn()} onKeyDown={externalKeyDown} />);

    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });

    expect(externalKeyDown).toHaveBeenCalledTimes(2);
  });

  it('passes through disabled and layout class names', () => {
    render(
      <JobDescriptionTextarea
        value=""
        onValueChange={vi.fn()}
        disabled
        className="min-h-[300px] resize-none"
      />
    );
    const textarea = screen.getByRole('textbox');
    expect(textarea).toBeDisabled();
    expect(textarea).toHaveClass('min-h-[300px]', 'resize-none', 'font-mono');
  });

  it('is the JD textarea at every known call site', () => {
    const missing: string[] = [];
    for (const relativePath of JD_CALL_SITES) {
      const source = readFileSync(join(process.cwd(), relativePath), 'utf8');
      if (!source.includes("from '@/components/common/job-description-textarea'")) {
        missing.push(relativePath);
      }
    }
    expect(missing).toEqual([]);
  });
});
