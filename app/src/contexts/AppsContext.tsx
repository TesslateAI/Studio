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
  appInstallsApi,
  appVersionsApi,
  type AppInstance,
  type InstallRequest,
  type InstallResult,
  type PublishRequest,
  type PublishResult,
} from '../lib/api';
import { useAuth } from './AuthContext';

/**
 * AppsContext
 *
 * Installed-app state for the current user plus publish/install/uninstall
 * mutations. Mount ABOVE any component that needs marketplace install
 * awareness (e.g. app library page, installed-apps sidebar). Unauthenticated
 * users see an empty `myInstalls` list and a no-op `refresh`.
 */

export interface AppsContextValue {
  myInstalls: AppInstance[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  installApp: (args: InstallRequest) => Promise<InstallResult>;
  uninstallApp: (appInstanceId: string) => Promise<void>;
  publishVersion: (args: PublishRequest) => Promise<PublishResult>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const AppsContext = createContext<AppsContextValue | null>(null);

function extractError(err: unknown, fallback: string): string {
  // FastAPI returns `detail` as either a plain string OR a structured
  // object — e.g. `{message, errors}` from the install router when the
  // underlying ProjectionError carries a manifest validation error list.
  // Surface the message; the caller can also read err.response.data.detail
  // directly to render field-level errors.
  const e = err as {
    response?: { data?: { detail?: string | { message?: string } } };
    message?: string;
  };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message;
  }
  return e?.message ?? fallback;
}

export function AppsProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [myInstalls, setMyInstalls] = useState<AppInstance[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setMyInstalls([]);
      setError(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const envelope = await appInstallsApi.listMine({ limit: 200 });
      setMyInstalls(envelope.items);
    } catch (err) {
      setError(extractError(err, 'Failed to load installed apps'));
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const installApp = useCallback(
    async (args: InstallRequest) => {
      try {
        const result = await appInstallsApi.install(args);
        await refresh();
        return result;
      } catch (err) {
        const msg = extractError(err, 'Failed to install app');
        setError(msg);
        throw err;
      }
    },
    [refresh]
  );

  const uninstallApp = useCallback(
    async (appInstanceId: string) => {
      try {
        await appInstallsApi.uninstall(appInstanceId);
        await refresh();
      } catch (err) {
        const msg = extractError(err, 'Failed to uninstall app');
        setError(msg);
        throw err;
      }
    },
    [refresh]
  );

  const publishVersion = useCallback(async (args: PublishRequest) => {
    try {
      return await appVersionsApi.publish(args);
    } catch (err) {
      const msg = extractError(err, 'Failed to publish app version');
      setError(msg);
      throw err;
    }
  }, []);

  const value = useMemo<AppsContextValue>(
    () => ({
      myInstalls,
      isLoading,
      error,
      refresh,
      installApp,
      uninstallApp,
      publishVersion,
    }),
    [myInstalls, isLoading, error, refresh, installApp, uninstallApp, publishVersion]
  );

  return <AppsContext.Provider value={value}>{children}</AppsContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApps(): AppsContextValue {
  const ctx = useContext(AppsContext);
  if (!ctx) throw new Error('useApps must be used within AppsProvider');
  return ctx;
}
