import { useNavigate, useLocation } from 'react-router-dom';
import {
  SignIn,
  UserPlus,
  List,
  X,
} from '@phosphor-icons/react';
import { motion, AnimatePresence } from 'framer-motion';
import { useState } from 'react';

interface PublicMarketplaceHeaderProps {
  isLoading?: boolean;
}

/**
 * Public Marketplace Header
 * Minimal dark design matching Tesslate's internal design system.
 * Tesslate logo, pill nav buttons, sign in/up CTAs.
 */
export function PublicMarketplaceHeader({ isLoading = false }: PublicMarketplaceHeaderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isMarketplaceHome = location.pathname === '/marketplace';
  const isBrowseAgents = location.pathname.includes('/browse/agent');
  const isBrowseBases = location.pathname.includes('/browse/base');

  const navItems = [
    { label: 'Explore', path: '/marketplace', active: isMarketplaceHome },
    { label: 'Agents', path: '/marketplace/browse/agent', active: isBrowseAgents },
    { label: 'Templates', path: '/marketplace/browse/base', active: isBrowseBases },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border)] bg-[var(--bg)]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Logo + Nav */}
          <div className="flex items-center gap-6">
            <button
              onClick={() => navigate('/marketplace')}
              className="flex items-center gap-2.5 group"
            >
              <svg className="w-6 h-6 text-[var(--primary)] flex-shrink-0" viewBox="0 0 161.9 126.66">
                <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor" />
                <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor" />
                <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor" />
              </svg>
              <span className="text-sm font-bold text-[var(--text)] hidden sm:block">
                Tesslate
              </span>
            </button>

            {/* Desktop Nav — pill buttons */}
            <nav className="hidden md:flex items-center gap-1">
              {navItems.map((item) => (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  className={`btn btn-sm ${item.active ? 'btn-tab-active' : 'btn-tab'}`}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            {/* Auth Buttons */}
            {!isLoading && (
              <>
                <button
                  onClick={() => navigate('/login')}
                  className="btn hidden sm:flex"
                >
                  <SignIn size={14} />
                  Sign In
                </button>
                <button
                  onClick={() => navigate('/register')}
                  className="btn btn-filled"
                >
                  <UserPlus size={14} />
                  <span className="hidden sm:inline">Sign Up Free</span>
                  <span className="sm:hidden">Sign Up</span>
                </button>
              </>
            )}

            {/* Mobile Menu Toggle */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="btn btn-icon md:hidden"
              aria-label="Menu"
            >
              {mobileMenuOpen ? <X size={16} /> : <List size={16} />}
            </button>
          </div>
        </div>

        {/* Mobile Menu */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
              className="md:hidden overflow-hidden border-t border-[var(--border)]"
            >
              <nav className="flex flex-col gap-1 py-3">
                {navItems.map((item) => (
                  <button
                    key={item.path}
                    onClick={() => { navigate(item.path); setMobileMenuOpen(false); }}
                    className={`w-full text-left px-3 py-2 rounded-[var(--radius-small)] text-xs font-medium transition-colors ${
                      item.active
                        ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                        : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </header>
  );
}

export default PublicMarketplaceHeader;
