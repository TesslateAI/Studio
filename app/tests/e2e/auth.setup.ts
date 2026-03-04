/**
 * Global setup for Playwright E2E tests.
 *
 * This file:
 * 1. Registers a test user via API
 * 2. Logs in through the web UI
 * 3. Saves authentication state to .auth/user.json
 *
 * All other tests will reuse this auth state (no need to login in every test).
 */

import { test as setup, expect } from '@playwright/test';

const authFile = 'tests/e2e/.auth/user.json';

// Generate unique email for test user (avoid conflicts across test runs)
const TEST_EMAIL = `e2e-test-${Date.now()}@example.com`;
const TEST_PASSWORD = 'E2ETestPass123!';
const TEST_NAME = 'E2E Test User';

setup('authenticate', async ({ page, request }) => {
  // Step 1: Register test user via API
  const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
  const apiURL = baseURL.replace('5173', '8000'); // Frontend on 5173, backend on 8000

  const registerResponse = await request.post(`${apiURL}/api/auth/register`, {
    data: {
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
      name: TEST_NAME,
    },
  });

  // Registration may fail if user already exists (ok for local dev reruns)
  if (registerResponse.status() !== 201) {
    console.log(
      `Registration failed (status ${registerResponse.status()}), user may already exist`
    );
  }

  // Step 2: Login through web UI
  await page.goto('/login');

  await page.fill('input[type="email"]', TEST_EMAIL);
  await page.fill('input[type="password"]', TEST_PASSWORD);
  await page.click('button[type="submit"]');

  // Wait for successful login redirect
  await page.waitForURL('/dashboard', { timeout: 10000 });

  // Verify we're logged in
  await expect(page).toHaveURL('/dashboard');

  // Step 3: Save authentication state
  await page.context().storageState({ path: authFile });

  console.log(`✅ Authentication state saved to ${authFile}`);
});
