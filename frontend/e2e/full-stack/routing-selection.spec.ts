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
// The admin entrance itself, not the Next origin `page` talks to. Only the
// failure path uses it, to tell a stale backend from a stale browser.
const adminApiUrl = process.env.E2E_ADMIN_API_URL ?? '';
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
    E2E_ADMIN_API_URL: adminApiUrl,
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
  try {
    await expect(
      page.getByRole('row').filter({ hasText: `${alias} (p100)` }),
    ).toBeVisible();
  } catch (failure) {
    // This assertion failed three times on main on 2026-08-18, on commits that
    // touched nothing near it, and the investigation ran out of evidence rather
    // than out of hypotheses. What the browser's trace could establish: the PUT
    // returned 200 with the new alias in its body, and a GET issued two
    // milliseconds later reached the server -- fresh `Date`, fourteen
    // milliseconds of server time, no `Age` -- and came back with the old one.
    // What nothing could establish is whether the *database* had the write by
    // then, and thirty rounds against the real admin entrance on a fast machine
    // never reproduced it, so the question cannot be answered by trying again
    // locally. It has to be answered on the run that fails.
    //
    // So the next failure records the fork instead of leaving it open. The poll
    // goes straight to the admin entrance, past both the browser and the Next
    // proxy that `page` speaks to, which is what makes the two answers mean
    // different things:
    //
    //   the API says the new alias  -> the write landed; the stale view came
    //                                  from the browser or the proxy in front
    //                                  of it, and the backend is not the place
    //                                  to look
    //   the API says the old alias  -> the write had not landed when the page
    //                                  refetched, and the timestamps below say
    //                                  how long it took to
    //
    // Deliberately not a retry: the assertion has already failed by the time
    // this runs and the failure is rethrown unchanged with the evidence added.
    // A poll that rescued the test would turn the one signal into silence.
    const evidence = await pollPolicyFromBothSides(page);
    await test.info().attach('admin-entrance-after-failure', {
      body: evidence,
      contentType: 'text/plain',
    });
    throw new Error(`${(failure as Error).message}\n\n${evidence}`);
  }
}

/**
 * What the chat policy looks like from both sides, for three seconds, once the
 * browser has already given up.
 *
 * Two readers, and the pair is the point. `direct` goes to the admin entrance
 * on its own port; `proxied` goes to the Next origin the page itself uses, so
 * it crosses the same middleware rewrite the failing refetch crossed. Between
 * them they name the layer:
 *
 *   direct new, proxied old  -> the write landed and something between the
 *                               browser and the backend served an older answer
 *   both old, then new       -> the backend had not committed yet, and the
 *                               timestamp says for how long
 *   both old, and they stay  -> the write did not land at all, and the PUT's
 *                               own 200 was describing something it never
 *                               persisted
 *
 * Timestamps are milliseconds from the first read, so a value that arrives late
 * is distinguishable from one that never arrives.
 *
 * Never throws: it runs on a path that is already failing, and an error here
 * would replace the real assertion's message with this function's.
 */
async function pollPolicyFromBothSides(page: Page): Promise<string> {
  const lines = [
    'chat policy after the assertion gave up',
    `  direct  = ${adminApiUrl}/admin/routing-policies`,
    '  proxied = the page origin, through the Next middleware rewrite',
    '',
  ];
  const started = Date.now();

  type Policy = { capability: string; candidates: { model_alias: string; priority: number }[] };

  const describe = async (
    read: () => Promise<{ status: number; body: unknown }>,
  ): Promise<string> => {
    try {
      const { status, body } = await read();
      const chat = (body as Policy[]).find((policy) => policy.capability === 'chat');
      const candidates = (chat?.candidates ?? [])
        .map((c) => `${c.model_alias} (p${c.priority})`)
        .join(', ');
      return `${status} ${candidates || '<no chat policy>'}`;
    } catch (error) {
      return `unreachable: ${String(error)}`;
    }
  };

  for (let i = 0; i < 12; i += 1) {
    const at = Date.now() - started;
    const direct = await describe(async () => {
      const response = await fetch(`${adminApiUrl}/admin/routing-policies`);
      return { status: response.status, body: await response.json() };
    });
    const proxied = await describe(async () => {
      const response = await page.request.get('/admin/routing-policies');
      return { status: response.status(), body: await response.json() };
    });
    lines.push(
      `  +${String(at).padStart(4)} ms   direct: ${direct.padEnd(28)} proxied: ${proxied}`,
    );
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return lines.join('\n');
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
