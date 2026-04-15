import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));

const listApps = vi.fn();
const listVersions = vi.fn();

vi.mock('../lib/api', () => ({
  marketplaceAppsApi: {
    list: (...a: unknown[]) => listApps(...a),
    listVersions: (...a: unknown[]) => listVersions(...a),
  },
  appBillingApi: {
    getCreatorWallet: vi.fn(),
    getLedger: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
  },
}));

const mockUser = vi.fn();
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: mockUser() }),
}));

vi.mock('../contexts/TeamContext', () => ({
  useTeam: () => ({ activeTeam: null }),
}));

import CreatorStudioPage from './CreatorStudioPage';

function renderPage() {
  return render(
    <MemoryRouter>
      <CreatorStudioPage />
    </MemoryRouter>
  );
}

describe('CreatorStudioPage', () => {
  beforeEach(() => {
    listApps.mockReset();
    listVersions.mockReset();
    mockUser.mockReset();
    listApps.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
  });

  it('shows become-a-creator state when user has no stripe account', () => {
    mockUser.mockReturnValue({ id: 'u1', email: 'a@b.co' });
    renderPage();
    expect(screen.getByText(/Become a creator/i)).toBeInTheDocument();
  });

  it('shows tabs when user is a creator', async () => {
    mockUser.mockReturnValue({ id: 'u1', email: 'a@b.co', creator_stripe_account_id: 'acct_1' });
    renderPage();
    await waitFor(() => expect(screen.getByText('Creator Studio')).toBeInTheDocument());
    expect(screen.getByText('My Apps')).toBeInTheDocument();
    expect(screen.getByText('Drafts')).toBeInTheDocument();
    expect(screen.getByText('Submissions')).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('Publish New Version')).toBeInTheDocument();
  });
});
