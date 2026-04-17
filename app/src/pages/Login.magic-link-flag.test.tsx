/**
 * Regression tests for the magic_link_login feature flag UI gating.
 *
 * Backend enforces the flag at the router (returns 404 when disabled;
 * backend integration tests cover that). These tests pin the UI behavior:
 *
 *   Flag ON (default on minikube / beta / prod):
 *     - Landing view is the magic-link email form ("Send sign-in link"
 *       is the primary button).
 *     - Password form is reachable via "Sign in with password instead".
 *
 *   Flag OFF:
 *     - Landing view is the classic password form.
 *     - NO affordance to switch to magic-link anywhere in the DOM.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Mock everything Login.tsx pulls in that would make jsdom unhappy.
vi.mock('../lib/api', () => ({
  authApi: { login: vi.fn(), verify2fa: vi.fn(), resend2faCode: vi.fn() },
  revokeServerSession: vi.fn(),
}));
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ checkAuth: vi.fn() }),
}));
vi.mock('../theme/ThemeContext', () => ({
  useTheme: () => ({ refreshUserTheme: vi.fn() }),
}));
vi.mock('../components/PulsingGridSpinner', () => ({
  PulsingGridSpinner: () => null,
}));
vi.mock('../components/MiniAsteroids', () => ({ MiniAsteroids: () => null }));
vi.mock('../components/ui/TesslateLogo', () => ({ TesslateLogo: () => null }));
vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

// useFeatureFlag is the thing we're actually testing — controllable per-test.
const useFeatureFlagMock = vi.fn<(flag: string) => boolean>();
vi.mock('../contexts/useFeatureFlag', () => ({
  useFeatureFlag: (flag: string) => useFeatureFlagMock(flag),
}));

beforeEach(() => {
  useFeatureFlagMock.mockReset();
});

async function renderLogin() {
  const { default: Login } = await import('./Login');
  render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>
  );
}

describe('Login page: magic_link_login feature flag UI gating', () => {
  it('flag ON: landing view is the magic-link form, includes OAuth', async () => {
    useFeatureFlagMock.mockImplementation((flag) => (flag === 'magic_link_login' ? true : false));
    await renderLogin();

    // Primary action is the email-link send button.
    expect(screen.getByRole('button', { name: /send sign-in link/i })).toBeInTheDocument();
    // OAuth is part of the landing view.
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with github/i })).toBeInTheDocument();
    // Password field must NOT be visible by default.
    expect(screen.queryByPlaceholderText(/password/i)).not.toBeInTheDocument();
    // But a toggle to reach the password form IS present.
    expect(
      screen.getByRole('button', { name: /sign in with password instead/i })
    ).toBeInTheDocument();
  });

  it('flag OFF: landing view is the classic password form WITH OAuth', async () => {
    // NOTE: when the flag is off, the password form is the landing — and
    // OAuth lives there (classic behavior). When the flag is on, OAuth
    // moves to the magic-email landing and the password form is lean.
    useFeatureFlagMock.mockImplementation(() => false);
    await renderLogin();

    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument();
    // Every magic-link affordance is absent.
    expect(screen.queryByRole('button', { name: /send sign-in link/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /sign in with password instead/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /sign in with an email link instead/i })
    ).not.toBeInTheDocument();
  });

  it('flag ON, toggled to password: OAuth is hidden (password view is lean)', async () => {
    useFeatureFlagMock.mockImplementation((flag) => (flag === 'magic_link_login' ? true : false));
    await renderLogin();

    // Click the toggle to reveal the password form.
    fireEvent.click(screen.getByRole('button', { name: /sign in with password instead/i }));

    // Password form is now visible.
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument();
    // OAuth buttons are NOT rendered in this view.
    expect(screen.queryByRole('button', { name: /continue with google/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /continue with github/i })).not.toBeInTheDocument();
    // But the escape hatch back to magic-link IS present.
    expect(
      screen.getByRole('button', { name: /sign in with an email link instead/i })
    ).toBeInTheDocument();
  });
});
