import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useAbortController } from '@/hooks/use-abort-controller';

describe('useAbortController', () => {
  it('hands out a live signal and aborts it when abort() is called', () => {
    const { result } = renderHook(() => useAbortController());

    let signal!: AbortSignal;
    act(() => {
      signal = result.current.getSignal();
    });
    expect(signal.aborted).toBe(false);

    act(() => {
      result.current.abort();
    });
    expect(signal.aborted).toBe(true);
  });

  it('cancels the previous operation when a new signal is requested', () => {
    const { result } = renderHook(() => useAbortController());

    let first!: AbortSignal;
    let second!: AbortSignal;
    act(() => {
      first = result.current.getSignal();
    });
    act(() => {
      second = result.current.getSignal();
    });

    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(false);
    expect(first).not.toBe(second);
  });

  it('aborts the latest in-flight operation on unmount', () => {
    const { result, unmount } = renderHook(() => useAbortController());

    let signal!: AbortSignal;
    act(() => {
      signal = result.current.getSignal();
    });
    unmount();

    expect(signal.aborted).toBe(true);
  });

  it('abort() before any getSignal() is a safe no-op', () => {
    const { result } = renderHook(() => useAbortController());
    expect(() => act(() => result.current.abort())).not.toThrow();
  });
});
