import { useCallback, useEffect, useRef } from 'react';

/**
 * Owns the AbortController for a component's latest cancelable operation.
 *
 * - `getSignal()` starts a new operation: any operation still in flight is
 *   aborted first, then a fresh controller/signal is returned. Pass the signal
 *   down through the lib/api layer (all long-running calls accept one).
 * - `abort()` cancels the current operation explicitly (Cancel button).
 * - Unmount aborts automatically, so a navigation away never leaves a
 *   state-update callback for a dead component pending.
 *
 * The hook never touches React state; callers decide what cancellation means
 * for their own UI (usually: clear the loading flag, stay on the form).
 */
export function useAbortController(): {
  getSignal: () => AbortSignal;
  abort: () => void;
} {
  const controllerRef = useRef<AbortController | null>(null);

  const getSignal = useCallback((): AbortSignal => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    return controller.signal;
  }, []);

  const abort = useCallback((): void => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(
    () => (): void => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    },
    []
  );

  return { getSignal, abort };
}
