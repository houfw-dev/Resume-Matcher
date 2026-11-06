import type { ComponentProps } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'en' }),
}));

const overlay = (): Element => {
  const node = document.querySelector('.bg-black\\/50');
  if (!node) throw new Error('dialog overlay not found');
  return node;
};

function renderDialog(
  contentProps: Partial<ComponentProps<typeof DialogContent>> = {}
): ReturnType<typeof vi.fn> {
  const onOpenChange = vi.fn();
  render(
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent {...contentProps}>
        <DialogTitle>dialog-gates-title</DialogTitle>
      </DialogContent>
    </Dialog>
  );
  return onOpenChange;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('DialogContent close gates', () => {
  it('closes via X, Escape and backdrop by default', () => {
    const onOpenChange = renderDialog();

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    fireEvent.click(overlay());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(onOpenChange).toHaveBeenCalledTimes(3);
  });

  it('does not close on Escape when closeOnEscape is false', () => {
    const onOpenChange = renderDialog({ closeOnEscape: false });

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).not.toHaveBeenCalled();

    // Other gates keep working.
    fireEvent.click(overlay());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it('does not close on backdrop click when closeOnBackdrop is false', () => {
    const onOpenChange = renderDialog({ closeOnBackdrop: false });

    fireEvent.click(overlay());
    expect(onOpenChange).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it('omits the close button when showCloseButton is false', () => {
    const onOpenChange = renderDialog({ showCloseButton: false });

    expect(screen.queryByRole('button', { name: 'common.close' })).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    fireEvent.click(overlay());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });
});
