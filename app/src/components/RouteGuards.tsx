import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

/**
 * PrivateRoute - Protects routes that require authentication
 * Uses the centralized AuthContext for consistent auth state
 */
export function PrivateRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  // Loading state - show nothing while checking auth
  if (isLoading) {
    return null;
  }

  // Not authenticated - redirect to login, preserving intended destination
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  // Authenticated - show protected content
  return <>{children}</>;
}

/**
 * PublicOnlyRoute - Redirects authenticated users away from auth pages (login, register)
 * Prevents logged-in users from seeing login/register forms
 */
export function PublicOnlyRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  // Loading state - show nothing while checking auth
  if (isLoading) {
    return null;
  }

  // Authenticated - redirect to saved destination or dashboard
  if (isAuthenticated) {
    const from = (location.state as { from?: string })?.from || '/chat';
    return <Navigate to={from} replace />;
  }

  return <>{children}</>;
}
