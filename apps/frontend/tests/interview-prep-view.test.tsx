import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { InterviewPrepView } from '@/components/builder/interview-prep-view';
import type { InterviewPrepData } from '@/components/common/resume_previewer_context';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string, params?: Record<string, string>) =>
      params?.title ? `${key} ${params.title}` : key,
  }),
}));

const interviewPrep: InterviewPrepData = {
  role_fit_analysis: ['Backend API experience fits the role.'],
  resume_questions: [
    {
      question: 'How did you build the API?',
      focus_area: 'Backend architecture',
      suggested_answer_points: ['Discuss resume-grounded API work.'],
    },
  ],
  project_follow_ups: [
    {
      question: 'What tradeoffs did you make in the matcher project?',
      focus_area: 'Project tradeoffs',
      suggested_answer_points: ['Explain real implementation choices.'],
    },
  ],
  skill_gaps: [
    {
      skill: 'Kubernetes',
      why_it_matters: 'The JD mentions deployments.',
      preparation_suggestion: 'Review basics without claiming experience.',
    },
  ],
  talking_points: ['Connect API work to the role.'],
};

describe('InterviewPrepView', () => {
  it('renders an empty state and calls onGenerate', () => {
    const onGenerate = vi.fn();
    render(
      <InterviewPrepView
        interviewPrep={null}
        isGenerating={false}
        onGenerate={onGenerate}
        isTailoredResume
      />
    );

    fireEvent.click(
      screen.getByRole('button', { name: /builder\.generatePrompt\.generateButton/ })
    );

    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it('threads the standalone JD input and with-JD action through the empty state', () => {
    const onGenerate = vi.fn();
    const onGenerateWithJobDescription = vi.fn();
    const onJobDescriptionChange = vi.fn();
    render(
      <InterviewPrepView
        interviewPrep={null}
        isGenerating={false}
        onGenerate={onGenerate}
        isTailoredResume={false}
        showJobDescription
        jobDescription="Need Kubernetes"
        onJobDescriptionChange={onJobDescriptionChange}
        onGenerateWithJobDescription={onGenerateWithJobDescription}
      />
    );

    const textarea = screen.getByLabelText('builder.generatePrompt.jobDescriptionLabel');
    expect(textarea).toHaveValue('Need Kubernetes');
    fireEvent.change(textarea, { target: { value: 'Need FastAPI' } });
    expect(onJobDescriptionChange).toHaveBeenCalledWith('Need FastAPI');

    fireEvent.click(
      screen.getByRole('button', { name: /builder\.generatePrompt\.generateWithJd/ })
    );
    expect(onGenerateWithJobDescription).toHaveBeenCalledTimes(1);

    // The resume-only action stays available alongside the JD-targeted one.
    fireEvent.click(
      screen.getByRole('button', { name: /builder\.generatePrompt\.generateWithoutJd/ })
    );
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it('renders loading and error states in the empty view', () => {
    render(
      <InterviewPrepView
        interviewPrep={null}
        isGenerating
        error="Generation failed"
        onGenerate={vi.fn()}
        isTailoredResume
      />
    );

    expect(screen.getByText('Generation failed')).toBeInTheDocument();
    expect(screen.getByText('common.generating')).toBeInTheDocument();
  });

  it('disables generation when job context is unavailable', () => {
    const onGenerate = vi.fn();
    render(
      <InterviewPrepView
        interviewPrep={null}
        isGenerating={false}
        error={null}
        onGenerate={onGenerate}
        isTailoredResume
        canGenerate={false}
        unavailableMessage="No saved job context"
      />
    );

    expect(screen.getByText('interviewPrep.unavailableTitle')).toBeInTheDocument();
    expect(screen.getByText('No saved job context')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders generated interview prep sections', () => {
    render(
      <InterviewPrepView
        interviewPrep={interviewPrep}
        isGenerating={false}
        onGenerate={vi.fn()}
        isTailoredResume
      />
    );

    expect(screen.getByText('Backend API experience fits the role.')).toBeInTheDocument();
    expect(screen.getByText('How did you build the API?')).toBeInTheDocument();
    expect(
      screen.getByText('What tradeoffs did you make in the matcher project?')
    ).toBeInTheDocument();
    expect(screen.getByText('Kubernetes')).toBeInTheDocument();
    expect(screen.getByText('Connect API work to the role.')).toBeInTheDocument();
  });

  it('shows a default unavailable message for generated prep when regeneration is blocked', () => {
    render(
      <InterviewPrepView
        interviewPrep={interviewPrep}
        isGenerating={false}
        onGenerate={vi.fn()}
        isTailoredResume
        canGenerate={false}
      />
    );

    expect(screen.getByText('interviewPrep.missingContextDescription')).toBeInTheDocument();
    expect(screen.getByText('Backend API experience fits the role.')).toBeInTheDocument();
  });
});
