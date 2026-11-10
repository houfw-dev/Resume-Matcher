'use client';

import * as React from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTranslations } from '@/lib/i18n';

/**
 * Swiss International Style Dialog Component
 *
 * Native implementation without external dependencies.
 * - Square corners (rounded-none) - Brutalist aesthetic
 * - Black borders and hard shadows
 * - Canvas background (#F0F0E8)
 * - WCAG 2.2 AA: role="dialog", aria-modal, aria-labelledby wired to title
 */

interface DialogContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  titleId: string;
}

const DialogContext = React.createContext<DialogContextValue | null>(null);

const useDialogContext = () => {
  const context = React.useContext(DialogContext);
  if (!context) {
    throw new Error('Dialog components must be used within a Dialog');
  }
  return context;
};

/**
 * Reference-counted body scroll lock. Nested dialogs each take a lock; the
 * page only scrolls again once the LAST one unmounts, so closing an inner
 * ConfirmDialog never unlocks the background while its parent stays open.
 */
let bodyScrollLockCount = 0;

export function useBodyScrollLock(active: boolean): void {
  React.useEffect(() => {
    if (!active) return;
    bodyScrollLockCount += 1;
    document.body.style.overflow = 'hidden';
    return () => {
      bodyScrollLockCount = Math.max(0, bodyScrollLockCount - 1);
      if (bodyScrollLockCount === 0) {
        document.body.style.overflow = '';
      }
    };
  }, [active]);
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Modal focus management: moves focus into the container on open, cycles Tab
 * / Shift+Tab within it, and restores focus to the previously focused element
 * on close. Required for aria-modal to mean anything to keyboard and screen
 * reader users.
 */
export function useFocusTrap(
  active: boolean,
  containerRef: React.RefObject<HTMLElement | null>
): void {
  React.useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    if (!container) return;

    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const getFocusable = (): HTMLElement[] =>
      Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));

    // Initial focus: first interactive element, or the dialog itself when it
    // has none (e.g. a pure informational modal).
    (getFocusable()[0] ?? container).focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      // Nested dialogs each register a document-level trap; only the topmost
      // one (last in portal DOM order) may redirect focus, otherwise the
      // outer dialog would fight the inner one for every Tab press.
      const openDialogs = document.querySelectorAll('[aria-modal="true"]');
      const topmost = openDialogs[openDialogs.length - 1];
      if (topmost && topmost !== container) return;
      const focusable = getFocusable();
      if (focusable.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!container.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [active, containerRef]);
}

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

const Dialog: React.FC<DialogProps> = ({ open, onOpenChange, children }) => {
  // Stable id per dialog instance for aria-labelledby wiring to DialogTitle.
  const titleId = React.useId();
  return (
    <DialogContext.Provider value={{ open, onOpenChange, titleId }}>
      {children}
    </DialogContext.Provider>
  );
};

interface DialogTriggerProps {
  asChild?: boolean;
  children: React.ReactNode;
}

const DialogTrigger: React.FC<DialogTriggerProps> = ({ asChild, children }) => {
  const { onOpenChange } = useDialogContext();

  if (asChild && React.isValidElement(children)) {
    const childProps = (children as React.ReactElement<{ onClick?: () => void }>).props;
    const originalOnClick = childProps.onClick;
    return React.cloneElement(children as React.ReactElement<{ onClick?: () => void }>, {
      onClick: () => {
        originalOnClick?.();
        onOpenChange(true);
      },
    });
  }

  return <button onClick={() => onOpenChange(true)}>{children}</button>;
};

interface DialogCloseProps {
  asChild?: boolean;
  children: React.ReactNode;
  className?: string;
}

const DialogClose: React.FC<DialogCloseProps> = ({ asChild, children, className }) => {
  const { onOpenChange } = useDialogContext();

  if (asChild && React.isValidElement(children)) {
    const childProps = (children as React.ReactElement<{ onClick?: () => void }>).props;
    const originalOnClick = childProps.onClick;
    return React.cloneElement(children as React.ReactElement<{ onClick?: () => void }>, {
      onClick: () => {
        originalOnClick?.();
        onOpenChange(false);
      },
    });
  }

  return (
    <button onClick={() => onOpenChange(false)} className={className}>
      {children}
    </button>
  );
};

interface DialogContentProps {
  children: React.ReactNode;
  className?: string;
  /** Allow closing with the Escape key (default true). */
  closeOnEscape?: boolean;
  /** Allow closing by clicking the backdrop overlay (default true). */
  closeOnBackdrop?: boolean;
  /** Render the top-right close button (default true). */
  showCloseButton?: boolean;
}

const DialogContent: React.FC<DialogContentProps> = ({
  children,
  className,
  closeOnEscape = true,
  closeOnBackdrop = true,
  showCloseButton = true,
}) => {
  const { open, onOpenChange, titleId } = useDialogContext();
  const { t } = useTranslations();
  const contentRef = React.useRef<HTMLDivElement>(null);

  // Handle escape key
  React.useEffect(() => {
    if (!closeOnEscape) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onOpenChange(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open, onOpenChange, closeOnEscape]);

  // Nested-dialog-safe scroll lock and keyboard focus containment.
  useBodyScrollLock(open);
  useFocusTrap(open, contentRef);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    // The close handler lives on the outermost fixed layer: the flex wrapper
    // below covers the whole viewport and sits above the visual overlay, so a
    // handler on the overlay alone would never receive real outside clicks.
    <div
      className="fixed inset-0 z-50"
      onClick={closeOnBackdrop ? () => onOpenChange(false) : undefined}
    >
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/50 animate-in fade-in-0" />
      {/* Content */}
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <div
          ref={contentRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          className={cn(
            'relative w-full max-w-lg outline-none',
            'border border-black bg-background shadow-sw-lg',
            'rounded-none',
            'animate-in fade-in-0 zoom-in-95 duration-200',
            className
          )}
          // Clicks inside the dialog must not bubble to the backdrop handler.
          onClick={(e) => e.stopPropagation()}
        >
          {children}
          {showCloseButton && (
            <button
              onClick={() => onOpenChange(false)}
              className="absolute right-4 top-4 opacity-70 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
            >
              <X className="h-5 w-5" />
              <span className="sr-only">{t('common.close')}</span>
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};

interface DialogHeaderProps {
  children: React.ReactNode;
  className?: string;
}

const DialogHeader: React.FC<DialogHeaderProps> = ({ className, children, ...props }) => (
  <div className={cn('flex flex-col space-y-1.5 text-center sm:text-left', className)} {...props}>
    {children}
  </div>
);

interface DialogFooterProps {
  children: React.ReactNode;
  className?: string;
}

const DialogFooter: React.FC<DialogFooterProps> = ({ className, children, ...props }) => (
  <div
    className={cn('flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2', className)}
    {...props}
  >
    {children}
  </div>
);

interface DialogTitleProps {
  children: React.ReactNode;
  className?: string;
}

const DialogTitle: React.FC<DialogTitleProps> = ({ className, children, ...props }) => {
  const { titleId } = useDialogContext();
  return (
    <h2
      id={titleId}
      className={cn('font-serif text-lg font-bold leading-none tracking-tight', className)}
      {...props}
    >
      {children}
    </h2>
  );
};

interface DialogDescriptionProps {
  children: React.ReactNode;
  className?: string;
}

const DialogDescription: React.FC<DialogDescriptionProps> = ({ className, children, ...props }) => (
  <p className={cn('text-sm text-ink-soft', className)} {...props}>
    {children}
  </p>
);

export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
};
