import { describe, expect, it } from 'vitest';
import { isAbortError } from '@/lib/utils/abort';

describe('isAbortError', () => {
  it('recognizes the normalized Error produced by apiFetch on caller cancel', () => {
    const error = new Error('The operation was aborted.');
    error.name = 'AbortError';
    expect(isAbortError(error)).toBe(true);
  });

  it('recognizes DOMException-shaped abort records without relying on instanceof', () => {
    expect(isAbortError({ name: 'AbortError' })).toBe(true);
  });

  it.each([
    ['plain Error', new Error('boom')],
    ['null', null],
    ['undefined', undefined],
    ['string', 'AbortError'],
    ['different error name', { name: 'TypeError' }],
    ['empty object', {}],
  ])('rejects %s', (_label, value) => {
    expect(isAbortError(value)).toBe(false);
  });
});
