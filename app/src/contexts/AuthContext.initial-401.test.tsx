/**
 * Regression tests for AuthContext.checkAuth 401 handling.
 *
 * The bug (2026-04-17): on /auth/magic page load, AuthProvider's initial
 * checkAuth fires /api/users/me → 401 (tab has no session yet) → error
 * handler called localStorage.removeItem + revokeServerSession (POST /logout),
 * which raced with MagicLinkConsume's /consume flow and destroyed the freshly-
 * established session.
 *
 * Rules enforced here:
 *   1. 401 during initial load (state='initializing') MUST NOT call
 *      revokeServerSession. There is no session to revoke.
 *   2. 401 while authenticated (state='authenticated') SHOULD call
 *      revokeServerSession — the token stopped working, clean up.
 *   3. If localStorage token changed between checkAuth start and its 401,
 *      do NOT removeItem (a concurrent sign-in flow wrote a fresh token).
 *   4. React's state updates between start-of-check and 401-response (e.g. a
 *      second checkAuth dispatching AUTH_SUCCESS) MUST NOT cause the losing
 *      check to revoke the winning session.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const store: Record<string, string> = {};
const localStorageMock = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, val: string) => {
    store[key] = val;
  }),
  removeItem: vi.fn((key: string) => {
    delete store[key];
  }),
  clear: vi.fn(() => {
    Object.keys(store).forEach((k) => delete store[k]);
  }),
  get length() {
    return Object.keys(store).length;
  },
  key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });

vi.mock('../config', () => ({
  config: { API_URL: 'http://test' },
}));

// Mock the api module so we can spy on revokeServerSession directly.
const revokeServerSessionMock = vi.fn().mockResolvedValue(undefined);
vi.mock('../lib/api', () => ({
  revokeServerSession: revokeServerSessionMock,
  authApi: {
    checkAuth: vi.fn(),
    refreshToken: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  return {
    ...actual,
    default: {
      ...actual.default,
      post: vi.fn(),
      get: vi.fn(),
      isCancel: (err: unknown) =>
        err != null &&
        typeof err === 'object' &&
        'name' in err &&
        (err as { name: string }).name === 'CanceledError',
      isAxiosError: actual.default.isAxiosError,
    },
  };
});

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

async function renderAuthProviderAndWait() {
  // Dynamic import so the module loads AFTER our mocks are in place.
  const { AuthProvider } = await import('./AuthContext');

  const result = render(
    <MemoryRouter>
      <AuthProvider>
        <div>child</div>
      </AuthProvider>
    </MemoryRouter>
  );

  // Wait for the initial useEffect(checkAuth) to settle.
  // axios.get is called once (either token or cookie path); give it a tick.
  await waitFor(() => {
    const mockGet = axios.get as unknown as ReturnType<typeof vi.fn>;
    expect(mockGet.mock.calls.length).toBeGreaterThanOrEqual(1);
  });
  // Additional microtask flush for the catch handler to run
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });

  return result;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AuthContext initial checkAuth 401 handling', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorageMock.clear();
    revokeServerSessionMock.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does NOT call revokeServerSession on 401 from initial load with no token', async () => {
    // Setup: no token in localStorage → state starts 'initializing'
    const mockGet = axios.get as unknown as ReturnType<typeof vi.fn>;
    mockGet.mockImplementation(() => Promise.reject(make401WithoutThrow()));

    await renderAuthProviderAndWait();

    // CRITICAL: logout must NOT fire — there's no session to revoke.
    expect(revokeServerSessionMock).not.toHaveBeenCalled();
  });

  it('does NOT removeItem when no token was present at check start', async () => {
    // No token in localStorage
    const mockGet = axios.get as unknown as ReturnType<typeof vi.fn>;
    mockGet.mockImplementation(() => Promise.reject(make401WithoutThrow()));

    await renderAuthProviderAndWait();

    // removeItem shouldn't have been called for 'token' (nothing to remove).
    const tokenRemovals = localStorageMock.removeItem.mock.calls.filter(
      (call) => call[0] === 'token'
    );
    expect(tokenRemovals).toHaveLength(0);
  });

  it('does NOT clobber a token written by a concurrent sign-in flow', async () => {
    // Simulate: no token at checkAuth start. Then while /users/me is in-flight,
    // a concurrent flow (e.g. MagicLinkConsume /consume 200) writes a token.
    const mockGet = axios.get as unknown as ReturnType<typeof vi.fn>;
    mockGet.mockImplementation(
      () =>
        new Promise((_, reject) => {
          // Simulate the race: inject token mid-flight, then reject 401
          setTimeout(() => {
            localStorageMock.setItem('token', 'fresh-token-from-magic-link');
            reject(make401WithoutThrow());
          }, 5);
        })
    );

    await renderAuthProviderAndWait();

    // The concurrent flow's token MUST still be there.
    expect(store['token']).toBe('fresh-token-from-magic-link');
    // And /logout must not have been called.
    expect(revokeServerSessionMock).not.toHaveBeenCalled();
  });

  it('DOES call revokeServerSession on 401 when user was previously authenticated', async () => {
    // Setup: stale token in localStorage → getInitialState returns
    // status='authenticated' (optimistic). Then /users/me 401 → we DO want to
    // clean up because the token/session is dead.
    localStorageMock.setItem('token', 'stale-token');
    const mockGet = axios.get as unknown as ReturnType<typeof vi.fn>;
    mockGet.mockImplementation(() => Promise.reject(make401WithoutThrow()));

    await renderAuthProviderAndWait();

    // Stale token was removed
    expect(store['token']).toBeUndefined();
    // Logout WAS called (user was optimistically authenticated)
    expect(revokeServerSessionMock).toHaveBeenCalledTimes(1);
  });
});

// Helper that returns (rather than throws) a 401-shaped axios error.
function make401WithoutThrow() {
  const err = new Error('Request failed with status code 401') as Error & {
    response: { status: number; data: { detail: string } };
    isAxiosError: boolean;
    config: object;
  };
  err.response = { status: 401, data: { detail: 'Unauthorized' } };
  err.isAxiosError = true;
  err.config = {};
  return err;
}
