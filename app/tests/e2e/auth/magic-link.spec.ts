/**
 * End-to-end tests for magic-link (passwordless) login.
 *
 * REQUIRES A REAL DEPLOYMENT (minikube locally, or beta/prod-like in CI).
 * NOT run against `vite dev` + `uvicorn` — those bypass Ingress, CSRF cookie
 * semantics, `Secure` cookie gating on HTTPS, and the production build. The
 * bugs this suite guards against (CSRF middleware blocking /verify;
 * AuthProvider /logout race after /consume) only manifest in the real stack.
 *
 * Cluster requirements:
 *   - Backend env: TEST_HELPERS_ENABLED=1, SMTP_HOST unset (so the email
 *     service captures codes to the in-memory inbox endpoint).
 *   - Feature flag magic_link_login=true (beta/prod yaml already set this;
 *     for minikube override via kubectl set env or overlay patch).
 *
 * Invocation:
 *   scripts/minikube.sh up                     # or equivalent
 *   kubectl --context=tesslate set env deploy/tesslate-backend \
 *       TEST_HELPERS_ENABLED=1 -n tesslate
 *   kubectl --context=tesslate rollout status deploy/tesslate-backend -n tesslate
 *   PLAYWRIGHT_BASE_URL=http://studio.localhost \
 *       npx playwright test --project=chromium-anon
 *
 * These tests target the specific bugs that hit production on 2026-04-17:
 *   1. CSRF middleware blocking /verify POST (403)
 *   2. AuthProvider initial /users/me 401 racing with /consume and firing
 *      /api/auth/logout, which destroyed the freshly-established session
 */

import { test, expect, type Page, type APIRequestContext } from '@playwright/test';

// Don't reuse the authed storageState from auth.setup — every magic-link test
// needs a fresh, unauthenticated browser session.
test.use({ storageState: { cookies: [], origins: [] } });

// In a real deployment, frontend and backend share the Ingress host — /api/*
// proxies to backend. So API calls go to the same origin as the UI.
// PLAYWRIGHT_API_URL is an override for split-host setups.
const BACKEND_URL =
  process.env.PLAYWRIGHT_API_URL || process.env.PLAYWRIGHT_BASE_URL || 'http://studio.localhost';

async function registerUser(
  request: APIRequestContext,
  email: string,
  password: string
): Promise<void> {
  const resp = await request.post(`${BACKEND_URL}/api/auth/register`, {
    data: { email, password, name: 'Magic Link E2E' },
  });
  if (resp.status() !== 201) {
    // If the user already exists from a prior run, that's OK.
    const body = await resp.text();
    if (!body.includes('ALREADY_EXISTS') && !body.toLowerCase().includes('already')) {
      throw new Error(`Register failed: ${resp.status()} ${body}`);
    }
  }
}

async function popMagicLinkInbox(
  request: APIRequestContext,
  email: string
): Promise<{ link_url: string; code: string } | null> {
  // Poll — the email dispatch is fire-and-forget.
  for (let i = 0; i < 20; i++) {
    const resp = await request.get(
      `${BACKEND_URL}/api/__test__/magic-link-inbox?email=${encodeURIComponent(email)}`
    );
    if (resp.status() === 404) {
      throw new Error('Test helper endpoint 404 — backend must run with TEST_HELPERS_ENABLED=1');
    }
    const body = (await resp.json()) as
      | { found: true; link_url: string; code: string }
      | { found: false };
    if (body.found) return { link_url: body.link_url, code: body.code };
    await new Promise((r) => setTimeout(r, 100));
  }
  return null;
}

async function requestMagicLink(page: Page, email: string): Promise<void> {
  await page.goto('/login');
  // The magic-link email form is the DEFAULT landing view when the feature
  // flag is enabled (which it is on minikube). Password is behind a toggle.
  await page.fill('input[type="email"]', email);
  await page.click('button:has-text("Send sign-in link")');
  await expect(page.locator('text=Check your email')).toBeVisible({ timeout: 10000 });
}

function uniqueEmail(tag: string): string {
  return `magic-e2e-${tag}-${Date.now()}@example.com`;
}

// ---------------------------------------------------------------------------
// CSRF regression — POST /verify must not be blocked by CSRF middleware
// ---------------------------------------------------------------------------

test.describe('magic-link CSRF regression', () => {
  test('POST /api/auth/magic-link/verify is not blocked by CSRF (direct API call)', async ({
    request,
  }) => {
    const email = uniqueEmail('csrf');
    // Fresh browser — no csrf cookie.
    const resp = await request.post(`${BACKEND_URL}/api/auth/magic-link/verify`, {
      data: { email, code: '000000' },
    });
    // 401 (bad code) is acceptable; 403 (CSRF reject) is the regression we're guarding.
    expect(resp.status()).not.toBe(403);
  });

  test('POST /api/auth/magic-link/request is not blocked by CSRF (direct API call)', async ({
    request,
  }) => {
    const email = uniqueEmail('csrf-req');
    const resp = await request.post(`${BACKEND_URL}/api/auth/magic-link/request`, {
      data: { email },
    });
    expect(resp.status()).not.toBe(403);
    expect(resp.status()).toBe(200); // always-200 enumeration protection
  });

  test('POST /api/auth/magic-link/consume is not blocked by CSRF (direct API call)', async ({
    request,
  }) => {
    const resp = await request.post(`${BACKEND_URL}/api/auth/magic-link/consume`, {
      data: { token: 'garbage' },
    });
    // 401 (invalid token) acceptable; 403 (CSRF) is the regression.
    expect(resp.status()).not.toBe(403);
    expect(resp.status()).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// Full code-entry sign-in flow through the browser
// ---------------------------------------------------------------------------

test.describe('magic-link code sign-in flow', () => {
  test('user can sign in by typing the emailed code', async ({ page, request }) => {
    const email = uniqueEmail('code');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    await requestMagicLink(page, email);

    const popped = await popMagicLinkInbox(request, email);
    expect(popped, 'test inbox should contain the emailed code').not.toBeNull();
    const code = popped!.code;
    expect(code).toMatch(/^\d{6}$/);

    // Click "Enter code instead"
    await page.click('button:has-text("Enter code instead")');

    // Fill the 6-box OTP input (one digit per box)
    const otpInputs = page.locator('input[inputmode="numeric"]');
    await expect(otpInputs).toHaveCount(6);
    for (let i = 0; i < 6; i++) {
      await otpInputs.nth(i).fill(code[i]);
    }
    await page.click('button:has-text("Sign in")');

    // Should land on /home (or wherever authenticated users go)
    await page.waitForURL(/\/(home|dashboard|chat)/, { timeout: 10000 });
    // Sanity: localStorage has a token
    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();
  });

  test('wrong code shows inline error, stays on the code page', async ({ page, request }) => {
    const email = uniqueEmail('badcode');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    await requestMagicLink(page, email);
    await popMagicLinkInbox(request, email); // drain

    await page.click('button:has-text("Enter code instead")');
    const otpInputs = page.locator('input[inputmode="numeric"]');
    for (let i = 0; i < 6; i++) await otpInputs.nth(i).fill('0');
    await page.click('button:has-text("Sign in")');

    // We should NOT get redirected to /login (the frontend interceptor bug
    // would have hijacked the 401 and redirected). Toast should show.
    await expect(page.locator('text=Invalid or expired code')).toBeVisible({ timeout: 5000 });
    await expect(page).toHaveURL(/\/login/); // still on the login page, in code mode
  });
});

// ---------------------------------------------------------------------------
// Full link-click sign-in flow (tests the AuthProvider initial-401 race fix)
// ---------------------------------------------------------------------------

test.describe('magic-link click sign-in flow', () => {
  test('user can sign in by clicking the emailed link URL', async ({ page, request }) => {
    const email = uniqueEmail('link');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    await requestMagicLink(page, email);

    const popped = await popMagicLinkInbox(request, email);
    expect(popped).not.toBeNull();
    const linkUrl = popped!.link_url;
    expect(linkUrl).toContain('/auth/magic?token=');

    // Track request patterns during the flow.
    //   - /logout  → AuthProvider initial-401 race regression
    //   - /consume → must fire EXACTLY ONCE per token (strict-mode + double-click + scanner guard)
    const logoutCalls: string[] = [];
    const consumeCalls: string[] = [];
    page.on('request', (req) => {
      const url = req.url();
      if (url.includes('/api/auth/logout')) logoutCalls.push(url);
      if (url.includes('/api/auth/magic-link/consume')) {
        consumeCalls.push(`${req.method()} ${url}`);
      }
    });

    // Navigate to the magic-link landing page.
    const parsed = new URL(linkUrl);
    await page.goto(parsed.pathname + parsed.search);

    // Landing page must NOT auto-consume (anti-email-scanner defense).
    // Give it a moment to settle and confirm no consume call fired yet.
    await page.waitForSelector('button:has-text("Continue signing in")');
    await page.waitForTimeout(500);
    expect(
      consumeCalls,
      'Landing page must NOT call /consume until the user clicks — scanners would preflight-consume the token.'
    ).toHaveLength(0);

    // Click "Continue" — THIS is what triggers the POST.
    await page.click('button:has-text("Continue signing in")');
    await page.waitForURL(/\/(home|dashboard|chat)/, { timeout: 10000 });

    // localStorage should have a token
    const token = await page.evaluate(() => localStorage.getItem('token'));
    expect(token).toBeTruthy();

    // Give any lingering async handlers a moment to fire
    await page.waitForTimeout(500);

    // REGRESSION CHECK: /logout must not fire during sign-in.
    expect(
      logoutCalls,
      `/api/auth/logout fired during sign-in — AuthContext initial-401 race regressed. Calls: ${logoutCalls.join(', ')}`
    ).toHaveLength(0);

    // STRICT-MODE REGRESSION CHECK: /consume must fire exactly once. A
    // regression of the consumedTokenRef guard (or re-introducing the
    // `cancelled` flag bug) would either zero this out or double it.
    expect(
      consumeCalls,
      `Expected exactly 1 POST /consume call per token; got ${consumeCalls.length}: ${consumeCalls.join(' | ')}`
    ).toHaveLength(1);
    expect(consumeCalls[0]).toMatch(/^POST /);
  });

  test('post-login redirect is preserved through the magic link', async ({ page, request }) => {
    const email = uniqueEmail('redirect');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    // Full UI-driven send flow (Login.tsx writes / clears sessionStorage
    // based on location.state.from during the send; stashing before Send
    // would be overwritten, so we intercept AFTER send and BEFORE the
    // user clicks the email link).
    await page.goto('/login');
    await page.fill('input[type="email"]', email);
    await page.click('button:has-text("Send sign-in link")');
    await page.waitForSelector('text=Check your email');

    // Simulate the protected-route bounce by writing the redirect key
    // sessionStorage AFTER Login's send handler has run. This mirrors what
    // would happen organically: Login.tsx stashes '/referrals' during send
    // when location.state.from === '/referrals'; we can't easily seed
    // location.state from Playwright, so we emulate its effect here.
    await page.evaluate(() => {
      sessionStorage.setItem('magic_link_redirect', '/referrals');
    });

    const popped = await popMagicLinkInbox(request, email);
    expect(popped).not.toBeNull();
    const parsed = new URL(popped!.link_url);
    await page.goto(parsed.pathname + parsed.search);
    await page.click('button:has-text("Continue signing in")');

    // Should land on the stashed path, not the generic /home fallback.
    await page.waitForURL(/\/referrals/, { timeout: 10000 });

    // MagicLinkConsume must clear the key after consumption so a later
    // OAuth or password login in this tab isn't misrouted to /referrals.
    const leftover = await page.evaluate(() => sessionStorage.getItem('magic_link_redirect'));
    expect(leftover).toBeNull();
  });

  test('clicking the same link twice shows "invalid or expired" on the second attempt', async ({
    page,
    request,
  }) => {
    const email = uniqueEmail('replay');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    await requestMagicLink(page, email);
    const popped = await popMagicLinkInbox(request, email);
    expect(popped).not.toBeNull();
    const linkUrl = popped!.link_url;
    const parsed = new URL(linkUrl);

    // First attempt consumes — goto + click Continue.
    await page.goto(parsed.pathname + parsed.search);
    await page.click('button:has-text("Continue signing in")');
    await page.waitForURL(/\/(home|dashboard|chat)/, { timeout: 10000 });

    // Logout to reset state
    await page.evaluate(() => localStorage.removeItem('token'));

    // Second attempt: click Continue again with the same token → error state.
    await page.goto(parsed.pathname + parsed.search);
    await page.click('button:has-text("Continue signing in")');
    await expect(page.locator('text=invalid or has expired')).toBeVisible({ timeout: 5000 });
  });

  test('an invalid token shows the error page after Continue, not a logout loop', async ({
    page,
  }) => {
    const logoutCalls: string[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/api/auth/logout')) logoutCalls.push(req.url());
    });

    await page.goto('/auth/magic?token=definitely-not-valid');
    // The landing page renders idle with the button; no consume fires yet.
    await page.click('button:has-text("Continue signing in")');
    await expect(page.locator('text=invalid or has expired')).toBeVisible({ timeout: 5000 });

    // No destructive /logout calls should fire for an unauthenticated tab.
    await page.waitForTimeout(500);
    expect(logoutCalls).toHaveLength(0);
  });

  test('landing page does NOT auto-consume — defends against email-scanner preflight', async ({
    page,
    request,
  }) => {
    const email = uniqueEmail('preflight');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    await requestMagicLink(page, email);
    const popped = await popMagicLinkInbox(request, email);
    expect(popped).not.toBeNull();

    const consumeCalls: string[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/api/auth/magic-link/consume')) {
        consumeCalls.push(`${req.method()} ${req.url()}`);
      }
    });

    const parsed = new URL(popped!.link_url);
    await page.goto(parsed.pathname + parsed.search);

    // Give the page a full second to settle. A scanner-style preflight
    // would show up as a GET /consume here. Our page MUST wait for the
    // user click — so consumeCalls should still be empty.
    await page.waitForSelector('button:has-text("Continue signing in")');
    await page.waitForTimeout(1000);

    expect(
      consumeCalls,
      `Landing page called /consume without a user click — email scanners will consume the token before the user does. Calls: ${consumeCalls.join(' | ')}`
    ).toHaveLength(0);

    // Token must STILL be usable after the no-op wait (proves scanner would
    // NOT have drained it even if it had hit the page).
    await page.click('button:has-text("Continue signing in")');
    await page.waitForURL(/\/(home|dashboard|chat)/, { timeout: 10000 });
  });
});

// ---------------------------------------------------------------------------
// Rate limit E2E
// ---------------------------------------------------------------------------

test.describe('magic-link rate limit', () => {
  test('6th request in the window is silent (200 but no email sent)', async ({ request }) => {
    const email = uniqueEmail('ratelimit');
    await registerUser(request, email, 'X-WontBeUsed-999!');

    // Drain any lingering inbox entry.
    await popMagicLinkInbox(request, email);

    // Fire 6 requests.
    for (let i = 0; i < 6; i++) {
      const resp = await request.post(`${BACKEND_URL}/api/auth/magic-link/request`, {
        data: { email },
      });
      // Always 200 — never leak rate-limit state to attackers.
      expect(resp.status()).toBe(200);
    }

    // Count captured emails in the inbox. Limit is 5/10min, so exactly 5 emails.
    let captured = 0;
    while (await popMagicLinkInbox(request, email)) {
      captured++;
      if (captured > 10) break; // safety — should never loop
    }
    expect(captured, `Rate limit should cap emails at 5 in the window; got ${captured}.`).toBe(5);
  });
});
