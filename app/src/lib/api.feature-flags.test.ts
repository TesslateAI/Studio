/**
 * Tests for feature flag fetch and fallback in api.ts
 *
 * Covers:
 * - Every call fetches fresh (no stale cache)
 * - Success updates the fallback
 * - Failure returns last known good flags
 * - First-ever failure returns empty flags
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGet = vi.fn();

const mockInstance = {
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
  get: mockGet,
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  patch: vi.fn(),
  request: vi.fn(),
  defaults: { headers: { common: {} } },
};

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  return {
    ...actual,
    default: {
      ...actual.default,
      create: vi.fn(() => mockInstance),
      post: vi.fn(),
      get: vi.fn(),
      isAxiosError: actual.default.isAxiosError,
      isCancel: actual.default.isCancel,
    },
  };
});

vi.mock('../config', () => ({
  config: { API_URL: 'http://test' },
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('featureFlagsApi fetch and fallback', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
  });

  it('every call fetches fresh from the API', async () => {
    const v1 = { env: 'beta', flags: { two_fa: false } };
    const v2 = { env: 'beta', flags: { two_fa: true } };

    mockGet.mockResolvedValue({ data: v1 });
    const { featureFlagsApi } = await import('./api');

    const result1 = await featureFlagsApi.getFlags();
    expect(result1).toEqual(v1);

    // Backend toggled the flag — next fetch should get the new value
    mockGet.mockResolvedValue({ data: v2 });

    const result2 = await featureFlagsApi.getFlags();
    expect(result2).toEqual(v2);

    const flagsCalls = mockGet.mock.calls.filter(([url]: [string]) => url === '/api/feature-flags');
    // Prefetch + getFlags + getFlags = 3 calls
    expect(flagsCalls.length).toBe(3);
  });

  it('failure after success returns last known good flags', async () => {
    const good = { env: 'production', flags: { two_fa: true } };
    mockGet.mockResolvedValue({ data: good });

    const { featureFlagsApi } = await import('./api');
    await featureFlagsApi.getFlags(); // succeeds, updates fallback

    // Backend goes down
    mockGet.mockImplementation((url: string) => {
      if (url === '/api/feature-flags') return Promise.reject(new Error('503'));
      return Promise.resolve({ data: {} });
    });

    const result = await featureFlagsApi.getFlags();
    expect(result).toEqual(good); // falls back to last known good
  });

  it('first-ever failure returns empty flags', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/api/feature-flags') return Promise.reject(new Error('Network error'));
      return Promise.resolve({ data: {} });
    });

    const { featureFlagsApi } = await import('./api');

    const result = await featureFlagsApi.getFlags();
    expect(result).toEqual({ env: '', flags: {} });
  });
});
