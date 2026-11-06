import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FineTuneWizardView } from '@/components/builder/fine-tune/fine-tune-wizard';
import type {
  FineTuneCustomModule,
  FineTuneEntryOption,
} from '@/components/builder/fine-tune/fine-tune-dialog';
import { useFineTuneWizard } from '@/hooks/use-fine-tune-wizard';
import type { FineTuneConfirmResponse, FineTunePreviewResponse } from '@/lib/api/fine-tune';
import type { TemplateSettings } from '@/lib/types/template-settings';

const mocks = vi.hoisted(() => ({
  previewFineTune: vi.fn(),
  confirmFineTune: vi.fn(),
}));

vi.mock('@/lib/i18n', () => ({
  // Mirror the engine: key echoed, {placeholders} substituted so tests can
  // assert which params (detail/target/count) were passed.
  useTranslations: () => ({
    t: (key: string, params?: Record<string, string>) =>
      params
        ? `${key}|${Object.entries(params)
            .map(([name, value]) => `${name}=${value}`)
            .join('&')}`
        : key,
  }),
}));

vi.mock('@/lib/api/fine-tune', () => ({
  previewFineTune: (...args: unknown[]) => mocks.previewFineTune(...args),
  confirmFineTune: (...args: unknown[]) => mocks.confirmFineTune(...args),
}));

// The real paginator measures DOM nodes (ResizeObserver etc.); scope outline
// behavior is covered via fine-tune-scope + heading matching unit tests.
vi.mock('@/components/preview', () => ({
  PaginatedPreview: () => <div data-testid="paginated-preview">preview stub</div>,
}));

const PREVIEW: FineTunePreviewResponse = {
  preview_id: 'prev-1',
  expires_at: null,
  scope: { kind: 'all', targets: [] },
  improved_data: {} as FineTunePreviewResponse['improved_data'],
  diff_summary: {
    total_changes: 1,
    skills_added: 0,
    skills_removed: 0,
    descriptions_modified: 1,
    certifications_added: 0,
    high_risk_changes: 0,
  },
  detailed_changes: [
    {
      field_path: 'workExperience[0].description[2]',
      field_type: 'description',
      change_type: 'modified',
      original_value: 'Old bullet',
      new_value: 'New bullet',
      confidence: 'high',
    },
  ],
  warnings: [
    'GROUNDING_REVIEW workExperience[0].description: Kept unverified skydiving claim.',
    'Ignored out-of-range target: work_9',
  ],
};

interface ModuleOverrides {
  hasSummary?: boolean;
  hasWorkExperience?: boolean;
  hasEducation?: boolean;
  hasProjects?: boolean;
  hasAdditional?: boolean;
  customModules?: FineTuneCustomModule[];
  experienceEntries?: FineTuneEntryOption[];
  projectEntries?: FineTuneEntryOption[];
}

interface HarnessProps extends ModuleOverrides {
  onApplied: (result: { mode: string; resumeId: string }) => void | Promise<void>;
  onError: (message: string) => void;
  /** When provided, renders a third start button that opens with this preset. */
  preset?: string[];
}

const DEFAULT_EXPERIENCE: FineTuneEntryOption[] = [
  { title: 'Job A', subtitle: 'Acme' },
  { title: 'Job B' },
];
const DEFAULT_PROJECTS: FineTuneEntryOption[] = [{ title: 'Project X' }];

function Harness({
  onApplied,
  onError,
  preset,
  hasSummary = true,
  hasWorkExperience = true,
  hasEducation = true,
  hasProjects = true,
  hasAdditional = true,
  customModules = [],
  experienceEntries = DEFAULT_EXPERIENCE,
  projectEntries = DEFAULT_PROJECTS,
}: HarnessProps) {
  const wizard = useFineTuneWizard({ resumeId: 'res-1', onApplied, onError });
  return (
    <div>
      <button type="button" data-testid="start-all" onClick={() => wizard.open()}>
        start all
      </button>
      <button
        type="button"
        data-testid="start-work"
        onClick={() => wizard.open(['workExperience'])}
      >
        start work preset
      </button>
      {preset && (
        <button type="button" data-testid="start-preset" onClick={() => wizard.open(preset)}>
          start custom preset
        </button>
      )}
      <FineTuneWizardView
        wizard={wizard}
        experienceEntries={experienceEntries}
        projectEntries={projectEntries}
        hasSummary={hasSummary}
        hasWorkExperience={hasWorkExperience}
        hasEducation={hasEducation}
        hasProjects={hasProjects}
        hasAdditional={hasAdditional}
        customModules={customModules}
        settings={{} as TemplateSettings}
      />
    </div>
  );
}

const generateButton = () => screen.getByRole('button', { name: 'fineTune.dialog.generate' });

// The visual checkbox glyph inside a selectable row (section / entry / region).
const checkboxMark = (row: HTMLElement): HTMLElement | null => row.querySelector('span.w-5');

beforeEach(() => {
  mocks.previewFineTune.mockReset();
  mocks.confirmFineTune.mockReset();
});

describe('fine-tune wizard: scope dialog', () => {
  it('disables generation in module mode with no module selected', () => {
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-all'));

    expect(generateButton()).toBeEnabled(); // all-scope default
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));
    expect(generateButton()).toBeDisabled();
    expect(screen.getByText('fineTune.dialog.selectAtLeastOne')).toBeInTheDocument();
  });

  it('opens in module mode with a preset section preselected', () => {
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-work'));

    expect(screen.getByRole('radio', { name: /scopeModules/ })).toBeChecked();
    expect(generateButton()).toBeEnabled();
  });

  it('sends only the checked entry token after drilling into a section', () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));

    // First matching button is the section row, second is the expand chevron.
    const sectionControls = () =>
      screen.getAllByRole('button', { name: /fineTune\.dialog\.modules\.workExperience/ });
    fireEvent.click(sectionControls()[0]); // select whole section
    fireEvent.click(sectionControls()[0]); // deselect again
    fireEvent.click(sectionControls()[1]); // expand entries

    fireEvent.click(screen.getByRole('button', { name: /Job A/ }));
    fireEvent.click(generateButton());

    expect(mocks.previewFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({
        scope: { kind: 'modules', targets: ['work_0'] },
      })
    );
  });

  it('shows no module rows and disables generation for a minimal resume', () => {
    render(
      <Harness
        onApplied={vi.fn()}
        onError={vi.fn()}
        hasSummary={false}
        hasWorkExperience={false}
        hasEducation={false}
        hasProjects={false}
        hasAdditional={false}
        customModules={[]}
        experienceEntries={[]}
        projectEntries={[]}
      />
    );
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));

    for (const key of [
      'summary',
      'workExperience',
      'education',
      'personalProjects',
      'additional',
    ]) {
      expect(screen.queryByText(`fineTune.dialog.modules.${key}`)).not.toBeInTheDocument();
    }
    // The legacy aggregated custom row is never produced by the content-driven UI.
    expect(screen.queryByText('fineTune.dialog.modules.customSections')).not.toBeInTheDocument();
    expect(generateButton()).toBeDisabled();
    expect(screen.getByText('fineTune.dialog.selectAtLeastOne')).toBeInTheDocument();
  });

  it('gates the summary row on hasSummary', () => {
    const withSummary = render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(withSummary.getByTestId('start-all'));
    fireEvent.click(withSummary.getByRole('radio', { name: /scopeModules/ }));
    expect(
      withSummary.getByRole('button', { name: /fineTune\.dialog\.modules\.summary/ })
    ).toBeInTheDocument();
    withSummary.unmount();

    const withoutSummary = render(
      <Harness onApplied={vi.fn()} onError={vi.fn()} hasSummary={false} />
    );
    fireEvent.click(withoutSummary.getByTestId('start-all'));
    fireEvent.click(withoutSummary.getByRole('radio', { name: /scopeModules/ }));
    expect(
      withoutSummary.queryByRole('button', { name: /fineTune\.dialog\.modules\.summary/ })
    ).toBeNull();
    // Other built-in rows remain available. (Exact string: the row's drill
    // chevron carries a selectEntries aria-label that also embeds the name.)
    expect(
      withoutSummary.getByRole('button', {
        name: 'fineTune.dialog.modules.workExperience',
      })
    ).toBeInTheDocument();
  });

  it('lists each custom block by its real heading and sends its custom_<key> token', () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    const customModules: FineTuneCustomModule[] = [
      { key: 'publications', displayName: 'Publications' },
      { key: 'custom_1', displayName: '兴趣爱好' },
    ];
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} customModules={customModules} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));

    // Real headings, one plain checkbox row each, with no entry-drill chevron.
    const publicationsRow = screen.getByRole('button', { name: 'Publications' });
    const hobbiesRow = screen.getByRole('button', { name: '兴趣爱好' });
    expect(publicationsRow).toBeInTheDocument();
    expect(hobbiesRow).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /selectEntries.*Publications/ })).toBeNull();
    expect(screen.queryByText('fineTune.dialog.modules.customSections')).toBeNull();

    fireEvent.click(publicationsRow);
    fireEvent.click(generateButton());

    expect(mocks.previewFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({
        scope: { kind: 'modules', targets: ['custom_publications'] },
      })
    );
  });

  it('sends the double-prefixed token for a builder-keyed custom block, in click order', () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    const customModules: FineTuneCustomModule[] = [
      { key: 'publications', displayName: 'Publications' },
      { key: 'custom_1', displayName: '兴趣爱好' },
    ];
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} customModules={customModules} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));

    fireEvent.click(screen.getByRole('button', { name: '兴趣爱好' }));
    fireEvent.click(screen.getByRole('button', { name: 'Publications' }));
    fireEvent.click(generateButton());

    expect(mocks.previewFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({
        scope: {
          kind: 'modules',
          targets: ['custom_custom_1', 'custom_publications'],
        },
      })
    );
  });

  it('opens module mode with a custom_<key> preset preselected', () => {
    render(
      <Harness
        onApplied={vi.fn()}
        onError={vi.fn()}
        preset={['custom_self_evaluation']}
        customModules={[{ key: 'self_evaluation', displayName: '自我评价' }]}
      />
    );
    fireEvent.click(screen.getByTestId('start-preset'));

    expect(screen.getByRole('radio', { name: /scopeModules/ })).toBeChecked();
    expect(screen.getByRole('button', { name: '自我评价' })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    expect(generateButton()).toBeEnabled();
  });

  it('drills into a project entry and sends only the checked region token', () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    const projectEntries: FineTuneEntryOption[] = [
      {
        title: 'Project X',
        regions: ['techStack', 'background', 'duties', 'highlights'],
      },
    ];
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} projectEntries={projectEntries} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));

    // Expand the projects section, then the entry's sub-module panel.
    fireEvent.click(
      screen.getByRole('button', {
        name: 'fineTune.dialog.selectEntries|module=fineTune.dialog.modules.personalProjects',
      })
    );
    expect(
      screen.getByRole('button', { name: 'fineTune.dialog.selectRegions|module=Project X' })
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'fineTune.dialog.selectRegions|module=Project X' })
    );

    for (const regionId of ['techStack', 'background', 'duties', 'highlights']) {
      expect(
        screen.getByRole('button', { name: `fineTune.dialog.regions.${regionId}` })
      ).toBeInTheDocument();
    }

    const highlightsRow = screen.getByRole('button', {
      name: 'fineTune.dialog.regions.highlights',
    });
    expect(highlightsRow).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(highlightsRow);
    expect(highlightsRow).toHaveAttribute('aria-pressed', 'true');

    // The check must be VISIBLE: blue fill + white glyph. A regression left
    // the fill white, making the white checkmark impossible to see.
    expect(checkboxMark(highlightsRow)).toHaveClass('bg-blue-700');
    const techStackRow = screen.getByRole('button', {
      name: 'fineTune.dialog.regions.techStack',
    });
    expect(checkboxMark(techStackRow)).not.toHaveClass('bg-blue-700');

    // The entry row shows the partial state (some regions checked): blue
    // border, white fill, inner blue square — not a filled check.
    const entryMark = checkboxMark(screen.getByRole('button', { name: 'Project X' }));
    expect(entryMark).toHaveClass('border-blue-700');
    expect(entryMark).not.toHaveClass('bg-blue-700');
    expect(entryMark?.querySelector('span.w-2')).not.toBeNull();

    fireEvent.click(generateButton());

    expect(mocks.previewFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({
        scope: { kind: 'modules', targets: ['project_0:highlights'] },
      })
    );
  });

  it('hides region rows when the whole entry is checked and sweeps the region token', () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    const projectEntries: FineTuneEntryOption[] = [
      { title: 'Project X', regions: ['duties', 'highlights'] },
    ];
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} projectEntries={projectEntries} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));
    fireEvent.click(
      screen.getByRole('button', {
        name: 'fineTune.dialog.selectEntries|module=fineTune.dialog.modules.personalProjects',
      })
    );

    // Select a region first: the entry row stays unchecked and the row shows.
    fireEvent.click(
      screen.getByRole('button', { name: 'fineTune.dialog.selectRegions|module=Project X' })
    );
    const highlightsRow = screen.getByRole('button', {
      name: 'fineTune.dialog.regions.highlights',
    });
    fireEvent.click(highlightsRow);
    expect(highlightsRow).toBeInTheDocument();

    // Checking the whole entry sweeps the region token and hides the panel.
    // Exact name: the drill chevron's aria-label also contains "Project X".
    fireEvent.click(screen.getByRole('button', { name: 'Project X' }));
    expect(checkboxMark(screen.getByRole('button', { name: 'Project X' }))).toHaveClass(
      'bg-blue-700'
    );
    expect(screen.queryByRole('button', { name: 'fineTune.dialog.regions.highlights' })).toBeNull();
    expect(
      screen.getByRole('button', { name: 'fineTune.dialog.selectRegions|module=Project X' })
    ).toBeDisabled();

    fireEvent.click(generateButton());
    expect(mocks.previewFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({
        scope: { kind: 'modules', targets: ['project_0'] },
      })
    );
  });

  it('shows no sub-module chevron for an entry without label regions', () => {
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(screen.getByRole('radio', { name: /scopeModules/ }));
    fireEvent.click(
      screen.getByRole('button', {
        name: 'fineTune.dialog.selectEntries|module=fineTune.dialog.modules.personalProjects',
      })
    );

    // DEFAULT_PROJECTS carries no regions: entry row exists, drill chevron doesn't.
    expect(screen.getByRole('button', { name: /Project X/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /fineTune\.dialog\.selectRegions/ })).toBeNull();
  });
});

describe('fine-tune wizard: preview', () => {
  it('generates an all-scope preview with instruction and renders both tabs + warnings', async () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-all'));

    fireEvent.change(screen.getByLabelText('fineTune.dialog.instructionLabel'), {
      target: { value: 'Quantify impact' },
    });
    fireEvent.click(generateButton());

    await waitFor(() => expect(screen.getByText('fineTune.preview.title')).toBeInTheDocument());

    expect(mocks.previewFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({
        scope: { kind: 'all', targets: [] },
        instruction: 'Quantify impact',
      })
    );
    expect(screen.getByTestId('paginated-preview')).toBeInTheDocument();
    expect(
      screen.getByText(/groundingWarning.*Kept unverified skydiving claim/)
    ).toBeInTheDocument();
    expect(screen.getByText(/ignoredTarget.*work_9/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'fineTune.preview.tabChanges' }));
    expect(screen.getByText('workExperience[0].description[2]')).toBeInTheDocument();
    expect(screen.getByText('fineTune.preview.changeModified')).toBeInTheDocument();
    expect(screen.getByText('Old bullet')).toBeInTheDocument();
    expect(screen.getByText('New bullet')).toBeInTheDocument();
  });

  it('bounds both tabs to a definite-height dialog so content scrolls above the footer', async () => {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(generateButton());
    await waitFor(() => expect(screen.getByText('fineTune.preview.title')).toBeInTheDocument());

    // A max-height-only (indefinite) dialog collapses an absolute/flex-1
    // content area to zero height and the rendered tab shows nothing.
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveClass('h-[92vh]', 'flex', 'flex-col', 'overflow-hidden');

    // Rendered tab: the paginator (h-full root) resolves against the definite
    // height chain instead of collapsing.
    const previewStub = screen.getByTestId('paginated-preview');
    expect(previewStub.parentElement).toHaveClass('h-full');
    expect(previewStub.parentElement?.parentElement).toHaveClass('flex-1', 'min-h-0');

    // Changes tab: the list is a percentage-height scroll region; h-full now
    // resolves, so long lists scroll instead of clipping behind the footer.
    fireEvent.click(screen.getByRole('button', { name: 'fineTune.preview.tabChanges' }));
    const scrollRegion = screen.getByText('Old bullet').closest('.overflow-y-auto');
    expect(scrollRegion).not.toBeNull();
    expect(scrollRegion).toHaveClass('h-full');
  });

  it('renders before/after values with preserved line breaks', async () => {
    const multilinePreview: FineTunePreviewResponse = {
      ...PREVIEW,
      preview_id: 'prev-2',
      detailed_changes: [
        {
          field_path: 'workExperience[0]',
          field_type: 'experience',
          change_type: 'modified',
          original_value: 'Engineer | Acme | 2020\nlocation: NY',
          new_value: 'Engineer | Acme | 2020\nlocation: Remote',
          confidence: 'medium',
        },
      ],
    };
    mocks.previewFineTune.mockResolvedValueOnce(multilinePreview);
    render(<Harness onApplied={vi.fn()} onError={vi.fn()} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(generateButton());
    await waitFor(() => expect(screen.getByText('fineTune.preview.title')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'fineTune.preview.tabChanges' }));

    // Function matcher: Testing Library only normalizes node text, not the
    // string matcher, so assert raw textContent (newline must survive).
    const paragraphWith = (expected: string) =>
      screen.getByText(
        (_content, element) => element?.tagName === 'P' && element.textContent === expected
      );
    expect(paragraphWith('Engineer | Acme | 2020\nlocation: NY')).toHaveClass(
      'whitespace-pre-line'
    );
    expect(paragraphWith('Engineer | Acme | 2020\nlocation: Remote')).toHaveClass(
      'whitespace-pre-line'
    );
  });

  it('returns to the scope dialog with an error when generation reports a conflict', async () => {
    mocks.previewFineTune.mockRejectedValueOnce(
      new Error('Resume changed after preview; retry preview')
    );
    const onError = vi.fn();
    render(<Harness onApplied={vi.fn()} onError={onError} />);
    fireEvent.click(screen.getByTestId('start-all'));
    fireEvent.click(generateButton());

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Resume changed after preview; retry preview'
      )
    );
    expect(onError).toHaveBeenCalledWith('Resume changed after preview; retry preview');
    expect(generateButton()).toBeInTheDocument(); // still on the scope step
    expect(screen.queryByText('fineTune.preview.title')).not.toBeInTheDocument();
  });
});

describe('fine-tune wizard: confirm and persist', () => {
  async function reachPreview(onApplied: HarnessProps['onApplied'], onError = vi.fn()) {
    mocks.previewFineTune.mockResolvedValueOnce(PREVIEW);
    const result = render(<Harness onApplied={onApplied} onError={onError} />);
    fireEvent.click(result.getByTestId('start-all'));
    fireEvent.click(result.getByRole('button', { name: 'fineTune.dialog.generate' }));
    await waitFor(() => expect(result.getByText('fineTune.preview.title')).toBeInTheDocument());
    return result;
  }

  it('overwrites after a second confirmation and reloads via onApplied', async () => {
    const onApplied = vi.fn().mockResolvedValue(undefined);
    const confirmResponse: FineTuneConfirmResponse = {
      resume_id: 'res-1',
      mode: 'overwrite',
      title: null,
    };
    mocks.confirmFineTune.mockResolvedValueOnce(confirmResponse);

    const result = await reachPreview(onApplied);

    fireEvent.click(result.getByRole('button', { name: 'fineTune.preview.overwrite' }));
    expect(result.getByText('fineTune.preview.overwriteConfirmTitle')).toBeInTheDocument();

    // Footer trigger + confirm-dialog button share the label; confirm the latter.
    const confirmButtons = result.getAllByRole('button', {
      name: 'fineTune.preview.overwrite',
    });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(mocks.confirmFineTune).toHaveBeenCalledTimes(1));
    expect(mocks.confirmFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({ preview_id: 'prev-1', mode: 'overwrite' })
    );
    expect(onApplied).toHaveBeenCalledWith({ mode: 'overwrite', resumeId: 'res-1' });
    await waitFor(() =>
      expect(result.queryByText('fineTune.preview.title')).not.toBeInTheDocument()
    );
  });

  it('saves a titled copy and reports the new resume id', async () => {
    const onApplied = vi.fn().mockResolvedValue(undefined);
    mocks.confirmFineTune.mockResolvedValueOnce({
      resume_id: 'res-2',
      mode: 'copy',
      title: 'Polished version',
    } satisfies FineTuneConfirmResponse);

    const result = await reachPreview(onApplied);

    fireEvent.click(result.getByRole('button', { name: 'fineTune.preview.saveCopy' }));
    const titleInput = result.getByLabelText('fineTune.preview.copyTitleLabel');
    fireEvent.change(titleInput, { target: { value: 'Polished version' } });
    fireEvent.click(result.getByRole('button', { name: 'fineTune.preview.createCopy' }));

    await waitFor(() => expect(mocks.confirmFineTune).toHaveBeenCalledTimes(1));
    expect(mocks.confirmFineTune).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({ mode: 'copy', title: 'Polished version' })
    );
    expect(onApplied).toHaveBeenCalledWith({ mode: 'copy', resumeId: 'res-2' });
  });
});
