import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Menu, ArrowLeft, X } from 'lucide-react';
import { SettingsSidebar, SettingsSidebarMobile } from '../components/settings/SettingsSidebar';
import { MobileWarning } from '../components/MobileWarning';

// Map routes to display titles
const routeTitles: Record<string, string> = {
  '/settings/profile': 'Profile',
  '/settings/preferences': 'Preferences',
  '/settings/security': 'Security',
  '/settings/deployment': 'Deployment',
  '/settings/billing': 'Billing',
};

export function SettingsLayout() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  // Get current page title
  const currentTitle = routeTitles[location.pathname] || 'Settings';

  const handleCloseMobileMenu = () => {
    setIsMobileMenuOpen(false);
  };

  return (
    <motion.div
      className="h-screen flex overflow-hidden bg-[var(--bg)]"
      initial={{ opacity: 1 }}
      animate={{ opacity: 1 }}
    >
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Desktop Sidebar - Uses the collapsible SettingsSidebar */}
      <div className="flex-shrink-0 h-full">
        <SettingsSidebar />
      </div>

      {/* Mobile Header - shown only on mobile, with safe area for notched devices */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 bg-[var(--sidebar-bg)] border-b border-[var(--sidebar-border)] flex items-center justify-between px-3 pt-[env(safe-area-inset-top)] h-[calc(48px+env(safe-area-inset-top))]">
        <button
          onClick={() => navigate('/dashboard')}
          className="flex items-center gap-2 text-[var(--sidebar-text)]/60 hover:text-[var(--sidebar-text)] transition-colors min-h-[44px] min-w-[44px]"
        >
          <ArrowLeft size={18} />
          <span className="text-sm font-medium">Back</span>
        </button>

        <h1 className="font-semibold text-[var(--sidebar-text)] text-sm">{currentTitle}</h1>

        <button
          onClick={() => setIsMobileMenuOpen(true)}
          className="flex items-center justify-center text-[var(--sidebar-text)]/60 hover:text-[var(--sidebar-text)] transition-colors min-h-[44px] min-w-[44px]"
        >
          <Menu size={20} />
        </button>
      </div>

      {/* Mobile Drawer Overlay */}
      <AnimatePresence>
        {isMobileMenuOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="md:hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-50"
              onClick={handleCloseMobileMenu}
            />

            {/* Drawer - slides in from left, responsive width for different screen sizes */}
            <motion.div
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{
                type: 'spring',
                stiffness: 400,
                damping: 30,
              }}
              className="md:hidden fixed inset-y-0 left-0 z-50 w-[70vw] max-w-[240px] min-w-[180px] pt-[env(safe-area-inset-top)]"
            >
              <div className="h-full bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] relative">
                {/* Close button with proper touch target */}
                <button
                  onClick={handleCloseMobileMenu}
                  className="absolute top-3 right-2 flex items-center justify-center min-h-[44px] min-w-[44px] text-[var(--sidebar-text)]/40 hover:text-[var(--sidebar-text)] transition-colors z-10"
                >
                  <X size={18} />
                </button>

                <SettingsSidebarMobile onClose={handleCloseMobileMenu} />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Main Content Area */}
      <motion.div
        className="flex-1 flex flex-col overflow-hidden"
        initial={{ opacity: 1 }}
        animate={{ opacity: 1 }}
      >
        <main className="flex-1 overflow-y-auto md:pt-0 pt-[calc(48px+env(safe-area-inset-top))]">
          <Outlet />
        </main>
      </motion.div>
    </motion.div>
  );
}
