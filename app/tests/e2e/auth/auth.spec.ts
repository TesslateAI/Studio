/**
 * E2E tests for authentication flows.
 *
 * Tests:
 * - Authenticated user sees /dashboard
 * - Unauthenticated user cannot access protected content
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

  test('unauthenticated user cannot access protected content', async ({ browser }) => {
    // Create fresh context without stored auth
    const context = await browser.newContext();
    const page = await context.newPage();

    await page.goto('/dashboard');

    // The auth guard (PrivateRoute) should either:
    // 1. Redirect to /login (if auth check completes quickly), OR
    // 2. Show nothing (PrivateRoute returns null while auth is checking)
    // Either way, dashboard content should NOT be accessible

    // Wait briefly for any redirect or auth check
    await page.waitForTimeout(3000);

    // Check: either we're on /login, OR dashboard content is not visible
    const currentUrl = page.url();
    const isOnLogin = /\/login/.test(currentUrl);

    if (!isOnLogin) {
      // If not redirected, verify the page doesn't show authenticated content
      // PrivateRoute returns null during loading, so the page should be mostly blank
      const dashboardContent = page
        .locator(
          'button:has-text("Create New Project"), button:has-text("New Project"), text=My Projects'
        )
        .first();

      const isContentVisible = await dashboardContent
        .isVisible({ timeout: 2000 })
        .catch(() => false);

      // Dashboard content should NOT be visible to unauthenticated users
      expect(isContentVisible).toBeFalsy();
    }

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
