/**
 * AdminMarketplaceReviewPage tests — verifies superuser gating.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));

const mockUseAuth = vi.fn();
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

const adminValue = {
  submissionQueue: [],
  yankQueue: [],
  stats: null,
  isLoading: false,
  error: null,
  refreshAll: vi.fn().mockResolvedValue(undefined),
  advanceSubmission: vi.fn(),
  approveYank: vi.fn(),
  rejectYank: vi.fn(),
};
vi.mock('../contexts/AdminContext', () => ({
  useRequiredAdmin: () => adminValue,
}));

import AdminMarketplaceReviewPage from './AdminMarketplaceReviewPage';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/marketplace" element={<AdminMarketplaceReviewPage />} />
        <Route path="/dashboard" element={<div>DASHBOARD</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AdminMarketplaceReviewPage', () => {
  it('renders for superuser', () => {
    mockUseAuth.mockReturnValue({ user: { id: 'u1', is_superuser: true } });
    renderAt('/admin/marketplace');
    expect(screen.getByText('Marketplace Review')).toBeInTheDocument();
    expect(screen.getByText('Submissions')).toBeInTheDocument();
  });

  it('redirects non-superuser to /dashboard', () => {
    mockUseAuth.mockReturnValue({ user: { id: 'u1', is_superuser: false } });
    renderAt('/admin/marketplace');
    expect(screen.getByText('DASHBOARD')).toBeInTheDocument();
    expect(screen.queryByText('Marketplace Review')).not.toBeInTheDocument();
  });
});
