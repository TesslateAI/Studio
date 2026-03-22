/**
 * Tests for deploymentsApi.deployContainerPush and deploymentsApi.exportProject in api.ts
 *
 * Covers:
 * - deployContainerPush() calls POST /deploy-container
 * - exportProject() calls POST /export
 * - Correct payload forwarding and return values
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

describe('deploymentsApi.deployContainerPush', () => {
  let deploymentsApi: typeof import('./api').deploymentsApi;

  beforeEach(async () => {
    vi.clearAllMocks();
    const apiModule = await import('./api');
    deploymentsApi = apiModule.deploymentsApi;
  });

  it('calls POST /api/deployments/{slug}/deploy-container with correct payload', async () => {
    const mockResponse = {
      data: {
        id: 'dep-1',
        project_id: 'proj-1',
        provider: 'aws-apprunner',
        deployment_id: 'svc-123',
        deployment_url: 'https://abc.awsapprunner.com',
        status: 'deploying',
        logs: null,
        error: null,
        created_at: '2026-03-22T00:00:00Z',
        updated_at: '2026-03-22T00:00:00Z',
        completed_at: null,
      },
    };
    mockPost.mockResolvedValueOnce(mockResponse);

    const payload = {
      provider: 'aws-apprunner',
      container_id: 'cid-1',
      port: 3000,
      cpu: '0.5',
      memory: '1Gi',
      region: 'us-west-2',
      env_vars: { NODE_ENV: 'production' },
    };

    const result = await deploymentsApi.deployContainerPush('my-project', payload);

    expect(mockPost).toHaveBeenCalledWith(
      '/api/deployments/my-project/deploy-container',
      payload
    );
    expect(result.provider).toBe('aws-apprunner');
    expect(result.status).toBe('deploying');
  });

  it('works with minimal payload (only provider)', async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        id: 'dep-2',
        project_id: 'proj-1',
        provider: 'gcp-cloudrun',
        deployment_id: null,
        deployment_url: null,
        status: 'pending',
        logs: null,
        error: null,
        created_at: '2026-03-22T00:00:00Z',
        updated_at: '2026-03-22T00:00:00Z',
        completed_at: null,
      },
    });

    const result = await deploymentsApi.deployContainerPush('slug', {
      provider: 'gcp-cloudrun',
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/api/deployments/slug/deploy-container',
      { provider: 'gcp-cloudrun' }
    );
    expect(result.provider).toBe('gcp-cloudrun');
  });
});

describe('deploymentsApi.exportProject', () => {
  let deploymentsApi: typeof import('./api').deploymentsApi;

  beforeEach(async () => {
    vi.clearAllMocks();
    const apiModule = await import('./api');
    deploymentsApi = apiModule.deploymentsApi;
  });

  it('calls POST /api/deployments/{slug}/export with correct payload', async () => {
    const mockResponse = {
      data: {
        id: 'exp-1',
        project_id: 'proj-1',
        provider: 'dockerhub',
        status: 'success',
        image_ref: 'myuser/myapp:v1',
        pull_command: 'docker pull myuser/myapp:v1',
        download_url: null,
        logs: ['Pushed successfully'],
        error: null,
        created_at: '2026-03-22T00:00:00Z',
        completed_at: '2026-03-22T00:01:00Z',
      },
    };
    mockPost.mockResolvedValueOnce(mockResponse);

    const payload = {
      provider: 'dockerhub',
      container_id: 'cid-1',
      image_name: 'myuser/myapp',
      tag: 'v1',
    };

    const result = await deploymentsApi.exportProject('my-project', payload);

    expect(mockPost).toHaveBeenCalledWith(
      '/api/deployments/my-project/export',
      payload
    );
    expect(result.provider).toBe('dockerhub');
    expect(result.pull_command).toBe('docker pull myuser/myapp:v1');
    expect(result.image_ref).toBe('myuser/myapp:v1');
  });

  it('handles download export provider', async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        id: 'exp-2',
        project_id: 'proj-1',
        provider: 'download',
        status: 'success',
        image_ref: null,
        pull_command: null,
        download_url: '/api/downloads/exp-2.zip',
        logs: null,
        error: null,
        created_at: '2026-03-22T00:00:00Z',
        completed_at: '2026-03-22T00:00:05Z',
      },
    });

    const result = await deploymentsApi.exportProject('slug', {
      provider: 'download',
    });

    expect(result.download_url).toBe('/api/downloads/exp-2.zip');
    expect(result.image_ref).toBeNull();
  });

  it('propagates errors from the API', async () => {
    mockPost.mockRejectedValueOnce(new Error('Auth required'));

    await expect(
      deploymentsApi.exportProject('my-project', { provider: 'ghcr' })
    ).rejects.toThrow('Auth required');
  });
});
