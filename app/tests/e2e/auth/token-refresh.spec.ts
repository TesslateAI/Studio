/**
 * E2E tests for the access + refresh token pair system.
 *
 * Verifies:
 * - Login sets both access token and refresh cookie
 * - Access token has ~15 min lifetime
 * - Refresh endpoint renews the access token via cookie
 * - Expired/invalid tokens are rejected
 */

import { test, expect } from '@playwright/test';

test.describe('Token Refresh', () => {
  test('authenticated session has a valid access token in localStorage', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL('/dashboard');

    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
    expect(token!.split('.').length).toBe(3); // JWT has 3 parts
  });

  test('access token exp claim is ~15 minutes from issue time', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL('/dashboard');

    const result = await page.evaluate(() => {
      const token = localStorage.getItem('token');
      if (!token) return null;

      const payload = JSON.parse(atob(token.split('.')[1]));
      const expMs = payload.exp * 1000;
      const nowMs = Date.now();
      const deltaMinutes = (expMs - nowMs) / (1000 * 60);

      return { deltaMinutes };
    });

    expect(result).not.toBeNull();
    // Token should expire between 0 and 16 minutes from now
    expect(result!.deltaMinutes).toBeGreaterThan(0);
    expect(result!.deltaMinutes).toBeLessThanOrEqual(16);
  });

  test('refresh endpoint renews access token via cookie', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL('/dashboard');

    const result = await page.evaluate(async () => {
      const oldToken = localStorage.getItem('token');
      const apiUrl = window.location.origin.replace('5173', '8000');

      // Refresh uses httpOnly cookie (tesslate_refresh) — no Bearer header needed
      const response = await fetch(`${apiUrl}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });

      if (!response.ok) return { ok: false, status: response.status };

      const data = await response.json();
      return {
        ok: true,
        hasNewToken: !!data.access_token,
        tokenChanged: data.access_token !== oldToken,
      };
    });

    expect(result.ok).toBe(true);
    expect(result.hasNewToken).toBe(true);
  });

  test('invalid token is rejected by protected endpoints', async ({ request }) => {
    const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
    const payload = btoa(
      JSON.stringify({
        sub: '00000000-0000-0000-0000-000000000001',
        exp: Math.floor(Date.now() / 1000) - 3600,
      })
    );
    const fakeToken = `${header}.${payload}.invalidsignature`;

    const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173';
    const apiURL = baseURL.replace('5173', '8000');

    const response = await request.get(`${apiURL}/api/users/me`, {
      headers: { Authorization: `Bearer ${fakeToken}` },
    });

    expect(response.status()).toBe(401);
  });
});
