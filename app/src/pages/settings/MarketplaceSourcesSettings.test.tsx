/**
 * Tests for MarketplaceSourcesSettings (Wave 5).
 *
 * Covers the user-visible contract from the implementation plan:
 *   1. The list of sources renders with handle, display name, and trust chip
 *   2. The Add modal submits a create request with the entered fields
 *   3. System rows (scope=system) are read-only — no edit/delete affordance
 *   4. Untrusted sources show the "MCP & app installs blocked" warning
 *   5. Test connection and Sync buttons invoke the matching API methods
 *
 * Mocks every dependency at the boundary so the page renders without a
 * router/auth/team provider. The harness uses a controllable `currentUser`
 * spy so individual tests can flip the superuser flag if needed.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { MarketplaceSourceResponse } from '../../lib/api';

vi.mock('../../config', () => ({ config: { API_URL: 'http://test' } }));

// vi.mock factories are hoisted above any module-level `const` references,
// so use `vi.hoisted` to declare the spies in the same hoisted bucket.
const {
  toastSuccess,
  toastError,
  listSources,
  createSource,
  updateSource,
  deleteSource,
  testSource,
  syncSource,
  promoteSource,
  currentUser,
  currentTeam,
} = vi.hoisted(() => {
  return {
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    listSources: vi.fn(),
    createSource: vi.fn(),
    updateSource: vi.fn(),
    deleteSource: vi.fn(),
    testSource: vi.fn(),
    syncSource: vi.fn(),
    promoteSource: vi.fn(),
    currentUser: vi.fn(),
    currentTeam: vi.fn(),
  };
});

vi.mock('react-hot-toast', () => ({
  default: { success: toastSuccess, error: toastError },
}));

// API mocks — the component imports the named object, not individual fns.
vi.mock('../../lib/api', () => ({
  marketplaceSourcesApi: {
    list: (...a: unknown[]) => listSources(...a),
    create: (...a: unknown[]) => createSource(...a),
    update: (...a: unknown[]) => updateSource(...a),
    delete: (...a: unknown[]) => deleteSource(...a),
    test: (...a: unknown[]) => testSource(...a),
    sync: (...a: unknown[]) => syncSource(...a),
    promote: (...a: unknown[]) => promoteSource(...a),
  },
}));

// Auth + team contexts — keep them stubable so individual tests can flip
// the superuser flag without re-mocking the whole module.
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: currentUser() }),
}));

vi.mock('../../contexts/TeamContext', () => ({
  useTeam: () => ({ activeTeam: currentTeam(), teamSwitchKey: 0 }),
}));

// Spinner is not under test — render a simple stub so the loading branch
// returns immediately.
vi.mock('../../components/PulsingGridSpinner', () => ({
  LoadingSpinner: () => <div data-testid="loading-spinner" />,
}));

// SettingsSection just wraps content; replace with a transparent passthrough.
vi.mock('../../components/settings', () => ({
  SettingsSection: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// ConfirmDialog uses createPortal which jsdom handles, but we can render
// inline to avoid the portal indirection in queries.
vi.mock('../../components/modals/ConfirmDialog', () => ({
  ConfirmDialog: ({
    isOpen,
    title,
    onConfirm,
    confirmText,
  }: {
    isOpen: boolean;
    title: string;
    onConfirm: () => void;
    confirmText?: string;
  }) =>
    isOpen ? (
      <div data-testid="confirm-dialog">
        <span>{title}</span>
        <button onClick={onConfirm}>{confirmText ?? 'Confirm'}</button>
      </div>
    ) : null,
}));

import MarketplaceSourcesSettings from './MarketplaceSourcesSettings';

const ISO = '2026-04-29T12:00:00Z';

function makeSource(over: Partial<MarketplaceSourceResponse> = {}): MarketplaceSourceResponse {
  return {
    id: 'src-1',
    handle: 'tesslate-official',
    display_name: 'Tesslate Official',
    base_url: 'https://marketplace.tesslate.com',
    scope: 'system',
    user_id: null,
    team_id: null,
    trust_level: 'official',
    is_system: true,
    is_active: true,
    has_token: false,
    pinned_hub_id: 'hub-tesslate',
    capabilities: ['agents', 'apps', 'themes', 'skills', 'connectors'],
    policies: {},
    last_synced_at: ISO,
    last_sync_error: null,
    sync_etag: 'etag-1',
    created_at: ISO,
    updated_at: ISO,
    ...over,
  };
}

const SOURCES: MarketplaceSourceResponse[] = [
  // System row — must be read-only
  makeSource(),
  // Untrusted user row — must show the install-blocked warning chip
  makeSource({
    id: 'src-2',
    handle: 'partner-anon',
    display_name: 'Partner Hub (anonymous)',
    base_url: 'https://partner.example.com',
    scope: 'user',
    user_id: 'user-1',
    trust_level: 'untrusted',
    is_system: false,
    has_token: false,
    capabilities: ['agents'],
    last_synced_at: null,
  }),
  // Private user row — has token, supports promote (when superuser)
  makeSource({
    id: 'src-3',
    handle: 'partner-private',
    display_name: 'Partner Hub (token)',
    base_url: 'https://private.example.com',
    scope: 'user',
    user_id: 'user-1',
    trust_level: 'private',
    is_system: false,
    has_token: true,
    capabilities: ['agents', 'apps'],
  }),
];

beforeEach(() => {
  listSources.mockReset();
  createSource.mockReset();
  updateSource.mockReset();
  deleteSource.mockReset();
  testSource.mockReset();
  syncSource.mockReset();
  promoteSource.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  currentUser.mockReturnValue({ id: 'user-1', email: 'a@b.co', is_superuser: false });
  currentTeam.mockReturnValue({ slug: 'personal', name: 'Personal', is_personal: true });
  listSources.mockResolvedValue(SOURCES);
});

describe('MarketplaceSourcesSettings', () => {
  it('lists every source visible to the user with handle and display name', async () => {
    render(<MarketplaceSourcesSettings />);

    await waitFor(() => {
      expect(screen.getByText('Tesslate Official')).toBeInTheDocument();
    });
    expect(screen.getByText('Partner Hub (anonymous)')).toBeInTheDocument();
    expect(screen.getByText('Partner Hub (token)')).toBeInTheDocument();

    // Trust chips render
    expect(screen.getByText('Official')).toBeInTheDocument();
    expect(screen.getByText('Untrusted')).toBeInTheDocument();
    expect(screen.getByText('Private')).toBeInTheDocument();
  });

  it('marks system rows as read-only — no edit/delete buttons', async () => {
    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Tesslate Official'));

    // System row should NOT have edit/delete affordance
    expect(screen.queryByTestId('source-edit-tesslate-official')).not.toBeInTheDocument();
    expect(screen.queryByTestId('source-delete-tesslate-official')).not.toBeInTheDocument();

    // System row badge present
    expect(screen.getByText('System')).toBeInTheDocument();

    // Non-system rows DO have those buttons
    expect(screen.getByTestId('source-edit-partner-private')).toBeInTheDocument();
    expect(screen.getByTestId('source-delete-partner-private')).toBeInTheDocument();
  });

  it('shows the "MCP & app installs blocked" warning for untrusted sources', async () => {
    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Partner Hub (anonymous)'));

    // The warning chip text is what users see when a source has no token
    expect(screen.getByText(/MCP .* app installs blocked/i)).toBeInTheDocument();
  });

  it('opens the add form and POSTs the entered values', async () => {
    createSource.mockResolvedValue(
      makeSource({
        id: 'src-new',
        handle: 'new-hub',
        display_name: 'New Hub',
        base_url: 'https://new.example.com',
        scope: 'user',
        user_id: 'user-1',
        trust_level: 'untrusted',
        is_system: false,
      })
    );

    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Tesslate Official'));

    fireEvent.click(screen.getByTestId('add-marketplace-source'));

    // Type into the inputs (placeholders identify them uniquely in the form)
    fireEvent.change(screen.getByPlaceholderText(/partner-hub/i), {
      target: { value: 'new-hub' },
    });
    fireEvent.change(screen.getByPlaceholderText(/Partner Marketplace/i), {
      target: { value: 'New Hub' },
    });
    fireEvent.change(screen.getByPlaceholderText(/marketplace.example.com/i), {
      target: { value: 'https://new.example.com' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Add source/i }));

    await waitFor(() => {
      expect(createSource).toHaveBeenCalledTimes(1);
    });
    expect(createSource).toHaveBeenCalledWith({
      handle: 'new-hub',
      display_name: 'New Hub',
      base_url: 'https://new.example.com',
      scope: 'user',
    });
    expect(toastSuccess).toHaveBeenCalledWith(expect.stringContaining('New Hub'));
  });

  it('Test connection invokes the API and surfaces the capability count', async () => {
    testSource.mockResolvedValue({
      hub_id: 'hub-private',
      api_version: '1.0.0',
      display_name: 'Partner Hub (token)',
      capabilities: ['agents', 'apps'],
      policies: {},
      auto_trust_level: 'private',
      pinned_hub_id_changed: true,
    });

    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Partner Hub (token)'));

    fireEvent.click(screen.getByTestId('source-test-partner-private'));

    await waitFor(() => {
      expect(testSource).toHaveBeenCalledWith('src-3');
    });
    // Toast must mention the capability count and the hub-id-pin status
    await waitFor(() => {
      expect(toastSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/capability|capabilities/i)
      );
    });
    expect(toastSuccess.mock.calls[0][0]).toMatch(/hub identity pinned/);
  });

  it('Sync now invokes the API and reports the event count', async () => {
    syncSource.mockResolvedValue({
      source_id: 'src-3',
      source_handle: 'partner-private',
      events_processed: 7,
      items_upserted: 5,
      items_deleted: 1,
      items_deactivated: 0,
      versions_yanked: 0,
      versions_removed: 0,
      pricing_changes: 0,
      etag_advanced_to: 'etag-2',
      error: null,
      skipped_reason: null,
      last_sync_error: null,
      last_synced_at: ISO,
    });

    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Partner Hub (token)'));

    fireEvent.click(screen.getByTestId('source-sync-partner-private'));

    await waitFor(() => {
      expect(syncSource).toHaveBeenCalledWith('src-3');
    });
    await waitFor(() => {
      expect(toastSuccess).toHaveBeenCalledWith(
        expect.stringMatching(/7 events/)
      );
    });
  });

  it('hides the promote action for non-superusers', async () => {
    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Partner Hub (token)'));
    expect(screen.queryByTestId('source-promote-partner-private')).not.toBeInTheDocument();
  });

  it('shows the promote action for superusers on private rows only', async () => {
    currentUser.mockReturnValue({ id: 'user-1', email: 'a@b.co', is_superuser: true });

    render(<MarketplaceSourcesSettings />);
    await waitFor(() => screen.getByText('Partner Hub (token)'));

    // Promote shown for the `private` row
    expect(screen.getByTestId('source-promote-partner-private')).toBeInTheDocument();
    // Promote NOT shown for the `untrusted` row (must add a token first)
    expect(screen.queryByTestId('source-promote-partner-anon')).not.toBeInTheDocument();
    // Promote NOT shown for the system row
    expect(screen.queryByTestId('source-promote-tesslate-official')).not.toBeInTheDocument();
  });
});
