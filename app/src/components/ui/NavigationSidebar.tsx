import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../../theme/ThemeContext';
import { Tooltip } from './Tooltip';
import toast from 'react-hot-toast';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FolderOpen,
  Store,
  Package,
  Settings,
  Sun,
  Moon,
  BookOpen,
  LogOut,
  ChevronLeft,
  ChevronRight,
  FileText,
  Sparkles,
  MessageCircle
} from 'lucide-react';
import { billingApi } from '../../lib/api';

interface NavigationSidebarProps {
  activePage: 'dashboard' | 'marketplace' | 'library' | 'feedback';
  showContent?: boolean;
}

export function NavigationSidebar({ activePage, showContent = true }: NavigationSidebarProps) {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('navigationSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [isPremium, setIsPremium] = useState(false);
  const [loadingSubscription, setLoadingSubscription] = useState(true);

  useEffect(() => {
    localStorage.setItem('navigationSidebarExpanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

  useEffect(() => {
    // Check subscription status
    const checkSubscription = async () => {
      try {
        const subscription = await billingApi.getSubscription();
        setIsPremium(subscription.tier === 'pro');
      } catch (error) {
        console.error('Failed to check subscription:', error);
      } finally {
        setLoadingSubscription(false);
      }
    };
    checkSubscription();
  }, []);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <motion.div
      initial={false}
      animate={{ width: isExpanded ? 192 : 48 }}
      transition={{
        type: "spring",
        stiffness: 700,
        damping: 28,
        mass: 0.4
      }}
      className="hidden md:flex flex-col h-screen bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] overflow-x-hidden"
    >
      {/* Tesslate Logo */}
      <div className={`flex items-center h-12 flex-shrink-0 ${isExpanded ? 'px-3 gap-3' : 'justify-center'} border-b border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]`}>
        <svg className="w-5 h-5 text-[var(--primary)] flex-shrink-0" viewBox="0 0 161.9 126.66">
          <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
          <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
          <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
        </svg>
        {isExpanded && (
          <span className="text-lg font-bold text-[var(--sidebar-text)]">Tesslate</span>
        )}
      </div>

      <motion.div
        className="py-3 gap-1 flex flex-col flex-1 overflow-y-auto overflow-x-hidden"
        initial={{ opacity: 0 }}
        animate={{ opacity: showContent ? 1 : 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      >

      {/* Navigation Items */}
      {isExpanded ? (
        <button
          onClick={() => navigate('/dashboard')}
          className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
            activePage === 'dashboard'
              ? 'bg-[var(--sidebar-active)]'
              : 'hover:bg-[var(--sidebar-hover)]'
          }`}
        >
          <FolderOpen
            size={18}
            className={`transition-colors ${
              activePage === 'dashboard'
                ? 'text-[var(--sidebar-text)]'
                : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
            }`}
          />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Projects</span>
        </button>
      ) : (
        <Tooltip content="Projects" side="right" delay={200}>
          <button
            onClick={() => navigate('/dashboard')}
            className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
              activePage === 'dashboard'
                ? 'bg-[var(--sidebar-active)]'
                : 'hover:bg-[var(--sidebar-hover)]'
            }`}
          >
            <FolderOpen
              size={18}
              className={`transition-colors ${
                activePage === 'dashboard'
                  ? 'text-[var(--sidebar-text)]'
                  : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
              }`}
            />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => navigate('/marketplace')}
          className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
            activePage === 'marketplace'
              ? 'bg-[var(--sidebar-active)]'
              : 'hover:bg-[var(--sidebar-hover)]'
          }`}
        >
          <Store
            size={18}
            className={`transition-colors ${
              activePage === 'marketplace'
                ? 'text-[var(--sidebar-text)]'
                : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
            }`}
          />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Marketplace</span>
        </button>
      ) : (
        <Tooltip content="Marketplace" side="right" delay={200}>
          <button
            onClick={() => navigate('/marketplace')}
            className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
              activePage === 'marketplace'
                ? 'bg-[var(--sidebar-active)]'
                : 'hover:bg-[var(--sidebar-hover)]'
            }`}
          >
            <Store
              size={18}
              className={`transition-colors ${
                activePage === 'marketplace'
                  ? 'text-[var(--sidebar-text)]'
                  : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
              }`}
            />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => navigate('/library')}
          className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
            activePage === 'library'
              ? 'bg-[var(--sidebar-active)]'
              : 'hover:bg-[var(--sidebar-hover)]'
          }`}
        >
          <BookOpen
            size={18}
            className={`transition-colors ${
              activePage === 'library'
                ? 'text-[var(--sidebar-text)]'
                : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
            }`}
          />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Library</span>
        </button>
      ) : (
        <Tooltip content="Library" side="right" delay={200}>
          <button
            onClick={() => navigate('/library')}
            className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
              activePage === 'library'
                ? 'bg-[var(--sidebar-active)]'
                : 'hover:bg-[var(--sidebar-hover)]'
            }`}
          >
            <BookOpen
              size={18}
              className={`transition-colors ${
                activePage === 'library'
                  ? 'text-[var(--sidebar-text)]'
                  : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
              }`}
            />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => navigate('/feedback')}
          className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
            activePage === 'feedback'
              ? 'bg-[var(--sidebar-active)]'
              : 'hover:bg-[var(--sidebar-hover)]'
          }`}
        >
          <MessageCircle
            size={18}
            className={`transition-colors ${
              activePage === 'feedback'
                ? 'text-[var(--sidebar-text)]'
                : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
            }`}
          />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Feedback</span>
        </button>
      ) : (
        <Tooltip content="Feedback" side="right" delay={200}>
          <button
            onClick={() => navigate('/feedback')}
            className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
              activePage === 'feedback'
                ? 'bg-[var(--sidebar-active)]'
                : 'hover:bg-[var(--sidebar-hover)]'
            }`}
          >
            <MessageCircle
              size={18}
              className={`transition-colors ${
                activePage === 'feedback'
                  ? 'text-[var(--sidebar-text)]'
                  : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
              }`}
            />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => toast('Components library coming soon!')}
          className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
        >
          <Package size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Components</span>
        </button>
      ) : (
        <Tooltip content="Components" side="right" delay={200}>
          <button
            onClick={() => toast('Components library coming soon!')}
            className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
          >
            <Package size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <a
          href="https://docs.tesslate.com"
          target="_blank"
          rel="noopener noreferrer"
          className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
        >
          <FileText size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Documentation</span>
        </a>
      ) : (
        <Tooltip content="Documentation" side="right" delay={200}>
          <a
            href="https://docs.tesslate.com"
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
          >
            <FileText size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          </a>
        </Tooltip>
      )}

      <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

      {/* Premium Upgrade Button */}
      {!loadingSubscription && !isPremium && (
        <>
          {isExpanded ? (
            <div className="mx-2 my-1 flex-shrink-0">
              <button
                onClick={() => navigate('/billing/plans')}
                className="w-full bg-gradient-to-r from-[var(--primary)] to-[var(--primary-hover)] hover:from-[var(--primary-hover)] hover:to-[var(--primary-hover)] text-white rounded-lg p-3 transition-all shadow-lg hover:shadow-xl"
              >
                <div className="flex items-center justify-center gap-2">
                  <Sparkles size={16} />
                  <span className="text-sm font-bold">Premium</span>
                </div>
              </button>
            </div>
          ) : (
            <Tooltip content="Premium" side="right" delay={200}>
              <button
                onClick={() => navigate('/billing/plans')}
                className="flex items-center justify-center h-9 bg-gradient-to-r from-[var(--primary)] to-[var(--primary-hover)] hover:from-[var(--primary-hover)] hover:to-[var(--primary-hover)] text-white transition-all w-full flex-shrink-0"
              >
                <Sparkles size={18} />
              </button>
            </Tooltip>
          )}
          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />
        </>
      )}

      {/* Utility Items */}
      {isExpanded ? (
        <button
          onClick={toggleTheme}
          className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
        >
          {theme === 'dark' ? (
            <Sun size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          ) : (
            <Moon size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          )}
          <span className="text-sm font-medium text-[var(--sidebar-text)]">{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
        </button>
      ) : (
        <Tooltip content={theme === 'dark' ? 'Light Mode' : 'Dark Mode'} side="right" delay={200}>
          <button
            onClick={toggleTheme}
            className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
          >
            {theme === 'dark' ? (
              <Sun size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
            ) : (
              <Moon size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
            )}
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => navigate('/settings')}
          className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
        >
          <Settings size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Settings</span>
        </button>
      ) : (
        <Tooltip content="Settings" side="right" delay={200}>
          <button
            onClick={() => navigate('/settings')}
            className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
          >
            <Settings size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={logout}
          className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
        >
          <LogOut size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Logout</span>
        </button>
      ) : (
        <Tooltip content="Logout" side="right" delay={200}>
          <button
            onClick={logout}
            className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
          >
            <LogOut size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          </button>
        </Tooltip>
      )}

      {/* Spacer to push collapse button to bottom */}
      <div className="flex-1" />

      <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

      {/* Collapse/Expand Toggle */}
      {isExpanded ? (
        <button
          onClick={() => setIsExpanded(false)}
          className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
        >
          <ChevronLeft size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          <span className="text-sm font-medium text-[var(--sidebar-text)]">Collapse</span>
        </button>
      ) : (
        <Tooltip content="Expand" side="right" delay={200}>
          <button
            onClick={() => setIsExpanded(true)}
            className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
          >
            <ChevronRight size={18} className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors" />
          </button>
        </Tooltip>
      )}
      </motion.div>
    </motion.div>
  );
}
