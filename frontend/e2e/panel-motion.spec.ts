import { expect, test } from '@playwright/test';

const VIEWPORTS = [
  { width: 390, height: 844, mobile: true },
  { width: 768, height: 844, mobile: true },
  { width: 1024, height: 844, mobile: false },
  { width: 1280, height: 844, mobile: false },
];

test.describe('panel motion', () => {
  test.use({ contextOptions: { reducedMotion: 'no-preference' } });

  test('moves mobile navigation, keeps its exit inert, and restores menu focus', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/chat');

    const trigger = page.getByRole('button', { name: 'Open the menu' });
    await trigger.click();
    // Closing sets aria-hidden at the start of the exit, so role-based
    // locators deliberately stop seeing it. The DOM selector verifies the
    // visual-only interval that remains.
    const panel = page.locator('[role="dialog"][aria-label="Navigation"]');
    await expect(panel).toHaveAttribute('data-panel-state', 'open');
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');

    await page.getByRole('button', { name: 'Close the menu' }).click();
    await expect(panel).toHaveAttribute('data-panel-state', 'closed');
    await expect(panel).toHaveAttribute('inert', '');
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(panel).toHaveCount(0, { timeout: 1_000 });
    await expect(trigger).toBeFocused();
  });

  for (const viewport of VIEWPORTS) {
    test(`keeps assistant geometry and the document width sound at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto('/chat');
      await page.getByRole('button', { name: 'Open the assistant' }).click();

      const drawer = page.getByRole('complementary', { name: 'Management assistant' });
      await expect(drawer).toHaveAttribute('data-panel-state', 'open');
      await expect(drawer).not.toHaveAttribute('aria-modal');
      await expect(page.locator('.nexus-panel-backdrop')).toHaveCount(0);
      await expect
        .poll(() =>
          page.evaluate(
            () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          ),
        )
        .toBe(true);

      const drawerBox = await drawer.boundingBox();
      expect(drawerBox).not.toBeNull();
      if (viewport.mobile) {
        expect(Math.round(drawerBox!.width)).toBe(viewport.width);
      } else {
        expect(Math.round(drawerBox!.width)).toBe(384);
        expect(Math.round(drawerBox!.x)).toBe(viewport.width - 384);
        await expect(page.locator('.h-\\[100dvh\\]')).toHaveClass(/lg:pr-96/);
      }
    });
  }
});

test('reduced motion opens and closes panels without an animation wait', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Open the menu' }).click();
  await page.getByRole('button', { name: 'Close the menu' }).click();

  await expect(page.getByRole('dialog', { name: 'Navigation' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Open the menu' })).toBeFocused();
});
