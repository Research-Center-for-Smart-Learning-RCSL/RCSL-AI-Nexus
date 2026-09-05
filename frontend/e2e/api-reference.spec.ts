import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 } });

test('uses error cards without horizontal document overflow on a phone viewport', async ({
  page,
}) => {
  await page.goto('/api-docs');

  await expect(page.getByRole('heading', { name: 'Errors' })).toBeVisible();
  await expect(page.getByTestId('api-error-card')).toHaveCount(17);
  await expect(page.getByRole('table')).toBeHidden();

  expect(
    await page.locator('html').evaluate((element) => element.scrollWidth <= window.innerWidth),
  ).toBe(true);

  const search = page.getByRole('searchbox', { name: 'Search errors' });
  await search.fill('quota_exceeded');

  await expect(page.getByTestId('api-error-card')).toHaveCount(1);
  await expect(page.getByTestId('api-error-card')).toContainText('429');
  await expect(page.getByTestId('api-error-card')).toContainText('quota_exceeded');
  expect(
    await page.locator('html').evaluate((element) => element.scrollWidth <= window.innerWidth),
  ).toBe(true);
});
