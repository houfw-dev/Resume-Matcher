import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  downloadOutreachPdf,
  generateCoverLetter,
  generateCoverLetterFromResume,
  generateInterviewPrep,
  generateOutreachMessage,
  getOutreachPdfUrl,
} from '@/lib/api/resume';

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
    // Defaults to resume-only generation.
    expect(JSON.parse(init.body)).toEqual({ job_description: '' });
  });

  it('posts the pasted job description for role-targeted interview prep', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ interview_prep: interviewPrep, message: 'ok' }), {
        status: 200,
      })
    );

    await generateInterviewPrep('res-123', 'Need Kubernetes');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res-123/generate-interview-prep');
    expect(JSON.parse(init.body)).toEqual({ job_description: 'Need Kubernetes' });
  });

  it('throws a useful error when interview prep generation fails', async () => {
    fetchMock.mockResolvedValue(new Response('server boom', { status: 500 }));

    await expect(generateInterviewPrep('res-123')).rejects.toThrow(
      'Failed to generate interview preparation'
    );
  });
});

describe('on-demand cover letter and outreach', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts the pasted job description when generating a cover letter', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ content: 'JD letter', message: 'ok' }), { status: 200 })
    );

    await expect(generateCoverLetter('res-123', 'Need FastAPI')).resolves.toBe('JD letter');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res-123/generate-cover-letter');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ job_description: 'Need FastAPI' });
  });

  it('defaults to an empty job description for resume-only cover letters', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ content: 'Resume-only', message: 'ok' }), { status: 200 })
    );

    await generateCoverLetter('res-123');

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ job_description: '' });
  });

  it('posts the pasted job description when generating an outreach message', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ content: 'JD outreach', message: 'ok' }), { status: 200 })
    );

    await expect(generateOutreachMessage('res-123', 'Need Kubernetes')).resolves.toBe(
      'JD outreach'
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res-123/generate-outreach');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ job_description: 'Need Kubernetes' });
  });

  it('defaults to an empty job description for resume-only outreach messages', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ content: 'Resume-only', message: 'ok' }), { status: 200 })
    );

    await generateOutreachMessage('res-123');

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ job_description: '' });
  });
});

describe('outreach PDF export', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('builds the outreach PDF URL with encoded id and page size', () => {
    expect(getOutreachPdfUrl('res 123')).toBe('/api/v1/resumes/res%20123/outreach/pdf?pageSize=A4');
    expect(getOutreachPdfUrl('res-123', 'LETTER', 'zh')).toBe(
      '/api/v1/resumes/res-123/outreach/pdf?pageSize=LETTER&lang=zh'
    );
  });

  it('downloads the outreach PDF as a blob', async () => {
    fetchMock.mockResolvedValue(
      new Response(new Blob(['%PDF-1.4 synthetic'], { type: 'application/pdf' }), {
        status: 200,
      })
    );

    const blob = await downloadOutreachPdf('res-123', 'A4', 'en');

    expect(blob).toBeInstanceOf(Blob);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/resumes/res-123/outreach/pdf?pageSize=A4&lang=en'
    );
  });

  it('throws a useful error when the outreach PDF endpoint fails', async () => {
    fetchMock.mockResolvedValue(new Response('no content', { status: 404 }));

    await expect(downloadOutreachPdf('res-123')).rejects.toThrow(
      'Failed to download outreach message (status 404)'
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
