/**
 * Helpers for user-initiated request cancellation.
 *
 * `apiFetch` normalizes every cancellation (native fetch AbortError,
 * DOMException, or its own wrapped timeout) into an Error whose `name` is
 * `'AbortError'`, so callers only need this one shape check to distinguish a
 * deliberate cancel from a real failure and stay silent instead of showing an
 * error banner for an action the user asked to stop.
 */
export function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name: unknown }).name === 'AbortError'
  );
}
