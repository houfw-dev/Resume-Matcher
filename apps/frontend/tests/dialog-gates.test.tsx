import { useState } from 'react';
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

/**
 * The full-viewport flex wrapper that sits ABOVE the visual overlay in DOM
 * order. In a real browser this is the element hit-testing returns for an
 * outside click — dispatching on the overlay node directly would bypass the
 * layering bug this suite guards against.
 */
const outsideLayer = (): HTMLElement => {
  const dialog = screen.getByRole('dialog');
  const layer = dialog.parentElement;
  if (!layer) throw new Error('dialog outside layer not found');
  return layer;
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

function DialogHarness({ nested = false }: { nested?: boolean }) {
  const [open, setOpen] = useState(false);
  const [nestedOpen, setNestedOpen] = useState(false);
  return (
    <>
      <button type="button" data-testid="trigger" onClick={() => setOpen(true)}>
        open
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={false}>
          <DialogTitle>outer title</DialogTitle>
          <input aria-label="first-field" />
          <button type="button" data-testid="open-nested" onClick={() => setNestedOpen(true)}>
            open nested
          </button>
          <button type="button" data-testid="last-field">
            last
          </button>
          {nested && (
            <Dialog open={nestedOpen} onOpenChange={setNestedOpen}>
              <DialogContent showCloseButton={false}>
                <DialogTitle>nested title</DialogTitle>
                <button
                  type="button"
                  data-testid="nested-close"
                  onClick={() => setNestedOpen(false)}
                >
                  close nested
                </button>
                <button type="button" data-testid="nested-second">
                  nested second
                </button>
              </DialogContent>
            </Dialog>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

afterEach(() => {
  vi.clearAllMocks();
  document.body.style.overflow = '';
});

describe('DialogContent close gates', () => {
  it('closes via X, Escape and a real outside click by default', () => {
    const onOpenChange = renderDialog();

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).toHaveBeenLastCalledWith(false);

    // Hit-test equivalent: click the topmost full-viewport wrapper, not the
    // overlay node itself. The event bubbles to the outermost fixed layer.
    fireEvent.click(outsideLayer());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(onOpenChange).toHaveBeenCalledTimes(3);
  });

  it('still closes when the click lands on the visual overlay itself', () => {
    const onOpenChange = renderDialog();
    fireEvent.click(overlay());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it('does not close when the click originates inside the dialog', () => {
    const onOpenChange = renderDialog();
    fireEvent.click(screen.getByRole('dialog'));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('does not close on Escape when closeOnEscape is false', () => {
    const onOpenChange = renderDialog({ closeOnEscape: false });

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onOpenChange).not.toHaveBeenCalled();

    // Other gates keep working.
    fireEvent.click(outsideLayer());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it('does not close on backdrop click when closeOnBackdrop is false', () => {
    const onOpenChange = renderDialog({ closeOnBackdrop: false });

    fireEvent.click(outsideLayer());
    expect(onOpenChange).not.toHaveBeenCalled();
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
    fireEvent.click(outsideLayer());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });
});

describe('DialogContent focus management', () => {
  it('moves focus into the dialog on open and restores it on close', () => {
    render(<DialogHarness />);
    const trigger = screen.getByTestId('trigger');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // Real browsers focus a button on click; jsdom's fireEvent does not, so
    // focus explicitly to make the restore contract deterministic.
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByLabelText('first-field')).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('traps Tab at both boundaries inside the dialog', () => {
    render(<DialogHarness />);
    fireEvent.click(screen.getByTestId('trigger'));
    const first = screen.getByLabelText('first-field');
    const last = screen.getByTestId('last-field');
    expect(first).toHaveFocus();

    // jsdom performs no native Tab navigation, so exercise the boundary wrap
    // logic directly: Tab on the last element jumps back to the first ...
    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(first).toHaveFocus();

    // ... and Shift+Tab on the first wraps to the last.
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();
  });

  it('pulls focus back into the dialog when it has escaped outside', () => {
    render(<DialogHarness />);
    fireEvent.click(screen.getByTestId('trigger'));
    const first = screen.getByLabelText('first-field');

    screen.getByTestId('trigger').focus();
    expect(first).not.toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(first).toHaveFocus();
  });

  it('lets only the topmost nested dialog trap Tab', () => {
    const focusSpy = vi.spyOn(HTMLElement.prototype, 'focus');
    render(<DialogHarness nested />);
    fireEvent.click(screen.getByTestId('trigger'));
    fireEvent.click(screen.getByTestId('open-nested'));
    const nestedClose = screen.getByTestId('nested-close');
    expect(nestedClose).toHaveFocus();
    focusSpy.mockClear();

    // A plain Tab inside the nested dialog must not be hijacked by the outer
    // trap. End-state focus alone cannot prove this (the inner trap would win
    // the fight back), so assert the outer trap never programmatically touched
    // any of its own elements.
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(nestedClose).toHaveFocus();
    const outerElements = [
      screen.getByLabelText('first-field'),
      screen.getByTestId('open-nested'),
      screen.getByTestId('last-field'),
    ];
    const hijacked = focusSpy.mock.instances.filter((el) =>
      outerElements.includes(el as HTMLElement)
    );
    expect(hijacked).toHaveLength(0);
    focusSpy.mockRestore();
  });
});

describe('DialogContent scroll lock', () => {
  it('locks body scroll while open and releases it on close', () => {
    render(<DialogHarness />);
    expect(document.body.style.overflow).toBe('');

    fireEvent.click(screen.getByTestId('trigger'));
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.body.style.overflow).toBe('');
  });

  it('keeps the lock while a nested dialog is open and releases only at the end', () => {
    render(<DialogHarness nested />);
    fireEvent.click(screen.getByTestId('trigger'));
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.click(screen.getByTestId('open-nested'));
    const nestedDialog = screen.getByText('nested title').closest('[role="dialog"]');
    expect(nestedDialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');

    // Closing the inner dialog must not unlock the outer dialog's background.
    fireEvent.click(screen.getByTestId('nested-close'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.body.style.overflow).toBe('');
  });
});
