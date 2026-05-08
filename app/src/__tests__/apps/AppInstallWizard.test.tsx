/**
 * AppInstallWizard — compat gating + install button enablement.
 *
 * The Phase 5 rewrite collapsed the multi-step wizard into a single
 * `AppInstallModal` review screen with collapsible advanced sections.
 * `AppInstallWizard` is now a thin forwarding wrapper. The previous
 * `compat-step` / `wallet-step` / `wizard-next` testids no longer
 * exist; gating happens via `compat-blocker` + `install-confirm-btn`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../../config', () => ({
  config: { API_URL: 'http://test' },
}));

const getVersion = vi.fn();
const compat = vi.fn();

vi.mock('../../lib/api', () => ({
  appVersionsApi: {
    get: (...args: unknown[]) => getVersion(...args),
    compat: (...args: unknown[]) => compat(...args),
  },
}));

const installApp = vi.fn();

vi.mock('../../contexts/AppsContext', () => ({
  useApps: () => ({ installApp }),
}));

vi.mock('../../contexts/TeamContext', () => ({
  useTeam: () => ({
    teams: [{ id: 't1', name: 'Team 1', slug: 'team-1' }],
    activeTeam: { id: 't1', name: 'Team 1', slug: 'team-1' },
  }),
}));

import { AppInstallWizard } from '../../components/apps/AppInstallWizard';

const baseVersion = {
  id: 'v1',
  app_id: 'a1',
  version: '1.0.0',
  manifest_schema_version: '1',
  manifest_hash: 'h',
  bundle_hash: 'b',
  approval_state: 'approved',
  yanked_at: null,
  yanked_reason: null,
  yanked_is_critical: false,
  published_at: null,
  created_at: '',
  manifest_json: {},
  feature_set_hash: 'x',
  required_features: [],
};

describe('AppInstallWizard', () => {
  beforeEach(() => {
    getVersion.mockReset();
    compat.mockReset();
    installApp.mockReset();
  });

  it('disables install and shows compat-blocker when compat.compatible=false', async () => {
    getVersion.mockResolvedValue(baseVersion);
    compat.mockResolvedValue({
      compatible: false,
      missing_features: ['feature.x'],
      unsupported_manifest_schema: false,
      upgrade_required: true,
      server_manifest_schemas: ['1'],
      server_feature_set_hash: 'x',
    });

    render(
      <AppInstallWizard
        appVersionId="v1"
        onClose={() => {}}
        onDone={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('compat-blocker')).toBeInTheDocument();
    });
    expect(screen.getByText(/not compatible/i)).toBeInTheDocument();
    expect(screen.getByTestId('install-confirm-btn')).toBeDisabled();
  });

  it('enables install when compat.compatible=true with a selected team', async () => {
    getVersion.mockResolvedValue(baseVersion);
    compat.mockResolvedValue({
      compatible: true,
      missing_features: [],
      unsupported_manifest_schema: false,
      upgrade_required: false,
      server_manifest_schemas: ['1'],
      server_feature_set_hash: 'x',
    });

    render(
      <AppInstallWizard
        appVersionId="v1"
        onClose={() => {}}
        onDone={() => {}}
      />
    );

    // Wait for the compat fetch to resolve — install button enables
    // once compat.compatible flips and the active team is preselected.
    await waitFor(() => {
      expect(screen.getByTestId('install-confirm-btn')).not.toBeDisabled();
    });
    expect(screen.queryByTestId('compat-blocker')).not.toBeInTheDocument();
  });
});
