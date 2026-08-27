import { vi } from 'vitest';

type Listener = (event?: unknown) => void;

/**
 * One matchMedia stub for every suite, keyed by query. A single-boolean stub
 * answers every query identically, which made states like the landing
 * backdrop's — reduced motion off AND the lg breakpoint met — unrepresentable,
 * so the code behind them shipped untested.
 */
export function stubMatchMedia(
  initial: Record<string, boolean> = {},
  options: { legacy?: boolean } = {},
) {
  const state = new Map(Object.entries(initial));
  const listeners = new Map<string, Set<Listener>>();

  const factory = (query: string): MediaQueryList => {
    let callbacks = listeners.get(query);
    if (!callbacks) {
      callbacks = new Set();
      listeners.set(query, callbacks);
    }
    const bound = callbacks;
    const list = {
      get matches() {
        return state.get(query) ?? false;
      },
      media: query,
      onchange: null,
      addListener: (callback: Listener) => bound.add(callback),
      removeListener: (callback: Listener) => bound.delete(callback),
      addEventListener: (_type: string, callback: Listener) => bound.add(callback),
      removeEventListener: (_type: string, callback: Listener) => bound.delete(callback),
      dispatchEvent: () => false,
    };
    if (options.legacy) {
      // Safari <14 shape: only the deprecated pair exists.
      Reflect.deleteProperty(list, 'addEventListener');
      Reflect.deleteProperty(list, 'removeEventListener');
    }
    return list as unknown as MediaQueryList;
  };

  const spy = vi.fn(factory);
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: spy,
  });

  return {
    /** Change a query's answer and notify its subscribers. */
    set(query: string, matches: boolean) {
      state.set(query, matches);
      listeners.get(query)?.forEach((callback) => callback());
    },
    listenerCount(query: string) {
      return listeners.get(query)?.size ?? 0;
    },
  };
}

export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
export const PANEL_BREAKPOINT_QUERY = '(min-width: 64rem)';
