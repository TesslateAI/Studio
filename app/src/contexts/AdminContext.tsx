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
  adminMarketplaceApi,
  appSubmissionsApi,
  appYanksApi,
  type AdminStats,
  type ScanRunResult,
  type SubmissionQueueItem,
  type YankQueueItem,
} from '../lib/api';
import { useAuth } from './AuthContext';

/**
 * AdminContext
 *
 * Marketplace admin state (submission queue, yank queue, aggregate stats) plus
 * review mutations. Only populates data when `useAuth().user.is_superuser` is
 * true; otherwise value is `null` and admin pages should redirect away.
 */

export interface AdminContextValue {
  submissionQueue: SubmissionQueueItem[];
  yankQueue: YankQueueItem[];
  stats: AdminStats | null;
  isLoading: boolean;
  error: string | null;
  refreshAll: () => Promise<void>;
  advanceSubmission: (submissionId: string, toStage: string, notes?: string) => Promise<void>;
  runStage1Scan: (submissionId: string) => Promise<ScanRunResult>;
  runStage2Eval: (submissionId: string) => Promise<ScanRunResult>;
  approveYank: (yankRequestId: string) => Promise<{ needsSecondAdmin: boolean }>;
  rejectYank: (yankRequestId: string, note?: string) => Promise<void>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const AdminContext = createContext<AdminContextValue | null>(null);

function extractError(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string };
  return e?.response?.data?.detail ?? e?.message ?? fallback;
}

export function AdminProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);

  const [submissionQueue, setSubmissionQueue] = useState<SubmissionQueueItem[]>([]);
  const [yankQueue, setYankQueue] = useState<YankQueueItem[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshAll = useCallback(async () => {
    if (!isSuperuser) {
      setSubmissionQueue([]);
      setYankQueue([]);
      setStats(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    const [queueResult, yankResult, statsResult] = await Promise.allSettled([
      adminMarketplaceApi.getQueue({ limit: 100 }),
      adminMarketplaceApi.getYankQueue({ limit: 100 }),
      adminMarketplaceApi.getStats(),
    ]);

    if (queueResult.status === 'fulfilled') {
      setSubmissionQueue(queueResult.value.items);
    } else {
      setError(extractError(queueResult.reason, 'Failed to load submission queue'));
    }
    if (yankResult.status === 'fulfilled') {
      setYankQueue(yankResult.value.items);
    } else if (!error) {
      setError(extractError(yankResult.reason, 'Failed to load yank queue'));
    }
    if (statsResult.status === 'fulfilled') {
      setStats(statsResult.value);
    }
    setIsLoading(false);
  }, [isSuperuser, error]);

  useEffect(() => {
    void refreshAll();
    // refreshAll intentionally excluded to avoid loops from `error` changes;
    // admins can manually retry via the returned `refreshAll`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuperuser]);

  const advanceSubmission = useCallback(
    async (submissionId: string, toStage: string, notes?: string) => {
      try {
        await appSubmissionsApi.advance(submissionId, {
          to_stage: toStage,
          decision_notes: notes,
        });
        await refreshAll();
      } catch (err) {
        setError(extractError(err, 'Failed to advance submission'));
        throw err;
      }
    },
    [refreshAll]
  );

  const runStage1Scan = useCallback(
    async (submissionId: string) => {
      try {
        const out = await appSubmissionsApi.runStage1Scan(submissionId);
        await refreshAll();
        return out;
      } catch (err) {
        setError(extractError(err, 'Stage 1 scan failed'));
        throw err;
      }
    },
    [refreshAll]
  );

  const runStage2Eval = useCallback(
    async (submissionId: string) => {
      try {
        const out = await appSubmissionsApi.runStage2Eval(submissionId);
        await refreshAll();
        return out;
      } catch (err) {
        setError(extractError(err, 'Stage 2 eval failed'));
        throw err;
      }
    },
    [refreshAll]
  );

  const approveYank = useCallback(
    async (yankRequestId: string) => {
      try {
        const result = await appYanksApi.approve(yankRequestId);
        await refreshAll();
        return { needsSecondAdmin: result.needs_second_admin };
      } catch (err) {
        setError(extractError(err, 'Failed to approve yank'));
        throw err;
      }
    },
    [refreshAll]
  );

  const rejectYank = useCallback(
    async (yankRequestId: string, note?: string) => {
      try {
        await appYanksApi.reject(yankRequestId, note);
        await refreshAll();
      } catch (err) {
        setError(extractError(err, 'Failed to reject yank'));
        throw err;
      }
    },
    [refreshAll]
  );

  const value = useMemo<AdminContextValue>(
    () => ({
      submissionQueue,
      yankQueue,
      stats,
      isLoading,
      error,
      refreshAll,
      advanceSubmission,
      runStage1Scan,
      runStage2Eval,
      approveYank,
      rejectYank,
    }),
    [
      submissionQueue,
      yankQueue,
      stats,
      isLoading,
      error,
      refreshAll,
      advanceSubmission,
      runStage1Scan,
      runStage2Eval,
      approveYank,
      rejectYank,
    ]
  );

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}

/**
 * Returns the AdminContext value if the current user is a superuser, else
 * `null`. Admin pages should redirect when this is `null`.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useAdmin(): AdminContextValue | null {
  return useContext(AdminContext);
}

/**
 * Strict variant — throws if no provider is mounted. Use in admin-only pages
 * where you've already gated on `user.is_superuser`.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useRequiredAdmin(): AdminContextValue {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error('useRequiredAdmin must be used within AdminProvider');
  return ctx;
}
