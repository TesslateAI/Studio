import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import type { AppInstance } from '../lib/api';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));
vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const createSession = vi.fn();
// Mocks that fire on unmount must return a real Promise — the component
// chains `.catch` on the call.
const deleteSession = vi.fn(() => Promise.resolve(undefined));
const getAppVersion = vi.fn();
const getMarketplaceApp = vi.fn();
const getSpendSummary = vi.fn();
const getRuntime = vi.fn();
const listSchedules = vi.fn();

vi.mock('../lib/api', () => ({
  appInstallsApi: { listMine: vi.fn() },
  appRuntimeApi: {
    createSession: (...a: unknown[]) => createSession(...a),
    deleteSession: (...a: unknown[]) => deleteSession(...a),
    createInvocation: vi.fn(),
    deleteInvocation: vi.fn(),
  },
  appRuntimeStatusApi: {
    getRuntime: (...a: unknown[]) => getRuntime(...a),
    start: vi.fn(),
    stop: vi.fn(),
    listSchedules: (...a: unknown[]) => listSchedules(...a),
    patchSchedule: vi.fn(),
    runSchedule: vi.fn(),
  },
  appVersionsApi: { get: (...a: unknown[]) => getAppVersion(...a) },
  marketplaceAppsApi: { get: (...a: unknown[]) => getMarketplaceApp(...a) },
  appBillingApi: { getSpendSummary: (...a: unknown[]) => getSpendSummary(...a) },
}));

const instance: AppInstance = {
  id: 'i1',
  app_id: 'a1',
  app_version_id: 'v1',
  project_id: null,
  state: 'running',
  update_policy: 'manual',
  volume_id: null,
  installed_at: '2025-01-01T00:00:00Z',
  uninstalled_at: null,
  created_at: '2025-01-01T00:00:00Z',
  app_slug: 'alpha',
  app_name: 'Alpha',
  app_version: '1.0.0',
};

vi.mock('../contexts/AppsContext', () => ({
  useApps: () => ({
    myInstalls: [instance],
    isLoading: false,
    error: null,
    refresh: vi.fn(),
    installApp: vi.fn(),
    uninstallApp: vi.fn(),
    publishVersion: vi.fn(),
  }),
}));

// Stub the iframe host so the test doesn't touch postMessage plumbing.
vi.mock('../components/apps/IframeAppHost', () => ({
  default: () => <div data-testid="iframe-stub" />,
}));

// Stub EventSource for the SSE runtime stream — the page falls back to the
// one-shot GET /runtime after a 2s timeout, which is what we assert on.
class FakeEventSource {
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_url: string) {}
  close() {}
}
// @ts-expect-error shim for jsdom.
globalThis.EventSource = FakeEventSource;

import AppWorkspacePage from './AppWorkspacePage';

describe('AppWorkspacePage', () => {
  it('auto-mints a billing session once the manifest declares a UI surface', async () => {
    getMarketplaceApp.mockResolvedValue({
      id: 'a1',
      slug: 'alpha',
      name: 'Alpha',
      description: null,
      category: null,
      icon_ref: null,
      forkable: 'open',
      forked_from: null,
      visibility: 'public',
      state: 'published',
      reputation: {},
      creator_user_id: null,
      created_at: '',
      updated_at: '',
    });
    getAppVersion.mockResolvedValue({
      id: 'v1',
      app_id: 'a1',
      version: '1.0.0',
      manifest_schema_version: '1',
      manifest_hash: 'h',
      bundle_hash: null,
      approval_state: 'approved',
      yanked_at: null,
      yanked_reason: null,
      yanked_is_critical: false,
      published_at: null,
      created_at: '',
      manifest_json: {
        surfaces: [{ kind: 'ui', entrypoint: 'https://app.example.com' }],
      },
      feature_set_hash: '',
      required_features: [],
    });
    getSpendSummary.mockResolvedValue({
      total_usd_30d: 0,
      total_usd_7d: 0,
      total_usd_24h: 0,
      total_settled_usd: 0,
      total_unsettled_usd: 0,
      per_dimension: {},
      per_app: [],
    });
    getRuntime.mockResolvedValue({
      state: 'running',
      primary_url: 'https://app.example.com',
      project_slug: 'alpha-abc',
      containers: [],
    });
    listSchedules.mockResolvedValue([]);
    createSession.mockResolvedValue({
      session_id: 'sess1',
      app_instance_id: 'i1',
      litellm_key_id: 'k',
      api_key: 'secret-key',
      budget_usd: 5,
      ttl_seconds: 1800,
    });

    render(
      <MemoryRouter initialEntries={['/apps/installed/i1/workspace']}>
        <Routes>
          <Route path="/apps/installed/:appInstanceId/workspace" element={<AppWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId('app-workspace-page')).toBeInTheDocument());
    await waitFor(() => expect(createSession).toHaveBeenCalledOnce());
  });

  it('renders the embed-mode shell without the regular top bar', async () => {
    getMarketplaceApp.mockResolvedValue({
      id: 'a1', slug: 'alpha', name: 'Alpha', description: null, category: null,
      icon_ref: null, forkable: 'open', forked_from: null, visibility: 'public',
      state: 'published', reputation: {}, creator_user_id: null, created_at: '', updated_at: '',
    });
    getAppVersion.mockResolvedValue({
      id: 'v1', app_id: 'a1', version: '1.0.0', manifest_schema_version: '1',
      manifest_hash: 'h', bundle_hash: null, approval_state: 'approved',
      yanked_at: null, yanked_reason: null, yanked_is_critical: false,
      published_at: null, created_at: '',
      manifest_json: { surfaces: [{ kind: 'ui', entrypoint: 'https://app.example.com' }] },
      feature_set_hash: '', required_features: [],
    });
    getSpendSummary.mockResolvedValue({
      total_usd_30d: 0, total_usd_7d: 0, total_usd_24h: 0,
      total_settled_usd: 0, total_unsettled_usd: 0, per_dimension: {}, per_app: [],
    });
    getRuntime.mockResolvedValue({
      state: 'running',
      primary_url: 'https://app.example.com',
      project_slug: 'alpha-abc',
      containers: [],
    });
    listSchedules.mockResolvedValue([]);
    createSession.mockResolvedValue({
      session_id: 'sess2', app_instance_id: 'i1', litellm_key_id: 'k',
      api_key: 'secret', budget_usd: 5, ttl_seconds: 1800,
    });

    render(
      <MemoryRouter initialEntries={['/apps/embed/i1']}>
        <Routes>
          <Route path="/apps/embed/:appInstanceId" element={<AppWorkspacePage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId('app-workspace-embed')).toBeInTheDocument());
    // Embed mode strips the top bar, so the drawer toggle must not render.
    expect(screen.queryByTestId('drawer-toggle-btn')).toBeNull();
  });
});
