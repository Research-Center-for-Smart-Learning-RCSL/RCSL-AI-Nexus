import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';

function withClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
    writable: true,
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('useCopyToClipboard', () => {
  it('says Copied for the window and then stops', async () => {
    vi.useFakeTimers();
    const writeText = vi.fn(async () => {});
    withClipboard(writeText);
    const { result } = renderHook(() => useCopyToClipboard(2000));

    await act(async () => {
      await result.current.copy('hello');
    });
    expect(writeText).toHaveBeenCalledWith('hello');
    expect(result.current.copied).toBe(true);

    act(() => void vi.advanceTimersByTime(2000));
    expect(result.current.copied).toBe(false);
  });

  it('gives each copy the whole window rather than what was left of the last', async () => {
    // The one thing `code-block.tsx` had that the other two did not: without
    // clearing first, a second press inherits the remainder of the first
    // timer and the label flickers off early.
    vi.useFakeTimers();
    withClipboard(async () => {});
    const { result } = renderHook(() => useCopyToClipboard(2000));

    await act(async () => {
      await result.current.copy('one');
    });
    act(() => void vi.advanceTimersByTime(1500));
    await act(async () => {
      await result.current.copy('two');
    });

    act(() => void vi.advanceTimersByTime(1500));
    expect(result.current.copied).toBe(true);
    act(() => void vi.advanceTimersByTime(500));
    expect(result.current.copied).toBe(false);
  });

  it('does not fire its timer on a component that has gone', async () => {
    /**
     * `one-time-secret.tsx` and `export-markdown.tsx` both lacked this, and the
     * first of the two lives in a dialog that is routinely dismissed inside
     * the two seconds — which is a state update on an unmounted component.
     */
    vi.useFakeTimers();
    withClipboard(async () => {});
    const { result, unmount } = renderHook(() => useCopyToClipboard(2000));

    await act(async () => {
      await result.current.copy('hello');
    });
    unmount();

    expect(() => act(() => void vi.advanceTimersByTime(5000))).not.toThrow();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('reports a refused clipboard instead of pretending it worked', async () => {
    // A browser can deny it, and on the one-time-secret screen a silent
    // failure is somebody closing a dialog holding nothing.
    withClipboard(async () => {
      throw new Error('denied');
    });
    const { result } = renderHook(() => useCopyToClipboard());

    let outcome: boolean | undefined;
    await act(async () => {
      outcome = await result.current.copy('hello');
    });

    expect(outcome).toBe(false);
    await waitFor(() => {
      expect(result.current.failed).toBe(true);
      expect(result.current.copied).toBe(false);
    });
  });

  it('clears a previous failure when the next attempt succeeds', async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockRejectedValueOnce(new Error('denied'))
      .mockResolvedValueOnce(undefined);
    withClipboard(writeText);
    const { result } = renderHook(() => useCopyToClipboard());

    await act(async () => {
      await result.current.copy('hello');
    });
    await act(async () => {
      await result.current.copy('hello');
    });

    expect(result.current.failed).toBe(false);
    expect(result.current.copied).toBe(true);
  });
});
