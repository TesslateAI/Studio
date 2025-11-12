import React, { createContext, useState, useContext, useEffect, ReactNode } from 'react';
import { authApi } from '../lib/api';
import { authManager } from '../lib/auth';

interface User {
  id: string;
  name: string;
  email: string;
  is_superuser?: boolean;
  subscription_tier?: string;
  credits_balance?: number;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string, referralCode?: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Check authentication on mount
  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const token = await authManager.getToken();
      if (token) {
        // Try to get current user
        const userData = await authApi.getCurrentUser();
        setUser(userData);
        setIsAuthenticated(true);
        await authManager.saveUser(userData);
      }
    } catch (error) {
      // Token invalid or expired
      await authManager.clearAll();
      setUser(null);
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    try {
      const response = await authApi.login(email, password);
      await authManager.saveToken(response.access_token);

      // Fetch user data
      const userData = await authApi.getCurrentUser();
      setUser(userData);
      setIsAuthenticated(true);
      await authManager.saveUser(userData);
    } catch (error) {
      throw error;
    }
  };

  const register = async (name: string, email: string, password: string, referralCode?: string) => {
    try {
      await authApi.register(name, email, password, referralCode);

      // Auto-login after registration
      await login(email, password);
    } catch (error) {
      throw error;
    }
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } catch (error) {
      // Ignore errors
    } finally {
      await authManager.clearAll();
      setUser(null);
      setIsAuthenticated(false);
    }
  };

  const refreshUser = async () => {
    try {
      const userData = await authApi.getCurrentUser();
      setUser(userData);
      await authManager.saveUser(userData);
    } catch (error) {
      console.error('Failed to refresh user:', error);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
