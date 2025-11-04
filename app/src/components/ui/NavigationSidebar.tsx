import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../../theme/ThemeContext';
import { Tooltip } from './Tooltip';
import toast from 'react-hot-toast';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Folder,
  Storefront,
  Package,
  Gear,
  Sun,
  Moon,
  Books,
  SignOut,
  CaretLeft,
  CaretRight
} from '@phosphor-icons/react';

interface NavigationSidebarProps {
  activePage: 'dashboard' | 'marketplace' | 'library';
}

export function NavigationSidebar({ activePage }: NavigationSidebarProps) {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('navigationSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });

  useEffect(() => {
    localStorage.setItem('navigationSidebarExpanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

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
      className="hidden md:flex flex-col bg-[var(--surface)] border-r border-white/10 overflow-x-hidden"
    >
      {/* Tesslate Logo */}
      <div className={`flex items-center h-12 flex-shrink-0 ${isExpanded ? 'px-3 gap-3' : 'justify-center'} border-b border-white/10`}>
        <svg className="w-5 h-5 text-[var(--primary)] flex-shrink-0" viewBox="0 0 161.9 126.66">
          <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
          <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
          <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
        </svg>
        {isExpanded && (
          <span className="text-lg font-bold text-[var(--text)]">Tesslate</span>
        )}
      </div>

      <div className="py-3 gap-1 flex flex-col flex-1 overflow-y-auto overflow-x-hidden">

      {/* Navigation Items */}
      {isExpanded ? (
        <button
          onClick={() => navigate('/dashboard')}
          className={`flex items-center h-9 transition-all w-full flex-shrink-0 px-3 gap-3 ${
            activePage === 'dashboard'
              ? 'text-[var(--primary)] bg-[var(--primary)]/10 border-l-2 border-[var(--primary)]'
              : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
          }`}
        >
          <Folder size={18} weight="fill" />
          <span className="text-sm font-medium">Projects</span>
        </button>
      ) : (
        <Tooltip content="Projects" side="right" delay={200}>
          <button
            onClick={() => navigate('/dashboard')}
            className={`flex items-center justify-center h-9 transition-all w-full flex-shrink-0 ${
              activePage === 'dashboard'
                ? 'text-[var(--primary)] bg-[var(--primary)]/10 border-l-2 border-[var(--primary)]'
                : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
            }`}
          >
            <Folder size={18} weight="fill" />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => navigate('/marketplace')}
          className={`flex items-center h-9 transition-all w-full flex-shrink-0 px-3 gap-3 ${
            activePage === 'marketplace'
              ? 'text-[var(--primary)] bg-[var(--primary)]/10 border-l-2 border-[var(--primary)]'
              : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
          }`}
        >
          <Storefront size={18} weight="fill" />
          <span className="text-sm font-medium">Marketplace</span>
        </button>
      ) : (
        <Tooltip content="Marketplace" side="right" delay={200}>
          <button
            onClick={() => navigate('/marketplace')}
            className={`flex items-center justify-center h-9 transition-all w-full flex-shrink-0 ${
              activePage === 'marketplace'
                ? 'text-[var(--primary)] bg-[var(--primary)]/10 border-l-2 border-[var(--primary)]'
                : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
            }`}
          >
            <Storefront size={18} weight="fill" />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => navigate('/library')}
          className={`flex items-center h-9 transition-all w-full flex-shrink-0 px-3 gap-3 ${
            activePage === 'library'
              ? 'text-[var(--primary)] bg-[var(--primary)]/10 border-l-2 border-[var(--primary)]'
              : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
          }`}
        >
          <Books size={18} weight="fill" />
          <span className="text-sm font-medium">Library</span>
        </button>
      ) : (
        <Tooltip content="Library" side="right" delay={200}>
          <button
            onClick={() => navigate('/library')}
            className={`flex items-center justify-center h-9 transition-all w-full flex-shrink-0 ${
              activePage === 'library'
                ? 'text-[var(--primary)] bg-[var(--primary)]/10 border-l-2 border-[var(--primary)]'
                : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
            }`}
          >
            <Books size={18} weight="fill" />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => toast('Components library coming soon!')}
          className="flex items-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0 px-3 gap-3"
        >
          <Package size={18} weight="fill" />
          <span className="text-sm font-medium">Components</span>
        </button>
      ) : (
        <Tooltip content="Components" side="right" delay={200}>
          <button
            onClick={() => toast('Components library coming soon!')}
            className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
          >
            <Package size={18} weight="fill" />
          </button>
        </Tooltip>
      )}

      <div className="h-px bg-white/10 my-1 mx-2 flex-shrink-0" />

      {/* Utility Items */}
      {isExpanded ? (
        <button
          onClick={toggleTheme}
          className="flex items-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0 px-3 gap-3"
        >
          {theme === 'dark' ? <Sun size={18} weight="fill" /> : <Moon size={18} weight="fill" />}
          <span className="text-sm font-medium">{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
        </button>
      ) : (
        <Tooltip content={theme === 'dark' ? 'Light Mode' : 'Dark Mode'} side="right" delay={200}>
          <button
            onClick={toggleTheme}
            className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
          >
            {theme === 'dark' ? <Sun size={18} weight="fill" /> : <Moon size={18} weight="fill" />}
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={() => toast('Settings coming soon!')}
          className="flex items-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0 px-3 gap-3"
        >
          <Gear size={18} weight="fill" />
          <span className="text-sm font-medium">Settings</span>
        </button>
      ) : (
        <Tooltip content="Settings" side="right" delay={200}>
          <button
            onClick={() => toast('Settings coming soon!')}
            className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
          >
            <Gear size={18} weight="fill" />
          </button>
        </Tooltip>
      )}

      {isExpanded ? (
        <button
          onClick={logout}
          className="flex items-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0 px-3 gap-3"
        >
          <SignOut size={18} weight="fill" />
          <span className="text-sm font-medium">Logout</span>
        </button>
      ) : (
        <Tooltip content="Logout" side="right" delay={200}>
          <button
            onClick={logout}
            className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
          >
            <SignOut size={18} weight="fill" />
          </button>
        </Tooltip>
      )}

      {/* Spacer to push collapse button to bottom */}
      <div className="flex-1" />

      <div className="h-px bg-white/10 my-1 mx-2 flex-shrink-0" />

      {/* Collapse/Expand Toggle */}
      {isExpanded ? (
        <button
          onClick={() => setIsExpanded(false)}
          className="flex items-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0 px-3 gap-3"
        >
          <CaretLeft size={18} weight="bold" />
          <span className="text-sm font-medium">Collapse</span>
        </button>
      ) : (
        <Tooltip content="Expand" side="right" delay={200}>
          <button
            onClick={() => setIsExpanded(true)}
            className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
          >
            <CaretRight size={18} weight="bold" />
          </button>
        </Tooltip>
      )}
      </div>
    </motion.div>
  );
}
