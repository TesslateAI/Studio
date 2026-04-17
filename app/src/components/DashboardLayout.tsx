import { Outlet, useLocation } from 'react-router-dom';
import { NavigationSidebar } from './ui';
import { MobileWarning } from './MobileWarning';
import { List } from '@phosphor-icons/react';

import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';

export function DashboardLayout() {
  const location = useLocation();
  const fromLogin = location.state?.fromLogin === true;
  const [showSidebarContainer, setShowSidebarContainer] = useState(!fromLogin);
  const [showSidebarContent, setShowSidebarContent] = useState(!fromLogin);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Close mobile nav on route change
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    // Only run animation if coming from login
    if (fromLogin) {
      // Step 1: Background loads (already visible)
      // Step 2: Show empty sidebar container after 200ms
      const containerTimer = setTimeout(() => {
        setShowSidebarContainer(true);
      }, 200);

      // Step 3: Show sidebar content after container animation completes (800ms total)
      const contentTimer = setTimeout(() => {
        setShowSidebarContent(true);
      }, 800);

      return () => {
        clearTimeout(containerTimer);
        clearTimeout(contentTimer);
      };
    }
  }, [fromLogin]);

  // Determine active page based on current path
  const getActivePage = (): 'home' | 'chat' | 'apps' | 'dashboard' | 'marketplace' | 'library' | 'feedback' => {
    const path = location.pathname;
    if (path.includes('/home')) return 'home';
    if (path.includes('/chat')) return 'chat';
    if (path.startsWith('/apps')) return 'apps';
    if (path.includes('/marketplace')) return 'marketplace';
    if (path.includes('/library')) return 'library';
    if (path.includes('/feedback')) return 'feedback';
    return 'dashboard';
  };

  return (
    <motion.div
      className="h-screen flex overflow-hidden bg-[var(--sidebar-bg)]"
      initial={fromLogin ? { opacity: 0 } : { opacity: 1 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Mobile hamburger button — fixed top-left */}
      <button
        onClick={() => setMobileNavOpen(true)}
        className="md:hidden fixed top-2.5 left-2.5 z-40 p-1.5 rounded-[var(--radius-small)] bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
        aria-label="Open navigation"
      >
        <List size={18} weight="bold" />
      </button>

      {/* Mobile sidebar overlay */}
      {mobileNavOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/40 z-50"
          onClick={() => setMobileNavOpen(false)}
        />
      )}
      {mobileNavOpen && (
        <div className="md:hidden fixed inset-y-0 left-0 z-50">
          <NavigationSidebar
            activePage={getActivePage()}
            showContent
            forceVisible
          />
        </div>
      )}

      {/* Navigation Sidebar Container - Slides in and resizes (desktop) */}
      {showSidebarContainer && (
        <motion.div
          key="sidebar-container"
          initial={fromLogin ? { x: -300, width: 320 } : false}
          animate={{ x: 0, width: "auto" }}
          transition={fromLogin ? {
            duration: 0.45,
            ease: [0.45, 0, 0.55, 1]
          } : { duration: 0 }}
          className="flex-shrink-0 h-full"
        >
          {/* Navigation Sidebar - This stays mounted during navigation */}
          <NavigationSidebar
            activePage={getActivePage()}
            showContent={showSidebarContent}
          />
        </motion.div>
      )}

      {/* Main Content Area — floating panel with 8px margin, 12px radius */}
      {/* Sidebar bg shows through the margin gap — content "glows" relative to sidebar */}
      <motion.div
        className="flex-1 flex flex-col overflow-hidden app-panel"
        style={{
          borderRadius: 'var(--radius)',
          margin: 'var(--app-margin)',
          marginLeft: '0',
          border: 'var(--border-width) solid var(--border)',
          backgroundColor: 'var(--bg)',
        }}
        initial={fromLogin ? { opacity: 0 } : { opacity: 1 }}
        animate={{ opacity: 1 }}
        transition={fromLogin ? { delay: 0.5, duration: 0.4 } : { duration: 0 }}
      >
        <Outlet />
      </motion.div>

    </motion.div>
  );
}
