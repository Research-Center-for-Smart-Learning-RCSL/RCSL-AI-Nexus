import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// Testing Library auto-cleans only when Vitest's globals are enabled, and they
// are not (vitest.config.ts declares no `globals: true`, so every test imports
// what it uses). Without this, a second `render` in the same file leaves the
// first one's DOM in place and every `getByTestId` fails with "found multiple
// elements" — which reads as a broken assertion rather than as missing setup.
afterEach(cleanup);

// jsdom in this configuration exposes no `localStorage`, which is not obvious
// until something reads it: `window.localStorage` is `undefined` rather than
// throwing, so a component that guards with try/catch degrades silently and its
// persistence goes untested. An in-memory Storage stands in, cleared between
// tests by whoever needs it — the shape browsers implement, so a test that
// passes here is testing the same contract the app meets in a browser.
if (typeof window !== 'undefined' && !window.localStorage) {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => [...store.keys()][index] ?? null,
    removeItem: (key: string) => void store.delete(key),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
  };
  Object.defineProperty(window, 'localStorage', { value: storage, configurable: true });
}

if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}
