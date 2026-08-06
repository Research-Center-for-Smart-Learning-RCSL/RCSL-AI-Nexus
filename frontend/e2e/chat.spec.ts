import { expect, test } from '@playwright/test';

type AdminState = {
  chatRequests: unknown[];
  disconnectedStreams: number;
};

test('cancels streams through Stop and page navigation', async ({
  page,
  request,
}) => {
  const adminURL = process.env.E2E_ADMIN_API_URL;
  test.skip(!adminURL, 'Run through pnpm test:e2e to start the SSE fixture.');

  await request.post(`${adminURL}/__e2e__/reset`);
  await page.goto('/chat');

  await page.getByLabel('Message').fill('Give me a deliberately long answer.');
  await page.getByRole('button', { name: 'Send' }).click();

  await expect(page.getByText('Partial reply')).toBeVisible();
  await page.getByRole('button', { name: 'Stop' }).click();

  await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
  await expect(page.getByText('Partial reply')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);

  await expect
    .poll(async () => {
      const response = await request.get(`${adminURL}/__e2e__/state`);
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
  await page.goto('/api-docs');

  await expect
    .poll(async () => {
      const response = await request.get(`${adminURL}/__e2e__/state`);
      const state = (await response.json()) as AdminState;
      return state.disconnectedStreams;
    })
    .toBe(2);

  const response = await request.get(`${adminURL}/__e2e__/state`);
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
