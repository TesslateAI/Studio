import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  appBillingApi,
  type LedgerEntry,
  type WalletSnapshot,
} from '../lib/api';
import { useAuth } from './AuthContext';

/**
 * WalletContext
 *
 * Installer + (optional) creator wallet snapshots plus a rolling ledger for
 * the current user. Creator wallet is lazy: the backend returns 403 for
 * non-creators and we surface that as `creatorWallet === null` (not an error).
 */

export interface WalletContextValue {
  installerWallet: WalletSnapshot | null;
  creatorWallet: WalletSnapshot | null;
  recentLedger: LedgerEntry[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const WalletContext = createContext<WalletContextValue | null>(null);

function extractError(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string };
  return e?.response?.data?.detail ?? e?.message ?? fallback;
}

function statusOf(err: unknown): number | undefined {
  return (err as { response?: { status?: number } })?.response?.status;
}

export function WalletProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [installerWallet, setInstallerWallet] = useState<WalletSnapshot | null>(null);
  const [creatorWallet, setCreatorWallet] = useState<WalletSnapshot | null>(null);
  const [recentLedger, setRecentLedger] = useState<LedgerEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setInstallerWallet(null);
      setCreatorWallet(null);
      setRecentLedger([]);
      setError(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);

    const [installerResult, creatorResult, ledgerResult] = await Promise.allSettled([
      appBillingApi.getInstallerWallet(),
      appBillingApi.getCreatorWallet(),
      appBillingApi.getLedger({ limit: 20 }),
    ]);

    if (installerResult.status === 'fulfilled') {
      setInstallerWallet(installerResult.value);
    } else {
      setError(extractError(installerResult.reason, 'Failed to load wallet'));
    }

    if (creatorResult.status === 'fulfilled') {
      setCreatorWallet(creatorResult.value);
    } else if (statusOf(creatorResult.reason) === 403) {
      // User isn't a creator — not an error, just no wallet.
      setCreatorWallet(null);
    } else {
      // Non-403 creator-wallet failures are surfaced but non-fatal.
      setCreatorWallet(null);
    }

    if (ledgerResult.status === 'fulfilled') {
      setRecentLedger(ledgerResult.value.items);
    } else {
      setRecentLedger([]);
    }

    setIsLoading(false);
  }, [isAuthenticated]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<WalletContextValue>(
    () => ({
      installerWallet,
      creatorWallet,
      recentLedger,
      isLoading,
      error,
      refresh,
    }),
    [installerWallet, creatorWallet, recentLedger, isLoading, error, refresh]
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWallet(): WalletContextValue {
  const ctx = useContext(WalletContext);
  if (!ctx) throw new Error('useWallet must be used within WalletProvider');
  return ctx;
}
