import { useEffect, useRef, useState } from 'react';
import { projectsApi } from '../lib/api';

export type IframeHealthPhase = 'idle' | 'checking' | 'installing' | 'healthy' | 'error';

export interface IframeHealthState {
  phase: IframeHealthPhase;
  statusCode: number | null;
  error: string | null;
  /** Bumps once when phase transitions to `healthy`, so consumers can use it
   *  as a React `key` to remount/refresh the iframe. */
  reloadToken: number;
}

export interface UseIframeHealthOptions {
  enabled: boolean;
  projectSlug: string | null | undefined;
  containerId: string | null | undefined;
  /** Polling interval while not healthy (ms). Default 2000. */
  intervalMs?: number;
  /** Cap on consecutive errors before flipping to `error`. Default 60
   *  (= 2 minutes at default interval). Below the cap we keep showing
   *  `installing` so deps installs that take a while don't flash an error. */
  maxInstallingPolls?: number;
}

const INSTALLING_STATUS_CODES = new Set([404, 502, 503, 504]);

function classify(
  result: { healthy: boolean; status_code?: number; error?: string },
  installingPolls: number,
  maxInstallingPolls: number
): { phase: IframeHealthPhase; statusCode: number | null; error: string | null } {
  if (result.healthy) {
    return { phase: 'healthy', statusCode: result.status_code ?? null, error: null };
  }
  const code = result.status_code ?? null;
  // Transport-level failures (no status_code) during the early install
  // window are almost always "container not yet listening" — treat as
  // installing until we exceed the budget.
  if (code === null || INSTALLING_STATUS_CODES.has(code)) {
    if (installingPolls >= maxInstallingPolls) {
      return {
        phase: 'error',
        statusCode: code,
        error: result.error ?? 'App did not become ready in time',
      };
    }
    return { phase: 'installing', statusCode: code, error: null };
  }
  return {
    phase: 'error',
    statusCode: code,
    error: result.error ?? `Unexpected response from app (${code})`,
  };
}

/**
 * Polls the orchestrator's container-health endpoint to determine when an
 * iframe target is ready to be displayed. Designed for two callers: the
 * project builder preview pane and the Tesslate Apps workspace surface.
 *
 * - While the container is starting / installing deps, the response is
 *   typically 503 (service unavailable) or 404 (route not yet bound). The
 *   hook surfaces these as `installing` so the UI can show a friendly
 *   message instead of a browser error page.
 * - Other 4xx/5xx responses surface as `error` since they likely indicate
 *   a misconfigured app (auth, manifest, etc.) rather than a startup race.
 * - Polling stops as soon as `healthy` is reached. To re-arm the check
 *   after a stop/restart, flip `enabled` off then on.
 */
export function useIframeHealth(opts: UseIframeHealthOptions): IframeHealthState {
  const {
    enabled,
    projectSlug,
    containerId,
    intervalMs = 2000,
    maxInstallingPolls = 60,
  } = opts;

  const [state, setState] = useState<IframeHealthState>({
    phase: 'idle',
    statusCode: null,
    error: null,
    reloadToken: 0,
  });

  const installingPollsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    installingPollsRef.current = 0;

    const clearTimer = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    if (!enabled || !projectSlug || !containerId) {
      clearTimer();
      setState((prev) =>
        prev.phase === 'idle' ? prev : { ...prev, phase: 'idle', error: null }
      );
      return () => {
        cancelledRef.current = true;
        clearTimer();
      };
    }

    // Start in `checking` so the UI can show a neutral spinner before the
    // first poll resolves (avoids a flicker of "ready" when the iframe
    // hasn't been verified yet).
    setState((prev) =>
      prev.phase === 'healthy' ? prev : { ...prev, phase: 'checking', error: null }
    );

    const poll = async () => {
      if (cancelledRef.current) return;
      try {
        const result = await projectsApi.checkContainerHealth(projectSlug, containerId);
        if (cancelledRef.current) return;

        if (!result.healthy) {
          installingPollsRef.current += 1;
        }

        const { phase, statusCode, error } = classify(
          result,
          installingPollsRef.current,
          maxInstallingPolls
        );

        setState((prev) => {
          // First transition into healthy bumps the reload token exactly
          // once so the iframe can be force-remounted with a fresh URL.
          // Subsequent identical responses don't churn the token.
          if (phase === 'healthy' && prev.phase !== 'healthy') {
            return {
              phase,
              statusCode,
              error,
              reloadToken: prev.reloadToken + 1,
            };
          }
          if (
            prev.phase === phase &&
            prev.statusCode === statusCode &&
            prev.error === error
          ) {
            return prev;
          }
          return { ...prev, phase, statusCode, error };
        });

        if (phase !== 'healthy' && !cancelledRef.current) {
          timerRef.current = setTimeout(poll, intervalMs);
        }
      } catch (err) {
        if (cancelledRef.current) return;
        installingPollsRef.current += 1;
        const error = err instanceof Error ? err.message : 'Health check failed';
        const phase: IframeHealthPhase =
          installingPollsRef.current >= maxInstallingPolls ? 'error' : 'installing';
        setState((prev) =>
          prev.phase === phase && prev.error === error
            ? prev
            : { ...prev, phase, error }
        );
        if (phase !== 'healthy' && !cancelledRef.current) {
          timerRef.current = setTimeout(poll, intervalMs);
        }
      }
    };

    poll();

    return () => {
      cancelledRef.current = true;
      clearTimer();
    };
  }, [enabled, projectSlug, containerId, intervalMs, maxInstallingPolls]);

  return state;
}
