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

      checkInProgressRef.current = true;
      dispatch({ type: 'AUTH_START' });

      try {
        // Check token auth first (faster, synchronous check)
        const token = localStorage.getItem('token');

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

        // Clear invalid token and revoke server session if expired
        if (shouldLogoutOnError(authError.toAuthError())) {
          localStorage.removeItem('token');
          revokeServerSession(); // non-blocking, best-effort
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
