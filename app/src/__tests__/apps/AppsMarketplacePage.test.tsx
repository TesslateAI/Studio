/**
 * AppsMarketplacePage smoke test.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

vi.mock('../../config', () => ({
  config: { API_URL: 'http://test' },
}));

const list = vi.fn();
const listVersions = vi.fn();

vi.mock('../../lib/api', () => ({
  marketplaceAppsApi: {
    list: (...args: unknown[]) => list(...args),
    listVersions: (...args: unknown[]) => listVersions(...args),
  },
}));

vi.mock('../../contexts/AppsContext', () => ({
  useApps: () => ({
    myInstalls: [],
    installApp: vi.fn(),
  }),
}));

vi.mock('../../contexts/TeamContext', () => ({
  useTeam: () => ({
    teams: [],
    activeTeam: null,
  }),
}));

// AppInstallWizard pulls in TeamContext/AppsContext; stub it.
vi.mock('../../components/apps/AppInstallWizard', () => ({
  AppInstallWizard: () => null,
}));

import AppsMarketplacePage from '../../pages/AppsMarketplacePage';

function wrap(node: ReactNode) {
  return <MemoryRouter>{node}</MemoryRouter>;
}

describe('AppsMarketplacePage', () => {
  beforeEach(() => {
    list.mockReset();
    listVersions.mockReset();
  });

  it('renders app cards from API response', async () => {
    list.mockResolvedValue({
      items: [
        {
          id: 'app-1',
          slug: 'alpha',
          name: 'Alpha App',
          description: 'First app',
          category: 'productivity',
          icon_ref: null,
          forkable: 'true',
          forked_from: null,
          visibility: 'public',
          state: 'approved',
          reputation: {},
          creator_user_id: null,
          created_at: '',
          updated_at: '',
        },
        {
          id: 'app-2',
          slug: 'beta',
          name: 'Beta App',
          description: 'Second app',
          category: 'ai',
          icon_ref: null,
          forkable: 'no',
          forked_from: null,
          visibility: 'public',
          state: 'approved',
          reputation: {},
          creator_user_id: 'u1',
          created_at: '',
          updated_at: '',
        },
      ],
      total: 2,
      limit: 20,
      offset: 0,
    });

    render(wrap(<AppsMarketplacePage />));

    await waitFor(() => {
      expect(screen.getByText('Alpha App')).toBeInTheDocument();
      expect(screen.getByText('Beta App')).toBeInTheDocument();
    });
    expect(list).toHaveBeenCalled();
  });
});
