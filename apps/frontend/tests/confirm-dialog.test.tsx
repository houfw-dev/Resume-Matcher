import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string) => key,
  }),
}));

describe('ConfirmDialog', () => {
  it('contains long descriptions within a scrollable flex column', () => {
    const description = `Download failed: ${'unbroken-error-token-'.repeat(30)}`;

    render(
      <ConfirmDialog
        open
        onOpenChange={vi.fn()}
        title="Download failed"
        description={description}
        onConfirm={vi.fn()}
      />
    );

    const descriptionElement = screen.getByText(description);
    expect(descriptionElement).toHaveClass(
      'max-h-60',
      'overflow-y-auto',
      'whitespace-pre-wrap',
      '[overflow-wrap:anywhere]'
    );
    expect(descriptionElement.parentElement).toHaveClass('min-w-0', 'flex-1');
  });

  it('renders optional children between the header and the footer', () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={vi.fn()}
        title="Regenerate"
        description="Existing content will be replaced."
        onConfirm={vi.fn()}
      >
        <textarea aria-label="dialog-job-description" defaultValue="Need FastAPI" />
      </ConfirmDialog>
    );

    const dialog = screen.getByRole('dialog');
    const child = screen.getByLabelText('dialog-job-description');
    expect(dialog).toContainElement(child);
    expect(child).toHaveValue('Need FastAPI');
  });
});
