import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useDebounced } from '@/lib/use-debounced';

/**
 * The wait between what somebody is typing and what the server is asked.
 *
 * Two screens have now found the same defect. The audit log found it first —
 * "typing one action name sent a dozen requests, eleven of which described a
 * prefix that matches nothing by definition" — and the refusals screen
 * repeated it with a filter that costs more: an unindexed `LIKE '%…%'` run
 * twice per request, plus an audit row per request, so a twelve-character name
 * was twelve audit entries naming twelve prefixes of it.
 */

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('useDebounced', () => {
  it('starts with the value it was given, so nothing renders empty', () => {
    const { result } = renderHook(() => useDebounced('wu'));

    expect(result.current).toBe('wu');
  });

  it('holds the old value until the typing stops', () => {
    const { result, rerender } = renderHook(({ value }) => useDebounced(value), {
      initialProps: { value: '' },
    });

    for (const prefix of ['d', 'de', 'dep']) {
      rerender({ value: prefix });
      act(() => void vi.advanceTimersByTime(100));
    }

    // Three hundred milliseconds have passed, but never three hundred without
    // a keystroke: nothing has settled.
    expect(result.current).toBe('');

    act(() => void vi.advanceTimersByTime(300));
    expect(result.current).toBe('dep');
  });

  it('settles once, on the last value rather than on each of them', () => {
    const seen: string[] = [];
    const { rerender } = renderHook(
      ({ value }) => {
        seen.push(useDebounced(value));
      },
      { initialProps: { value: '' } },
    );

    for (const prefix of ['d', 'de', 'dep', 'depa']) rerender({ value: prefix });
    act(() => void vi.advanceTimersByTime(300));

    expect([...new Set(seen)]).toEqual(['', 'depa']);
  });

  it('drops a pending value when the component goes away', () => {
    // The timer is cleared on unmount, so a screen closed inside the window
    // does not wake up to set state on nothing.
    const { unmount } = renderHook(() => useDebounced('wu'));

    unmount();

    expect(() => vi.advanceTimersByTime(300)).not.toThrow();
  });
});
