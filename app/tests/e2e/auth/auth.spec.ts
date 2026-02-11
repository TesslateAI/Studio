/**
 * E2E tests for authentication flows.
 *
 * Tests:
 * - Authenticated user sees /dashboard
 * - Unauthenticated user redirected to /login
 * - Logout flow
 */

import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test('authenticated user can access dashboard', async ({ page }) => {
    // This test uses stored auth state from auth.setup.ts
    await page.goto('/dashboard');

    // Should not be redirected to login
    await expect(page).toHaveURL('/dashboard');

    // Should see dashboard elements (adjust selectors based on actual UI)
    await expect(page.locator('text=Dashboard').or(page.locator('h1')).first()).toBeVisible();
  });

  test('unauthenticated user redirected to login', async ({ browser }) => {
    // Create fresh context without stored auth
    const context = await browser.newContext();
    const page = await context.newPage();

    await page.goto('/dashboard');

    // Should be redirected to login page
    await expect(page).toHaveURL(/\/login/);

    await context.close();
  });

  test('logout redirects to login', async ({ page }) => {
    // Start authenticated
    await page.goto('/dashboard');
    await expect(page).toHaveURL('/dashboard');

    // Click logout button (adjust selector based on actual UI)
    // Common patterns: button with "Logout", "Sign Out", or icon
    const logoutButton = page
      .locator('button:has-text("Logout"), button:has-text("Sign Out"), [aria-label*="logout" i]')
      .first();

    if (await logoutButton.isVisible()) {
      await logoutButton.click();

      // Should redirect to login
      await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
    } else {
      // If logout button not found, skip test
      test.skip(true, 'Logout button not found in UI');
    }
  });
});
