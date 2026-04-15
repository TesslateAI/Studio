/**
 * AppInstallWizard — compat gating + step navigation.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

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

describe('AppInstallWizard', () => {
  beforeEach(() => {
    getVersion.mockReset();
    compat.mockReset();
    installApp.mockReset();
  });

  it('blocks advancement when compat.compatible=false', async () => {
    getVersion.mockResolvedValue({
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
    });
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
      expect(screen.getByTestId('compat-step')).toBeInTheDocument();
    });
    expect(screen.getByText(/not compatible/i)).toBeInTheDocument();
    expect(screen.getByTestId('wizard-next')).toBeDisabled();
  });

  it('allows advancing to wallet step when compatible', async () => {
    getVersion.mockResolvedValue({
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
    });
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

    await waitFor(() => {
      expect(screen.getByTestId('compat-step')).toBeInTheDocument();
    });
    const next = screen.getByTestId('wizard-next');
    expect(next).not.toBeDisabled();
    fireEvent.click(next);
    await waitFor(() => {
      expect(screen.getByTestId('wallet-step')).toBeInTheDocument();
    });
  });
});
