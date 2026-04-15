import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import type { AppInstance } from '../lib/api';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));
vi.mock('react-hot-toast', () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const uninstallApp = vi.fn();
const refresh = vi.fn();

vi.mock('../contexts/AppsContext', () => ({
  useApps: () => ({
    myInstalls: installs,
    isLoading: false,
    error: null,
    refresh,
    installApp: vi.fn(),
    uninstallApp,
    publishVersion: vi.fn(),
  }),
}));

const installs: AppInstance[] = [
  {
    id: 'i1',
    app_id: 'a1',
    app_version_id: 'v1',
    project_id: null,
    state: 'installed',
    update_policy: 'manual',
    volume_id: null,
    installed_at: '2025-01-01T00:00:00Z',
    uninstalled_at: null,
    created_at: '2025-01-01T00:00:00Z',
    app_slug: 'alpha',
    app_name: 'Alpha',
    app_version: '1.0.0',
  },
  {
    id: 'i2',
    app_id: 'a2',
    app_version_id: 'v2',
    project_id: null,
    state: 'running',
    update_policy: 'manual',
    volume_id: null,
    installed_at: '2025-01-02T00:00:00Z',
    uninstalled_at: null,
    created_at: '2025-01-02T00:00:00Z',
    app_slug: 'beta',
    app_name: 'Beta',
    app_version: '2.0.0',
  },
];

import MyAppsPage from './MyAppsPage';

describe('MyAppsPage', () => {
  it('renders a card for each non-uninstalled install', () => {
    render(
      <MemoryRouter>
        <MyAppsPage />
      </MemoryRouter>
    );
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByTestId('app-open-i1')).toBeInTheDocument();
    expect(screen.getByTestId('app-open-i2')).toBeInTheDocument();
  });
});
