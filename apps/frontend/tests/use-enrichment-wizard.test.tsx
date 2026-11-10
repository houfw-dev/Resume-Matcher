import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const analyzeMock = vi.fn();
const enhanceMock = vi.fn();
const applyMock = vi.fn();

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/api/enrichment', () => ({
  analyzeResume: (...args: unknown[]) => analyzeMock(...args),
  generateEnhancements: (...args: unknown[]) => enhanceMock(...args),
  applyEnhancements: (...args: unknown[]) => applyMock(...args),
}));

import { useEnrichmentWizard } from '@/hooks/use-enrichment-wizard';

/** A call that only settles (with an AbortError) when its signal is aborted. */
function abortAwareCall(signalIndex: number): (...args: unknown[]) => Promise<never> {
  return (...args: unknown[]) => {
    const signal = args[signalIndex] as AbortSignal | undefined;
    return new Promise<never>((_resolve, reject) => {
      signal?.addEventListener('abort', () => {
        const err = new Error('aborted');
        err.name = 'AbortError';
        reject(err);
      });
    });
  };
}

const ANALYSIS = {
  items_to_enrich: [
    {
      item_id: 'exp-1',
      item_type: 'experience' as const,
      title: 'Backend engineer',
      current_description: ['did things'],
      weakness_reason: 'weak',
    },
  ],
  questions: [
    { question_id: 'q-1', item_id: 'exp-1', question: 'What did you build?', placeholder: '...' },
  ],
};

describe('useEnrichmentWizard cancellation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('threads an AbortSignal into analyze and aborts it on reset without an error', async () => {
    analyzeMock.mockImplementation(abortAwareCall(1));
    const { result } = renderHook(() => useEnrichmentWizard('r1'));

    await act(async () => {
      void result.current.startAnalysis();
    });
    expect(result.current.state.step).toBe('analyzing');
    const signal = analyzeMock.mock.calls[0][1] as AbortSignal;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(false);

    await act(async () => result.current.reset());

    expect(signal.aborted).toBe(true);
    expect(result.current.state.step).toBe('idle');
    // Flush the rejected continuation; it must not flip the wizard to error.
    await act(async () => {});
    expect(result.current.state.step).toBe('idle');
    expect(result.current.state.error).toBeNull();
  });

  it('aborts the in-flight enhancement generation from the questions step', async () => {
    analyzeMock.mockResolvedValue(ANALYSIS);
    const { result } = renderHook(() => useEnrichmentWizard('r1'));

    await act(async () => {
      await result.current.startAnalysis();
    });
    expect(result.current.state.step).toBe('questions');

    act(() => result.current.setAnswer('q-1', 'I built the billing service.'));
    enhanceMock.mockImplementation(abortAwareCall(2));

    await act(async () => {
      void result.current.generateEnhancements();
    });
    expect(result.current.state.step).toBe('generating');
    const signal = enhanceMock.mock.calls[0][2] as AbortSignal;
    expect(signal).toBeInstanceOf(AbortSignal);

    await act(async () => result.current.reset());
    expect(signal.aborted).toBe(true);
    await act(async () => {});
    expect(result.current.state.step).toBe('idle');
    expect(result.current.state.error).toBeNull();
  });

  it('aborts the analyze request when the wizard unmounts', async () => {
    analyzeMock.mockImplementation(abortAwareCall(1));
    const { result, unmount } = renderHook(() => useEnrichmentWizard('r1'));

    await act(async () => {
      void result.current.startAnalysis();
    });
    const signal = analyzeMock.mock.calls[0][1] as AbortSignal;

    unmount();
    expect(signal.aborted).toBe(true);
  });

  it('still surfaces genuine failures on the error step', async () => {
    analyzeMock.mockRejectedValue(new Error('LLM down'));
    const { result } = renderHook(() => useEnrichmentWizard('r1'));

    await act(async () => {
      await result.current.startAnalysis();
    });

    expect(result.current.state.step).toBe('error');
    expect(result.current.state.error).toBe('LLM down');
  });
});
