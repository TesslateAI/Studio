/**
 * Tests for configSyncApi in api.ts
 *
 * Covers:
 * - configSyncApi.save() calls POST /sync-config
 * - configSyncApi.load() calls POST /setup-config with config payload
 * - Correct return types
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock axios before api.ts imports it
// ---------------------------------------------------------------------------

const mockPost = vi.fn();
const mockGet = vi.fn();

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');

  const mockInstance = {
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    get: mockGet,
    post: mockPost,
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

describe('configSyncApi', () => {
  let configSyncApi: typeof import('./api').configSyncApi;

  beforeEach(async () => {
    vi.clearAllMocks();
    const apiModule = await import('./api');
    configSyncApi = apiModule.configSyncApi;
  });

  describe('save', () => {
    it('calls POST /api/projects/{slug}/sync-config', async () => {
      const mockResponse = {
        data: {
          status: 'saved',
          sections: {
            apps: 2,
            infrastructure: 1,
            connections: 1,
            deployments: 1,
            previews: 1,
          },
        },
      };
      mockPost.mockResolvedValueOnce(mockResponse);

      const result = await configSyncApi.save('my-project-abc123');

      expect(mockPost).toHaveBeenCalledWith('/api/projects/my-project-abc123/sync-config');
      expect(result).toEqual(mockResponse.data);
      expect(result.status).toBe('saved');
      expect(result.sections.apps).toBe(2);
    });

    it('propagates errors from the API', async () => {
      mockPost.mockRejectedValueOnce(new Error('Network error'));

      await expect(configSyncApi.save('my-project')).rejects.toThrow('Network error');
    });
  });

  describe('load', () => {
    it('calls POST /api/projects/{slug}/setup-config with config', async () => {
      const config = {
        apps: {
          frontend: {
            directory: '.',
            port: 3000,
            start: 'npm start',
            env: {},
          },
        },
        infrastructure: {},
        primaryApp: 'frontend',
      };

      const mockResponse = {
        data: {
          container_ids: ['uuid-1', 'uuid-2'],
          primary_container_id: 'uuid-1',
        },
      };
      mockPost.mockResolvedValueOnce(mockResponse);

      const result = await configSyncApi.load('my-project-abc123', config);

      expect(mockPost).toHaveBeenCalledWith(
        '/api/projects/my-project-abc123/setup-config',
        config
      );
      expect(result).toEqual(mockResponse.data);
      expect(result.container_ids).toHaveLength(2);
      expect(result.primary_container_id).toBe('uuid-1');
    });

    it('propagates errors from the API', async () => {
      const config = {
        apps: {},
        infrastructure: {},
        primaryApp: 'frontend',
      };
      mockPost.mockRejectedValueOnce(new Error('Validation failed'));

      await expect(configSyncApi.load('my-project', config)).rejects.toThrow('Validation failed');
    });
  });
});
