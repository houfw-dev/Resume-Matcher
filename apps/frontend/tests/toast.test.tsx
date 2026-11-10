import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { ToastProvider, useToast, type ToastInput } from '@/components/ui/toast';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

function Harness({ toasts }: { toasts: ToastInput[] }) {
  const { toast } = useToast();
  return (
    <button type="button" onClick={() => toasts.forEach((input) => toast(input))}>
      emit
    </button>
  );
}

function renderWithProvider(toasts: ToastInput[]) {
  return render(
    <ToastProvider>
      <Harness toasts={toasts} />
    </ToastProvider>
  );
}

// Timer-driven setState must flush inside act, matching the codebase's
// fake-timer convention (see use-file-upload.test.tsx).
async function tick(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('ToastProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the title and description of an emitted toast', () => {
    renderWithProvider([{ title: 'Saved', description: 'Cover letter saved', variant: 'success' }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.getByText('Cover letter saved')).toBeInTheDocument();
  });

  it('exposes errors as role=alert and other variants as role=status', () => {
    renderWithProvider([
      { description: 'boom', variant: 'error' },
      { description: 'done', variant: 'success' },
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    expect(screen.getByRole('alert')).toHaveTextContent('boom');
    expect(screen.getByRole('status')).toHaveTextContent('done');
  });

  it('announces the stack through a polite localized live region', () => {
    renderWithProvider([{ description: 'ping' }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    const region = screen.getByRole('region', { name: 'common.notifications' });
    expect(region).toHaveAttribute('aria-live', 'polite');
  });

  it('auto-dismisses a success toast after its 5s default duration', async () => {
    renderWithProvider([{ description: 'ephemeral', variant: 'success' }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    await tick(4_999);
    expect(screen.getByText('ephemeral')).toBeInTheDocument();
    await tick(1);
    expect(screen.queryByText('ephemeral')).toBeNull();
  });

  it('keeps error toasts for 8s so longer failure messages stay readable', async () => {
    renderWithProvider([{ description: 'failure detail', variant: 'error' }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    await tick(7_999);
    expect(screen.getByText('failure detail')).toBeInTheDocument();
    await tick(1);
    expect(screen.queryByText('failure detail')).toBeNull();
  });

  it('respects a custom durationMs override', async () => {
    renderWithProvider([{ description: 'short', durationMs: 500 }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    await tick(499);
    expect(screen.getByText('short')).toBeInTheDocument();
    await tick(1);
    expect(screen.queryByText('short')).toBeNull();
  });

  it('dismisses immediately when the close button is activated', () => {
    renderWithProvider([{ description: 'closable' }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    fireEvent.click(screen.getByRole('button', { name: 'common.close' }));
    expect(screen.queryByText('closable')).toBeNull();
  });

  it('caps the visible stack at three and evicts the oldest toast', () => {
    renderWithProvider([
      { description: 'one' },
      { description: 'two' },
      { description: 'three' },
      { description: 'four' },
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));

    expect(screen.queryByText('one')).toBeNull();
    expect(screen.getByText('two')).toBeInTheDocument();
    expect(screen.getByText('three')).toBeInTheDocument();
    expect(screen.getByText('four')).toBeInTheDocument();
  });

  it('pauses the dismissal clock while hovered and resumes on leave', async () => {
    renderWithProvider([{ description: 'hovered', variant: 'success' }]);
    fireEvent.click(screen.getByRole('button', { name: 'emit' }));
    const toast = screen.getByText('hovered').closest('div[role="status"]')!;

    fireEvent.mouseEnter(toast);
    await tick(10_000);
    expect(screen.getByText('hovered')).toBeInTheDocument();

    fireEvent.mouseLeave(toast);
    await tick(4_999);
    expect(screen.getByText('hovered')).toBeInTheDocument();
    await tick(1);
    expect(screen.queryByText('hovered')).toBeNull();
  });

  it('never steals focus or locks body scroll (non-blocking contract)', () => {
    renderWithProvider([{ description: 'no focus trap' }]);
    const trigger = screen.getByRole('button', { name: 'emit' });
    trigger.focus();

    fireEvent.click(trigger);

    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe('');
    expect(document.querySelector('[aria-modal="true"]')).toBeNull();
  });

  it('omits the portal region from server markup so hydration matches', () => {
    // Regression: a `typeof document !== 'undefined'` fork renders the portal
    // on the client's first render but never on the server, producing a
    // hydration mismatch (Next.js recoverable error). The mount-gated portal
    // keeps the SSR string and the first client render identical; the region
    // only appears after the mount effect (covered by the region test above).
    const html = renderToStaticMarkup(
      <ToastProvider>
        <span>app-shell</span>
      </ToastProvider>
    );
    expect(html).toContain('app-shell');
    expect(html).not.toContain('role="region"');
  });

  it('throws when useToast is called outside a provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Harness toasts={[{ description: 'orphan' }]} />)).toThrow(
      'useToast must be used within a ToastProvider'
    );
    spy.mockRestore();
  });
});

describe('resume-builder notification migration', () => {
  const builderSource = readFileSync(
    join(process.cwd(), 'components/builder/resume-builder.tsx'),
    'utf8'
  );
  const interviewViewSource = readFileSync(
    join(process.cwd(), 'components/builder/interview-prep-view.tsx'),
    'utf8'
  );

  it('routes acknowledgments through the toast system, not a blocking dialog state', () => {
    expect(builderSource).toContain("from '@/components/ui/toast'");
    expect(builderSource).toContain('useToast()');
    expect(builderSource).not.toContain('notificationDialog');
    expect(builderSource).not.toContain('setNotificationDialog');
  });

  it('reports interview-prep failures exactly once (inline bar, no duplicate toast)', () => {
    const occurrences = builderSource.match(/interviewPrepGenerateFailed/g) ?? [];
    expect(occurrences).toHaveLength(1);
    // The inline error surface in the view must remain in place.
    expect(interviewViewSource).toMatch(/\{error &&/);
  });
});
