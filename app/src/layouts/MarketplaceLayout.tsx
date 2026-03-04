import { Outlet, useLocation } from 'react-router-dom';
import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import axios from 'axios';
import { NavigationSidebar } from '../components/ui';
import { MobileWarning } from '../components/MobileWarning';
import { PublicMarketplaceHeader } from './PublicMarketplaceHeader';
import { PublicMarketplaceFooter } from './PublicMarketplaceFooter';
import { MarketplaceAuthContext } from '../contexts/MarketplaceAuthContext';
import { config } from '../config';

const API_URL = config.API_URL;

type AuthState = 'loading' | 'authenticated' | 'unauthenticated';

/**
 * Adaptive Marketplace Layout
 *
 * Industry-standard approach:
 * - Non-blocking: Content renders immediately, auth check happens in background
 * - Defaults to public view during loading (better SEO, faster FCP)
 * - Seamlessly transitions to authenticated view when auth confirmed
 * - Single route definition, no duplication
 * - Provides auth state via context (no duplicate checks in children)
 * - Reuses existing NavigationSidebar for authenticated users
 */
export function MarketplaceLayout() {
  const location = useLocation();
  const [authState, setAuthState] = useState<AuthState>('loading');

  // Check auth on mount - non-blocking
  // Matches PrivateRoute pattern for consistency
  // IMPORTANT: Uses raw axios to bypass the api interceptor that redirects 401 to /login
  useEffect(() => {
    let mounted = true;

    const checkAuth = async () => {
      try {
        // Fast path: If token exists in localStorage, trust it (same as PrivateRoute)
        // This is fast, synchronous, and avoids network latency
        const token = localStorage.getItem('token');
        if (token) {
          if (mounted) setAuthState('authenticated');
          return;
        }

        // Slow path: No token, check cookie-based auth (OAuth users)
        // Uses raw axios to avoid the 401 redirect interceptor in api.ts
        // We want to handle 401 ourselves (show public view), not redirect to /login
        const response = await axios.get(`${API_URL}/api/users/me`, {
          withCredentials: true, // Send cookies for OAuth session
        });
        if (mounted) {
          setAuthState(response.status === 200 ? 'authenticated' : 'unauthenticated');
        }
      } catch {
        // 401 or any error = not authenticated = show public view
        if (mounted) setAuthState('unauthenticated');
      }
    };

    checkAuth();

    return () => {
      mounted = false;
    };
  }, []);

  // Determine active page for sidebar
  const activePage = useMemo((): 'dashboard' | 'marketplace' | 'library' | 'feedback' => {
    const path = location.pathname;
    if (path.includes('/marketplace')) return 'marketplace';
    if (path.includes('/library')) return 'library';
    if (path.includes('/feedback')) return 'feedback';
    return 'dashboard';
  }, [location.pathname]);

  // Context value - shared with all marketplace pages/components
  const authContextValue = useMemo(
    () => ({
      isAuthenticated: authState === 'authenticated',
      isLoading: authState === 'loading',
    }),
    [authState]
  );

  // Authenticated view: Full DashboardLayout with sidebar
  if (authState === 'authenticated') {
    return (
      <MarketplaceAuthContext.Provider value={authContextValue}>
        <motion.div
          className="h-screen flex overflow-hidden bg-[var(--bg)]"
          initial={{ opacity: 0.95 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15 }}
        >
          <MobileWarning />

          {/* Navigation Sidebar */}
          <div className="flex-shrink-0 h-full">
            <NavigationSidebar activePage={activePage} showContent={true} />
          </div>

          {/* Main Content */}
          <div className="flex-1 flex flex-col overflow-hidden">
            <Outlet />
          </div>
        </motion.div>
      </MarketplaceAuthContext.Provider>
    );
  }

  // Public view (default during loading + unauthenticated)
  // This is intentional: showing public view during loading is better for:
  // 1. SEO (crawlers see public content immediately)
  // 2. Performance (no blocking render)
  // 3. UX (content appears instantly)
  return (
    <MarketplaceAuthContext.Provider value={authContextValue}>
      <div className="min-h-screen flex flex-col bg-[var(--bg)]">
        {/* Public Header with auth-aware CTAs */}
        <PublicMarketplaceHeader isLoading={authState === 'loading'} />

        {/* Main Content - always renders immediately */}
        <main className="flex-1">
          <Outlet />
        </main>

        {/* SEO-friendly Footer */}
        <PublicMarketplaceFooter />
      </div>
    </MarketplaceAuthContext.Provider>
  );
}

export default MarketplaceLayout;
