import { useNavigate } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';

/**
 * Public Marketplace Footer
 * - SEO-friendly with proper navigation links
 * - Category links for crawlers
 * - Sign up CTA
 */
export function PublicMarketplaceFooter() {
  const navigate = useNavigate();
  const { theme } = useTheme();

  return (
    <footer
      className={`
        border-t mt-16 py-12
        ${theme === 'light' ? 'bg-black/5 border-black/10' : 'bg-white/5 border-white/10'}
      `}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {/* Marketplace */}
          <div>
            <h3 className={`font-semibold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
              Marketplace
            </h3>
            <ul className="space-y-2">
              <li>
                <a
                  href="/marketplace/browse/agent"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  AI Agents
                </a>
              </li>
              <li>
                <a
                  href="/marketplace/browse/base"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Project Templates
                </a>
              </li>
              <li>
                <a
                  href="/marketplace/browse/agent?category=frontend"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Frontend
                </a>
              </li>
              <li>
                <a
                  href="/marketplace/browse/agent?category=backend"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Backend
                </a>
              </li>
            </ul>
          </div>

          {/* Categories */}
          <div>
            <h3 className={`font-semibold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
              Categories
            </h3>
            <ul className="space-y-2">
              <li>
                <a
                  href="/marketplace/browse/agent?category=builder"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Builder
                </a>
              </li>
              <li>
                <a
                  href="/marketplace/browse/agent?category=fullstack"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Fullstack
                </a>
              </li>
              <li>
                <a
                  href="/marketplace/browse/agent?category=data"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Data & ML
                </a>
              </li>
              <li>
                <a
                  href="/marketplace/browse/agent?category=devops"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  DevOps
                </a>
              </li>
            </ul>
          </div>

          {/* Company */}
          <div>
            <h3 className={`font-semibold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
              Company
            </h3>
            <ul className="space-y-2">
              <li>
                <a
                  href="/"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  About
                </a>
              </li>
              <li>
                <a
                  href="/register"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Sign Up
                </a>
              </li>
              <li>
                <a
                  href="/login"
                  className={`text-sm ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}`}
                >
                  Sign In
                </a>
              </li>
            </ul>
          </div>

          {/* Get Started */}
          <div>
            <h3 className={`font-semibold mb-4 ${theme === 'light' ? 'text-black' : 'text-white'}`}>
              Get Started
            </h3>
            <p className={`text-sm mb-4 ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
              Build faster with AI-powered coding agents and pre-built templates.
            </p>
            <button
              onClick={() => navigate('/register')}
              className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors"
            >
              Start Building Free
            </button>
          </div>
        </div>

        <div
          className={`
            mt-12 pt-8 border-t text-center
            ${theme === 'light' ? 'border-black/10' : 'border-white/10'}
          `}
        >
          <p className={`text-sm ${theme === 'light' ? 'text-black/40' : 'text-white/40'}`}>
            &copy; {new Date().getFullYear()} Tesslate. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}

export default PublicMarketplaceFooter;
