import { expect, test, type Locator, type Page } from '@playwright/test';

/**
 * The join the other browser paths deliberately do not make.
 *
 * `routing-policies.spec.ts` proves the form sends the right PUT, and the
 * backend integration suite proves the gateway routes on whatever is stored.
 * Both can be green while the two are connected to different things: an alias
 * the form writes and the gateway never reads, a capability name that means one
 * thing in the editor and another in the policy table, a save that lands in a
 * different tenant. Nothing observed a policy edit changing what the gateway
 * actually served, and ROADMAP has carried that gap since the editor shipped.
 *
 * Here the browser edits the policy through the real form against the real
 * admin entrance, and the assertion is the model reference a real HTTP runtime
 * was then asked for by the real gateway. Everything between is unmodified
 * application code over one Postgres.
 */

// One policy and one runtime recorder, both mutable, shared by everything in
// this file. Parallel execution would make each test's observation depend on
// what another had just changed.
test.describe.configure({ mode: 'serial' });

const gatewayUrl = process.env.E2E_GATEWAY_URL ?? '';
const gatewayKey = process.env.E2E_GATEWAY_KEY ?? '';
const runtimeUrl = process.env.E2E_RUNTIME_URL ?? '';
const initialAlias = process.env.E2E_INITIAL_ALIAS ?? '';
const refs: Record<string, string> = JSON.parse(process.env.E2E_MODEL_REFS ?? '{}');

const otherAlias =
  Object.keys(refs).find((alias) => alias !== initialAlias) ?? '';

/**
 * Fail rather than skip on missing wiring.
 *
 * A skip here would be indistinguishable from a pass in every report, and this
 * file exists precisely because a gap that nothing reported stayed open for
 * weeks. The runner sets all of these together or starts nothing.
 */
test.beforeAll(() => {
  const missing = Object.entries({
    E2E_GATEWAY_URL: gatewayUrl,
    E2E_GATEWAY_KEY: gatewayKey,
    E2E_RUNTIME_URL: runtimeUrl,
    E2E_INITIAL_ALIAS: initialAlias,
  })
    .filter(([, value]) => !value)
    .map(([name]) => name);
  expect(
    missing,
    'The full-stack harness must supply the gateway, its key and the runtime.',
  ).toEqual([]);
  expect(otherAlias, 'The harness must seed a second alias to switch to.').toBeTruthy();
});

/**
 * Open one select and choose from the list that select owns.
 *
 * The same reasoning as `routing-policies.spec.ts`: Base UI portals the popup
 * to the document body and leaves it mounted after it closes, so a page-wide
 * query for an option can land in a list the test has already finished with.
 */
async function chooseOption(page: Page, trigger: Locator, option: string) {
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  const listId = await trigger.getAttribute('aria-controls');
  expect(listId, 'An open select must name the list it controls.').toBeTruthy();
  await page
    .locator(`[id="${listId}"]`)
    .getByRole('option', { name: option, exact: true })
    .click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
}

async function resetRuntime() {
  const response = await fetch(`${runtimeUrl}/__e2e__/reset`, { method: 'POST' });
  expect(response.ok, 'The fake runtime must accept a reset.').toBeTruthy();
}

async function generationsSeen(): Promise<{ model: string }[]> {
  const response = await fetch(`${runtimeUrl}/__e2e__/generations`);
  expect(response.ok, 'The fake runtime must report what it was asked for.').toBeTruthy();
  const body = (await response.json()) as { generations: { model: string }[] };
  return body.generations;
}

/**
 * One non-streaming completion through the gateway, as an integrator would.
 *
 * `model: 'chat'` is the capability, not a model name: which model answers is
 * the routing policy's decision, and that is the whole point of the assertion
 * below.
 */
async function askTheGateway() {
  const response = await fetch(`${gatewayUrl}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${gatewayKey}`,
    },
    body: JSON.stringify({
      model: 'chat',
      messages: [{ role: 'user', content: 'which model is this' }],
      stream: false,
    }),
  });
  expect(
    response.status,
    `The gateway refused the completion: ${await response.clone().text()}`,
  ).toBe(200);
  return response.json();
}

async function selectSoleCandidate(page: Page, alias: string) {
  const row = page.getByRole('row').filter({ hasText: 'chat' }).first();
  await row.getByRole('button', { name: 'Edit' }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Edit routing policy')).toBeVisible();
  await chooseOption(page, dialog.getByLabel('Model alias').first(), alias);
  await dialog.getByRole('button', { name: 'Save changes' }).click();
  await expect(dialog).toBeHidden();

  // Asserted against the table the page refetched, so the test proceeds on what
  // the server returned rather than on the optimistic state of a form.
  await expect(
    page.getByRole('row').filter({ hasText: `${alias} (p100)` }),
  ).toBeVisible();
}

test('a routing policy edited in the browser changes which model the gateway serves', async ({
  page,
}) => {
  await resetRuntime();

  // The seeded policy first, so the switch below is a change rather than the
  // only state ever observed. Without this the test could pass against a
  // gateway that always served the second alias for an unrelated reason.
  const before = await askTheGateway();
  expect(before.choices[0].message.content).toContain(refs[initialAlias]);
  expect((await generationsSeen()).map((g) => g.model)).toEqual([refs[initialAlias]]);

  await page.goto('/routing-policies');
  await selectSoleCandidate(page, otherAlias);

  await resetRuntime();
  const after = await askTheGateway();

  expect(after.choices[0].message.content).toContain(refs[otherAlias]);
  expect((await generationsSeen()).map((g) => g.model)).toEqual([refs[otherAlias]]);
});
