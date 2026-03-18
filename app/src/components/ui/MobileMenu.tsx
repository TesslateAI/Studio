import { type ReactNode, useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { NavigationSidebar } from './NavigationSidebar';

// Props kept for backwards compatibility — pages still pass items
interface MobileMenuProps {
  leftItems?: Array<{
    icon: ReactNode;
    title: string;
    onClick: () => void;
    active?: boolean;
    disabled?: boolean;
    dataTour?: string;
  }>;
  rightItems?: Array<{
    icon: ReactNode;
    title: string;
    onClick: () => void;
    active?: boolean;
    disabled?: boolean;
    dataTour?: string;
  }>;
}

export function MobileMenu(_props: MobileMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();

  // Listen for toggle events from hamburger buttons
  useEffect(() => {
    const handleToggle = () => setIsOpen(prev => !prev);
    window.addEventListener('toggleMobileMenu', handleToggle);
    return () => window.removeEventListener('toggleMobileMenu', handleToggle);
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

  // Determine active page from current route
  const getActivePage = (): 'dashboard' | 'marketplace' | 'library' | 'feedback' => {
    const path = location.pathname;
    if (path.includes('/marketplace')) return 'marketplace';
    if (path.includes('/library')) return 'library';
    if (path.includes('/feedback')) return 'feedback';
    return 'dashboard';
  };

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
          activePage={getActivePage()}
          showContent={true}
          forceVisible
        />
      </div>
    </>
  );
}
