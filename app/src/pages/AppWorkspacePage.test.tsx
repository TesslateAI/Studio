import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import type { AppInstance } from '../lib/api';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));
vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

// Mock monaco (imported transitively via IframeAppHost? no — only via Source page).
// AppWorkspacePage does NOT import monaco, so no mock needed for it specifically.

const createSession = vi.fn();
const deleteSession = vi.fn();
const getAppVersion = vi.fn();
const getMarketplaceApp = vi.fn();
const getSpendSummary = vi.fn();

vi.mock('../lib/api', () => ({
  appInstallsApi: { listMine: vi.fn() },
  appRuntimeApi: {
    createSession: (...a: unknown[]) => createSession(...a),
    deleteSession: (...a: unknown[]) => deleteSession(...a),
    createInvocation: vi.fn(),
    deleteInvocation: vi.fn(),
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

// IframeAppHost imports lib/api (already mocked). Provide a light stub to avoid
// trying to touch DOM postMessage flow in this test.
vi.mock('../components/apps/IframeAppHost', () => ({
  default: () => <div data-testid="iframe-stub" />,
}));

import AppWorkspacePage from './AppWorkspacePage';

describe('AppWorkspacePage', () => {
  it('starts a session and shows an Active badge', async () => {
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
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByTestId('session-badge')).toHaveTextContent('No session'));

    fireEvent.click(screen.getByTestId('start-session-btn'));

    await waitFor(() => expect(createSession).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(screen.getByTestId('session-badge').textContent).toMatch(/Active/)
    );
  });
});
