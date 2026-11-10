'use client';

import * as React from 'react';
import { createPortal } from 'react-dom';
import CheckCircle from 'lucide-react/dist/esm/icons/check-circle';
import AlertTriangle from 'lucide-react/dist/esm/icons/alert-triangle';
import AlertCircle from 'lucide-react/dist/esm/icons/alert-circle';
import Info from 'lucide-react/dist/esm/icons/info';
import X from 'lucide-react/dist/esm/icons/x';
import { cn } from '@/lib/utils';
import { useTranslations } from '@/lib/i18n';

/**
 * Swiss International Style toast system.
 *
 * Non-blocking, auto-dismissing feedback for success/info/warning/error
 * acknowledgments. Unlike ConfirmDialog it never moves focus, locks scroll,
 * or renders aria-modal — the user keeps working while the toast is visible.
 * ConfirmDialog stays reserved for decisions (delete/reset/overwrite).
 *
 * Visual contract: 1px black border, hard offset shadow, square corners,
 * brand tokens only.
 */

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

export interface ToastInput {
  description: string;
  title?: string;
  variant?: ToastVariant;
  /** Per-toast override; defaults depend on the variant. */
  durationMs?: number;
}

interface ToastEntry {
  id: number;
  description: string;
  title?: string;
  variant: ToastVariant;
  durationMs: number;
}

interface ToastContextValue {
  toast: (input: ToastInput) => number;
  dismiss: (id: number) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

/** Errors stay longer: failure messages tend to be longer and need reading. */
const DEFAULT_DURATION_MS: Record<ToastVariant, number> = {
  success: 5_000,
  info: 5_000,
  warning: 6_000,
  error: 8_000,
};

/** Oldest toasts leave first so the stack never covers the whole viewport. */
const MAX_VISIBLE_TOASTS = 3;

const VARIANT_ICON: Record<ToastVariant, React.ComponentType<{ className?: string }>> = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

const VARIANT_ICON_CLASS: Record<ToastVariant, string> = {
  success: 'text-success',
  error: 'text-destructive',
  warning: 'text-warning',
  info: 'text-primary',
};

interface ToastCardProps {
  entry: ToastEntry;
  onDismiss: (id: number) => void;
}

function ToastCard({ entry, onDismiss }: ToastCardProps) {
  const { t } = useTranslations();
  const [paused, setPaused] = React.useState(false);

  // Each toast owns its dismissal clock. Hover/focus pauses it so a long
  // error message (or a URL inside it) cannot time out while being read.
  React.useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(() => onDismiss(entry.id), entry.durationMs);
    return () => window.clearTimeout(timer);
  }, [paused, entry.id, entry.durationMs, onDismiss]);

  const Icon = VARIANT_ICON[entry.variant];

  return (
    <div
      // role="alert" gives errors an assertive live announcement; the other
      // variants stay polite via the region's aria-live below.
      role={entry.variant === 'error' ? 'alert' : 'status'}
      aria-atomic="true"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className="pointer-events-auto flex w-full items-start gap-3 border border-black bg-background p-4 shadow-sw-card animate-in fade-in-0 slide-in-from-right-2 duration-200"
    >
      <Icon className={cn('mt-0.5 h-5 w-5 shrink-0', VARIANT_ICON_CLASS[entry.variant])} />
      <div className="min-w-0 flex-1">
        {entry.title && (
          <p className="font-serif text-sm font-bold uppercase tracking-tight text-ink">
            {entry.title}
          </p>
        )}
        <p className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-ink-soft [overflow-wrap:anywhere]">
          {entry.description}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(entry.id)}
        aria-label={t('common.close')}
        className="shrink-0 opacity-70 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslations();
  const [toasts, setToasts] = React.useState<ToastEntry[]>([]);
  const nextId = React.useRef(0);
  // SSR has no document and the server HTML must match the client's FIRST
  // render. A `typeof document` fork would diverge (server omits the portal,
  // hydration render includes it) and throw a hydration error; a mount flag
  // keeps the first client render portal-free and attaches it post-hydration.
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => {
    setMounted(true);
  }, []);

  const dismiss = React.useCallback((id: number) => {
    setToasts((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const toast = React.useCallback((input: ToastInput) => {
    const variant: ToastVariant = input.variant ?? 'info';
    const id = nextId.current++;
    const entry: ToastEntry = {
      id,
      description: input.description,
      title: input.title,
      variant,
      durationMs: input.durationMs ?? DEFAULT_DURATION_MS[variant],
    };
    setToasts((current) => [...current, entry].slice(-MAX_VISIBLE_TOASTS));
    return id;
  }, []);

  const value = React.useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {mounted &&
        createPortal(
          <div
            role="region"
            aria-live="polite"
            aria-label={t('common.notifications')}
            className="pointer-events-none fixed right-4 top-4 z-[60] flex w-full max-w-sm flex-col gap-3"
          >
            {toasts.map((entry) => (
              <ToastCard key={entry.id} entry={entry} onDismiss={dismiss} />
            ))}
          </div>,
          document.body
        )}
    </ToastContext.Provider>
  );
}
