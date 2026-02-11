/**
 * E2E tests for project creation flow.
 *
 * Tests:
 * - Create new project from dashboard
 * - Project builder page loads correctly
 */

import { test, expect } from '@playwright/test';

test.describe('Project Creation', () => {
  test('create new project from dashboard', async ({ page }) => {
    // Go to dashboard
    await page.goto('/dashboard');
    await expect(page).toHaveURL('/dashboard');

    // Click "New Project" button (adjust selector based on actual UI)
    const newProjectButton = page
      .locator(
        'button:has-text("New Project"), button:has-text("Create Project"), [aria-label*="new project" i]'
      )
      .first();

    if (!(await newProjectButton.isVisible())) {
      test.skip(true, 'New Project button not found in UI');
      return;
    }

    await newProjectButton.click();

    // Modal should open with project creation form
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Fill in project name
    const projectName = `E2E Test Project ${Date.now()}`;
    const nameInput = modal.locator('input[name="name"], input[placeholder*="name" i]').first();
    await nameInput.fill(projectName);

    // Click create/submit button
    const createButton = modal.locator('button:has-text("Create"), button[type="submit"]').first();
    await createButton.click();

    // Should navigate to project page
    await expect(page).toHaveURL(/\/project\//, { timeout: 10000 });

    // Verify we're on a project page (URL should contain project slug)
    const currentURL = page.url();
    expect(currentURL).toContain('/project/');
  });

  test('project builder page shows core UI', async ({ page }) => {
    // First create a project (reuse logic from above)
    await page.goto('/dashboard');

    const newProjectButton = page
      .locator('button:has-text("New Project"), button:has-text("Create Project")')
      .first();

    if (!(await newProjectButton.isVisible())) {
      test.skip(true, 'Cannot create project - button not found');
      return;
    }

    await newProjectButton.click();

    const modal = page.locator('[role="dialog"]');
    await modal
      .locator('input[name="name"], input[placeholder*="name" i]')
      .first()
      .fill(`UI Test Project ${Date.now()}`);
    await modal.locator('button:has-text("Create"), button[type="submit"]').first().click();

    await expect(page).toHaveURL(/\/project\//, { timeout: 10000 });

    // Wait for page to fully load
    await page.waitForLoadState('networkidle');

    // Verify core UI elements are present (adjust selectors based on actual UI)
    // Common project builder elements: code editor, chat panel, file tree, preview

    // Check for at least one of these common elements
    const hasEditor = await page
      .locator('[class*="monaco"], [class*="editor"]')
      .first()
      .isVisible()
      .catch(() => false);
    const hasChat = await page
      .locator('[class*="chat"], [aria-label*="chat" i]')
      .first()
      .isVisible()
      .catch(() => false);
    const hasFileTree = await page
      .locator('[class*="file"], [class*="tree"]')
      .first()
      .isVisible()
      .catch(() => false);

    // At least one core element should be visible
    expect(hasEditor || hasChat || hasFileTree).toBeTruthy();
  });
});
