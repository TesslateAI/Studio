import { useCallback, useEffect, useRef, useState } from 'react';
import { automationsApi } from '../lib/api';
import type { ApprovalRequest } from '../types/automations';

interface PendingApprovalsState {
  approvals: ApprovalRequest[];
  count: number;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

interface Options {
  /** Polling interval in ms. Default 30s. Pass 0 to disable. */
  pollMs?: number;
  /** Skip the network call entirely (e.g., when unauthenticated). */
  enabled?: boolean;
}

/**
 * Polling hook for the cross-automation pending-approvals list.
 *
 * Used by both the NavigationSidebar badge (cares about ``count``) and
 * the full ``ApprovalsPage`` (cares about ``approvals``). The endpoint
 * is cheap (a small JSON list) so a single shared poll covers both
 * call sites without coordination.
 *
 * Failure is non-blocking: a transient error keeps the previously
 * fetched list visible (so the badge doesn't flicker) and exposes
 * ``error`` for callers that want to surface it.
 */
export function usePendingApprovals({
  pollMs = 30_000,
  enabled = true,
}: Options = {}): PendingApprovalsState {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const fetchOnce = useCallback(async () => {
    if (!enabled) return;
    try {
      const list = await automationsApi.approvals.listPending();
      if (cancelledRef.current) return;
      setApprovals(list);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ||
        (err as Error).message ||
        'Failed to load approvals';
      setError(msg);
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    cancelledRef.current = false;
    if (!enabled) {
      setLoading(false);
      return () => {
        cancelledRef.current = true;
      };
    }
    fetchOnce();
    if (pollMs <= 0) {
      return () => {
        cancelledRef.current = true;
      };
    }
    const id = window.setInterval(fetchOnce, pollMs);
    return () => {
      cancelledRef.current = true;
      window.clearInterval(id);
    };
  }, [enabled, pollMs, fetchOnce]);

  return {
    approvals,
    count: approvals.length,
    loading,
    error,
    refresh: fetchOnce,
  };
}

/** Convenience wrapper for callers that only need the count (e.g. badge). */
export function usePendingApprovalCount(opts?: Options): number {
  return usePendingApprovals(opts).count;
}
