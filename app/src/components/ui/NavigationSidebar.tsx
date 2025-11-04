import { useNavigate } from 'react-router-dom';
import { useTheme } from '../../theme/ThemeContext';
import { Tooltip } from './Tooltip';
import toast from 'react-hot-toast';
import {
  Folder,
  Storefront,
  Package,
  Gear,
  Sun,
  Moon,
  Books,
  SignOut
} from '@phosphor-icons/react';

interface NavigationSidebarProps {
  activePage: 'dashboard' | 'marketplace' | 'library';
}

export function NavigationSidebar({ activePage }: NavigationSidebarProps) {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="hidden md:flex flex-col w-12 bg-[var(--surface)] border-r border-white/10 py-3 gap-1">
      {/* Tesslate Logo */}
      <div className="flex items-center justify-center h-9 mb-1 flex-shrink-0">
        <svg className="w-5 h-5 text-[var(--primary)]" viewBox="0 0 161.9 126.66">
          <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
          <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
          <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
        </svg>
      </div>

      <div className="h-px bg-white/10 my-1 mx-2 flex-shrink-0" />

      {/* Navigation Items */}
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

      <Tooltip content="Components" side="right" delay={200}>
        <button
          onClick={() => toast('Components library coming soon!')}
          className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
        >
          <Package size={18} weight="fill" />
        </button>
      </Tooltip>

      <div className="h-px bg-white/10 my-1 mx-2 flex-shrink-0" />

      {/* Utility Items */}
      <Tooltip content={theme === 'dark' ? 'Light Mode' : 'Dark Mode'} side="right" delay={200}>
        <button
          onClick={toggleTheme}
          className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
        >
          {theme === 'dark' ? <Sun size={18} weight="fill" /> : <Moon size={18} weight="fill" />}
        </button>
      </Tooltip>

      <Tooltip content="Settings" side="right" delay={200}>
        <button
          onClick={() => toast('Settings coming soon!')}
          className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
        >
          <Gear size={18} weight="fill" />
        </button>
      </Tooltip>

      <Tooltip content="Logout" side="right" delay={200}>
        <button
          onClick={logout}
          className="flex items-center justify-center h-9 text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 transition-all w-full flex-shrink-0"
        >
          <SignOut size={18} weight="fill" />
        </button>
      </Tooltip>
    </div>
  );
}
