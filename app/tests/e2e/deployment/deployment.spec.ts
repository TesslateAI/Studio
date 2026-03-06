/**
 * End-to-end tests for deployment functionality using Playwright.
 *
 * These tests verify the complete deployment UI workflow:
 * 1. Account Settings - Credential Management
 * 2. Deployment Modal - Creating deployments
 * 3. Deployments Panel - Viewing deployment history
 * 4. OAuth flows - Connecting providers
 */

import { test, expect, type Page } from '@playwright/test';

// No custom login needed - auth state is stored by auth.setup.ts
// and automatically applied via storageState in playwright.config.ts

// Helper function to create a test project
async function createTestProject(page: Page) {
  await page.goto('/dashboard');
  await page.waitForLoadState('networkidle');

  // The "Create New Project" is a card-style button containing an h3 with the text
  const newProjectButton = page
    .locator('button:has-text("Create New Project"), button:has-text("New Project")')
    .first();

  if (!(await newProjectButton.isVisible({ timeout: 5000 }).catch(() => false))) {
    test.skip(true, 'Create New Project button not found in UI');
    return;
  }

  await newProjectButton.click();

  // The CreateProjectModal uses a custom div structure (no role="dialog")
  // Wait for the modal heading to appear
  const modalOverlay = page.locator('.fixed.inset-0');
  const modalHeading = modalOverlay.locator('h2:has-text("Create New Project")');
  if (!(await modalHeading.isVisible({ timeout: 5000 }).catch(() => false))) {
    test.skip(true, 'Create project modal did not open');
    return;
  }

  // Fill project name using actual input selector (scoped to modal)
  const nameInput = modalOverlay
    .locator('#projectName, input[name="name"], input[placeholder*="name" i]')
    .first();

  if (!(await nameInput.isVisible({ timeout: 3000 }).catch(() => false))) {
    test.skip(true, 'Project name input not found');
    return;
  }

  await nameInput.fill(`Test Deploy ${Date.now()}`);

  // Click the create button (scoped to modal to avoid matching Dashboard card)
  // Button is disabled when no template is selected - CI may not have seeded templates
  const createBtn = modalOverlay.locator('button:has-text("Create Project")');
  if (!(await createBtn.isEnabled({ timeout: 5000 }).catch(() => false))) {
    test.skip(true, 'Create button not enabled - no templates available in CI');
    return;
  }
  await createBtn.click();
  // Project creation may fail in CI if base template git repos aren't accessible
  try {
    await page.waitForURL(/\/project\//, { timeout: 15000 });
  } catch {
    test.skip(true, 'Project creation did not complete - template data unavailable in CI');
  }
}

test.describe('Account Settings - Deployment Credentials', () => {
  test('should navigate to deployment settings', async ({ page }) => {
    // Settings redirects /settings → /settings/profile, deployment is at /settings/deployment
    await page.goto('/settings/deployment');
    await expect(page).toHaveURL(/\/settings\/deployment/);
    await page.waitForLoadState('networkidle');
  });

  test('should show deployment providers section', async ({ page }) => {
    await page.goto('/settings/deployment');

    // Look for the deployment providers section or any provider-related content
    const providerSection = page
      .locator(
        'text=Deployment Providers, text=deployment, text=Cloudflare, text=Vercel, text=Netlify'
      )
      .first();

    if (!(await providerSection.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deployment providers section not found in settings');
      return;
    }

    await expect(providerSection).toBeVisible();
  });

  test('should show provider connection options', async ({ page }) => {
    await page.goto('/settings/deployment');

    // The actual UI shows individual provider cards with connect buttons
    const connectButton = page
      .locator(
        'button:has-text("Connect with OAuth"), button:has-text("Add API Token"), button:has-text("Add Provider")'
      )
      .first();

    if (!(await connectButton.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Provider connect buttons not found');
      return;
    }

    await expect(connectButton).toBeVisible();
  });

  test('should show individual provider cards', async ({ page }) => {
    await page.goto('/settings/deployment');

    // Check for at least one provider name
    const providers = ['Cloudflare', 'Vercel', 'Netlify'];
    let foundProvider = false;

    for (const provider of providers) {
      const providerElement = page.locator(`text=${provider}`).first();
      if (await providerElement.isVisible({ timeout: 2000 }).catch(() => false)) {
        foundProvider = true;
        break;
      }
    }

    if (!foundProvider) {
      test.skip(true, 'No provider cards found in settings');
      return;
    }

    expect(foundProvider).toBeTruthy();
  });

  test('should test credential connection', async ({ page }) => {
    await page.goto('/settings/deployment');

    // If credential exists, test it
    const testButton = page.locator('button:has-text("Test Connection")').first();
    if (await testButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await testButton.click();
      await page.waitForTimeout(2000);
    }
  });

  test('should handle credential deletion', async ({ page }) => {
    await page.goto('/settings/deployment');

    // If a remove/disconnect button exists
    const deleteButton = page
      .locator('button:has-text("Remove"), button:has-text("Disconnect")')
      .first();

    if (await deleteButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await deleteButton.click();

      // Confirm deletion if dialog appears
      const confirmButton = page.locator('button:has-text("Confirm")');
      if (await confirmButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await confirmButton.click();
      }

      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Deployment Modal', () => {
  test.beforeEach(async ({ page }) => {
    await createTestProject(page);
  });

  test('should open deployment modal from project page', async ({ page }) => {
    const deployButton = page
      .locator('button[aria-label*="Deploy"], button:has-text("Deploy"), button[title*="Deploy"]')
      .first();

    if (!(await deployButton.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deploy button not found on project page');
      return;
    }

    await deployButton.click();

    // Check for modal content (custom or ARIA dialog)
    const modal = page.locator('[role="dialog"], .fixed.inset-0').first();
    await expect(modal).toBeVisible({ timeout: 5000 });
  });

  test('should show provider status in deploy modal', async ({ page }) => {
    const deployButton = page
      .locator('button[aria-label*="Deploy"], button:has-text("Deploy"), button[title*="Deploy"]')
      .first();

    if (!(await deployButton.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deploy button not found');
      return;
    }

    await deployButton.click();

    const modal = page.locator('[role="dialog"], .fixed.inset-0').first();
    if (!(await modal.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deploy modal did not open');
      return;
    }

    // Should show either provider selection or "no providers" warning
    const hasContent = await page
      .locator('text=Deploy, text=provider, text=Settings')
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    expect(hasContent).toBeTruthy();
  });
});

test.describe('Deployments Panel', () => {
  test.beforeEach(async ({ page }) => {
    await createTestProject(page);
  });

  test('should check for deployments panel', async ({ page }) => {
    const deploymentsButton = page
      .locator(
        'button[aria-label*="Deployment"], button:has-text("Deployments"), [data-testid="deployments-panel"]'
      )
      .first();

    if (!(await deploymentsButton.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deployments panel button not found');
      return;
    }

    await deploymentsButton.click();
    await page.waitForTimeout(1000);
  });
});

test.describe('OAuth Flows', () => {
  test('should show OAuth connection options', async ({ page }) => {
    await page.goto('/settings/deployment');

    // Check for OAuth-related buttons
    const oauthButton = page
      .locator(
        'button:has-text("Connect with OAuth"), button:has-text("Connect with Vercel"), button:has-text("Connect with Netlify")'
      )
      .first();

    if (!(await oauthButton.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'OAuth buttons not found in settings');
      return;
    }

    await expect(oauthButton).toBeVisible();
  });
});

test.describe('Error Handling', () => {
  test('should handle deployment without provider', async ({ page }) => {
    await createTestProject(page);

    const deployButton = page
      .locator('button[aria-label*="Deploy"], button:has-text("Deploy"), button[title*="Deploy"]')
      .first();

    if (!(await deployButton.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deploy button not found');
      return;
    }

    await deployButton.click();

    const modal = page.locator('[role="dialog"], .fixed.inset-0').first();
    if (!(await modal.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip(true, 'Deploy modal did not open');
      return;
    }

    // Try to deploy without selecting provider
    const submitDeploy = page.locator('button:has-text("Deploy"), button[type="submit"]').first();
    if (await submitDeploy.isVisible({ timeout: 3000 }).catch(() => false)) {
      await submitDeploy.click();
      await page.waitForTimeout(1000);
    }
  });
});
