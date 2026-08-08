import { expect, test } from '@playwright/test';

type AdminState = {
  chatRequests: unknown[];
  disconnectedStreams: number;
};

test('cancels streams through Stop and page navigation', async ({
  baseURL,
  page,
  request,
}, testInfo) => {
  const adminURL = process.env.E2E_ADMIN_API_URL;
  test.skip(!adminURL, 'Run through pnpm test:e2e to start the SSE fixture.');
  if (!baseURL) throw new Error('Playwright baseURL is required for this test.');

  const caseId = [
    testInfo.project.name,
    testInfo.workerIndex,
    testInfo.repeatEachIndex,
    testInfo.retry,
  ]
    .join('-')
    .replace(/[^a-zA-Z0-9_-]/g, '_');
  const fixtureURL = (path: 'reset' | 'state') =>
    `${adminURL}/__e2e__/${path}?case=${encodeURIComponent(caseId)}`;

  await page.context().addCookies([
    { name: 'e2e_case', value: caseId, url: baseURL },
  ]);

  await request.post(fixtureURL('reset'));
  await page.goto('/chat');

  await page.getByLabel('Message').fill('Give me a deliberately long answer.');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.getByText('Partial reply')).toBeVisible();
  await page.getByRole('button', { name: 'Stop' }).click();

  await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
  await expect(page.getByText('Partial reply')).toBeVisible();
  // Scoped to the application region rather than the page: under `--dev` Next
  // mounts its own off-screen role=alert for the development overlay, and only
  // an alert the person can actually see is a chat failure.
  await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);

  await expect
    .poll(async () => {
      const response = await request.get(fixtureURL('state'));
      const state = (await response.json()) as AdminState;
      return state.disconnectedStreams;
    })
    .toBe(1);

  // Navigating away exercises the hook's unmount cleanup rather than the Stop
  // button. Both must abort the same fetch or a background generation keeps a
  // model concurrency slot after the person has left the conversation.
  await page
    .getByLabel('Message')
    .fill('Keep generating until I leave this page.');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('Partial reply')).toHaveCount(2);
  // Located by destination, not by label. This was
  // `getByRole('link', { name: 'API', exact: true })` until 2026-08-08, and
  // renaming that nav item to 'API reference' on 2026-08-07 broke it — with
  // `exact: true`, 'API' stops matching. **CI was red on `main` for five
  // consecutive commits** before anyone read the frontend job, while ROADMAP
  // and PROGRESS both said the gates were green.
  //
  // The coupling was the defect rather than the rename. This test is about
  // whether client-side navigation aborts the stream; *which* link it leaves
  // through is incidental, so asserting the nav's copy gave it a way to fail
  // that has nothing to do with what it checks. The URL assertion below
  // already pins the destination.
  await page.getByRole('navigation').getByRole('link', { name: /api reference/i }).click();
  await expect(page).toHaveURL(/\/api-docs$/);

  await expect
    .poll(async () => {
      const response = await request.get(fixtureURL('state'));
      const state = (await response.json()) as AdminState;
      return state.disconnectedStreams;
    })
    .toBe(2);

  const response = await request.get(fixtureURL('state'));
  const state = (await response.json()) as AdminState;
  expect(state.chatRequests).toEqual([
    {
      capability: 'chat',
      messages: [
        { role: 'user', content: 'Give me a deliberately long answer.' },
      ],
      think: true,
    },
    {
      capability: 'chat',
      messages: [
        { role: 'user', content: 'Give me a deliberately long answer.' },
        { role: 'assistant', content: 'Partial reply' },
        { role: 'user', content: 'Keep generating until I leave this page.' },
      ],
      think: true,
    },
  ]);
});
