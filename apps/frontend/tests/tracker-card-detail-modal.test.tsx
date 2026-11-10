import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { CardDetailModal } from '@/components/tracker/card-detail-modal';
import type { ApplicationDetail } from '@/lib/api/tracker';

const getApplicationDetail = vi.fn();
const updateApplication = vi.fn();

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'zh' }),
}));
vi.mock('@/lib/api/tracker', () => ({
  getApplicationDetail: (...args: unknown[]) => getApplicationDetail(...args),
  updateApplication: (...args: unknown[]) => updateApplication(...args),
}));

function detail(): ApplicationDetail {
  return {
    application_id: 'app-1',
    job_id: 'job-1',
    resume_id: 'res-1',
    master_resume_id: null,
    status: 'interview',
    company: 'Acme',
    role: 'Engineer',
    applied_at: '2026-03-05T12:00:00Z',
    notes: null,
    position: 0,
    created_at: '2026-03-05T12:00:00Z',
    updated_at: '2026-03-05T12:00:00Z',
    job_content: null,
    resume: null,
  };
}

describe('CardDetailModal date localization', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getApplicationDetail.mockResolvedValue(detail());
  });

  it('renders the applied date in the active UI locale, not hardcoded en-US', async () => {
    render(
      <CardDetailModal applicationId="app-1" open onOpenChange={vi.fn()} onUpdated={vi.fn()} />
    );

    const dateLine = await screen.findByText(/2026/);
    await waitFor(() => expect(dateLine).toHaveTextContent('3月'));
    expect(dateLine).not.toHaveTextContent('Mar');
    expect(getApplicationDetail).toHaveBeenCalledWith('app-1');
  });
});
