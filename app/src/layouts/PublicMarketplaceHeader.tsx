import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import {
  Storefront,
  Sun,
  Moon,
  SignIn,
  UserPlus,
  List,
} from '@phosphor-icons/react';
import { motion } from 'framer-motion';
import { useState } from 'react';

interface PublicMarketplaceHeaderProps {
  isLoading?: boolean;
}

/**
 * Public Marketplace Header
 * - Shows sign up / sign in CTAs for non-logged users
 * - Mobile responsive with hamburger menu
 * - Theme toggle
 */
export function PublicMarketplaceHeader({ isLoading = false }: PublicMarketplaceHeaderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isMarketplaceHome = location.pathname === '/marketplace';

  return (
    <header
      className={`
        sticky top-0 z-50 border-b backdrop-blur-xl
        ${theme === 'light' ? 'bg-white/90 border-black/10' : 'bg-[#0a0a0a]/90 border-white/10'}
      `}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14 sm:h-16">
          {/* Logo / Brand */}
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/marketplace')}
              className="flex items-center gap-2"
            >
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--primary)] to-orange-600 flex items-center justify-center">
                <Storefront size={18} className="text-white" weight="bold" />
              </div>
              <span
                className={`font-heading font-bold text-lg hidden sm:block ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                Tesslate
              </span>
            </button>

            {/* Desktop Nav */}
            <nav className="hidden md:flex items-center gap-1 ml-4">
              <button
                onClick={() => navigate('/marketplace')}
                className={`
                  px-3 py-2 rounded-lg text-sm font-medium transition-colors
                  ${
                    isMarketplaceHome
                      ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                      : theme === 'light'
                        ? 'text-black/60 hover:text-black hover:bg-black/5'
                        : 'text-white/60 hover:text-white hover:bg-white/5'
                  }
                `}
              >
                Explore
              </button>
              <button
                onClick={() => navigate('/marketplace/browse/agent')}
                className={`
                  px-3 py-2 rounded-lg text-sm font-medium transition-colors
                  ${theme === 'light' ? 'text-black/60 hover:text-black hover:bg-black/5' : 'text-white/60 hover:text-white hover:bg-white/5'}
                `}
              >
                Agents
              </button>
              <button
                onClick={() => navigate('/marketplace/browse/base')}
                className={`
                  px-3 py-2 rounded-lg text-sm font-medium transition-colors
                  ${theme === 'light' ? 'text-black/60 hover:text-black hover:bg-black/5' : 'text-white/60 hover:text-white hover:bg-white/5'}
                `}
              >
                Templates
              </button>
            </nav>
          </div>

          {/* Right side actions */}
          <div className="flex items-center gap-2">
            {/* Theme Toggle */}
            <button
              onClick={toggleTheme}
              className={`
                p-2 rounded-lg transition-colors
                ${theme === 'light' ? 'hover:bg-black/5 text-black/60' : 'hover:bg-white/5 text-white/60'}
              `}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
            </button>

            {/* Auth Buttons - Don't show while loading to prevent flash */}
            {!isLoading && (
              <>
                <button
                  onClick={() => navigate('/login')}
                  className={`
                    hidden sm:flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
                    ${theme === 'light' ? 'hover:bg-black/5 text-black/70' : 'hover:bg-white/5 text-white/70'}
                  `}
                >
                  <SignIn size={18} />
                  Sign In
                </button>
                <button
                  onClick={() => navigate('/register')}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors"
                >
                  <UserPlus size={18} />
                  <span className="hidden sm:inline">Sign Up Free</span>
                  <span className="sm:hidden">Sign Up</span>
                </button>
              </>
            )}

            {/* Mobile Menu Toggle */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className={`
                md:hidden p-2 rounded-lg transition-colors
                ${theme === 'light' ? 'hover:bg-black/5 text-black/60' : 'hover:bg-white/5 text-white/60'}
              `}
              aria-label="Menu"
            >
              <List size={24} />
            </button>
          </div>
        </div>

        {/* Mobile Menu */}
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className={`
              md:hidden py-4 border-t
              ${theme === 'light' ? 'border-black/10' : 'border-white/10'}
            `}
          >
            <nav className="flex flex-col gap-1">
              <button
                onClick={() => {
                  navigate('/marketplace');
                  setMobileMenuOpen(false);
                }}
                className={`
                  px-3 py-2 rounded-lg text-sm font-medium text-left transition-colors
                  ${
                    isMarketplaceHome
                      ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                      : theme === 'light'
                        ? 'text-black/60 hover:bg-black/5'
                        : 'text-white/60 hover:bg-white/5'
                  }
                `}
              >
                Explore
              </button>
              <button
                onClick={() => {
                  navigate('/marketplace/browse/agent');
                  setMobileMenuOpen(false);
                }}
                className={`
                  px-3 py-2 rounded-lg text-sm font-medium text-left transition-colors
                  ${theme === 'light' ? 'text-black/60 hover:bg-black/5' : 'text-white/60 hover:bg-white/5'}
                `}
              >
                Agents
              </button>
              <button
                onClick={() => {
                  navigate('/marketplace/browse/base');
                  setMobileMenuOpen(false);
                }}
                className={`
                  px-3 py-2 rounded-lg text-sm font-medium text-left transition-colors
                  ${theme === 'light' ? 'text-black/60 hover:bg-black/5' : 'text-white/60 hover:bg-white/5'}
                `}
              >
                Templates
              </button>
            </nav>
          </motion.div>
        )}
      </div>
    </header>
  );
}

export default PublicMarketplaceHeader;
