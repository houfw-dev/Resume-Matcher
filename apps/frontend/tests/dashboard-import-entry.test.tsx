import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '@/app/(default)/dashboard/page';

const list = vi.fn();
const get = vi.fn();

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'en' }),
}));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({
    status: { llm_configured: true },
    isLoading: false,
    incrementResumes: vi.fn(),
    decrementResumes: vi.fn(),
    setHasMasterResume: vi.fn(),
  }),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResumeList: (...args: unknown[]) => list(...args),
  fetchResume: (...args: unknown[]) => get(...args),
  deleteResume: vi.fn(),
  retryProcessing: vi.fn(),
  fetchJobDescription: vi.fn().mockResolvedValue(null),
}));
vi.mock('@/components/dashboard/resume-upload-dialog', () => ({ ResumeUploadDialog: () => null }));
vi.mock('@/components/dashboard/master-resume-choice-dialog', () => ({
  MasterResumeChoiceDialog: () => null,
}));
vi.mock('@/components/dashboard/resume-import-workspace', () => ({
  ResumeImportWorkspace: ({
    onClose,
    onResumeMutated,
  }: {
    onClose: () => void;
    onResumeMutated?: () => void;
  }) => (
    <div role="dialog" aria-label="ws-stub" data-testid="resume-import-workspace">
      <button type="button" onClick={onClose}>
        ws-close
      </button>
      <button type="button" onClick={() => onResumeMutated?.()}>
        ws-mutate
      </button>
    </div>
  ),
}));

const row = (id: string, master = false) => ({
  resume_id: id,
  title: id,
  filename: `${id}.pdf`,
  is_master: master,
  processing_status: 'ready',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  parent_id: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  get.mockResolvedValue({
    processed_resume: { personalInfo: { name: 'Ada' } },
    raw_resume: { processing_status: 'ready' },
  });
});

describe('dashboard resume import entry card', () => {
  it('opens the import workspace from the empty-account card and closes back to the dashboard', async () => {
    list.mockResolvedValue([]);
    render(<Dashboard />);

    const card = await screen.findByRole('button', { name: 'importWorkspace.cta' });
    expect(card).toBeInTheDocument();

    fireEvent.click(card);
    expect(await screen.findByTestId('resume-import-workspace')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'ws-close' }));
    await waitFor(() =>
      expect(screen.queryByTestId('resume-import-workspace')).not.toBeInTheDocument()
    );
  });

  it('opens via keyboard and remains available in the master-resume branch', async () => {
    list.mockResolvedValue([row('master', true)]);
    get.mockResolvedValue({
      processed_resume: { personalInfo: { name: 'Ada' } },
      raw_resume: { processing_status: 'ready' },
    });
    render(<Dashboard />);

    // Wait for the master branch to settle (the cta card exists in both
    // branches, so the early no-master instance would otherwise be detached).
    await screen.findByText('dashboard.masterResume');

    const card = screen.getByRole('button', { name: 'importWorkspace.cta' });
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(await screen.findByTestId('resume-import-workspace')).toBeInTheDocument();
  });

  it('localizes processing status on tailored cards instead of the raw enum', async () => {
    list.mockResolvedValue([
      row('master', true),
      { ...row('tailored-failed'), processing_status: 'failed' },
      { ...row('tailored-ready'), processing_status: 'ready' },
    ]);
    render(<Dashboard />);
    await screen.findByText('dashboard.masterResume');

    expect(screen.getByText('dashboard.status.failed')).toBeInTheDocument();
    expect(screen.getByText('dashboard.status.ready')).toBeInTheDocument();
    // Raw backend enum strings must never reach the localized UI.
    expect(screen.queryByText('failed')).not.toBeInTheDocument();
    expect(screen.queryByText('ready')).not.toBeInTheDocument();
  });

  it('groups import and create actions in the footer bar with the tracker link', async () => {
    list.mockResolvedValue([]);
    render(<Dashboard />);

    const importButton = await screen.findByRole('button', { name: 'importWorkspace.cta' });
    const createButton = screen.getByRole('button', { name: 'dashboard.createResume' });
    const trackerLink = screen.getByRole('link', { name: /nav.applicationTracker/ });

    // All three module entries share the SwissGrid footer action group.
    const footerGroup = trackerLink.parentElement;
    expect(footerGroup).not.toBeNull();
    expect(footerGroup).toContainElement(importButton);
    expect(footerGroup).toContainElement(createButton);

    // They are footer buttons, not square grid cards anymore.
    expect(importButton.closest('[class*="aspect-square"]')).toBeNull();
    expect(createButton.closest('[class*="aspect-square"]')).toBeNull();
  });

  it('disables the create action without a ready master resume and enables it with one', async () => {
    list.mockResolvedValue([]);
    const { unmount } = render(<Dashboard />);
    expect(await screen.findByRole('button', { name: 'dashboard.createResume' })).toBeDisabled();
    unmount();

    list.mockResolvedValue([row('master', true)]);
    render(<Dashboard />);
    await screen.findByText('dashboard.masterResume');
    expect(screen.getByRole('button', { name: 'dashboard.createResume' })).toBeEnabled();
  });

  it('refreshes the resume list when the workspace reports a mutation', async () => {
    list.mockResolvedValue([]);
    render(<Dashboard />);
    await screen.findByRole('button', { name: 'importWorkspace.cta' });
    await waitFor(() => expect(list).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'importWorkspace.cta' }));
    await screen.findByTestId('resume-import-workspace');

    const callsBefore = list.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'ws-mutate' }));

    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(callsBefore));
    expect(list).toHaveBeenLastCalledWith(true);
  });
});
