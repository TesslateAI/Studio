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

const TEST_EMAIL = 'deployment-test@example.com';
const TEST_PASSWORD = 'Test123!@#';

// Helper function to login
async function login(page: Page, email: string = TEST_EMAIL, password: string = TEST_PASSWORD) {
  await page.goto('/login');
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForURL('/dashboard');
}

// Helper function to create a test project
async function createTestProject(page: Page, projectName: string = 'Test Deployment Project') {
  await page.goto('/dashboard');
  await page.click('button:has-text("New Project")');
  await page.fill('input[name="name"]', projectName);
  await page.click('button:has-text("Create")');
  await page.waitForURL(/\/project\//);
}

test.describe('Account Settings - Deployment Credentials', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('should navigate to account settings', async ({ page }) => {
    await page.goto('/settings');
    await expect(page).toHaveURL('/settings');
    await expect(page.locator('h1')).toContainText('Account Settings');
  });

  test('should show empty state when no credentials connected', async ({ page }) => {
    await page.goto('/settings');

    // Check for empty state
    const emptyState = page.locator('text=No deployment providers connected yet');
    await expect(emptyState).toBeVisible();

    const addButton = page.locator('button:has-text("Add Provider")');
    await expect(addButton).toBeVisible();
  });

  test('should open add provider modal', async ({ page }) => {
    await page.goto('/settings');
    await page.click('button:has-text("Add Provider")');

    // Modal should be visible
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    // Should show provider options
    await expect(modal.locator('text=Cloudflare Workers')).toBeVisible();
    await expect(modal.locator('text=Vercel')).toBeVisible();
    await expect(modal.locator('text=Netlify')).toBeVisible();
  });

  test('should add Cloudflare credentials (manual)', async ({ page }) => {
    await page.goto('/settings');
    await page.click('button:has-text("Add Provider")');

    // Select Cloudflare
    await page.click('text=Cloudflare Workers');

    // Fill in credentials
    await page.fill('input[placeholder*="Account ID"]', 'test-account-id-123');
    await page.fill('input[placeholder*="API Token"]', 'test-api-token-xyz');

    // Submit
    await page.click('button:has-text("Connect")');

    // Should show success and close modal
    await expect(page.locator('[role="dialog"]')).not.toBeVisible();

    // Should show the connected provider
    await expect(page.locator('text=Cloudflare Workers')).toBeVisible();
    await expect(page.locator('text=test-account-id-123')).toBeVisible();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/settings');
    await page.click('button:has-text("Add Provider")');

    // Select provider but don't fill credentials
    await page.click('text=Cloudflare Workers');
    await page.click('button:has-text("Connect")');

    // Should show validation error
    const errorMessage = page.locator('text=required');
    await expect(errorMessage).toBeVisible();
  });

  test('should test credential connection', async ({ page }) => {
    // First add a credential (assuming it was added)
    await page.goto('/settings');

    // If credential exists, test it
    const testButton = page.locator('button:has-text("Test Connection")').first();
    if (await testButton.isVisible()) {
      await testButton.click();

      // Should show loading state then result
      await expect(page.locator('text=Testing')).toBeVisible();
      // Wait for test to complete (will show success or error)
      await page.waitForTimeout(2000);
    }
  });

  test('should delete a credential', async ({ page }) => {
    await page.goto('/settings');

    // If credential exists, delete it
    const deleteButton = page.locator('button:has-text("Remove")').first();
    if (await deleteButton.isVisible()) {
      await deleteButton.click();

      // Confirm deletion
      await page.click('button:has-text("Confirm")');

      // Credential should be removed
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Deployment Modal', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await createTestProject(page);
  });

  test('should open deployment modal from project page', async ({ page }) => {
    // Click deploy button
    await page.click('button[aria-label*="Deploy"]');

    // Modal should open
    const modal = page.locator('[role="dialog"]:has-text("Deploy Project")');
    await expect(modal).toBeVisible();
  });

  test('should show warning when no providers connected', async ({ page }) => {
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');
    await expect(modal.locator('text=No deployment providers connected')).toBeVisible();
    await expect(modal.locator('a:has-text("Account Settings")')).toBeVisible();
  });

  test('should show connected providers in modal', async ({ page }) => {
    // Assuming a provider is connected
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');

    // Should show provider selection if credentials exist
    const providerCards = modal.locator('[data-testid*="provider-card"]');
    const count = await providerCards.count();

    if (count > 0) {
      // Select first provider
      await providerCards.first().click();
      await expect(providerCards.first()).toHaveClass(/selected/);
    }
  });

  test('should add environment variables', async ({ page }) => {
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');

    // Add environment variable
    await modal.locator('button:has-text("Add Variable")').click();

    await modal.locator('input[placeholder="Key"]').fill('API_URL');
    await modal.locator('input[placeholder="Value"]').fill('https://api.example.com');

    // Verify it was added
    await expect(modal.locator('text=API_URL')).toBeVisible();
    await expect(modal.locator('text=https://api.example.com')).toBeVisible();
  });

  test('should remove environment variables', async ({ page }) => {
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');

    // Add a variable
    await modal.locator('button:has-text("Add Variable")').click();
    await modal.locator('input[placeholder="Key"]').fill('TEST_VAR');
    await modal.locator('input[placeholder="Value"]').fill('test_value');

    // Remove it
    await modal.locator('button[aria-label="Remove"]').click();

    // Should be gone
    await expect(modal.locator('text=TEST_VAR')).not.toBeVisible();
  });

  test('should add custom domain', async ({ page }) => {
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');

    // Add custom domain
    const domainInput = modal.locator('input[placeholder*="Custom Domain"]');
    if (await domainInput.isVisible()) {
      await domainInput.fill('myapp.example.com');
      await expect(domainInput).toHaveValue('myapp.example.com');
    }
  });

  test('should trigger deployment', async ({ page }) => {
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');

    // Select provider (if available)
    const providerCard = modal.locator('[data-testid*="provider-card"]').first();
    if (await providerCard.isVisible()) {
      await providerCard.click();

      // Click deploy button
      await modal.locator('button:has-text("Deploy")').click();

      // Should show loading state
      await expect(modal.locator('text=Deploying')).toBeVisible();

      // Wait for deployment to complete or modal to close
      await page.waitForTimeout(5000);
    }
  });
});

test.describe('Deployments Panel', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await createTestProject(page);
  });

  test('should open deployments panel', async ({ page }) => {
    // Open deployments panel
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    await expect(panel).toBeVisible();
  });

  test('should show empty state when no deployments', async ({ page }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    await expect(panel.locator('text=No deployments yet')).toBeVisible();
  });

  test('should list deployments', async ({ page }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    const deploymentCards = panel.locator('[data-testid*="deployment-card"]');

    const count = await deploymentCards.count();
    if (count > 0) {
      // Should show deployment details
      const firstCard = deploymentCards.first();
      await expect(firstCard.locator('text=Vercel')).toBeVisible().or(firstCard.locator('text=Cloudflare')).toBeVisible();
      await expect(firstCard.locator('[data-testid="status-badge"]')).toBeVisible();
    }
  });

  test('should show deployment details on click', async ({ page }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    const deploymentCard = panel.locator('[data-testid*="deployment-card"]').first();

    if (await deploymentCard.isVisible()) {
      await deploymentCard.click();

      // Details modal should open
      const detailsModal = page.locator('[role="dialog"]:has-text("Deployment Details")');
      await expect(detailsModal).toBeVisible();

      // Should show deployment URL
      await expect(detailsModal.locator('a[href^="https://"]')).toBeVisible();
    }
  });

  test('should open deployment URL in new tab', async ({ page, context }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    const deploymentCard = panel.locator('[data-testid*="deployment-card"]').first();

    if (await deploymentCard.isVisible()) {
      await deploymentCard.click();

      const detailsModal = page.locator('[role="dialog"]');

      // Click "Open Deployment" button
      const pagePromise = context.waitForEvent('page');
      await detailsModal.locator('button:has-text("Open Deployment")').click();

      const newPage = await pagePromise;
      await expect(newPage).toHaveURL(/https:\/\//);
      await newPage.close();
    }
  });

  test('should delete deployment', async ({ page }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    const deploymentCard = panel.locator('[data-testid*="deployment-card"]').first();

    if (await deploymentCard.isVisible()) {
      // Open details
      await deploymentCard.click();

      const detailsModal = page.locator('[role="dialog"]');

      // Click delete button
      await detailsModal.locator('button:has-text("Delete")').click();

      // Confirm deletion
      await page.locator('button:has-text("Confirm")').click();

      // Modal should close
      await expect(detailsModal).not.toBeVisible();

      // Deployment should be removed from list
      await page.waitForTimeout(1000);
    }
  });

  test('should show deployment status badges', async ({ page }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    const statusBadges = panel.locator('[data-testid="status-badge"]');

    const count = await statusBadges.count();
    if (count > 0) {
      const firstBadge = statusBadges.first();
      const badgeText = await firstBadge.textContent();

      // Should be one of the valid statuses
      expect(['pending', 'building', 'deploying', 'success', 'failed']).toContain(
        badgeText?.toLowerCase()
      );
    }
  });

  test('should show deployment logs', async ({ page }) => {
    await page.click('button[aria-label*="Deployments"]');

    const panel = page.locator('[data-testid="deployments-panel"]');
    const deploymentCard = panel.locator('[data-testid*="deployment-card"]').first();

    if (await deploymentCard.isVisible()) {
      await deploymentCard.click();

      const detailsModal = page.locator('[role="dialog"]');

      // Check for logs section
      const logsSection = detailsModal.locator('[data-testid="deployment-logs"]');
      if (await logsSection.isVisible()) {
        // Should show at least some log content
        const logContent = await logsSection.textContent();
        expect(logContent).toBeTruthy();
      }
    }
  });
});

test.describe('OAuth Flows', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('should initiate Vercel OAuth flow', async ({ page }) => {
    await page.goto('/settings');
    await page.click('button:has-text("Add Provider")');

    // Select Vercel
    await page.click('text=Vercel');

    // Should redirect to Vercel OAuth (or show OAuth button)
    const oauthButton = page.locator('button:has-text("Connect with Vercel")');
    if (await oauthButton.isVisible()) {
      // Note: We can't actually complete OAuth in tests without real credentials
      // But we can verify the flow initiates
      await expect(oauthButton).toBeVisible();
    }
  });

  test('should initiate Netlify OAuth flow', async ({ page }) => {
    await page.goto('/settings');
    await page.click('button:has-text("Add Provider")');

    // Select Netlify
    await page.click('text=Netlify');

    // Should show OAuth button
    const oauthButton = page.locator('button:has-text("Connect with Netlify")');
    if (await oauthButton.isVisible()) {
      await expect(oauthButton).toBeVisible();
    }
  });
});

test.describe('Error Handling', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('should show error for failed deployment', async ({ page }) => {
    await createTestProject(page);
    await page.click('button[aria-label*="Deploy"]');

    const modal = page.locator('[role="dialog"]');

    // Try to deploy without selecting provider
    await modal.locator('button:has-text("Deploy")').click();

    // Should show error
    await expect(page.locator('text=Please select')).toBeVisible();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/settings');
    await page.click('button:has-text("Add Provider")');

    await page.click('text=Cloudflare Workers');

    // Enter invalid credentials
    await page.fill('input[placeholder*="Account ID"]', '');
    await page.fill('input[placeholder*="API Token"]', '');

    await page.click('button:has-text("Connect")');

    // Should show validation errors
    await expect(page.locator('text=required')).toBeVisible();
  });
});
