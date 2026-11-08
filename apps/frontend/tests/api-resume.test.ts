import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { generateCoverLetterFromResume, generateInterviewPrep } from '@/lib/api/resume';

const interviewPrep = {
  role_fit_analysis: ['Backend API experience fits the role.'],
  resume_questions: [
    {
      question: 'How did you build the API?',
      focus_area: 'Backend architecture',
      suggested_answer_points: ['Discuss resume-grounded API work.'],
    },
  ],
  project_follow_ups: [],
  skill_gaps: [
    {
      skill: 'Kubernetes',
      why_it_matters: 'The JD mentions deployments.',
      preparation_suggestion: 'Review basics without claiming experience.',
    },
  ],
  talking_points: ['Connect API work to the role.'],
};

describe('resume API', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('generates interview prep and parses the structured payload', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          interview_prep: interviewPrep,
          message: 'Interview preparation generated successfully',
        }),
        { status: 200 }
      )
    );

    await expect(generateInterviewPrep('res 123')).resolves.toEqual(interviewPrep);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res%20123/generate-interview-prep');
    expect(init.method).toBe('POST');
  });

  it('throws a useful error when interview prep generation fails', async () => {
    fetchMock.mockResolvedValue(new Response('server boom', { status: 500 }));

    await expect(generateInterviewPrep('res-123')).rejects.toThrow(
      'Failed to generate interview preparation'
    );
  });
});

describe('generateCoverLetterFromResume', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts the job description and parses the generated content', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ content: 'Tailored letter', message: 'ok' }), { status: 200 })
    );

    await expect(generateCoverLetterFromResume('res-123', 'Need FastAPI')).resolves.toBe(
      'Tailored letter'
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res-123/cover-letter/generate');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ job_description: 'Need FastAPI' });
  });

  it('defaults to an empty job description for resume-only generation', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ content: 'Resume-only letter', message: 'ok' }), {
        status: 200,
      })
    );

    await expect(generateCoverLetterFromResume('res-123')).resolves.toBe('Resume-only letter');

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ job_description: '' });
  });

  it('throws a useful error when generation fails', async () => {
    fetchMock.mockResolvedValue(new Response('server boom', { status: 500 }));

    await expect(generateCoverLetterFromResume('res-123')).rejects.toThrow(
      'Failed to generate cover letter'
    );
  });
});
