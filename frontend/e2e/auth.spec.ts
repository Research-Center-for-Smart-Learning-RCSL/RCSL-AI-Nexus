import { expect, test, type Page, type Route } from '@playwright/test';

const JSON_HEADERS = { 'content-type': 'application/json' };
const CSRF_TOKEN = 'csrf-e2e-auth';

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

function unauthenticated(route: Route) {
  return json(
    route,
    401,
    {
      code: 'authentication_required',
      message: 'Authentication required.',
      auth_mode: 'local',
    },
    { 'set-cookie': `nexus_csrf=${CSRF_TOKEN}; Path=/; SameSite=Lax` },
  );
}

function expectCsrf(route: Route) {
  expect(route.request().headers()['x-csrf-token']).toBe(CSRF_TOKEN);
}

function authenticated(route: Route) {
  return json(route, 200, {
    id: '11111111-1111-1111-1111-111111111111',
    auth_mode: 'local',
    login: 'operator@example.org',
    display_name: 'Operator',
    role: 'operator',
    scopes: ['chat:use'],
    session_expires_at: '2099-01-01T00:00:00Z',
  });
}

async function mockAdmin(page: Page, handler: (route: Route, url: URL) => Promise<void>) {
  await page.route('**/admin/**', async (route) => {
    const url = new URL(route.request().url());
    await handler(route, url);
  });
}

test('signs in with password and TOTP, then refreshes identity before redirecting', async ({
  page,
}) => {
  let signedIn = false;
  let authenticatedMeCalls = 0;
  let passwordBody: unknown;
  let totpBody: unknown;

  await mockAdmin(page, async (route, url) => {
    const request = route.request();
    if (url.pathname === '/admin/me') {
      if (signedIn) authenticatedMeCalls += 1;
      await (signedIn ? authenticated(route) : unauthenticated(route));
      return;
    }
    if (url.pathname === '/admin/auth/login' && request.method() === 'POST') {
      expectCsrf(route);
      passwordBody = request.postDataJSON();
      await json(route, 200, { challenge: 'challenge-123', next: 'totp' });
      return;
    }
    if (url.pathname === '/admin/auth/login/totp' && request.method() === 'POST') {
      expectCsrf(route);
      totpBody = request.postDataJSON();
      signedIn = true;
      await route.fulfill({ status: 204 });
      return;
    }
    await json(route, 404, { message: `Unhandled test route: ${url.pathname}` });
  });

  await page.goto('/login?next=%2Fchat');
  await page.getByLabel('Login').fill('operator@example.org');
  await page.getByLabel('Password').fill('not-a-real-password');
  await page.getByRole('button', { name: 'Continue' }).click();

  await expect(page.getByLabel('Verification code')).toBeVisible();
  expect(passwordBody).toEqual({
    login: 'operator@example.org',
    password: 'not-a-real-password',
  });

  await page.getByLabel('Verification code').fill('123456');
  await page.getByRole('button', { name: 'Sign in' }).click();

  // The default production build serves /chat immediately; under `--dev` this
  // navigation may cold-compile it while every worker starts at once. Left
  // wide enough for that path, since the assertions below — not this deadline
  // — are what prove the identity refetch gated the redirect.
  await expect(page).toHaveURL(/\/chat$/, { timeout: 20_000 });
  await expect(page.getByRole('textbox', { name: 'Message' })).toBeVisible();
  expect(authenticatedMeCalls).toBeGreaterThanOrEqual(1);
  expect(totpBody).toEqual({ challenge: 'challenge-123', code: '123456' });
});

test('requires recovery codes to be acknowledged after invitation enrolment', async ({
  page,
}) => {
  const token = 'invite-token-123';
  const password = 'Asterism-vault-river-constellation-927!';
  let acceptanceBody: unknown;

  await mockAdmin(page, async (route, url) => {
    const request = route.request();
    if (url.pathname === '/admin/me') {
      await unauthenticated(route);
      return;
    }
    if (url.pathname === '/admin/invitations' && request.method() === 'GET') {
      expect(url.searchParams.get('token')).toBe(token);
      await json(route, 200, {
        provisioning_uri: 'otpauth://totp/RCSL:test?secret=JBSWY3DPEHPK3PXP',
        secret: 'JBSWY3DPEHPK3PXP',
        login: 'new-user@example.org',
      });
      return;
    }
    if (url.pathname === '/admin/invitations/totp-qr') {
      expect(url.searchParams.get('token')).toBe(token);
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"/>',
      });
      return;
    }
    if (url.pathname === '/admin/invitations/accept' && request.method() === 'POST') {
      expectCsrf(route);
      acceptanceBody = request.postDataJSON();
      await json(route, 200, {
        recovery_codes: [
          'amber-river-01',
          'cobalt-vault-02',
          'cedar-orbit-03',
          'lunar-field-04',
          'maple-signal-05',
          'opal-garden-06',
          'quartz-harbor-07',
          'silver-comet-08',
          'violet-bridge-09',
          'willow-star-10',
        ],
      });
      return;
    }
    await json(route, 404, { message: `Unhandled test route: ${url.pathname}` });
  });

  await page.goto(`/accept-invite?token=${token}`);
  await expect(page.getByText('Setting up new-user@example.org')).toBeVisible();
  await expect(page.getByAltText('TOTP provisioning QR code')).toBeVisible();

  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password', { exact: true }).fill(password);
  await page.getByLabel('Code from your authenticator').fill('654321');
  await page.getByRole('button', { name: 'Create account' }).click();

  await expect(page.getByText('Your recovery codes')).toBeVisible();
  expect(acceptanceBody).toEqual({
    token,
    password,
    totp_code: '654321',
  });

  const continueButton = page.getByRole('button', { name: 'Go to the dashboard' });
  await expect(continueButton).toBeDisabled();
  await page.getByRole('checkbox', { name: 'I have saved these' }).check();
  await expect(continueButton).toBeEnabled();
});
