import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { stubMatchMedia } from '@/test-support/match-media';
import { useMediaQuery } from './use-media-query';

const QUERY = '(min-width: 64rem)';

// Both entry-curtain gates (reduced motion, the landing panel's breakpoint)
// reduce to this hook, so its contract is what those gates actually rest on.
describe('useMediaQuery', () => {
  it('answers the query and follows later changes', () => {
    const media = stubMatchMedia({ [QUERY]: false });
    const { result } = renderHook(() => useMediaQuery(QUERY));

    expect(result.current).toBe(false);
    act(() => media.set(QUERY, true));
    expect(result.current).toBe(true);
  });

  it('unsubscribes on unmount', () => {
    const media = stubMatchMedia({ [QUERY]: true });
    const { unmount } = renderHook(() => useMediaQuery(QUERY));

    expect(media.listenerCount(QUERY)).toBe(1);
    unmount();
    expect(media.listenerCount(QUERY)).toBe(0);
  });

  it('still follows changes through the deprecated listener pair (Safari <14)', () => {
    const media = stubMatchMedia({ [QUERY]: false }, { legacy: true });
    const { result, unmount } = renderHook(() => useMediaQuery(QUERY));

    expect(result.current).toBe(false);
    act(() => media.set(QUERY, true));
    expect(result.current).toBe(true);
    unmount();
    expect(media.listenerCount(QUERY)).toBe(0);
  });

  it('answers false, not null forever, when matchMedia is missing', () => {
    const original = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: undefined });
    try {
      const { result } = renderHook(() => useMediaQuery(QUERY));
      expect(result.current).toBe(false);
    } finally {
      Object.defineProperty(window, 'matchMedia', { configurable: true, value: original });
    }
  });
});
