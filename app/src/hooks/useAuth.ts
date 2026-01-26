import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

interface User {
  id: string;
  email: string;
  name?: string;
  avatar_url?: string;
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
}

/**
 * Hook to check authentication status without blocking the UI
 * Returns loading state while checking, then authenticated status
 */
export function useAuth(): AuthState & { checkAuth: () => Promise<void> } {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    user: null,
  });

  const checkAuth = useCallback(async () => {
    try {
      // Check if we have a token in localStorage (regular login)
      const token = localStorage.getItem('token');

      if (token) {
        // Verify token by fetching user
        const response = await axios.get(`${API_URL}/api/users/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (response.status === 200) {
          setState({
            isAuthenticated: true,
            isLoading: false,
            user: response.data,
          });
          return;
        }
      }

      // No token in localStorage, check if we have a valid cookie (OAuth login)
      const response = await axios.get(`${API_URL}/api/users/me`, {
        withCredentials: true,
      });

      if (response.status === 200) {
        setState({
          isAuthenticated: true,
          isLoading: false,
          user: response.data,
        });
        return;
      }

      // Not authenticated
      setState({
        isAuthenticated: false,
        isLoading: false,
        user: null,
      });
    } catch {
      // Not authenticated
      setState({
        isAuthenticated: false,
        isLoading: false,
        user: null,
      });
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  return { ...state, checkAuth };
}

/**
 * Quick check if user appears to be logged in (doesn't verify with server)
 * Useful for immediate UI decisions
 */
export function useQuickAuthCheck(): boolean {
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('token');
    setHasToken(!!token);
  }, []);

  return hasToken;
}

export default useAuth;
