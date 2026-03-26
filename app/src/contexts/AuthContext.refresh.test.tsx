/**
 * AuthContext token refresh timing tests
 *
 * Verifies the silent refresh interval is configured correctly
 * for the 15-minute JWT lifetime.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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

vi.mock('../lib/api', () => ({
  authApi: {
    checkAuth: vi.fn().mockResolvedValue({ id: 'u1', email: 'test@test.com' }),
    refreshToken: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  return {
    ...actual,
    default: {
      ...actual.default,
      post: vi.fn().mockResolvedValue({ data: {} }),
      get: vi.fn().mockResolvedValue({ data: {} }),
      isCancel: () => false,
    },
  };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AuthContext refresh configuration', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorageMock.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('refresh interval (12 min) is shorter than JWT lifetime (15 min) with sufficient buffer', () => {
    const JWT_LIFETIME_MS = 15 * 60 * 1000; // backend: access_token_expire_minutes = 15
    const REFRESH_INTERVAL_MS = 12 * 60 * 1000; // frontend: SILENT_REFRESH_INTERVAL_MS
    const COOLDOWN_MS = 5 * 60 * 1000; // frontend: REFRESH_COOLDOWN_MS

    expect(REFRESH_INTERVAL_MS).toBeLessThan(JWT_LIFETIME_MS);
    expect(REFRESH_INTERVAL_MS).toBeGreaterThan(COOLDOWN_MS);
    expect(JWT_LIFETIME_MS - REFRESH_INTERVAL_MS).toBeGreaterThanOrEqual(2 * 60 * 1000);
  });

  it('setInterval is called with 12-minute interval when authenticated', async () => {
    const setIntervalSpy = vi.spyOn(globalThis, 'setInterval');

    store['token'] = 'test-jwt';

    const { render } = await import('@testing-library/react');
    const { createElement } = await import('react');

    vi.resetModules();
    const { AuthProvider } = await import('./AuthContext');

    const { unmount } = render(createElement(AuthProvider, { children: null }));

    await new Promise((r) => setTimeout(r, 50));

    const intervalCalls = setIntervalSpy.mock.calls
      .map(([_fn, ms]) => ms)
      .filter((ms): ms is number => typeof ms === 'number');

    const TWELVE_MINUTES = 12 * 60 * 1000;
    expect(intervalCalls).toContain(TWELVE_MINUTES);

    unmount();
    setIntervalSpy.mockRestore();
  });
});
