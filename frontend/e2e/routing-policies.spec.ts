import { expect, test, type Page, type Route } from '@playwright/test';

const JSON_HEADERS = { 'content-type': 'application/json' };
const CSRF_TOKEN = 'csrf-e2e-routing';

type Requirement = {
  node_status: string[];
  model_state: string[];
  min_free_memory_gb: number | null;
};

type Candidate = {
  model_alias: string;
  priority: number;
  require: Requirement;
};

type SavePolicyBody = {
  candidates: Candidate[];
  thinking: boolean | null;
};

type Policy = SavePolicyBody & { capability: string };

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

function model(id: string, alias: string) {
  return {
    id,
    alias,
    ref: `${alias}:latest`,
    runtime: 'ollama',
    node_id: 'node-e2e-1',
    state: 'loaded',
    capabilities: ['chat'],
    resource_profile: { memory_gb: 8, context_length: 32_768 },
    observed_state: 'loaded',
    observed_memory_gb: 8,
    observed_at: '2026-08-06T00:00:00Z',
  };
}

async function installAdminApi(page: Page) {
  let policy: Policy = {
    capability: 'chat',
    candidates: [
      {
        model_alias: 'qwen-chat',
        priority: 100,
        require: {
          node_status: ['online'],
          model_state: ['loaded'],
          min_free_memory_gb: 8,
        },
      },
    ],
    thinking: null,
  };
  let savedBody: SavePolicyBody | null = null;
  let listReads = 0;
  let listReadsAtSave: number | null = null;

  await page.route('**/admin/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (url.pathname === '/admin/me' && request.method() === 'GET') {
      await json(
        route,
        200,
        {
          id: '33333333-3333-3333-3333-333333333333',
          auth_mode: 'local',
          login: 'operator@example.org',
          display_name: 'Operator',
          role: 'operator',
          scopes: ['model:read', 'routing:read', 'routing:write'],
          session_expires_at: '2099-01-01T00:00:00Z',
        },
        {
          'set-cookie': `nexus_csrf=${CSRF_TOKEN}; Path=/; SameSite=Lax`,
        },
      );
      return;
    }

    if (
      url.pathname === '/admin/routing-policies' &&
      request.method() === 'GET'
    ) {
      listReads += 1;
      await json(route, 200, [policy]);
      return;
    }

    if (url.pathname === '/admin/models' && request.method() === 'GET') {
      await json(route, 200, [
        model('model-e2e-chat', 'qwen-chat'),
        model('model-e2e-fast', 'qwen-fast'),
      ]);
      return;
    }

    if (
      url.pathname === '/admin/routing-policies/chat' &&
      request.method() === 'PUT'
    ) {
      expect(request.headers()['x-csrf-token']).toBe(CSRF_TOKEN);
      listReadsAtSave = listReads;
      savedBody = request.postDataJSON() as SavePolicyBody;
      policy = { capability: 'chat', ...savedBody };
      await json(route, 200, policy);
      return;
    }

    await json(route, 404, { message: `Unhandled test route: ${url.pathname}` });
  });

  return {
    listReads: () => listReads,
    listReadsAtSave: () => listReadsAtSave,
    savedBody: () => savedBody,
  };
}

test('edits a routing policy and refetches the saved state', async ({ page }) => {
  const api = await installAdminApi(page);

  await page.goto('/routing-policies');
  const initialRow = page.getByRole('row').filter({ hasText: 'qwen-chat (p100)' });
  await expect(initialRow).toContainText('Deployment default');
  await initialRow.getByRole('button', { name: 'Edit' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Edit routing policy')).toBeVisible();

  await dialog.getByLabel('Deliberation').click();
  await page.getByRole('option', { name: 'Answer directly' }).click();

  await dialog.getByLabel('Model alias').first().click();
  await page.getByRole('option', { name: 'qwen-fast', exact: true }).click();
  await dialog.getByLabel('Priority').first().fill('200');
  await dialog.getByLabel('Minimum free memory (GB)').first().fill('16');

  await dialog.getByRole('button', { name: 'Add candidate' }).click();
  await dialog.getByLabel('Model alias').nth(1).click();
  await page.getByRole('option', { name: 'qwen-chat', exact: true }).click();
  await dialog.getByLabel('Priority').nth(1).fill('50');
  await dialog
    .getByRole('checkbox', { name: 'degraded', exact: true })
    .nth(1)
    .check();
  await dialog
    .getByRole('checkbox', { name: 'downloaded', exact: true })
    .nth(1)
    .check();

  await dialog.getByRole('button', { name: 'Save changes' }).click();

  expect(api.savedBody()).toEqual({
    candidates: [
      {
        model_alias: 'qwen-fast',
        priority: 200,
        require: {
          node_status: ['online'],
          model_state: ['loaded'],
          min_free_memory_gb: 16,
        },
      },
      {
        model_alias: 'qwen-chat',
        priority: 50,
        require: {
          node_status: ['degraded'],
          model_state: ['downloaded'],
          min_free_memory_gb: null,
        },
      },
    ],
    thinking: false,
  });

  const savedRow = page.getByRole('row').filter({ hasText: 'qwen-fast (p200)' });
  await expect(savedRow.getByRole('cell').nth(1)).toHaveText('2');
  await expect(savedRow).toContainText('qwen-chat (p50)');
  await expect(savedRow).toContainText('Answer directly');
  expect(api.listReadsAtSave()).not.toBeNull();
  expect(api.listReads()).toBeGreaterThan(api.listReadsAtSave()!);
});
