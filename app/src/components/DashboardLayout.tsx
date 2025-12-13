import { Outlet, useLocation } from 'react-router-dom';
import { NavigationSidebar } from './ui';
import { MobileMenu } from './ui';
import { MobileWarning } from './MobileWarning';
import { DiscordSupport } from './DiscordSupport';
import { motion, AnimatePresence } from 'framer-motion';
import { useState, useEffect } from 'react';

export function DashboardLayout() {
  const location = useLocation();
  const fromLogin = location.state?.fromLogin === true;
  const [showSidebarContainer, setShowSidebarContainer] = useState(!fromLogin);
  const [showSidebarContent, setShowSidebarContent] = useState(!fromLogin);

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
  const getActivePage = (): 'dashboard' | 'marketplace' | 'library' | 'feedback' => {
    const path = location.pathname;
    if (path.includes('/marketplace')) return 'marketplace';
    if (path.includes('/library')) return 'library';
    if (path.includes('/feedback')) return 'feedback';
    return 'dashboard';
  };

  return (
    <motion.div
      className="h-screen flex overflow-hidden bg-[var(--bg)]"
      initial={fromLogin ? { opacity: 0 } : { opacity: 1 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Navigation Sidebar Container - Slides in and resizes */}
      {showSidebarContainer && (
        <motion.div
          key="sidebar-container"
          initial={fromLogin ? { x: -300, width: 320 } : false}
          animate={{ x: 0, width: "auto" }}
          transition={fromLogin ? {
            duration: 0.6,
            ease: [0.25, 0.1, 0.25, 1]
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

      {/* Main Content Area - Only this changes when navigating */}
      <motion.div
        className="flex-1 flex flex-col overflow-hidden"
        initial={fromLogin ? { opacity: 0 } : { opacity: 1 }}
        animate={{ opacity: 1 }}
        transition={fromLogin ? { delay: 0.5, duration: 0.4 } : { duration: 0 }}
      >
        <Outlet />
      </motion.div>

      {/* Discord Support */}
      <DiscordSupport />
    </motion.div>
  );
}
