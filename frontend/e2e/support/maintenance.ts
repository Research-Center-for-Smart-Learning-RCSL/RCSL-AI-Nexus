import type { Route } from '@playwright/test';

/**
 * The public maintenance status (#61) every mocked admin API must answer.
 *
 * The shell renders nothing protected until this has been read once, so a
 * spec that mocks `/admin/**` without it would see the "could not check
 * whether the platform is open" state rather than the screen under test.
 */
export const OPEN_MAINTENANCE_STATUS = {
  closed: false,
  phase: 'normal',
  message: null,
  expected_return_at: null,
  revision: 0,
};

/** Answers the status read and returns true, or returns false for any other route. */
export async function fulfillOpenMaintenance(route: Route, url: URL): Promise<boolean> {
  if (url.pathname !== '/admin/maintenance/status') return false;
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(OPEN_MAINTENANCE_STATUS),
  });
  return true;
}
