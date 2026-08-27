import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useMediaQuery } from './use-media-query';

// Both entry-curtain gates (reduced motion, the landing panel's breakpoint)
// reduce to this hook, so its contract is what those gates actually rest on.
describe('useMediaQuery', () => {
  afterEach(() => vi.restoreAllMocks());

  function mockMatchMedia(matches: boolean) {
    let listener: (() => void) | null = null;
    const media = {
      matches,
      media: '',
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: (_: string, callback: () => void) => {
        listener = callback;
      },
      removeEventListener: () => {
        listener = null;
      },
      dispatchEvent: () => false,
    };
    vi.spyOn(window, 'matchMedia').mockImplementation(() => media as MediaQueryList);
    return {
      set(value: boolean) {
        media.matches = value;
        listener?.();
      },
      get subscribed() {
        return listener !== null;
      },
    };
  }

  it('answers the query and follows later changes', () => {
    const media = mockMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery('(min-width: 64rem)'));

    expect(result.current).toBe(false);
    act(() => media.set(true));
    expect(result.current).toBe(true);
  });

  it('unsubscribes on unmount', () => {
    const media = mockMatchMedia(true);
    const { unmount } = renderHook(() => useMediaQuery('(min-width: 64rem)'));

    expect(media.subscribed).toBe(true);
    unmount();
    expect(media.subscribed).toBe(false);
  });

  it('answers false, not null forever, when matchMedia is missing', () => {
    const original = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: undefined });
    try {
      const { result } = renderHook(() => useMediaQuery('(min-width: 64rem)'));
      expect(result.current).toBe(false);
    } finally {
      Object.defineProperty(window, 'matchMedia', { configurable: true, value: original });
    }
  });
});
