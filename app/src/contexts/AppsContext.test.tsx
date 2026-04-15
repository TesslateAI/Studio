/**
 * AppsContext smoke tests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import type { ReactNode } from 'react';

vi.mock('../config', () => ({
  config: { API_URL: 'http://test' },
}));

const listMine = vi.fn();
const install = vi.fn();
const uninstall = vi.fn();
const publish = vi.fn();

vi.mock('../lib/api', () => ({
  appInstallsApi: {
    listMine: (...args: unknown[]) => listMine(...args),
    install: (...args: unknown[]) => install(...args),
    uninstall: (...args: unknown[]) => uninstall(...args),
  },
  appVersionsApi: {
    publish: (...args: unknown[]) => publish(...args),
  },
}));

vi.mock('./AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

import { AppsProvider, useApps } from './AppsContext';

const wrapper = ({ children }: { children: ReactNode }) => (
  <AppsProvider>{children}</AppsProvider>
);

describe('AppsContext', () => {
  beforeEach(() => {
    listMine.mockReset();
    install.mockReset();
    uninstall.mockReset();
    publish.mockReset();
  });

  it('throws when useApps is used outside provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useApps())).toThrow(/AppsProvider/);
    spy.mockRestore();
  });

  it('loads installs on mount', async () => {
    listMine.mockResolvedValue({ items: [{ id: 'i1' }], total: 1, limit: 200, offset: 0 });
    const { result } = renderHook(() => useApps(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.myInstalls).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it('installApp refreshes the list', async () => {
    listMine.mockResolvedValueOnce({ items: [], total: 0, limit: 200, offset: 0 });
    install.mockResolvedValue({
      app_instance_id: 'x',
      project_id: null,
      volume_id: 'v',
      node_name: 'n',
    });
    listMine.mockResolvedValueOnce({
      items: [{ id: 'new' }],
      total: 1,
      limit: 200,
      offset: 0,
    });

    const { result } = renderHook(() => useApps(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.installApp({
        app_version_id: 'v1',
        team_id: 't1',
      });
    });
    expect(install).toHaveBeenCalledOnce();
    expect(result.current.myInstalls).toHaveLength(1);
  });
});
