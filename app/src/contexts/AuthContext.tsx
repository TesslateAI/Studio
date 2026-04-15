/**
 * Centralized Authentication Context
 *
 * Single source of truth for authentication state across the application.
 * Handles both Bearer token (localStorage) and cookie-based (OAuth) auth.
 *
 * Features:
 * - Non-blocking initialization (UI renders immediately)
 * - Race-condition free (uses refs to track in-flight requests)
 * - Cross-tab synchronization (via storage events)
 * - Proper error classification and logging
 */

import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useRef,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react';
import axios from 'axios';
import {
  type AuthState,
  type AuthContextValue,
  type AuthUser,
  type AuthError,
  type AuthMethod,
  AuthenticationError,
  shouldLogoutOnError,
} from './auth/types';
import { authApi, revokeServerSession } from '../lib/api';
import { config } from '../config';

const API_URL = config.API_URL;

const SILENT_REFRESH_INTERVAL_MS = 12 * 60 * 1000; // 12 minutes — refresh before 15-min access token expires
const REFRESH_COOLDOWN_MS = 5 * 60 * 1000; // 5 minutes — minimum gap between refreshes

// =============================================================================
// Initial State
// =============================================================================

/**
 * Get initial state - trust localStorage token for fast initial render
 */
const getInitialState = (): AuthState => {
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('token');
  return {
    // If we have a token, optimistically assume authenticated
    // This prevents flash of unauthenticated content
    status: hasToken ? 'authenticated' : 'initializing',
    user: null,
    authMethod: hasToken ? 'token' : null,
    error: null,
    lastChecked: null,
  };
};

// =============================================================================
// Reducer
// =============================================================================

type AuthAction =
  | { type: 'AUTH_START' }
  | { type: 'AUTH_SUCCESS'; payload: { user: AuthUser; method: AuthMethod } }
  | { type: 'AUTH_FAILURE'; payload: AuthError }
  | { type: 'AUTH_LOGOUT' }
  | { type: 'USER_UPDATED'; payload: AuthUser }
  | { type: 'CLEAR_ERROR' };

function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'AUTH_START':
      return { ...state, error: null };

    case 'AUTH_SUCCESS':
      return {
        ...state,
        status: 'authenticated',
        user: action.payload.user,
        authMethod: action.payload.method,
        error: null,
        lastChecked: Date.now(),
      };

    case 'AUTH_FAILURE':
      return {
        ...state,
        status: 'unauthenticated',
        user: null,
        authMethod: null,
        error: action.payload,
        lastChecked: Date.now(),
      };

    case 'AUTH_LOGOUT':
      return {
        status: 'unauthenticated',
        user: null,
        authMethod: null,
        error: null,
        lastChecked: Date.now(),
      };

    case 'USER_UPDATED':
      return { ...state, user: action.payload };

    case 'CLEAR_ERROR':
      return { ...state, error: null };

    default:
      return state;
  }
}

// =============================================================================
// Context
// =============================================================================

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// =============================================================================
// Provider
// =============================================================================

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [state, dispatch] = useReducer(authReducer, undefined, getInitialState);
  const abortControllerRef = useRef<AbortController | null>(null);
  const checkInProgressRef = useRef(false);
  const mountedRef = useRef(true);
  const lastRefreshRef = useRef(0);

  // ==========================================================================
  // Core Auth Check
  // ==========================================================================

  const checkAuth = useCallback(
    async (options?: { force?: boolean }): Promise<boolean> => {
      // Prevent concurrent checks unless forced
      if (checkInProgressRef.current && !options?.force) {
        return state.status === 'authenticated';
      }

      // Abort any in-flight request
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();

      // Capture state AT START. If this check fails with 401, we must decide
      // whether to fire /api/auth/logout based on "was the user authenticated
      // when this check started", not "is the user authenticated by the time
      // the 401 comes back" — the latter can be true when a concurrent
      // checkAuth (e.g. from MagicLinkConsume after /consume 200) has flipped
      // the state to 'authenticated' in the meantime. Using current state
      // would then incorrectly revoke the freshly-established session.
      const statusAtStart = state.status;
      const tokenAtStart = localStorage.getItem('token');

      checkInProgressRef.current = true;
      dispatch({ type: 'AUTH_START' });

      try {
        // Check token auth first (faster, synchronous check)
        const token = tokenAtStart;

        if (token) {
          const response = await axios.get(`${API_URL}/api/users/me`, {
            headers: { Authorization: `Bearer ${token}` },
            signal: abortControllerRef.current.signal,
          });

          if (response.status === 200 && mountedRef.current) {
            dispatch({
              type: 'AUTH_SUCCESS',
              payload: { user: response.data, method: 'token' },
            });
            return true;
          }
        }

        // Fall through to cookie auth (OAuth users)
        const response = await axios.get(`${API_URL}/api/users/me`, {
          withCredentials: true,
          signal: abortControllerRef.current.signal,
        });

        if (response.status === 200 && mountedRef.current) {
          dispatch({
            type: 'AUTH_SUCCESS',
            payload: { user: response.data, method: 'cookie' },
          });
          return true;
        }

        if (mountedRef.current) {
          dispatch({
            type: 'AUTH_FAILURE',
            payload: {
              code: 'UNAUTHORIZED',
              message: 'Not authenticated',
              timestamp: Date.now(),
              recoverable: false,
            },
          });
        }
        return false;
      } catch (error) {
        // Handle abort (not an error)
        if (axios.isCancel(error)) {
          return false;
        }

        // Classify the error
        const authError = AuthenticationError.fromAxiosError(error);

        // Log for observability (NEVER log tokens or passwords)
        console.error('[Auth] Check failed:', {
          code: authError.code,
          recoverable: authError.recoverable,
          statusCode: authError.statusCode,
        });

        // Clear invalid token and revoke server session if expired.
        //
        // IMPORTANT: use statusAtStart / tokenAtStart (captured before awaiting
        // the network call), not the current state, because a concurrent
        // sign-in flow (OAuth callback, magic-link consume) may have flipped
        // state → 'authenticated' and written a new token while this check was
        // in flight. We must not destroy that fresh session.
        //
        // Rules:
        //   - Only revoke the server session if the user was actually
        //     authenticated when this check started. A 401 from 'initializing'
        //     or 'unauthenticated' state just means "not logged in yet".
        //   - Only remove the localStorage token if the value is still the one
        //     we started with. If it changed mid-flight, a concurrent flow
        //     wrote a fresh token and we must leave it alone.
        if (shouldLogoutOnError(authError.toAuthError())) {
          const wasAuthenticated = statusAtStart === 'authenticated';
          const currentToken = localStorage.getItem('token');
          if (tokenAtStart && currentToken === tokenAtStart) {
            localStorage.removeItem('token');
          }
          if (wasAuthenticated) {
            revokeServerSession(); // non-blocking, best-effort
          }
        }

        if (mountedRef.current) {
          dispatch({ type: 'AUTH_FAILURE', payload: authError.toAuthError() });
        }
        return false;
      } finally {
        checkInProgressRef.current = false;
      }
    },
    [state.status]
  );

  // ==========================================================================
  // Login
  // ==========================================================================

  const login = useCallback(
    async (email: string, password: string) => {
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();

      dispatch({ type: 'AUTH_START' });

      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);

      try {
        // Login without withCredentials to avoid sending stale cookies
        // that could conflict with the fresh credentials
        const response = await axios.post(`${API_URL}/api/auth/jwt/login`, formData, {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          signal: abortControllerRef.current.signal,
        });

        const { access_token } = response.data;
        localStorage.setItem('token', access_token);

        // Notify other tabs
        window.dispatchEvent(
          new StorageEvent('storage', {
            key: 'token',
            newValue: access_token,
          })
        );

        // Fetch user data
        await checkAuth({ force: true });
      } catch (error) {
        const authError = AuthenticationError.fromAxiosError(error);

        console.error('[Auth] Login failed:', {
          code: authError.code,
          statusCode: authError.statusCode,
        });

        if (mountedRef.current) {
          dispatch({ type: 'AUTH_FAILURE', payload: authError.toAuthError() });
        }
        throw authError;
      }
    },
    [checkAuth]
  );

  // ==========================================================================
  // Logout
  // ==========================================================================

  const logout = useCallback(async () => {
    abortControllerRef.current?.abort();

    await revokeServerSession();

    // Clear local state
    localStorage.removeItem('token');
    sessionStorage.clear();

    // Notify other tabs
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'token',
        newValue: null,
      })
    );

    if (mountedRef.current) {
      dispatch({ type: 'AUTH_LOGOUT' });
    }
  }, []);

  // ==========================================================================
  // Refresh User Data
  // ==========================================================================

  const refreshUser = useCallback(async () => {
    if (state.status !== 'authenticated') return;

    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(`${API_URL}/api/users/me`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        withCredentials: true,
      });

      if (mountedRef.current) {
        dispatch({ type: 'USER_UPDATED', payload: response.data });
      }
    } catch (error) {
      console.error('[Auth] Failed to refresh user:', error);
    }
  }, [state.status]);

  // ==========================================================================
  // Token Refresh
  // ==========================================================================

  const refreshToken = useCallback(async () => {
    try {
      await authApi.refreshToken();
    } catch {
      // Silent failure — the 401 interceptor handles actual session loss
    }
  }, []);

  // ==========================================================================
  // Clear Error
  // ==========================================================================

  const clearError = useCallback(() => {
    dispatch({ type: 'CLEAR_ERROR' });
  }, []);

  // ==========================================================================
  // Role Checker
  // ==========================================================================

  const hasRole = useCallback(
    (role: string): boolean => {
      if (!state.user) return false;
      if (role === 'admin') return state.user.is_superuser ?? false;
      return true;
    },
    [state.user]
  );

  // ==========================================================================
  // Effects
  // ==========================================================================

  // Desktop auto-login: when running inside the Tauri shell, ask the host for
  // the local user's JWT and store it in localStorage so the normal checkAuth()
  // flow picks it up.  No npm package needed — the Tauri host injects
  // window.__TESSLATE_DESKTOP_TOKEN__ via JS eval AND dispatches a custom event
  // to cover both "token ready before React" and "token arrives after React" cases.
  useEffect(() => {
    // Detect Tauri by the injected internals object (present in all Tauri v2 webviews).
    const isTauri = '__TAURI_INTERNALS__' in window || '__TAURI__' in window;
    if (!isTauri) return;

    const applyToken = (token: string) => {
      if (token && !localStorage.getItem('token')) {
        localStorage.setItem('token', token);
        checkAuth({ force: true });
      }
    };

    // Case 1: token already injected before React mounted.
    const win = window as Record<string, unknown>;
    const existing = win.__TESSLATE_DESKTOP_TOKEN__;
    if (typeof existing === 'string' && existing) {
      applyToken(existing);
      return;
    }

    // Case 2: token arrives after React mounts (host fetched it async).
    const handler = () => {
      const t = (window as Record<string, unknown>).__TESSLATE_DESKTOP_TOKEN__;
      if (typeof t === 'string') applyToken(t);
    };
    window.addEventListener('tesslate-desktop-token-ready', handler);
    return () => window.removeEventListener('tesslate-desktop-token-ready', handler);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Initial auth check on mount
  useEffect(() => {
    mountedRef.current = true;
    checkAuth();

    return () => {
      mountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Cross-tab synchronization
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key !== 'token') return;

      if (e.newValue) {
        // Token added in another tab - recheck auth
        checkAuth({ force: true });
      } else {
        // Token removed in another tab - logout this tab
        dispatch({ type: 'AUTH_LOGOUT' });
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [checkAuth]);

  // Proactive silent token refresh (every 30 min + on tab visibility change)
  useEffect(() => {
    if (state.status !== 'authenticated') return;

    const doRefresh = () => {
      lastRefreshRef.current = Date.now();
      refreshToken();
    };

    // Periodic refresh
    const intervalId = setInterval(doRefresh, SILENT_REFRESH_INTERVAL_MS);

    // Refresh when tab becomes visible (user returning after being away)
    // Skips if a refresh happened within the cooldown window
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        if (Date.now() - lastRefreshRef.current > REFRESH_COOLDOWN_MS) {
          doRefresh();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [state.status, refreshToken]);

  // ==========================================================================
  // Context Value
  // ==========================================================================

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      isAuthenticated: state.status === 'authenticated',
      isLoading: state.status === 'initializing',
      login,
      logout,
      checkAuth,
      refreshUser,
      refreshToken,
      clearError,
      hasRole,
    }),
    [state, login, logout, checkAuth, refreshUser, refreshToken, clearError, hasRole]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// =============================================================================
// Hooks
// =============================================================================

/**
 * Hook to access auth context
 * Must be used within AuthProvider
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}

/**
 * Quick check if user appears to be logged in (doesn't verify with server)
 * Useful for immediate UI decisions before full auth check completes
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useQuickAuthCheck(): boolean {
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('token');
  return hasToken;
}

// Export the context for advanced use cases (like MarketplaceLayout)
export { AuthContext };
