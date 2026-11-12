import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import React from 'react';
import type { ResumeData } from '@/components/dashboard/resume-component';
import { DEFAULT_TEMPLATE_SETTINGS, type TemplateSettings } from '@/lib/types/template-settings';
import {
  TEMPLATE_SETTINGS_STORAGE_KEY,
  getResumeTemplateSettingsStorageKey,
  storeTemplateSettings,
} from '@/lib/utils/template-settings-storage';

const fetchResume = vi.fn();
const updateResume = vi.fn();

let currentSearch = 'id=res-1';
let improvedData: { data: { resume_id: string; resume_preview: ResumeData } } | null = null;

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(currentSearch),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/api/resume', () => ({
  fetchResume: (...args: unknown[]) => fetchResume(...args),
  updateResume: (...args: unknown[]) => updateResume(...args),
  downloadResumePdf: vi.fn(),
  downloadCoverLetterPdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => ''),
  getCoverLetterPdfUrl: vi.fn(() => ''),
  updateCoverLetter: vi.fn(),
  updateOutreachMessage: vi.fn(),
  generateCoverLetter: vi.fn(),
  generateOutreachMessage: vi.fn(),
  generateInterviewPrep: vi.fn(),
  fetchJobDescription: vi.fn(() => Promise.resolve(null)),
}));

vi.mock('@/lib/i18n', () => {
  const t = (key: string) => key;
  return { useTranslations: () => ({ t }) };
});

vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ incrementResumes: vi.fn(), setHasMasterResume: vi.fn() }),
}));

vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en', contentLanguage: 'en' }),
}));

vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ improvedData }),
}));

vi.mock('@/components/preview', () => ({ PaginatedPreview: () => null }));
vi.mock('@/components/builder/resume-form', () => ({
  ResumeForm: ({ resumeData }: { resumeData: ResumeData }) => (
    <output data-testid="name">{resumeData.personalInfo?.name}</output>
  ),
}));
// Interactive stand-in: surfaces the active template and drives the same
// onChange contract the real FormattingControls uses.
vi.mock('@/components/builder/formatting-controls', () => ({
  FormattingControls: ({
    settings,
    onChange,
  }: {
    settings: TemplateSettings;
    onChange: (settings: TemplateSettings) => void;
  }) => (
    <div>
      <output data-testid="active-template">{settings.template}</output>
      <button data-testid="pick-vivid" onClick={() => onChange({ ...settings, template: 'vivid' })}>
        vivid
      </button>
    </div>
  ),
}));
vi.mock('@/components/builder/cover-letter-editor', () => ({ CoverLetterEditor: () => null }));
vi.mock('@/components/builder/outreach-editor', () => ({ OutreachEditor: () => null }));
vi.mock('@/components/builder/cover-letter-preview', () => ({ CoverLetterPreview: () => null }));
vi.mock('@/components/builder/outreach-preview', () => ({ OutreachPreview: () => null }));
vi.mock('@/components/builder/generate-prompt', () => ({ GeneratePrompt: () => null }));
vi.mock('@/components/builder/interview-prep-view', () => ({ InterviewPrepView: () => null }));
vi.mock('@/components/builder/jd-comparison-view', () => ({ JDComparisonView: () => null }));
vi.mock('@/components/builder/regenerate-wizard', () => ({ RegenerateWizard: () => null }));
vi.mock('@/hooks/use-regenerate-wizard', () => ({
  useRegenerateWizard: () => ({ step: 'idle', reset: vi.fn() }),
}));

const REAL_RESUME = {
  personalInfo: { name: 'Ada Lovelace', email: 'ada@example.com' },
  summary: 'Real summary from the server',
  workExperience: [],
  education: [],
  personalProjects: [],
  additional: {},
};

const importBuilder = async () => {
  const [{ ResumeBuilder }, { ToastProvider }] = await Promise.all([
    import('@/components/builder/resume-builder'),
    import('@/components/ui/toast'),
  ]);
  return function BuilderWithToast() {
    return (
      <ToastProvider>
        <ResumeBuilder />
      </ToastProvider>
    );
  };
};

const tick = async (ms = 0) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

const storedTemplate = (resumeId: string): string =>
  (
    JSON.parse(
      localStorage.getItem(getResumeTemplateSettingsStorageKey(resumeId))!
    ) as TemplateSettings
  ).template;

beforeEach(() => {
  currentSearch = 'id=res-1';
  improvedData = null;
  vi.useFakeTimers();
  localStorage.clear();
  fetchResume.mockReset();
  updateResume.mockReset();
  fetchResume.mockResolvedValue({ processed_resume: REAL_RESUME });
  updateResume.mockImplementation((_id: string, data: ResumeData) =>
    Promise.resolve({ processed_resume: data })
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe('builder per-resume template settings', () => {
  it('loads each resume’s own settings and writes changes only to the active resume', async () => {
    storeTemplateSettings({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'clean' });
    localStorage.setItem(
      getResumeTemplateSettingsStorageKey('res-1'),
      JSON.stringify({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'modern' })
    );
    localStorage.setItem(
      getResumeTemplateSettingsStorageKey('res-2'),
      JSON.stringify({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'latex' })
    );

    const Builder = await importBuilder();
    const view = render(<Builder />);
    await tick();
    expect(screen.getByTestId('active-template').textContent).toBe('modern');
    // Mount writes only res-1's own key; the global fallback is untouched.
    expect(storedTemplate('res-1')).toBe('modern');
    expect(JSON.parse(localStorage.getItem(TEMPLATE_SETTINGS_STORAGE_KEY)!).template).toBe('clean');

    // A ?id= switch remounts the editor at its key={resumeId} document
    // boundary (see ResumeBuilderDocument), so the fresh instance loads
    // res-2's own choice instead of carrying res-1's state over.
    currentSearch = 'id=res-2';
    view.rerender(<Builder />);
    await tick();
    expect(screen.getByTestId('active-template').textContent).toBe('latex');

    // A template change while res-2 is active is scoped to res-2.
    await act(async () => {
      screen.getByTestId('pick-vivid').click();
    });
    expect(screen.getByTestId('active-template').textContent).toBe('vivid');
    expect(storedTemplate('res-2')).toBe('vivid');
    // res-1 and the global choice never change.
    expect(storedTemplate('res-1')).toBe('modern');
    expect(JSON.parse(localStorage.getItem(TEMPLATE_SETTINGS_STORAGE_KEY)!).template).toBe('clean');
  });

  it('inherits and materializes the global choice for a resume without scoped settings', async () => {
    storeTemplateSettings({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'clean' });
    currentSearch = 'id=res-fresh';

    const Builder = await importBuilder();
    render(<Builder />);
    await tick();

    expect(screen.getByTestId('active-template').textContent).toBe('clean');
    // The inherited choice is pinned onto this resume's own key, so a later
    // global change cannot retroactively move it.
    expect(storedTemplate('res-fresh')).toBe('clean');
  });

  it('keeps brand-new documents (no id) on the legacy global key', async () => {
    currentSearch = '';
    storeTemplateSettings({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'clean' });

    const Builder = await importBuilder();
    render(<Builder />);
    await tick();
    expect(screen.getByTestId('active-template').textContent).toBe('clean');

    await act(async () => {
      screen.getByTestId('pick-vivid').click();
    });
    expect(JSON.parse(localStorage.getItem(TEMPLATE_SETTINGS_STORAGE_KEY)!).template).toBe('vivid');
    // No per-resume scoped key may be created while the document has no id.
    const scopedKeys = Object.keys(localStorage).filter((key) =>
      key.startsWith(`${TEMPLATE_SETTINGS_STORAGE_KEY}:`)
    );
    expect(scopedKeys).toHaveLength(0);
  });
});
