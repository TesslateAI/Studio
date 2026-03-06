/**
 * Hook for making cancellable API requests
 *
 * Automatically aborts in-flight requests on unmount to prevent:
 * - Memory leaks from state updates on unmounted components
 * - Race conditions from concurrent requests
 *
 * Usage:
 * ```tsx
 * const { execute } = useCancellableRequest<UserProfile>();
 *
 * useEffect(() => {
 *   execute(
 *     (signal) => api.get('/api/users/profile', { signal }).then(r => r.data),
 *     {
 *       onSuccess: setProfile,
 *       onError: (err) => toast.error(err.message),
 *       onFinally: () => setLoading(false),
 *     }
 *   );
 * }, [execute]);
 * ```
 */

import { useRef, useCallback, useEffect } from 'react';

interface RequestOptions<T> {
  /** Called with data on successful request (only if mounted) */
  onSuccess?: (data: T) => void;
  /** Called with error on failed request (only if mounted) */
  onError?: (error: Error) => void;
  /** Called after request completes (success or failure, only if mounted) */
  onFinally?: () => void;
}

interface CancellableRequestResult<T> {
  /** Execute a cancellable request */
  execute: (
    requestFn: (signal: AbortSignal) => Promise<T>,
    options?: RequestOptions<T>
  ) => Promise<T | null>;
  /** Manually abort the current request */
  abort: () => void;
  /** Check if a request is currently in progress */
  isLoading: boolean;
}

/**
 * Hook for making cancellable API requests
 *
 * @returns Object with execute function, abort function, and loading state
 */
export function useCancellableRequest<T>(): CancellableRequestResult<T> {
  const abortControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const loadingRef = useRef(false);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  const execute = useCallback(
    async (
      requestFn: (signal: AbortSignal) => Promise<T>,
      options: RequestOptions<T> = {}
    ): Promise<T | null> => {
      const { onSuccess, onError, onFinally } = options;

      // Abort previous request if still in progress
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();
      loadingRef.current = true;

      try {
        const result = await requestFn(abortControllerRef.current.signal);

        // Only update state if still mounted
        if (mountedRef.current) {
          onSuccess?.(result);
        }

        return result;
      } catch (error) {
        // Silently ignore abort errors - this is expected behavior
        if (error instanceof Error && error.name === 'AbortError') {
          return null;
        }

        // Also check for axios cancel
        if (
          error &&
          typeof error === 'object' &&
          'code' in error &&
          error.code === 'ERR_CANCELED'
        ) {
          return null;
        }

        // Only handle error if still mounted
        if (mountedRef.current) {
          console.error('[Request] Failed:', error);
          onError?.(error instanceof Error ? error : new Error('Request failed'));
        }

        return null;
      } finally {
        loadingRef.current = false;
        if (mountedRef.current) {
          onFinally?.();
        }
      }
    },
    []
  );

  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  return {
    execute,
    abort,
    get isLoading() {
      return loadingRef.current;
    },
  };
}

/**
 * Hook for making multiple cancellable requests in parallel
 * All requests share a single abort controller
 */
export function useCancellableParallelRequests() {
  const abortControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  const executeAll = useCallback(
    async <T>(
      requestFns: Array<(signal: AbortSignal) => Promise<T>>,
      options: {
        onAllSuccess?: (results: T[]) => void;
        onError?: (error: Error) => void;
        onFinally?: () => void;
      } = {}
    ): Promise<T[] | null> => {
      const { onAllSuccess, onError, onFinally } = options;

      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();

      try {
        const results = await Promise.all(
          requestFns.map((fn) => fn(abortControllerRef.current!.signal))
        );

        if (mountedRef.current) {
          onAllSuccess?.(results);
        }

        return results;
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          return null;
        }

        if (mountedRef.current) {
          onError?.(error instanceof Error ? error : new Error('Request failed'));
        }

        return null;
      } finally {
        if (mountedRef.current) {
          onFinally?.();
        }
      }
    },
    []
  );

  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  return { executeAll, abort };
}

export default useCancellableRequest;
