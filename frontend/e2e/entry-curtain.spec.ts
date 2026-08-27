import { expect, test } from '@playwright/test';

/**
 * The one spec that sees the entry curtain. Every other context runs with
 * reducedMotion 'reduce' (playwright.config.ts), under which no curtain
 * mounts at all — so without this file, a regression anywhere in the real
 * path (the dynamic scene import, the first-frame signal that lifts the
 * opaque cover, the exit) would leave first-time visitors staring at a blank
 * z-[100] layer while every suite stayed green.
 */
test.use({ contextOptions: { reducedMotion: 'no-preference' } });

test('the login curtain plays its real path and releases the form', async ({ page }) => {
  await page.goto('/login');

  const curtain = page.getByTestId('entry-curtain-tunnel');
  await expect(curtain).toBeVisible();

  // The cover lifting is the signal that something actually rendered — the
  // WebGL scene's first frame, or the CSS fallback on a machine without one.
  await expect(page.getByTestId('entry-curtain-cover')).toHaveClass(/opacity-0/, {
    timeout: 4000,
  });

  // Gone within its own watchdog ceiling, and the form is usable after it.
  await expect(curtain).toBeHidden({ timeout: 8000 });
  await expect(page.getByLabel('Login')).toBeFocused();
});

test('a second visit in the same tab session skips the curtain', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByTestId('entry-curtain-tunnel')).toBeHidden({ timeout: 8000 });

  await page.goto('/login');
  await expect(page.getByLabel('Login')).toBeVisible();
  await expect(page.getByTestId('entry-curtain-tunnel')).toHaveCount(0);
});
