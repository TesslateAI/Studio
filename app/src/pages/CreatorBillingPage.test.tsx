import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));

const getCreatorWallet = vi.fn();
const getLedger = vi.fn();

vi.mock('../lib/api', () => ({
  appBillingApi: {
    getCreatorWallet: (...a: unknown[]) => getCreatorWallet(...a),
    getLedger: (...a: unknown[]) => getLedger(...a),
  },
}));

const mockUser = vi.fn();
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: mockUser() }),
}));

import CreatorBillingPage from './CreatorBillingPage';

function renderPage() {
  return render(
    <MemoryRouter>
      <CreatorBillingPage />
    </MemoryRouter>
  );
}

describe('CreatorBillingPage', () => {
  beforeEach(() => {
    getCreatorWallet.mockReset();
    getLedger.mockReset();
    mockUser.mockReset();
  });

  it('shows onboarding prompt when wallet API returns 403', async () => {
    mockUser.mockReturnValue({ id: 'u1', email: 'a@b.co', creator_stripe_account_id: 'acct_1' });
    getCreatorWallet.mockRejectedValue({ response: { status: 403 } });
    getLedger.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Become a creator/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Connect Stripe/i)).toBeInTheDocument();
  });

  it('shows onboarding when user has no stripe account', async () => {
    mockUser.mockReturnValue({ id: 'u1', email: 'a@b.co' });
    getCreatorWallet.mockRejectedValue({ response: { status: 403 } });
    getLedger.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Become a creator/i)).toBeInTheDocument();
    });
  });
});
