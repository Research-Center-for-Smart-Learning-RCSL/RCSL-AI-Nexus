import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3100';

export default defineConfig({
  // Two disjoint sets, chosen by which stack the runner started.
  //
  // The full-stack paths need a Postgres, the real admin entrance and the real
  // gateway; the default paths need the deterministic admin fixture, and one of
  // them talks to it over a real socket rather than through interception, so it
  // cannot run against the real entrance. Excluded rather than skipped inside
  // the test: a skipped path reports as a path that ran, and these are the only
  // evidence that a policy edit reaches the gateway at all.
  testDir: process.env.E2E_FULL_STACK ? './e2e/full-stack' : './e2e',
  testIgnore: process.env.E2E_FULL_STACK ? [] : ['**/full-stack/**'],
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // No retries for the full-stack paths, whatever CI would otherwise ask for.
  // The database is seeded once per `run-e2e.mjs --full-stack`, before
  // Playwright starts, and the path under it edits the policy it began by
  // asserting. A retry therefore opens on state the previous attempt left, and
  // fails at the *precondition* rather than at the claim -- so retries cannot
  // pass, and the report names the wrong assertion. Re-running the command
  // re-seeds, which is the recovery that works.
  retries: process.env.E2E_FULL_STACK ? 0 : process.env.CI ? 2 : 0,
  // Retries exist to tell a flaky test from a broken one, not to hide it. With
  // this off, a test that fails and then passes leaves CI green and says so
  // only in a report nobody opens; the paths here assert cancellation and CSRF
  // contracts, where intermittent is the interesting result rather than noise.
  failOnFlakyTests: Boolean(process.env.CI),
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
