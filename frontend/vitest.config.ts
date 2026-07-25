import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// `@/` is resolved here rather than through vite-tsconfig-paths so the test
// setup has no dependency on how the plugin reads tsconfig; the alias mirrors
// the single entry under `paths` in tsconfig.json.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    // https so jsdom's cookie jar accepts the `__Host-` prefixed CSRF cookie,
    // which requires Secure and is otherwise dropped over http.
    environmentOptions: { jsdom: { url: 'https://localhost/' } },
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
  },
});
