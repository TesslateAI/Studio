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
  // Fast synchronous check: if a JWT token exists, render authenticated immediately
  // This avoids the public marketplace flash for logged-in users
  const [authState, setAuthState] = useState<AuthState>(
    () => localStorage.getItem('token') ? 'authenticated' : 'loading'
  );

  // Slow path: for cookie-based OAuth users without a token
  useEffect(() => {
    // Already authenticated via token — nothing to do
    if (authState === 'authenticated') return;

    let mounted = true;

    const checkAuth = async () => {
      try {
        // Uses raw axios to avoid the 401 redirect interceptor in api.ts
        const response = await axios.get(`${API_URL}/api/users/me`, {
          withCredentials: true,
        });
        if (mounted) {
          setAuthState(response.status === 200 ? 'authenticated' : 'unauthenticated');
        }
      } catch {
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

  // Loading state: show a neutral shell that won't flash the wrong layout
  // This only applies to cookie-based OAuth users (token users skip loading entirely)
  if (authState === 'loading') {
    return (
      <MarketplaceAuthContext.Provider value={authContextValue}>
        <div className="h-screen bg-[var(--sidebar-bg)]" />
      </MarketplaceAuthContext.Provider>
    );
  }

  // Authenticated view: Full DashboardLayout with sidebar
  if (authState === 'authenticated') {
    return (
      <MarketplaceAuthContext.Provider value={authContextValue}>
        <motion.div
          className="h-screen flex overflow-hidden bg-[var(--sidebar-bg)]"
          initial={{ opacity: 0.95 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15 }}
        >
          <MobileWarning />

          {/* Navigation Sidebar */}
          <div className="flex-shrink-0 h-full">
            <NavigationSidebar activePage={activePage} showContent={true} />
          </div>

          {/* Main Content — floating panel */}
          <div
            className="flex-1 flex flex-col overflow-hidden"
            style={{
              borderRadius: 'var(--radius)',
              margin: 'var(--app-margin)',
              marginLeft: '0',
              border: 'var(--border-width) solid var(--border)',
              backgroundColor: 'var(--bg)',
            }}
          >
            <Outlet />
          </div>
        </motion.div>
      </MarketplaceAuthContext.Provider>
    );
  }

  // Public view (unauthenticated only — loading is handled above)
  return (
    <MarketplaceAuthContext.Provider value={authContextValue}>
      <div className="min-h-screen flex flex-col bg-[var(--sidebar-bg)]">
        {/* Public Header */}
        <PublicMarketplaceHeader isLoading={false} />

        {/* Main Content */}
        <main className="flex-1 bg-[var(--bg)]">
          <Outlet />
        </main>

        {/* Footer */}
        <PublicMarketplaceFooter />
      </div>
    </MarketplaceAuthContext.Provider>
  );
}

export default MarketplaceLayout;
