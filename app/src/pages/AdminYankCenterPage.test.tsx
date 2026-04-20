/**
 * AdminYankCenterPage — verifies "Needs second admin" rendering for
 * pending critical yanks with a primary admin but no secondary.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../config', () => ({ config: { API_URL: 'http://test' } }));

const mockUseAuth = vi.fn();
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('../contexts/AdminContext', () => ({
  useRequiredAdmin: () => ({
    submissionQueue: [],
    yankQueue: [],
    stats: null,
    isLoading: false,
    error: null,
    refreshAll: vi.fn(),
    advanceSubmission: vi.fn(),
    runStage1Scan: vi.fn(),
    runStage2Eval: vi.fn(),
    approveYank: vi.fn(),
    rejectYank: vi.fn(),
  }),
}));

const listYanks = vi.fn();
vi.mock('../lib/api', () => ({
  appYanksApi: {
    list: (...a: unknown[]) => listYanks(...a),
  },
}));

import AdminYankCenterPage from './AdminYankCenterPage';

beforeEach(() => {
  listYanks.mockReset();
  mockUseAuth.mockReturnValue({ user: { id: 'u1', is_superuser: true } });
});

describe('AdminYankCenterPage', () => {
  it('renders "Needs second admin" for critical pending yank with primary set', async () => {
    listYanks.mockResolvedValue({
      items: [
        {
          id: 'y1',
          app_version_id: 'vvvvvvvv1234',
          requester_user_id: 'uuuuuuuu9999',
          severity: 'critical',
          reason: 'data leak',
          status: 'pending',
          primary_admin_id: 'aaaaaaaa1111',
          secondary_admin_id: null,
        },
      ],
      limit: 100,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <AdminYankCenterPage />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('needs-second-y1')).toHaveTextContent('Needs second admin');
  });
});
