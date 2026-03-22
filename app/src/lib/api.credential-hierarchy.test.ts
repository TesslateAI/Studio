/**
 * Tests for Credential Hierarchy UX
 *
 * Covers:
 * - deploymentCredentialsApi.list() accepts optional projectId parameter
 * - Correct query params forwarded to API
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock axios before api.ts imports it
// ---------------------------------------------------------------------------

const mockPost = vi.fn();
const mockGet = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();
const mockPatch = vi.fn();

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');

  const mockInstance = {
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
    patch: mockPatch,
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

describe('deploymentCredentialsApi.list', () => {
  let deploymentCredentialsApi: typeof import('./api').deploymentCredentialsApi;

  beforeEach(async () => {
    vi.clearAllMocks();
    const apiModule = await import('./api');
    deploymentCredentialsApi = apiModule.deploymentCredentialsApi;
  });

  it('calls GET /api/deployment-credentials with no params', async () => {
    mockGet.mockResolvedValueOnce({
      data: { credentials: [] },
    });

    const result = await deploymentCredentialsApi.list();

    expect(mockGet).toHaveBeenCalledWith('/api/deployment-credentials', {
      params: { provider: undefined, project_id: undefined },
    });
    expect(result.credentials).toEqual([]);
  });

  it('passes provider filter', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        credentials: [
          {
            id: 'cred-1',
            provider: 'vercel',
            project_id: null,
            is_default: true,
            metadata: {},
            created_at: '2026-03-22T00:00:00Z',
            updated_at: '2026-03-22T00:00:00Z',
          },
        ],
      },
    });

    const result = await deploymentCredentialsApi.list('vercel');

    expect(mockGet).toHaveBeenCalledWith('/api/deployment-credentials', {
      params: { provider: 'vercel', project_id: undefined },
    });
    expect(result.credentials).toHaveLength(1);
    expect(result.credentials[0].provider).toBe('vercel');
  });

  it('passes project_id filter', async () => {
    const projectId = 'proj-123';
    mockGet.mockResolvedValueOnce({
      data: {
        credentials: [
          {
            id: 'cred-2',
            provider: 'netlify',
            project_id: projectId,
            is_default: false,
            metadata: {},
            created_at: '2026-03-22T00:00:00Z',
            updated_at: '2026-03-22T00:00:00Z',
          },
        ],
      },
    });

    const result = await deploymentCredentialsApi.list(undefined, projectId);

    expect(mockGet).toHaveBeenCalledWith('/api/deployment-credentials', {
      params: { provider: undefined, project_id: projectId },
    });
    expect(result.credentials[0].project_id).toBe(projectId);
    expect(result.credentials[0].is_default).toBe(false);
  });

  it('passes both provider and project_id filters', async () => {
    mockGet.mockResolvedValueOnce({
      data: { credentials: [] },
    });

    await deploymentCredentialsApi.list('cloudflare', 'proj-456');

    expect(mockGet).toHaveBeenCalledWith('/api/deployment-credentials', {
      params: { provider: 'cloudflare', project_id: 'proj-456' },
    });
  });

  it('returns is_default true for account-level credentials', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        credentials: [
          {
            id: 'cred-3',
            provider: 'aws-apprunner',
            project_id: null,
            is_default: true,
            metadata: { aws_region: 'us-east-1' },
            created_at: '2026-03-22T00:00:00Z',
            updated_at: '2026-03-22T00:00:00Z',
          },
        ],
      },
    });

    const result = await deploymentCredentialsApi.list('aws-apprunner');
    expect(result.credentials[0].is_default).toBe(true);
    expect(result.credentials[0].project_id).toBeNull();
  });

  it('returns is_default false for project-specific credentials', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        credentials: [
          {
            id: 'cred-4',
            provider: 'gcp-cloudrun',
            project_id: 'proj-789',
            is_default: false,
            metadata: { gcp_region: 'us-central1' },
            created_at: '2026-03-22T00:00:00Z',
            updated_at: '2026-03-22T00:00:00Z',
          },
        ],
      },
    });

    const result = await deploymentCredentialsApi.list('gcp-cloudrun', 'proj-789');
    expect(result.credentials[0].is_default).toBe(false);
    expect(result.credentials[0].project_id).toBe('proj-789');
  });
});
