import { expect, test, type Page, type Route } from '@playwright/test';

import type { ApiKey } from '../src/features/api-keys/schema';

const JSON_HEADERS = { 'content-type': 'application/json' };
const OWNER_ID = '11111111-1111-1111-1111-111111111111';
const CSRF_TOKEN = 'csrf-e2e-api-keys';
const PLAINTEXT = 'nx_live_key-e2e-1.plaintext-shown-once';

type KeyWrite = Pick<
  ApiKey,
  | 'name'
  | 'scopes'
  | 'rate_limit_rpm'
  | 'quota_tokens_per_day'
  | 'allowed_cidrs'
  | 'expires_at'
  // Both verbs always send this one, and the update verb's `null` is a value
  // rather than silence: the server tells absent from null and only null
  // clears a default. A stub that dropped it would let the form stop sending
  // it and nothing here would notice.
  | 'default_capability'
>;

function json(
  route: Route,
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
) {
  return route.fulfill({
    status,
    headers: { ...JSON_HEADERS, ...headers },
    body: JSON.stringify(body),
  });
}

async function installAdminApi(page: Page) {
  const keys: ApiKey[] = [];
  let issuedBody: (KeyWrite & { owner_id: string }) | null = null;
  let updatedBody: Partial<KeyWrite> | null = null;

  await page.route('**/admin/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === '/admin/me' && request.method() === 'GET') {
      await json(
        route,
        200,
        {
          id: OWNER_ID,
          auth_mode: 'local',
          login: 'member@example.org',
          display_name: 'Member',
          role: 'user',
          scopes: ['api_key:read_own', 'api_key:write_own'],
          session_expires_at: '2099-01-01T00:00:00Z',
        },
        {
          'set-cookie': `nexus_csrf=${CSRF_TOKEN}; Path=/; SameSite=Lax`,
        },
      );
      return;
    }

    if (url.pathname === '/admin/api-keys' && request.method() === 'GET') {
      await json(route, 200, keys);
      return;
    }

    if (url.pathname === '/admin/api-keys' && request.method() === 'POST') {
      expect(request.headers()['x-csrf-token']).toBe(CSRF_TOKEN);
      issuedBody = request.postDataJSON() as KeyWrite & { owner_id: string };
      const key: ApiKey = {
        key_id: 'key-e2e-1',
        ...issuedBody,
        expires_at: `${issuedBody.expires_at}T00:00:00Z`,
        owner_display: 'Member',
        revoked_at: null,
        created_at: '2026-08-06T00:00:00Z',
        last_used_at: null,
        debug_logging_until: null,
      };
      keys.push(key);
      await json(route, 201, {
        key,
        plaintext: PLAINTEXT,
      });
      return;
    }

    const keyMatch = url.pathname.match(/^\/admin\/api-keys\/([^/]+)$/);
    if (keyMatch && request.method() === 'PATCH') {
      expect(request.headers()['x-csrf-token']).toBe(CSRF_TOKEN);
      updatedBody = request.postDataJSON() as Partial<KeyWrite>;
      const key = keys.find((candidate) => candidate.key_id === keyMatch[1]);
      expect(key).toBeDefined();
      Object.assign(key!, updatedBody);
      await json(route, 200, key);
      return;
    }

    const revokeMatch = url.pathname.match(
      /^\/admin\/api-keys\/([^/]+)\/revoke$/,
    );
    if (revokeMatch && request.method() === 'POST') {
      expect(request.headers()['x-csrf-token']).toBe(CSRF_TOKEN);
      const key = keys.find(
        (candidate) => candidate.key_id === revokeMatch[1],
      );
      expect(key).toBeDefined();
      key!.revoked_at = '2026-08-06T01:00:00Z';
      await route.fulfill({ status: 204 });
      return;
    }

    await json(route, 404, { message: `Unhandled test route: ${url.pathname}` });
  });

  return {
    keys,
    issuedBody: () => issuedBody,
    updatedBody: () => updatedBody,
  };
}

test('issues, edits, and revokes an API key', async ({ page }) => {
  const api = await installAdminApi(page);

  await page.goto('/api-keys');
  await expect(page.getByText('No API keys')).toBeVisible();

  await page.getByRole('button', { name: 'Issue key' }).click();
  const createDialog = page.getByRole('dialog');
  // `exact` because getByLabel matches a case-insensitive substring by default,
  // and the capability-defaulting field added on 2026-08-18 is labelled "When a
  // request names something else" — which contains "name" and made this
  // locator ambiguous rather than wrong.
  await createDialog.getByLabel('Name', { exact: true }).fill('browser-agent');
  await createDialog.getByRole('button', { name: 'Issue key' }).click();

  expect(api.issuedBody()).toMatchObject({
    name: 'browser-agent',
    owner_id: OWNER_ID,
    scopes: ['chat'],
    rate_limit_rpm: 240,
    quota_tokens_per_day: 90_000_000,
    allowed_cidrs: [],
  });
  expect(api.issuedBody()?.expires_at).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  await expect(createDialog.getByText(PLAINTEXT, { exact: true })).toBeVisible();
  await expect(createDialog.getByRole('alert')).toHaveCount(0);

  const done = createDialog.getByRole('button', { name: 'Done' });
  await expect(done).toBeDisabled();
  await createDialog
    .getByRole('checkbox', { name: 'I have saved this key' })
    .check();
  await expect(done).toBeEnabled();
  await done.click();

  const row = page.getByRole('row').filter({ hasText: 'browser-agent' });
  await expect(row).toContainText('key-e2e-1');
  await row.getByRole('button', { name: 'Edit' }).click();

  const editDialog = page.getByRole('dialog');
  await expect(editDialog.getByText('Edit browser-agent')).toBeVisible();
  await editDialog.getByLabel('Name', { exact: true }).fill('browser-agent-renamed');
  await editDialog.getByLabel('Rate limit (rpm)').fill('30');
  await editDialog.getByRole('button', { name: 'Save changes' }).click();

  expect(api.updatedBody()).toEqual({
    // Sent on every edit since 2026-08-18, seeded from the key's current value
    // by `edit-api-key-dialog`, so an edit that does not touch it cannot clear
    // it. `toEqual` rather than `toMatchObject` here on purpose: the assertion
    // is that the form sends this and nothing else.
    default_capability: null,
    name: 'browser-agent-renamed',
    scopes: ['chat'],
    rate_limit_rpm: 30,
    quota_tokens_per_day: 1_000_000,
    allowed_cidrs: [],
  });
  const renamedRow = page
    .getByRole('row')
    .filter({ hasText: 'browser-agent-renamed' });
  await expect(renamedRow).toContainText('30 rpm');

  await renamedRow.getByRole('button', { name: 'Revoke' }).click();
  const revokeDialog = page.getByRole('dialog');
  await expect(revokeDialog).toContainText('Revoke browser-agent-renamed?');
  await revokeDialog.getByRole('button', { name: 'Revoke' }).click();

  await expect(page.getByText('No active keys')).toBeVisible();
  await page.getByRole('button', { name: 'Show 1 revoked' }).click();
  const revokedRow = page
    .getByRole('row')
    .filter({ hasText: 'browser-agent-renamed' });
  await expect(revokedRow).toContainText('Revoked');
  await expect(revokedRow.getByRole('button', { name: 'Edit' })).toHaveCount(
    0,
  );
  await expect(revokedRow.getByRole('button', { name: 'Revoke' })).toHaveCount(
    0,
  );
  expect(api.keys[0]?.revoked_at).not.toBeNull();
});
