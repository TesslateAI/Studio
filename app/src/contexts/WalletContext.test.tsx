/**
 * WalletContext smoke tests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

vi.mock('../config', () => ({
  config: { API_URL: 'http://test' },
}));

const getInstallerWallet = vi.fn();
const getCreatorWallet = vi.fn();
const getLedger = vi.fn();

vi.mock('../lib/api', () => ({
  appBillingApi: {
    getInstallerWallet: (...a: unknown[]) => getInstallerWallet(...a),
    getCreatorWallet: (...a: unknown[]) => getCreatorWallet(...a),
    getLedger: (...a: unknown[]) => getLedger(...a),
  },
}));

vi.mock('./AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

import { WalletProvider, useWallet } from './WalletContext';

const wrapper = ({ children }: { children: ReactNode }) => (
  <WalletProvider>{children}</WalletProvider>
);

describe('WalletContext', () => {
  beforeEach(() => {
    getInstallerWallet.mockReset();
    getCreatorWallet.mockReset();
    getLedger.mockReset();
  });

  it('throws when used outside provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useWallet())).toThrow(/WalletProvider/);
    spy.mockRestore();
  });

  it('loads installer wallet and tolerates 403 creator wallet', async () => {
    getInstallerWallet.mockResolvedValue({
      id: 'w1',
      owner_type: 'installer',
      owner_user_id: 'u1',
      balance_usd: 5,
    });
    getCreatorWallet.mockRejectedValue({ response: { status: 403 } });
    getLedger.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });

    const { result } = renderHook(() => useWallet(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.installerWallet?.balance_usd).toBe(5);
    expect(result.current.creatorWallet).toBeNull();
    expect(result.current.recentLedger).toEqual([]);
  });
});
