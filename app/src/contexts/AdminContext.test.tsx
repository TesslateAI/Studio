/**
 * AdminContext smoke tests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

vi.mock('../config', () => ({
  config: { API_URL: 'http://test' },
}));

const getQueue = vi.fn();
const getYankQueue = vi.fn();
const getStats = vi.fn();

vi.mock('../lib/api', () => ({
  adminMarketplaceApi: {
    getQueue: (...a: unknown[]) => getQueue(...a),
    getYankQueue: (...a: unknown[]) => getYankQueue(...a),
    getStats: (...a: unknown[]) => getStats(...a),
  },
  appSubmissionsApi: { advance: vi.fn() },
  appYanksApi: { approve: vi.fn(), reject: vi.fn() },
}));

const authState = { user: { id: 'u1', is_superuser: true } as { id: string; is_superuser: boolean } | null };
vi.mock('./AuthContext', () => ({
  useAuth: () => ({ user: authState.user }),
}));

import { AdminProvider, useAdmin, useRequiredAdmin } from './AdminContext';

const wrapper = ({ children }: { children: ReactNode }) => (
  <AdminProvider>{children}</AdminProvider>
);

describe('AdminContext', () => {
  beforeEach(() => {
    getQueue.mockReset();
    getYankQueue.mockReset();
    getStats.mockReset();
    authState.user = { id: 'u1', is_superuser: true };
  });

  it('useAdmin returns null outside provider', () => {
    const { result } = renderHook(() => useAdmin());
    expect(result.current).toBeNull();
  });

  it('useRequiredAdmin throws outside provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useRequiredAdmin())).toThrow(/AdminProvider/);
    spy.mockRestore();
  });

  it('populates queues + stats for superusers', async () => {
    getQueue.mockResolvedValue({
      items: [{ submission_id: 's1', app_version_id: 'v1', app_id: 'a1', stage: 'review', check_count: 0 }],
      limit: 100,
      offset: 0,
    });
    getYankQueue.mockResolvedValue({ items: [], limit: 100, offset: 0 });
    getStats.mockResolvedValue({
      apps_total: 1,
      apps_approved: 0,
      apps_pending: 1,
      yanks_pending: 0,
      submissions_in_flight: 1,
      monitoring_runs_24h: 0,
    });

    const { result } = renderHook(() => useRequiredAdmin(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.submissionQueue).toHaveLength(1);
    expect(result.current.stats?.apps_total).toBe(1);
  });

  it('no-ops for non-superusers', async () => {
    authState.user = { id: 'u1', is_superuser: false };
    const { result } = renderHook(() => useRequiredAdmin(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(getQueue).not.toHaveBeenCalled();
    expect(result.current.stats).toBeNull();
  });
});
