import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// Testing Library auto-cleans only when Vitest's globals are enabled, and they
// are not (vitest.config.ts declares no `globals: true`, so every test imports
// what it uses). Without this, a second `render` in the same file leaves the
// first one's DOM in place and every `getByTestId` fails with "found multiple
// elements" — which reads as a broken assertion rather than as missing setup.
afterEach(cleanup);
