/**
 * BundleInstallWizard — required items can't be disabled.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../../config', () => ({
  config: { API_URL: 'http://test' },
}));

const bundleGet = vi.fn();
const versionGet = vi.fn();

vi.mock('../../lib/api', () => ({
  appBundlesApi: {
    get: (...args: unknown[]) => bundleGet(...args),
    install: vi.fn(),
  },
  appVersionsApi: {
    get: (...args: unknown[]) => versionGet(...args),
  },
}));

vi.mock('../../contexts/TeamContext', () => ({
  useTeam: () => ({
    teams: [{ id: 't1', name: 'Team 1', slug: 't1' }],
    activeTeam: { id: 't1', name: 'Team 1', slug: 't1' },
  }),
}));

import { BundleInstallWizard } from '../../components/apps/BundleInstallWizard';

describe('BundleInstallWizard', () => {
  beforeEach(() => {
    bundleGet.mockReset();
    versionGet.mockReset();
  });

  it('required items are toggled on and disabled; optional items can be toggled', async () => {
    bundleGet.mockResolvedValue({
      id: 'b1',
      slug: 'bundle',
      display_name: 'Bundle',
      status: 'published',
      consolidated_manifest_hash: null,
      items: [
        {
          app_version_id: 'v-req',
          order_index: 0,
          default_enabled: true,
          required: true,
        },
        {
          app_version_id: 'v-opt',
          order_index: 1,
          default_enabled: true,
          required: false,
        },
      ],
    });
    versionGet.mockResolvedValue({
      id: 'x',
      app_id: 'a',
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

    render(
      <BundleInstallWizard
        bundleId="b1"
        onClose={() => {}}
        onDone={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('items-step')).toBeInTheDocument();
    });

    const required = screen.getByTestId('item-toggle-v-req') as HTMLInputElement;
    const optional = screen.getByTestId('item-toggle-v-opt') as HTMLInputElement;

    // required: checked + disabled
    expect(required.checked).toBe(true);
    expect(required.disabled).toBe(true);

    // optional: checked by default_enabled, can be toggled off
    expect(optional.checked).toBe(true);
    expect(optional.disabled).toBe(false);
    fireEvent.click(optional);
    expect(optional.checked).toBe(false);

    // required is still on after clicking (no-op)
    fireEvent.click(required);
    expect(required.checked).toBe(true);
  });
});
