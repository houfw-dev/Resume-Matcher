import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useResumeProcessing } from '@/hooks/use-resume-processing';
import { fetchResume, retryProcessing } from '@/lib/api/resume';

vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  retryProcessing: vi.fn(),
}));

type FetchResumeResult = Awaited<ReturnType<typeof fetchResume>>;

const resumeRow = (
  processingStatus: string,
  processed: unknown,
  content = '# Parsed markdown'
): FetchResumeResult =>
  ({
    raw_resume: { processing_status: processingStatus, content },
    processed_resume: processed,
  }) as FetchResumeResult;

const READY_PROCESSED = { personalInfo: { name: 'Jane Applicant' } };
const processing = () => resumeRow('processing', {});
const ready = () => resumeRow('ready', READY_PROCESSED);
const emptyReady = () => resumeRow('ready', {});
const failed = () => resumeRow('failed', {});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const setDocumentHidden = (hidden: boolean) => {
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => hidden,
  });
};

const fetchResumeMock = vi.mocked(fetchResume);
const retryProcessingMock = vi.mocked(retryProcessing);

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
  if (Object.getOwnPropertyDescriptor(document, 'hidden')?.configurable) {
    Reflect.deleteProperty(document, 'hidden');
  }
});

describe('useResumeProcessing', () => {
  it('resolves immediately when the first poll reports a ready resume with content', async () => {
    fetchResumeMock.mockResolvedValue(ready());
    const { result } = renderHook(() => useResumeProcessing('resume-1'));

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(fetchResumeMock).toHaveBeenCalledTimes(1);
    expect(fetchResumeMock).toHaveBeenCalledWith('resume-1');
    expect(result.current.readyGeneration).toBe(1);
    expect(result.current.attemptsExhausted).toBe(false);
    expect(result.current.resume?.raw_resume?.content).toBe('# Parsed markdown');
  });

  it('polls with a 3s exponential backoff until the resume becomes ready', async () => {
    vi.useFakeTimers();
    fetchResumeMock.mockResolvedValueOnce(processing()).mockResolvedValueOnce(ready());
    const { result } = renderHook(() => useResumeProcessing('resume-2'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchResumeMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_999);
    });
    expect(fetchResumeMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchResumeMock).toHaveBeenCalledTimes(2);

    expect(result.current.status).toBe('ready');
    expect(result.current.readyGeneration).toBe(1);
  });

  it('stops polling after 12 background attempts and reports the cap', async () => {
    vi.useFakeTimers();
    fetchResumeMock.mockResolvedValue(processing());
    const { result } = renderHook(() => useResumeProcessing('resume-3'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(320_000);
    });

    // Immediate check + 12 scheduled retries.
    expect(fetchResumeMock).toHaveBeenCalledTimes(13);
    expect(result.current.status).toBe('failed');
    expect(result.current.attemptsExhausted).toBe(true);
    expect(result.current.readyGeneration).toBe(0);
  });

  it('treats a legacy ready row without parsed content as failed', async () => {
    fetchResumeMock.mockResolvedValue(emptyReady());
    const { result } = renderHook(() => useResumeProcessing('resume-4'));

    await waitFor(() => expect(result.current.status).toBe('failed'));
    expect(result.current.attemptsExhausted).toBe(false);
    expect(result.current.readyGeneration).toBe(0);
  });

  it('treats an explicit failed status as failed without retrying', async () => {
    fetchResumeMock.mockResolvedValue(failed());
    const { result } = renderHook(() => useResumeProcessing('resume-5'));

    await waitFor(() => expect(result.current.status).toBe('failed'));
    expect(fetchResumeMock).toHaveBeenCalledTimes(1);
  });

  it('surfaces a rejected poll (e.g. 404) as failed', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    fetchResumeMock.mockRejectedValue(new Error('Failed to load resume (status 404).'));
    const { result } = renderHook(() => useResumeProcessing('resume-6'));

    await waitFor(() => expect(result.current.status).toBe('failed'));
    consoleError.mockRestore();
  });

  it('retry posts to retry-processing then re-observes to a ready resume', async () => {
    fetchResumeMock.mockResolvedValueOnce(failed()).mockResolvedValueOnce(ready());
    retryProcessingMock.mockResolvedValue({
      resume_id: 'resume-7',
      processing_status: 'processing',
    });
    const { result } = renderHook(() => useResumeProcessing('resume-7'));

    await waitFor(() => expect(result.current.status).toBe('failed'));

    await act(async () => {
      await result.current.retry();
    });

    expect(retryProcessingMock).toHaveBeenCalledWith('resume-7');
    expect(fetchResumeMock).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe('ready');
    expect(result.current.readyGeneration).toBe(1);
  });

  it('retry failure throws to the caller and marks the watch failed', async () => {
    fetchResumeMock.mockResolvedValue(failed());
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    retryProcessingMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useResumeProcessing('resume-8'));

    await waitFor(() => expect(result.current.status).toBe('failed'));

    await act(async () => {
      await expect(result.current.retry()).rejects.toThrow('boom');
    });
    expect(result.current.status).toBe('failed');
    consoleError.mockRestore();
  });

  it('discards an in-flight poll for the previous resume id', async () => {
    const oldPoll = deferred<FetchResumeResult>();
    fetchResumeMock.mockImplementation((id: string) =>
      id === 'old' ? oldPoll.promise : Promise.resolve(ready())
    );
    const { result, rerender } = renderHook(({ id }) => useResumeProcessing(id), {
      initialProps: { id: 'old' },
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetchResumeMock).toHaveBeenLastCalledWith('old');

    rerender({ id: 'new' });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(fetchResumeMock).toHaveBeenLastCalledWith('new');

    // The stale poll resolves to a hard failure after the switch.
    await act(async () => {
      oldPoll.resolve(failed());
      await Promise.resolve();
    });
    expect(result.current.status).toBe('ready');
    expect(result.current.readyGeneration).toBe(1);
  });

  it('does not burn poll attempts while the tab is hidden, then resumes on visibility', async () => {
    vi.useFakeTimers();
    setDocumentHidden(true);
    fetchResumeMock.mockResolvedValueOnce(processing()).mockResolvedValueOnce(ready());
    const { result } = renderHook(() => useResumeProcessing('resume-9'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Initial check happens while mounted; hidden state only gates retries.
    expect(fetchResumeMock).toHaveBeenCalledTimes(1);

    // 3s backoff fires, re-arms every 3s while hidden, never polls.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetchResumeMock).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe('processing');

    setDocumentHidden(false);
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.status).toBe('ready');
    expect(fetchResumeMock).toHaveBeenCalledTimes(2);
  });

  it('does nothing while resumeId is null', () => {
    const { result } = renderHook(() => useResumeProcessing(null));
    expect(fetchResumeMock).not.toHaveBeenCalled();
    expect(result.current.status).toBe('processing');
  });
});
