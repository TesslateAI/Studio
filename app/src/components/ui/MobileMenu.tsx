import { type ReactNode, useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { NavigationSidebar } from './NavigationSidebar';

type MobileActivePage =
  | 'home'
  | 'chat'
  | 'dashboard'
  | 'marketplace'
  | 'library'
  | 'feedback'
  | 'builder'
  | 'settings';

type BuilderSectionRenderer = (ctx: {
  isExpanded: boolean;
  navButtonClass: (active: boolean) => string;
  navButtonClassCollapsed: (active: boolean) => string;
  iconClass: (active: boolean) => string;
  labelClass: (active: boolean) => string;
  inactiveNavButton: string;
  inactiveNavButtonCollapsed: string;
  inactiveIconClass: string;
  inactiveLabelClass: string;
}) => ReactNode;

// Props kept for backwards compatibility — pages still pass items
interface MobileMenuProps {
  leftItems?: Array<unknown>;
  rightItems?: Array<unknown>;
  /** Override route-based active page detection. */
  activePage?: MobileActivePage;
  /** Builder-specific items rendered inside the drawer's NavigationSidebar. */
  builderSection?: BuilderSectionRenderer;
}

export function MobileMenu({ activePage: activePageProp, builderSection }: MobileMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();

  // Listen for toggle events from hamburger buttons
  useEffect(() => {
    const handleToggle = () => setIsOpen(prev => !prev);
    const handleClose = () => setIsOpen(false);
    window.addEventListener('toggleMobileMenu', handleToggle);
    window.addEventListener('closeMobileMenu', handleClose);
    return () => {
      window.removeEventListener('toggleMobileMenu', handleToggle);
      window.removeEventListener('closeMobileMenu', handleClose);
    };
  }, []);

  // Close on escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen]);

  // Close on navigation
  useEffect(() => {
    setIsOpen(false);
  }, [location.pathname, location.search]);

  // Determine active page from current route (fallback when prop omitted)
  const routeActivePage = (): MobileActivePage => {
    const path = location.pathname;
    if (path.includes('/marketplace')) return 'marketplace';
    if (path.includes('/library')) return 'library';
    if (path.includes('/feedback')) return 'feedback';
    return 'dashboard';
  };

  const activePage = activePageProp ?? routeActivePage();

  return (
    <>
      {/* Backdrop */}
      <div
        className={`md:hidden fixed inset-0 bg-black/50 z-[60] transition-opacity duration-150 ${
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={() => setIsOpen(false)}
      />

      {/* Sidebar drawer — the real NavigationSidebar, forced visible + expanded */}
      <div
        className={`md:hidden fixed top-0 left-0 h-full z-[70] transition-transform duration-150 ease-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ width: 244 }}
      >
        <NavigationSidebar
          activePage={activePage}
          showContent={true}
          forceVisible
          builderSection={builderSection}
        />
      </div>
    </>
  );
}
