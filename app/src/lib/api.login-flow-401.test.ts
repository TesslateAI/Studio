/**
 * Tests that 401 responses from login-flow endpoints are NOT hijacked by the
 * axios response interceptor (no refresh attempt, no redirect).
 *
 * Regression test for the magic-link bug where a bad/expired code or link
 * caused the interceptor to run /api/auth/refresh → 401 → redirect to /login,
 * which hid the real "Invalid or expired code" error and looked like a silent
 * failure to the user.
 *
 * Login-flow endpoints covered:
 *   - /api/auth/login
 *   - /api/auth/2fa/verify, /api/auth/2fa/resend
 *   - /api/auth/magic-link/request, /consume, /verify
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import axios, { type AxiosError } from 'axios';

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  const mockInstance = {
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
    request: vi.fn(),
    defaults: { headers: { common: {} } },
  };
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

// Capture the interceptor error handler the api module registers on import.
type ErrorHandler = (err: AxiosError) => Promise<unknown>;
let errorHandler: ErrorHandler;

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((k: string) => store[k] ?? null),
    setItem: vi.fn((k: string, v: string) => {
      store[k] = v;
    }),
    removeItem: vi.fn((k: string) => {
      delete store[k];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
})();

Object.defineProperty(window, 'localStorage', { value: localStorageMock });

const locationMock = { pathname: '/login', href: '/login' };
Object.defineProperty(window, 'location', { value: locationMock, writable: true });

beforeEach(async () => {
  vi.resetModules();
  localStorageMock.clear();
  locationMock.pathname = '/login';
  locationMock.href = '/login';

  const axiosMod = await import('axios');
  const mockCreate = axiosMod.default.create as unknown as ReturnType<typeof vi.fn>;
  mockCreate.mockClear();

  // Trigger module load so interceptors register
  await import('./api');

  const instance = mockCreate.mock.results[0]?.value;
  expect(instance, 'axios.create should have been called').toBeDefined();
  const responseCalls = instance.interceptors.response.use.mock.calls;
  expect(responseCalls.length, 'response interceptor should be registered').toBeGreaterThan(0);
  errorHandler = responseCalls[0][1] as ErrorHandler;
});

afterEach(() => {
  vi.clearAllMocks();
});

function make401(url: string): AxiosError {
  return {
    isAxiosError: true,
    response: { status: 401, data: { detail: 'Invalid or expired' } },
    config: { url, headers: {} },
    message: 'Request failed with status code 401',
    name: 'AxiosError',
    toJSON: () => ({}),
  } as unknown as AxiosError;
}

const LOGIN_FLOW_URLS = [
  '/api/auth/login',
  '/api/auth/2fa/verify',
  '/api/auth/2fa/resend',
  '/api/auth/magic-link/request',
  '/api/auth/magic-link/consume',
  '/api/auth/magic-link/verify',
  // Also absolute-URL variants since the api instance uses a baseURL
  'http://test/api/auth/magic-link/verify',
];

describe('401 interceptor skips login-flow endpoints', () => {
  it.each(LOGIN_FLOW_URLS)(
    'rejects 401 from %s without triggering refresh or redirect',
    async (url) => {
      const mockPost = axios.post as unknown as ReturnType<typeof vi.fn>;
      mockPost.mockClear();

      const error = make401(url);

      // Interceptor should REJECT the original error, not trigger a refresh.
      await expect(errorHandler(error)).rejects.toBe(error);

      // No /api/auth/refresh call should have fired.
      expect(mockPost).not.toHaveBeenCalled();

      // No redirect should have occurred.
      expect(locationMock.href).toBe('/login');
    }
  );

  it('does NOT skip refresh for a normal API endpoint (sanity check)', async () => {
    // If our allowlist is too broad, this test will fail.
    const mockPost = axios.post as unknown as ReturnType<typeof vi.fn>;
    // Simulate refresh call failing so we don't retry the original request
    mockPost.mockRejectedValueOnce(new Error('refresh failed'));

    const error = make401('/api/projects/');

    try {
      await errorHandler(error);
    } catch {
      // expected — refresh rejection surfaces
    }

    // Refresh MUST be attempted for non-login-flow 401s
    expect(mockPost).toHaveBeenCalled();
    const callUrl = mockPost.mock.calls[0][0];
    expect(callUrl).toContain('/api/auth/refresh');
  });
});
