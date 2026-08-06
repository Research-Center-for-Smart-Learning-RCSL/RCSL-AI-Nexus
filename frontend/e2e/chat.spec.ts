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
  // Next dev mounts its own off-screen role=alert for the development overlay.
  // Only an alert in the application main region is a chat failure.
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
  await page.getByRole('link', { name: 'API', exact: true }).click();
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
